import asyncio
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import queue
import re
import threading
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple
import uuid

import anyio.to_thread
import numpy as np

try:
    import soundfile as sf
except ImportError:
    sf = None

try:
    import edge_tts
except ImportError:
    edge_tts = None

try:
    import azure.cognitiveservices.speech as speechsdk
except ImportError:
    speechsdk = None

from app.config import settings
from app.database import SessionLocal
from app.logger import tts_audit_logger
from app.models.tts_audit import TTSAuditLog
from app.services.silero_service import silero_tts
from app.services.tts_normalizer import apply_stress_overrides, clean_display_text
from app.services.tts_qa_validator import validate_and_fix_russian_tts

logger = logging.getLogger(__name__)

# Supported voice mappings for Azure Speech Services and Silero v5
DEFAULT_VOICE = "ru-RU-SvetlanaNeural"
ESTONIAN_VOICE = "et-EE-AnuNeural"

VOICE_MAP: Dict[str, str] = {
    "ru": DEFAULT_VOICE,
    "et": ESTONIAN_VOICE,
    "bilingual": "bilingual",
    "silero": "silero",
    "xenia": "silero",
    "kseniya": "silero",
    "ru-RU-SvetlanaMultilingualNeural": DEFAULT_VOICE,
    "ru-RU-SvetlanaNeural": DEFAULT_VOICE,
    "et-EE-AnuNeural": ESTONIAN_VOICE,
    "et-EE-KertNeural": "et-EE-KertNeural",
}

# Disk and memory caching (single canonical cache directory with LRU rotation)
AUDIO_CACHE_DIR = Path("static/audio/cache")
try:
    AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

_TTS_STREAM_CACHE: "OrderedDict[str, bytes]" = OrderedDict()
MAX_CACHE_ENTRIES = 500
MIN_VALID_AUDIO_BYTES = 800
MAX_DISK_CACHE_FILES = 1200
MAX_DISK_CACHE_BYTES = 100 * 1024 * 1024  # 100 MB
AZURE_SYNTHESIS_TIMEOUT_SEC = 10.0

# Registry of active in-flight tasks for deduplication of simultaneous requests
_IN_FLIGHT_TASKS: Dict[str, asyncio.Task[bytes]] = {}

# Singleton SpeechConfig & thread-safe synthesizer pool to avoid 150-300ms TLS/config overhead
_SPEECH_CONFIG_LOCK = threading.Lock()
_SPEECH_CONFIG_SINGLETON: Optional[Any] = None
_SPEECH_CONFIG_KEY_REGION: Optional[Tuple[str, str]] = None
_SYNTHESIZER_POOL: "queue.LifoQueue[Any]" = queue.LifoQueue(maxsize=4)


def is_valid_mp3_buffer(data: Optional[bytes]) -> bool:
    """
    Проверяет, что буфер содержит валидный MP3-аудиопоток размером >= 800 байт
    и корректным заголовком (ID3v2 или MPEG sync frame 0xFF 0xE0..0xFF).
    Позволяет кэшировать короткие эстонские и русские слова ('öö', 'ja', 'puu', '5').
    """
    if not data or len(data) < MIN_VALID_AUDIO_BYTES:
        return False
    if data[:3] == b"ID3":
        return True
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return True
    return False


def _store_in_memory_cache(cache: Dict[str, bytes], key: str, data: bytes) -> None:
    if isinstance(cache, OrderedDict):
        if key in cache:
            cache.move_to_end(key)
            cache[key] = data
            return
        while len(cache) >= MAX_CACHE_ENTRIES:
            cache.popitem(last=False)
        cache[key] = data
    else:
        if len(cache) >= MAX_CACHE_ENTRIES:
            keys_to_remove = list(cache.keys())[: max(1, MAX_CACHE_ENTRIES // 5)]
            for k in keys_to_remove:
                cache.pop(k, None)
        cache[key] = data


def _enforce_disk_cache_limits(cache_dir: Path) -> None:
    """LRU-ротация единого дискового кэша static/audio/cache/ по числу файлов и общему объему."""
    try:
        if not cache_dir.is_dir():
            return
        entries = []
        total_bytes = 0
        for p in cache_dir.glob("*.mp3"):
            try:
                st = p.stat()
                entries.append((st.st_mtime, st.st_size, p))
                total_bytes += st.st_size
            except OSError:
                continue

        if len(entries) <= MAX_DISK_CACHE_FILES and total_bytes <= MAX_DISK_CACHE_BYTES:
            return

        entries.sort(key=lambda item: item[0])  # Самые старые по mtime первыми
        target_files = int(MAX_DISK_CACHE_FILES * 0.85)
        target_bytes = int(MAX_DISK_CACHE_BYTES * 0.85)
        remaining_files = len(entries)

        for _, fsize, fpath in entries:
            if remaining_files <= target_files and total_bytes <= target_bytes:
                break
            try:
                fpath.unlink(missing_ok=True)
                total_bytes -= fsize
                remaining_files -= 1
            except OSError:
                continue
    except Exception as err:
        logger.warning(f"Disk cache LRU cleanup warning: {err}")


# Re-export normalization architecture from dedicated tts_normalizer module
from app.services.tts_normalizer import (
    TERMINOLOGY_MAP,
    CUSTOM_PHONETIC_MAP,
    apply_custom_phonetic_map,
    apply_phonetic_substitutions,
    get_tts_lexicon,
    ENGLISH_BRANDS,
    normalize_loanwords_and_brands,
    normalize_time_expressions,
    int_to_russian_cardinal,
    int_to_russian_nominative,
    normalize_math_expressions,
    normalize_celsius_expressions,
    normalize_russian_fractions,
    normalize_russian_decimals,
    normalize_roman_numerals,
    normalize_number_ranges,
    normalize_russian_ordinals_with_dot,
    normalize_russian_accents_and_yo,
    normalize_text_for_estonian_tts,
    normalize_estonian_measurement_units,
    normalize_estonian_fractions,
    normalize_estonian_math_signs,
    is_chemical_formula_or_acronym,
    clean_text_for_speech,
    prepare_speech_text,
    normalize_text_for_speech,
    prepare_worked_example_speech,
    auto_tag_estonian_phrases,
    filter_card_headers_from_speech,
    apply_ssml_sub_alias,
    apply_russian_ssml_sub_aliases,
)


def add_ssml_sentence_breaks(escaped_xml: str) -> str:
    """
    Добавляет <break time="500ms" /> после знаков препинания (. ! ?)
    в экранированный XML-текст.
    - Исключает XML-теги (<lang ...>, <say-as ...>, <break ...>).
    - Исключает десятичные точки (3.14) и время (14:30).
    - Исключает точку с запятой, чтобы не нарушать XML-сущности (&gt;, &lt;, &amp;).
    """
    xml_tags = []
    def mask_tag(m):
        idx = len(xml_tags)
        xml_tags.append(m.group(0))
        return f"__XML_TAG_{idx}__"

    t = re.sub(r'<[^>]+>', mask_tag, escaped_xml)

    masked = []
    def mask_num_time(m):
        idx = len(masked)
        masked.append(m.group(0))
        return f"NUMTIMEPLACEHOLDER{idx}NUMTIME"

    t = re.sub(r'\b\d+[:.]\d+\b', mask_num_time, t)

    pattern = re.compile(r'([.!?\u2026]+)(?!\s*<break\b)')
    def repl(m):
        return f'{m.group(1)} <break time="500ms" /> '

    t = pattern.sub(repl, t)

    for idx, orig in enumerate(masked):
        t = t.replace(f"NUMTIMEPLACEHOLDER{idx}NUMTIME", orig)

    for idx, orig_tag in enumerate(xml_tags):
        t = t.replace(f"__XML_TAG_{idx}__", orig_tag)

    t = re.sub(r'(?:<break\s+time="[^"]+"\s*\/?>\s*){2,}', '<break time="500ms" /> ', t)
    return re.sub(r'[ \t]+', ' ', t).strip()


# Ключевые термины эстонского языка для автоматической мультиязычной SSML-разметки
ESTONIAN_CORE_KEYWORDS = {
    "liidetav", "liidetavad", "liidetavat", "liidetava", "liidetavale",
    "vähendatav", "vähendatavat", "vähendatava", "vähendatavale",
    "vähendaja", "vähendajat", "vähendajale",
    "summa", "summat", "summas", "summale",
    "vahe", "vahet", "vahes", "vahele",
    "korrutis", "korrutist", "korrutaja", "korrutatav",
    "jagatis", "jagatist", "jagatav", "jagaja",
    "harjutus", "harjutuse", "harjutust", "harjutuses",
    "ülesanne", "ülesande", "ülesannet", "ülesandes",
    "vastus", "vastuse", "vastust", "vastuseks",
    "küsimus", "küsimuse", "küsimust", "küsimusele",
    "sadad", "kümned", "ühelised", "arvud", "arv",
    "tere", "aitäh", "palun", "näide", "näited",
    "tehe", "tehted", "lahutamine", "liitmine", "korrutamine", "jagamine",
}

def _stitch_and_clean_segments(raw_segments: List[Tuple[str, str]], fallback_text: str) -> List[Tuple[str, str]]:
    """Вспомогательная функция для склеивания и очистки смежных фрагментов одинакового голоса."""
    segments: List[Tuple[str, str]] = []
    for s_text, s_voice in raw_segments:
        s_clean = s_text.strip()
        if not s_clean:
            continue

        if not re.search(r'\w', s_clean):
            if segments:
                prev_text, prev_voice = segments[-1]
                segments[-1] = (f"{prev_text}{s_clean}", prev_voice)
            continue

        if segments and segments[-1][1] == s_voice:
            prev_text, prev_voice = segments[-1]
            if ("et-EE" in s_voice or s_voice == "et") and not re.search(r'[,.;:!?]\s*$', prev_text):
                segments[-1] = (f"{prev_text}, {s_clean}", prev_voice)
            else:
                segments[-1] = (f"{prev_text} {s_clean}", prev_voice)
        else:
            segments.append((s_clean, s_voice))

    if not segments:
        segments.append((fallback_text.strip(), DEFAULT_VOICE))

    return segments


ENGLISH_COMMON_TERMS = {
    "minecraft", "roblox", "lego", "youtube", "tiktok", "brawl", "stars",
    "fortnite", "google", "apple", "discord", "steam", "playstation", "xbox",
    "w", "a", "s", "d", "wasd", "shift", "space", "enter", "ctrl", "alt", "esc"
}


def _is_pure_english_brand_or_key(text: str) -> bool:
    clean = re.sub(r'[^a-zA-Z0-9\s]', '', text).strip().lower()
    words = clean.split()
    return bool(words) and all(w in ENGLISH_COMMON_TERMS for w in words)


def parse_bilingual_segments(
    text: str,
    already_normalized: bool = False,
    is_speech_text: bool = False,
) -> List[Tuple[str, str]]:
    """
    Разбивает двуязычный текст на последовательные сегменты (текст, голос):
    - Приоритет 1: Фрагменты внутри тегов <est>...</est> отправляются эстонскому диктору (et-EE-AnuNeural).
    - Приоритет 2: Фразы на эстонском языке в кавычках или термины в скобках без кириллицы (исключая формулы CO2, H2O и бренды).
    - Весь остальной текст озвучивается русским голосом (ru-RU-SvetlanaNeural).
    - Если во всем тексте нет кириллицы (чистый эстонский текст) — отправляется эстонскому диктору.
    - При is_speech_text=True: отключена вторичная нормализация для защиты грамматических форм и ударений.
    """
    if not text or not text.strip():
        return [(text or "", DEFAULT_VOICE)]

    if not already_normalized and not is_speech_text:
        text = auto_tag_estonian_phrases(text)
        text = normalize_text_for_speech(text, is_russian_context=True)

    # 1. Если во всём тексте нет кириллицы вообще — озвучиваем целиком эстонским диктором
    if not re.search(r'[а-яА-ЯёЁ]', text):
        clean_est = text.strip() if (is_speech_text or already_normalized) else normalize_text_for_estonian_tts(text.strip())
        return [(clean_est or text.strip(), ESTONIAN_VOICE)]

    # 2. Ищем эстонские фрагменты в русском тексте
    # Защищаем любые теги кроме <est>, <et> и их закрывающих
    masked_tags: List[str] = []
    def mask_tag(m: re.Match) -> str:
        idx = len(masked_tags)
        masked_tags.append(m.group(0))
        return f"__BILINGUAL_TAG_{idx}__"

    text_to_scan = re.sub(r'<(?!/?(?:est|et)\b)[^>]+>', mask_tag, text)

    pattern = re.compile(
        r'<\s*(?:est|et)(?:\s+[^>]*)?>(.*?)<\s*/\s*(?:est|et)\s*>'
        r'|[\'\"«“]([a-zA-ZäöüõÄÖÜÕšžŠŽ0-9\s\.,\?!-]{2,})[\'\"»”]'
        r'|\(([a-zA-ZäöüõÄÖÜÕšžŠŽ0-9\s\.,\?!-]{2,})\)'
        r'|\b([a-zA-ZäöüõÄÖÜÕšžŠŽ]{2,})\b',
        re.DOTALL
    )

    matches: List[Tuple[int, int, str, bool]] = []
    for m in pattern.finditer(text_to_scan):
        tag_val = m.group(1)
        quote_val = m.group(2)
        paren_val = m.group(3)
        latin_val = m.group(4)

        if tag_val is not None:
            clean = tag_val.strip()
            if clean:
                matches.append((m.start(), m.end(), clean, True))
        elif quote_val is not None:
            val = quote_val.strip()
            if val and not _is_pure_english_brand_or_key(val) and not is_chemical_formula_or_acronym(val):
                matches.append((m.start(), m.end(), val, False))
        elif paren_val is not None:
            val = paren_val.strip()
            if val and not _is_pure_english_brand_or_key(val) and not is_chemical_formula_or_acronym(val):
                matches.append((m.start(), m.end(), val, False))
        elif latin_val is not None:
            val = latin_val.strip()
            if val and not _is_pure_english_brand_or_key(val) and not is_chemical_formula_or_acronym(val):
                matches.append((m.start(), m.end(), val, False))

    def _unmask_bilingual(s: str) -> str:
        for idx, orig_tag in enumerate(masked_tags):
            s = s.replace(f"__BILINGUAL_TAG_{idx}__", orig_tag)
        return s

    if not matches:
        return [(_unmask_bilingual(text.strip()), DEFAULT_VOICE)]

    raw_segments: List[Tuple[str, str]] = []
    last_idx = 0

    for start, end, est_content, is_from_tag in matches:
        if start > last_idx:
            prefix = text_to_scan[last_idx:start]
            clean_prefix = prefix.rstrip(' ([«"“„')
            if clean_prefix:
                raw_segments.append((_unmask_bilingual(clean_prefix), DEFAULT_VOICE))

        clean_est = (
            est_content.strip()
            if (is_speech_text or (already_normalized and is_from_tag))
            else normalize_text_for_estonian_tts(est_content)
        )
        if clean_est:
            raw_segments.append((_unmask_bilingual(clean_est), ESTONIAN_VOICE))

        trailing_wrapper = re.match(r'^[\s)\]»"”„]*', text_to_scan[end:])
        if trailing_wrapper:
            last_idx = end + trailing_wrapper.end()
        else:
            last_idx = end

    if last_idx < len(text_to_scan):
        suffix = text_to_scan[last_idx:]
        clean_suffix = suffix.strip(' .')
        if clean_suffix:
            raw_segments.append((_unmask_bilingual(clean_suffix), DEFAULT_VOICE))

    return _stitch_and_clean_segments(raw_segments, text)


def _escape_ssml(text: str) -> str:
    """Экранирует специальные символы XML для корректного SSML, защищая тег <sub ...>...</sub>."""
    protected_tags = []
    def mask_tag(m):
        idx = len(protected_tags)
        protected_tags.append(m.group(0))
        return f"__SSML_PROTECTED_TAG_{idx}__"

    # Белый список тегов (whitelist): защищаем <sub ...>...</sub> от экранирования
    t = re.sub(r'<sub\b[^>]*>.*?<\/sub>', mask_tag, text, flags=re.IGNORECASE | re.DOTALL)

    t = (
        t.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )

    for idx, orig in enumerate(protected_tags):
        t = t.replace(f"__SSML_PROTECTED_TAG_{idx}__", orig)

    return t


def is_already_speech_text(text: str, explicit_flag: bool = False) -> bool:
    """
    Проверяет, является ли текст уже готовым речевым слоем:
    - явный флаг is_speech_text=True
    - либо эвристика: отсутствие цифр (0-9) и математических символов (+, *, =, /, :)
    """
    if explicit_flag:
        return True
    if not text:
        return False
    if re.search(r'\d', text):
        return False
    if re.search(r'[+*=]', text) or re.search(r'\s[-/:]\s', text):
        return False
    return True


def _format_estonian_ssml_segment(seg_text: str, is_speech_text: bool = False) -> str:
    """
    Форматирует уже нормализованный эстонский сегмент в валидный SSML-контент:
    - При is_speech_text=True: пропускает преобразование формул и say-as, только базовая разметка.
    - Озвучивает математические знаки (+ -> pluss, - -> miinus, = -> võrdub).
    - Преобразует порядковые числительные > 12 ('15. harjutus') в <say-as interpret-as="ordinal">15</say-as>.
    - Защищает временные метки 14:30 от разрыва и оборачивает их в <say-as interpret-as="time">.
    - Оборачивает количественные числительные в <say-as interpret-as="cardinal"> (кроме падежных 5-ga, 10-ni).
    - Добавляет мягкие паузы между перечисляемыми эстонскими словами через запятую.
    """
    if is_speech_text:
        s_clean = seg_text.strip()
        if not s_clean:
            return ""
        s_clean = re.sub(r'(?<=[a-zA-ZõäöüÕÄÖÜšžŠŽ])\s*/\s*(?=[a-zA-ZõäöüÕÄÖÜšžŠŽ])', ' või ', s_clean)
        s_clean = re.sub(r'\s+/\s+', ' või ', s_clean)
        esc = _escape_ssml(s_clean)
        esc = re.sub(r',\s*(?!<break\b)', ', <break time="250ms" /> ', esc)
        return add_ssml_sentence_breaks(esc)

    s_clean = normalize_estonian_math_signs(seg_text.strip())
    if not s_clean:
        return ""

    s_clean = re.sub(r'(?<=[a-zA-ZõäöüÕÄÖÜšžŠŽ])\s*/\s*(?=[a-zA-ZõäöüÕÄÖÜšžŠŽ])', ' või ', s_clean)
    s_clean = re.sub(r'\s+/\s+', ' või ', s_clean)
    esc = _escape_ssml(s_clean)

    # 1. Защищаем временные метки HH:MM
    say_as_protected: List[str] = []
    def _protect_say_as(tag_xml: str) -> str:
        idx = len(say_as_protected)
        say_as_protected.append(tag_xml)
        return f"SAYASPROTECTED{idx}SAYAS"

    esc = re.sub(
        r'\b([01]?\d|2[0-3]):([0-5]\d)\b',
        lambda m: _protect_say_as(f'<say-as interpret-as="time" format="hm24">{m.group(0)}</say-as>'),
        esc,
    )

    # 2. Порядковые числительные > 12 перед эстонским существительным (15. harjutus)
    esc = re.sub(
        r'\b(\d+)\.(?=\s+[a-zõäöüšž]{2,})',
        lambda m: _protect_say_as(f'<say-as interpret-as="ordinal">{m.group(1)}</say-as>'),
        esc,
    )

    # 3. Количественные числительные (кроме падежных форм 5-ga, 10-ni и т.д.)
    esc = re.sub(
        r'\b(\d+)\b(?!\s*-(?:ga|ni|st|le|lt|sse|s|l|ks|na|ta)\b)',
        r'<say-as interpret-as="cardinal">\1</say-as>',
        esc,
    )

    for idx, orig_tag in enumerate(say_as_protected):
        esc = esc.replace(f"SAYASPROTECTED{idx}SAYAS", orig_tag)

    # 4. Мягкая пауза после запятых для устранения склеивания эстонских слов
    esc = re.sub(r',\s*(?!<break\b)', ', <break time="250ms" /> ', esc)
    return add_ssml_sentence_breaks(esc)


def sanitize_math_actions_speech(text: str) -> str:
    """
    Санитизация речевого слоя.
    Омографы разрешаются на уровне системного промпта LLM естественными однозначными формами ('вычтем' / 'отнимаем').
    """
    if not text:
        return text
    return text


def build_ssml(
    text: str,
    voice: str = DEFAULT_VOICE,
    bilingual: bool = False,
    grade: Optional[int] = None,
    tier: Optional[str] = None,
    is_speech_text: bool = False,
) -> str:
    """
    Формирует единый SSML-документ для одного запроса к Azure Speech Services.
    Текст нормализуется ровно ОДИН раз перед генерацией SSML (без тройного прогона):
    - При is_speech_text=True: полностью обходит вызовы prepare_speech_text и normalize_text_for_estonian_tts.
    - Голос по умолчанию: ru-RU-SvetlanaNeural.
    - Эстонские фрагменты оборачиваются в <voice name="et-EE-AnuNeural"><lang xml:lang="et-EE">...</lang></voice>.
    - Исключает дублирование <break/> перед закрывающим </voice>.
    - При grade 1–2 или tier primary/junior адаптирует темп речи (rate="-5%") для младших классов.
    """
    if not text or not text.strip():
        return ""

    raw_stripped = sanitize_math_actions_speech(text.strip())

    is_junior_speed = (
        (grade is not None and 1 <= grade <= 2)
        or (tier is not None and str(tier).lower() in ("primary", "junior"))
    )

    is_explicit_est_voice = ("et-EE" in voice or voice == "et")
    has_cyrillic = bool(re.search(r'[а-яА-ЯёЁ]', raw_stripped))

    # Ветка 1: Чисто эстонский текст (без кириллицы) — единичная эстонская нормализация
    if not has_cyrillic and (is_explicit_est_voice or not _is_pure_english_brand_or_key(raw_stripped)):
        raw_est = re.sub(r'</?\s*est(?:\s+[^>]*)?>', '', raw_stripped, flags=re.IGNORECASE)
        if is_speech_text:
            norm_est = raw_est.strip()
        else:
            norm_est = normalize_text_for_estonian_tts(raw_est, verbalize_math_signs=True)
        if not norm_est:
            return ""
        inner_content = _format_estonian_ssml_segment(norm_est, is_speech_text=is_speech_text)
        if re.search(r'[.!?:]\s*$', raw_stripped) and not re.search(r'<break\b[^>]*\/>\s*$', inner_content):
            inner_content = f'{inner_content} <break time="500ms" />'
        voiced_inner = f'<prosody rate="-5%">{inner_content}</prosody>' if is_junior_speed else inner_content
        return (
            '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
            'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="et-EE">\n'
            f'  <voice name="{ESTONIAN_VOICE}">{voiced_inner}</voice>\n'
            '</speak>'
        )

    # Ветка 2: Русский / двуязычный текст — ровно ОДНА идемпотентная нормализация prepare_speech_text
    if is_speech_text:
        prepared_text = raw_stripped
    else:
        prepared_text = prepare_speech_text(raw_stripped, is_russian_context=True)
    if not prepared_text:
        return ""

    has_est_tag = bool(re.search(r'<\s*est(?:\s+[^>]*)?>', prepared_text, re.IGNORECASE))

    if bilingual or has_est_tag or (is_explicit_est_voice and re.search(r'[a-zA-ZäöüõÄÖÜÕšžŠŽ]', prepared_text)):
        segments = parse_bilingual_segments(prepared_text, already_normalized=True, is_speech_text=is_speech_text)
    else:
        segments = [(prepared_text, DEFAULT_VOICE)]

    # Выделяем ключевые эстонские термины из русских фрагментов в отдельные блоки эстонского диктора
    # При is_speech_text=True пропускаем вырезание ESTONIAN_CORE_KEYWORDS из русских блоков,
    # чтобы предотвратить паразитный разрыв русской речи эстонским диктором
    if not is_speech_text:
        expanded_segments: List[Tuple[str, str]] = []
        p_est_kw = re.compile(r'\b(' + '|'.join(re.escape(k) for k in ESTONIAN_CORE_KEYWORDS) + r')\b', re.IGNORECASE)

        for s_text, s_voice in segments:
            if s_voice == DEFAULT_VOICE:
                last_pos = 0
                for m in p_est_kw.finditer(s_text):
                    if m.start() > last_pos:
                        pre = s_text[last_pos:m.start()]
                        if pre.strip():
                            expanded_segments.append((pre, DEFAULT_VOICE))
                    kw = m.group(0)
                    expanded_segments.append((kw, ESTONIAN_VOICE))
                    last_pos = m.end()
                if last_pos < len(s_text):
                    post = s_text[last_pos:]
                    if post.strip():
                        expanded_segments.append((post, DEFAULT_VOICE))
            else:
                expanded_segments.append((s_text, s_voice))

        final_segments = _stitch_and_clean_segments(expanded_segments, prepared_text)
    else:
        final_segments = segments

    voice_blocks: List[str] = []
    for seg_text, seg_voice in final_segments:
        s_clean = seg_text.strip()
        if not s_clean:
            continue

        if "et-EE" in seg_voice or seg_voice == "et":
            esc = _format_estonian_ssml_segment(s_clean, is_speech_text=is_speech_text)
            if esc:
                voiced = f'<prosody rate="-5%">{esc}</prosody>' if is_junior_speed else esc
                voice_blocks.append(f'  <voice name="{ESTONIAN_VOICE}"><lang xml:lang="et-EE">{voiced}</lang></voice>')
        else:
            esc = _escape_ssml(s_clean)
            if not is_speech_text:
                esc = apply_russian_ssml_sub_aliases(esc)
            esc = add_ssml_sentence_breaks(esc)
            voiced = f'<prosody rate="-5%">{esc}</prosody>' if is_junior_speed else esc
            voice_blocks.append(f'  <voice name="{DEFAULT_VOICE}">{voiced}</voice>')

    if voice_blocks and re.search(r'[.!?:]\s*$', raw_stripped):
        last_b = voice_blocks[-1]
        if not re.search(r'<break\b[^>]*\/>\s*(?:<\/lang>\s*)?<\/voice>$', last_b):
            if re.search(r'<\/lang><\/voice>$', last_b):
                voice_blocks[-1] = re.sub(r'<\/lang><\/voice>$', r' <break time="500ms" /></lang></voice>', last_b)
            else:
                voice_blocks[-1] = re.sub(r'<\/voice>$', r'. <break time="500ms" /></voice>', last_b)

    joined_voices = "\n".join(voice_blocks)
    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="ru-RU">\n'
        f'{joined_voices}\n'
        '</speak>'
    )


def _get_speech_config(key: str, region: str) -> Any:
    """Возвращает потокобезопасный синглтон SpeechConfig, устраняя повторную инициализацию конфига при промахах кэша."""
    global _SPEECH_CONFIG_SINGLETON, _SPEECH_CONFIG_KEY_REGION
    with _SPEECH_CONFIG_LOCK:
        if _SPEECH_CONFIG_SINGLETON is None or _SPEECH_CONFIG_KEY_REGION != (key, region):
            cfg = speechsdk.SpeechConfig(subscription=key, region=region)
            cfg.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Audio16Khz128KBitRateMonoMp3
            )
            _SPEECH_CONFIG_SINGLETON = cfg
            _SPEECH_CONFIG_KEY_REGION = (key, region)
            while not _SYNTHESIZER_POOL.empty():
                try:
                    _SYNTHESIZER_POOL.get_nowait()
                except queue.Empty:
                    break
        return _SPEECH_CONFIG_SINGLETON


def _acquire_synthesizer(speech_config: Any) -> Any:
    try:
        return _SYNTHESIZER_POOL.get_nowait()
    except queue.Empty:
        return speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)


def _release_synthesizer(synthesizer: Any) -> None:
    try:
        _SYNTHESIZER_POOL.put_nowait(synthesizer)
    except queue.Full:
        pass


def _format_accent_diagnostics(text: str) -> dict:
    has_accent = "\u0301" in text
    accented_words = []
    if has_accent:
        for word in text.split():
            if "\u0301" in word:
                utf8_hex = " ".join(f"{b:02X}" for b in word.encode("utf-8"))
                accented_words.append(f"{word} (hex: {utf8_hex})")
    return {
        "present": has_accent,
        "words": accented_words,
    }


def log_tts_audit(
    raw_incoming_text: str,
    final_ssml: Optional[str] = None,
    endpoint: str = "/api/v1/voice/tts",
    is_speech_text: bool = False,
    device_id: Optional[str] = None,
    user_tier: Optional[str] = None,
    grade: Optional[int] = None,
    cache_status: str = "AZURE_SYNTHESIS",
    status: str = "SUCCESS",
    error_message: Optional[str] = None,
    duration_ms: float = 0.0,
) -> None:
    """
    Персистентно логирует запрос озвучки:
    1. Запись структурированного JSON в logs/tts_audit.log + дубль в sys.stdout.
    2. Асинхронная вставка в таблицу tts_audit_logs базы данных.
    Работает строго в try...finally/except, ни при каких условиях не роняя процесс синтеза.
    """
    try:
        ssml_str = final_ssml or ""
        has_accents = "\u0301" in ssml_str or "\u0301" in raw_incoming_text
        accented_words = [w for w in (ssml_str or raw_incoming_text).split() if "\u0301" in w]
        has_estonian = (
            "<est>" in raw_incoming_text
            or 'xml:lang="et-EE"' in ssml_str
            or "et-EE" in ssml_str
        )

        audit_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": f"tts_{uuid.uuid4().hex[:10]}",
            "device_id": device_id,
            "user_tier": user_tier,
            "grade": grade,
            "endpoint": endpoint,
            "is_speech_text": is_speech_text,
            "raw_incoming_text": raw_incoming_text,
            "final_ssml": final_ssml,
            "has_combining_accents": has_accents,
            "accented_words": accented_words,
            "has_estonian_tags": has_estonian,
            "duration_ms": round(duration_ms, 2),
            "cache_status": cache_status,
            "azure_result": status,
            "error_message": error_message,
        }

        # 1. Запись в логгер tarkapp.tts_audit (файл logs/tts_audit.log и stdout)
        json_line = json.dumps(audit_record, ensure_ascii=False)
        tts_audit_logger.info(json_line)

        # 2. Запись в базу данных
        def _write_db():
            try:
                with SessionLocal() as db_sess:
                    db_log = TTSAuditLog(
                        endpoint=endpoint,
                        device_id=device_id,
                        is_speech_text=is_speech_text,
                        incoming_text=raw_incoming_text,
                        final_ssml=final_ssml,
                        has_accents=has_accents,
                        has_estonian=has_estonian,
                        status=status,
                        error_message=error_message,
                        cache_status=cache_status,
                        duration_ms=round(duration_ms, 2),
                    )
                    db_sess.add(db_log)
                    db_sess.commit()

                    total_count = db_sess.query(TTSAuditLog).count()
                    if total_count > 1050:
                        oldest_ids = (
                            db_sess.query(TTSAuditLog.id)
                            .order_by(TTSAuditLog.id.asc())
                            .limit(total_count - 1000)
                            .all()
                        )
                        if oldest_ids:
                            del_ids = [row[0] for row in oldest_ids]
                            db_sess.query(TTSAuditLog).filter(TTSAuditLog.id.in_(del_ids)).delete(synchronize_session=False)
                            db_sess.commit()
            except Exception as db_err:
                logger.warning(f"Could not write TTSAuditLog to database: {db_err}")

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(anyio.to_thread.run_sync(_write_db))
        except RuntimeError:
            _write_db()
    except Exception as audit_err:
        logger.warning(f"Failed in log_tts_audit: {audit_err}")


def _synthesize_azure_ssml(ssml: str) -> bytes:
    """Синхронный вызов Azure Speech SDK speak_ssml_async().get() с пулом синтезаторов и синглтоном SpeechConfig."""
    if speechsdk is None:
        raise RuntimeError("azure-cognitiveservices-speech package is not installed.")

    key = settings.AZURE_SPEECH_KEY
    if not key:
        raise RuntimeError("AZURE_SPEECH_KEY is not configured in environment.")

    region = settings.AZURE_SPEECH_REGION or "northeurope"
    speech_config = _get_speech_config(key, region)
    synthesizer = _acquire_synthesizer(speech_config)

    azure_ssml = ssml.replace("ru-RU-SvetlanaMultilingualNeural", "ru-RU-SvetlanaNeural")
    has_accent = "\u0301" in azure_ssml
    accent_words = [w for w in azure_ssml.split() if "\u0301" in w]
    logger.info("=" * 60)
    logger.info(f"[TTS_INTERCEPT] >>> OUTGOING SSML TO AZURE SDK (len={len(azure_ssml)}):")
    logger.info(f"[TTS_INTERCEPT] FINAL SSML PAYLOAD:\n{azure_ssml}")
    logger.info(f"[TTS_INTERCEPT] CONTAINS COMBINING ACUTE (\\u0301): {has_accent}")
    if has_accent:
        logger.info(f"[TTS_INTERCEPT] ACCENTED WORDS: {accent_words}")
    logger.info("=" * 60)
    try:
        result = synthesizer.speak_ssml_async(azure_ssml).get()
    except Exception:
        # При сбое соединения не возвращаем поврежденный инстанс в пул
        raise

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        _release_synthesizer(synthesizer)
        logger.info(f"[TTS_INTERCEPT] Azure Speech SDK completed: {len(result.audio_data)} bytes received")
        return result.audio_data
    elif result.reason == speechsdk.ResultReason.Canceled:
        details = result.cancellation_details
        err_msg = (
            f"Azure Speech synthesis canceled. Reason: {details.reason}, "
            f"ErrorCode: {details.error_code}, Details: {details.error_details}"
        )
        logger.error(err_msg)
        raise RuntimeError(err_msg)
    else:
        raise RuntimeError(f"Azure Speech synthesis failed with reason: {result.reason}")


async def synthesize_estonian_audio_segment(
    text: str, voice: str = ESTONIAN_VOICE, sample_rate: int = 24000
) -> Optional[np.ndarray]:
    """
    Синтезирует эстонский фрагмент текста нативным голосом Microsoft TTS (et-EE-AnuNeural / et-EE-KertNeural).
    Приоритет 1: Azure Speech SDK (если сконфигурирован AZURE_SPEECH_KEY).
    Приоритет 2: Microsoft Edge TTS (edge-tts).
    Возвращает 1D numpy array float32 с частотой sample_rate.
    """
    clean_text = text.strip()
    if not clean_text:
        return None

    # Приоритет 1: Azure Speech SDK
    if speechsdk is not None and getattr(settings, "AZURE_SPEECH_KEY", None):
        try:
            esc_text = clean_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            v_name = voice if "et-EE" in voice else ESTONIAN_VOICE
            ssml = (
                f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="et-EE">'
                f'<voice name="{v_name}"><lang xml:lang="et-EE">{esc_text}</lang></voice></speak>'
            )
            raw_audio = await asyncio.wait_for(
                asyncio.to_thread(_synthesize_azure_ssml, ssml),
                timeout=AZURE_SYNTHESIS_TIMEOUT_SEC,
            )
            if raw_audio and sf is not None:
                data, sr = sf.read(io.BytesIO(raw_audio))
                if sr != sample_rate:
                    import scipy.signal
                    num_samples = int(len(data) * sample_rate / sr)
                    data = scipy.signal.resample(data, num_samples)
                return data.astype(np.float32)
        except Exception as az_err:
            logger.warning(f"[TTS] Azure synthesis for Estonian failed ({az_err}), falling back to edge-tts.")

    # Приоритет 2: Microsoft Edge TTS (edge-tts)
    if edge_tts is not None and sf is not None:
        try:
            v_name = voice if "et-EE" in voice else ESTONIAN_VOICE
            comm = edge_tts.Communicate(clean_text, v_name)
            raw_data = b""
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    raw_data += chunk["data"]
            if raw_data:
                data, sr = sf.read(io.BytesIO(raw_data))
                if sr != sample_rate:
                    import scipy.signal
                    num_samples = int(len(data) * sample_rate / sr)
                    data = scipy.signal.resample(data, num_samples)
                return data.astype(np.float32)
        except Exception as edge_err:
            logger.error(f"[TTS] edge-tts error for Estonian segment {repr(clean_text)}: {edge_err}", exc_info=True)

    return None


def synthesize_russian_audio_segment(
    text: str, speaker: Optional[str] = None, sample_rate: int = 24000
) -> Optional[np.ndarray]:
    """
    Синтезирует русский сегмент текста локальной моделью Silero TTS v5 (голос xenia/kseniya).
    Автоматически применяет нормализатор ударений (apply_stress_overrides).
    При сбое или отсутствии PyTorch выполняет фолбэк на Microsoft Azure/Edge TTS.
    """
    clean_text = text.strip()
    if not clean_text:
        return None

    # Применяем фонетический валидатор (TTS QA-линтер) перед синтезом Silero v5
    stressed_text = validate_and_fix_russian_tts(clean_text)

    # 1. Локальный инференс Silero v5
    if silero_tts.ensure_model_loaded():
        arr = silero_tts.synthesize(stressed_text, speaker=speaker, sample_rate=sample_rate)
        if arr is not None and len(arr) > 0:
            return arr

    # 2. Фолбэк на Azure Speech (если PyTorch недоступен в среде)
    logger.warning(f"[TTS] Silero v5 unavailable, falling back to Microsoft TTS for RU: {repr(clean_text[:40])}")
    if speechsdk is not None and getattr(settings, "AZURE_SPEECH_KEY", None) and sf is not None:
        try:
            esc = clean_display_text(stressed_text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            ssml = (
                f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="ru-RU">'
                f'<voice name="ru-RU-SvetlanaNeural">{esc}</voice></speak>'
            )
            raw_audio = _synthesize_azure_ssml(ssml)
            if raw_audio:
                data, sr = sf.read(io.BytesIO(raw_audio))
                if sr != sample_rate:
                    import scipy.signal
                    num_samples = int(len(data) * sample_rate / sr)
                    data = scipy.signal.resample(data, num_samples)
                return data.astype(np.float32)
        except Exception as az_err:
            logger.error(f"[TTS] Microsoft fallback error for RU: {az_err}")

    return None


async def _synthesize_single_line_stitched(
    text: str,
    voice: str = DEFAULT_VOICE,
    is_speech_text: bool = False,
    sample_rate: int = 24000,
) -> bytes:
    """Синтезирует одну строку текста с микропаузами 180 мс между билингвальными сегментами."""
    clean_text = text.strip()
    if not clean_text:
        return b""

    segments = parse_bilingual_segments(clean_text, is_speech_text=is_speech_text)
    if not segments:
        return b""

    audio_parts: List[np.ndarray] = []
    pause = np.zeros(int(0.18 * sample_rate), dtype=np.float32)

    for seg_text, seg_voice in segments:
        seg_clean = seg_text.strip()
        if not seg_clean:
            continue

        is_est = ("et-EE" in seg_voice or seg_voice == "et" or seg_voice == ESTONIAN_VOICE)
        if is_est:
            part = await synthesize_estonian_audio_segment(seg_clean, voice=seg_voice, sample_rate=sample_rate)
        else:
            part = await asyncio.to_thread(synthesize_russian_audio_segment, seg_clean, sample_rate=sample_rate)

        if part is not None and len(part) > 0:
            if audio_parts:
                audio_parts.append(pause)
            audio_parts.append(part)

    if not audio_parts:
        return b""

    combined = np.concatenate(audio_parts)

    if sf is not None:
        bio = io.BytesIO()
        sf.write(bio, combined, sample_rate, format="MP3")
        return bio.getvalue()

    return b""


async def synthesize_bilingual_stitched_audio(
    text: str,
    voice: str = DEFAULT_VOICE,
    is_speech_text: bool = False,
    sample_rate: int = 24000,
) -> bytes:
    """
    Билингвальная склейка (Bilingual Stitcher):
    1. Если текст состоит из нескольких шагов (разделитель \\n) — синтезирует каждый шаг
       с паузой ровно 500 мс (тишиной) между шагами.
    2. Внутри каждого шага: русские сегменты -> Silero v5, эстонские -> Microsoft TTS (AnuNeural).
    3. Результат кодируется в валидный MP3-буфер.
    """
    clean_text = text.strip()
    if not clean_text:
        return b""

    # Разбиваем текст на шаги либо по переносу строк (\n), либо по маркерам шагов
    # («Шаг первый/второй...», «Шаг 1/2...», «1. ... 2. ...», «(1) ... (2) ...»)
    # Это гарантирует вставку паузы ровно 500 мс между шагами в поле «Как решить задание самому»
    step_split_pat = re.compile(
        r'(?:\r?\n)+|(?<=[.!?…])\s+(?=(?:Шаг\s+[\w\+]+[:.]?|(?:\(?\d+[\.\)]))\s*)',
        re.IGNORECASE
    )
    lines = [l.strip() for l in step_split_pat.split(clean_text) if l and l.strip()]
    if len(lines) > 1:
        step_audio_parts: List[np.ndarray] = []
        step_pause = np.zeros(int(0.5 * sample_rate), dtype=np.float32)  # ровно 500 мс

        for line in lines:
            line_bytes = await _synthesize_single_line_stitched(
                line, voice=voice, is_speech_text=is_speech_text, sample_rate=sample_rate
            )
            if line_bytes and sf is not None:
                data, sr = sf.read(io.BytesIO(line_bytes))
                if sr != sample_rate:
                    import scipy.signal
                    num_samples = int(len(data) * sample_rate / sr)
                    data = scipy.signal.resample(data, num_samples)
                if step_audio_parts:
                    step_audio_parts.append(step_pause)
                step_audio_parts.append(data.astype(np.float32))

        if not step_audio_parts:
            return b""

        combined = np.concatenate(step_audio_parts)
        if sf is not None:
            bio = io.BytesIO()
            sf.write(bio, combined, sample_rate, format="MP3")
            return bio.getvalue()
        return b""

    return await _synthesize_single_line_stitched(
        clean_text, voice=voice, is_speech_text=is_speech_text, sample_rate=sample_rate
    )


async def synthesize_steps_audio(
    steps: List[str],
    voice: str = DEFAULT_VOICE,
    sample_rate: int = 24000,
) -> bytes:
    """
    Склейка составного аудио для шагов решения (аудиогид) с паузой ровно 500 мс (тишиной) между шагами.
    """
    valid_steps = [s.strip() for s in steps if s and s.strip()]
    if not valid_steps:
        return b""

    step_audio_parts: List[np.ndarray] = []
    step_pause = np.zeros(int(0.5 * sample_rate), dtype=np.float32)  # ровно 500 мс

    for step in valid_steps:
        step_bytes = await _synthesize_single_line_stitched(
            step, voice=voice, is_speech_text=True, sample_rate=sample_rate
        )
        if step_bytes and sf is not None:
            data, sr = sf.read(io.BytesIO(step_bytes))
            if sr != sample_rate:
                import scipy.signal
                num_samples = int(len(data) * sample_rate / sr)
                data = scipy.signal.resample(data, num_samples)
            if step_audio_parts:
                step_audio_parts.append(step_pause)
            step_audio_parts.append(data.astype(np.float32))

    if not step_audio_parts:
        return b""

    combined = np.concatenate(step_audio_parts)
    if sf is not None:
        bio = io.BytesIO()
        sf.write(bio, combined, sample_rate, format="MP3")
        return bio.getvalue()
    return b""


async def get_or_synthesize_audio(
    text: str,
    voice: str = DEFAULT_VOICE,
    bilingual: bool = False,
    grade: Optional[int] = None,
    tier: Optional[str] = None,
    is_speech_text: bool = False,
    device_id: Optional[str] = None,
    endpoint: str = "/api/v1/voice/tts",
) -> bytes:
    """
    Получает готовый байтовый буфер аудио (MP3) с единым дисковым кэшем
    (static/audio/cache/{md5}.mp3 + LRU-ротация), RAM-кэшем, жестким таймаутом 10с,
    гарантированной очисткой _IN_FLIGHT_TASKS и персистентным аудитом в logs/tts_audit.log и БД.
    Поддерживает:
    - Silero v5 (русский) + Microsoft TTS (эстонский) с билингвальной склейкой (при TTS_PROVIDER='silero')
    - Прямой Azure SSML пайплайн (при TTS_PROVIDER='microsoft')
    """
    start_time = time.perf_counter()
    use_silero = (getattr(settings, "TTS_PROVIDER", "silero") == "silero")
    cache_status = "SILERO_SYNTHESIS" if use_silero else "AZURE_SYNTHESIS"
    audit_status = "SUCCESS"
    error_msg = None
    ssml = None

    clean_text = text.strip()
    if not clean_text:
        return b""

    try:
        # ВЕТКА 1: Локальный Silero v5 (RU) + Microsoft TTS (ET)
        if use_silero:
            cache_hash = hashlib.md5(
                f"silero_v5:{voice}:{is_speech_text}:{clean_text}".encode("utf-8")
            ).hexdigest()
            ssml = f"<silero_pipeline text={repr(clean_text[:60])} voice={voice} is_speech_text={is_speech_text} />"

            # 1.1 Быстрый возврат из оперативной памяти
            if cache_hash in _TTS_STREAM_CACHE:
                if isinstance(_TTS_STREAM_CACHE, OrderedDict):
                    _TTS_STREAM_CACHE.move_to_end(cache_hash)
                cache_status = "RAM_HIT"
                logger.info(f"[TTS_INTERCEPT] CACHE STATUS: RAM_HIT (hash={cache_hash})")
                return _TTS_STREAM_CACHE[cache_hash]

            # 1.2 Проверка единого локального файлового кэша на диске
            cache_file = AUDIO_CACHE_DIR / f"{cache_hash}.mp3"
            if cache_file.is_file():
                try:
                    if cache_file.stat().st_size >= MIN_VALID_AUDIO_BYTES:
                        cached_bytes = cache_file.read_bytes()
                        if is_valid_mp3_buffer(cached_bytes):
                            try:
                                os.utime(cache_file, None)
                            except OSError:
                                pass
                            cache_status = "DISK_HIT"
                            logger.info(f"[TTS_INTERCEPT] CACHE STATUS: DISK_HIT (hash={cache_hash}, path={cache_file})")
                            _store_in_memory_cache(_TTS_STREAM_CACHE, cache_hash, cached_bytes)
                            return cached_bytes
                except Exception as read_err:
                    logger.warning(f"Failed reading cache file {cache_file}: {read_err}")

            # 1.3 Дедупликация in-flight задач
            existing_task = _IN_FLIGHT_TASKS.get(cache_hash)
            if existing_task is not None and not existing_task.done():
                cache_status = "AWAITING_IN_FLIGHT"
                try:
                    return await asyncio.wait_for(asyncio.shield(existing_task), timeout=AZURE_SYNTHESIS_TIMEOUT_SEC)
                except Exception:
                    _IN_FLIGHT_TASKS.pop(cache_hash, None)

            # 1.4 Синтез через Silero Bilingual Stitcher
            cache_status = "SILERO_SYNTHESIS"
            async def _silero_worker() -> bytes:
                try:
                    sr = getattr(settings, "SILERO_SAMPLE_RATE", 24000)
                    audio_bytes = await synthesize_bilingual_stitched_audio(
                        clean_text, voice=voice, is_speech_text=is_speech_text, sample_rate=sr
                    )
                    if is_valid_mp3_buffer(audio_bytes):
                        try:
                            AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                            cache_file.write_bytes(audio_bytes)
                            _enforce_disk_cache_limits(AUDIO_CACHE_DIR)
                            logger.info(f"[TTS_INTERCEPT] Cached Silero audio to disk: {cache_file} ({len(audio_bytes)} bytes)")
                        except Exception as write_err:
                            logger.warning(f"Failed to write audio cache file {cache_file}: {write_err}")

                        _store_in_memory_cache(_TTS_STREAM_CACHE, cache_hash, audio_bytes)
                        return audio_bytes

                    logger.warning("[TTS] Silero synthesis returned empty audio, attempting Azure SSML fallback...")
                finally:
                    _IN_FLIGHT_TASKS.pop(cache_hash, None)
                return b""

            task = asyncio.create_task(_silero_worker())
            _IN_FLIGHT_TASKS[cache_hash] = task
            task.add_done_callback(lambda _: _IN_FLIGHT_TASKS.pop(cache_hash, None))
            audio_res = await asyncio.wait_for(asyncio.shield(task), timeout=15.0)
            if audio_res and is_valid_mp3_buffer(audio_res):
                return audio_res

        # ВЕТКА 2 (или резервный фолбэк): Azure Speech SSML
        ssml = build_ssml(
            clean_text,
            voice=voice,
            bilingual=bilingual,
            grade=grade,
            tier=tier,
            is_speech_text=is_speech_text,
        )
        if not ssml:
            audit_status = "ERROR"
            error_msg = "build_ssml returned empty SSML"
            return b""
        ssml_hash = hashlib.md5(ssml.encode("utf-8")).hexdigest()

        if ssml_hash in _TTS_STREAM_CACHE:
            if isinstance(_TTS_STREAM_CACHE, OrderedDict):
                _TTS_STREAM_CACHE.move_to_end(ssml_hash)
            cache_status = "RAM_HIT"
            return _TTS_STREAM_CACHE[ssml_hash]

        cache_file = AUDIO_CACHE_DIR / f"{ssml_hash}.mp3"
        if cache_file.is_file():
            try:
                if cache_file.stat().st_size >= MIN_VALID_AUDIO_BYTES:
                    cached_bytes = cache_file.read_bytes()
                    if is_valid_mp3_buffer(cached_bytes):
                        try:
                            os.utime(cache_file, None)
                        except OSError:
                            pass
                        cache_status = "DISK_HIT"
                        _store_in_memory_cache(_TTS_STREAM_CACHE, ssml_hash, cached_bytes)
                        return cached_bytes
            except Exception as read_err:
                logger.warning(f"Failed reading cache file {cache_file}: {read_err}")

        existing_task = _IN_FLIGHT_TASKS.get(ssml_hash)
        if existing_task is not None and not existing_task.done():
            cache_status = "AWAITING_IN_FLIGHT"
            try:
                return await asyncio.wait_for(asyncio.shield(existing_task), timeout=AZURE_SYNTHESIS_TIMEOUT_SEC)
            except Exception:
                _IN_FLIGHT_TASKS.pop(ssml_hash, None)

        cache_status = "AZURE_SYNTHESIS"
        async def _worker() -> bytes:
            try:
                audio_bytes = await asyncio.wait_for(
                    asyncio.to_thread(_synthesize_azure_ssml, ssml),
                    timeout=AZURE_SYNTHESIS_TIMEOUT_SEC,
                )
                if is_valid_mp3_buffer(audio_bytes):
                    try:
                        AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                        cache_file.write_bytes(audio_bytes)
                        _enforce_disk_cache_limits(AUDIO_CACHE_DIR)
                    except Exception as write_err:
                        logger.warning(f"Failed to write audio cache file {cache_file}: {write_err}")

                    _store_in_memory_cache(_TTS_STREAM_CACHE, ssml_hash, audio_bytes)
                return audio_bytes
            finally:
                _IN_FLIGHT_TASKS.pop(ssml_hash, None)

        task = asyncio.create_task(_worker())
        _IN_FLIGHT_TASKS[ssml_hash] = task
        task.add_done_callback(lambda _: _IN_FLIGHT_TASKS.pop(ssml_hash, None))

        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=AZURE_SYNTHESIS_TIMEOUT_SEC)
        finally:
            if task.done():
                _IN_FLIGHT_TASKS.pop(ssml_hash, None)
    except Exception as exc:
        audit_status = "ERROR"
        error_msg = str(exc)
        raise
    finally:
        duration_ms = (time.perf_counter() - start_time) * 1000
        log_tts_audit(
            raw_incoming_text=text,
            final_ssml=ssml,
            endpoint=endpoint,
            is_speech_text=is_speech_text,
            device_id=device_id,
            user_tier=tier,
            grade=grade,
            cache_status=cache_status,
            status=audit_status,
            error_message=error_msg,
            duration_ms=duration_ms,
        )


async def generate_speech_stream(
    text: str,
    voice: str = DEFAULT_VOICE,
) -> AsyncGenerator[bytes, None]:
    """Стримит моно-озвучку порциями по 16 КБ из кэшированного буфера."""
    if not text or not text.strip():
        return

    audio_bytes = await get_or_synthesize_audio(text, voice=voice, bilingual=False)
    chunk_size = 16384
    for i in range(0, len(audio_bytes), chunk_size):
        yield audio_bytes[i:i + chunk_size]


async def generate_bilingual_speech_stream(
    text: str,
) -> AsyncGenerator[bytes, None]:
    """Стримит двуязычную озвучку порциями по 16 КБ из кэшированного буфера."""
    if not text or not text.strip():
        return

    audio_bytes = await get_or_synthesize_audio(text, voice=DEFAULT_VOICE, bilingual=True)
    chunk_size = 16384
    for i in range(0, len(audio_bytes), chunk_size):
        yield audio_bytes[i:i + chunk_size]
