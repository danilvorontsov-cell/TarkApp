import asyncio
import hashlib
import logging
from pathlib import Path
import re
from typing import AsyncGenerator, Dict, List, Optional, Tuple

try:
    import azure.cognitiveservices.speech as speechsdk
except ImportError:
    speechsdk = None

from app.config import settings

logger = logging.getLogger(__name__)

# Supported voice mappings for Azure Speech Services
DEFAULT_VOICE = "ru-RU-SvetlanaNeural"
ESTONIAN_VOICE = "et-EE-AnuNeural"

VOICE_MAP: Dict[str, str] = {
    "ru": DEFAULT_VOICE,
    "et": ESTONIAN_VOICE,
    "ru-RU-SvetlanaMultilingualNeural": DEFAULT_VOICE,
    "ru-RU-SvetlanaNeural": DEFAULT_VOICE,
    "et-EE-AnuNeural": ESTONIAN_VOICE,
    "et-EE-KertNeural": "et-EE-KertNeural",
}

# Disk and memory caching
AUDIO_CACHE_DIR = Path("static/audio/cache")
try:
    AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

_TTS_STREAM_CACHE: Dict[str, bytes] = {}
MAX_CACHE_ENTRIES = 500
MIN_VALID_AUDIO_BYTES = 4096

# Registry of active in-flight tasks for deduplication of simultaneous requests
_IN_FLIGHT_TASKS: Dict[str, asyncio.Task[bytes]] = {}


def _store_in_memory_cache(cache: Dict[str, bytes], key: str, data: bytes) -> None:
    if len(cache) >= MAX_CACHE_ENTRIES:
        # FIFO eviction of oldest 20%
        keys_to_remove = list(cache.keys())[: max(1, MAX_CACHE_ENTRIES // 5)]
        for k in keys_to_remove:
            cache.pop(k, None)
    cache[key] = data


# Re-export normalization architecture from dedicated tts_normalizer module
from app.services.tts_normalizer import (
    TERMINOLOGY_MAP,
    CUSTOM_PHONETIC_MAP,
    apply_custom_phonetic_map,
    ENGLISH_BRANDS,
    normalize_loanwords_and_brands,
    normalize_time_expressions,
    int_to_russian_cardinal,
    int_to_russian_nominative,
    normalize_math_expressions,
    normalize_roman_numerals,
    normalize_number_ranges,
    normalize_russian_ordinals_with_dot,
    normalize_russian_accents_and_yo,
    normalize_text_for_estonian_tts,
    normalize_estonian_measurement_units,
    clean_text_for_speech,
    prepare_speech_text,
    normalize_text_for_speech,
    prepare_worked_example_speech,
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
            if segments and segments[-1][1] == DEFAULT_VOICE:
                prev_text, prev_voice = segments[-1]
                segments[-1] = (f"{prev_text}{s_clean}", prev_voice)
            continue

        if segments and segments[-1][1] == s_voice:
            prev_text, prev_voice = segments[-1]
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


def parse_bilingual_segments(text: str) -> List[Tuple[str, str]]:
    """
    Разбивает двуязычный текст на последовательные сегменты (текст, голос):
    - Приоритет 1: Фрагменты внутри тегов <est>...</est> отправляются эстонскому диктору (et-EE-AnuNeural).
    - Приоритет 2: Фразы на эстонском языке в кавычках или термины в скобках без кириллицы.
    - Весь остальной текст (русский язык + свободная английская латиница Minecraft, Roblox, W/A/S/D)
      озвучивается русским голосом (ru-RU-SvetlanaMultilingualNeural).
    - Если во всем тексте нет кириллицы (чистый эстонский текст) — отправляется эстонскому диктору.
    """
    if not text or not text.strip():
        return [(text or "", DEFAULT_VOICE)]

    text = normalize_text_for_speech(text, is_russian_context=True)

    # 1. Если во всём тексте нет кириллицы вообще — озвучиваем целиком эстонским диктором
    if not re.search(r'[а-яА-ЯёЁ]', text):
        clean_est = normalize_text_for_estonian_tts(text.strip())
        return [(clean_est or text.strip(), ESTONIAN_VOICE)]

    # 2. Ищем эстонские фрагменты в русском тексте
    pattern = re.compile(
        r'<\s*est(?:\s+[^>]*)?>(.*?)<\s*/\s*est\s*>'
        r'|[\'\"«“]([a-zA-ZäöüõÄÖÜÕšžŠŽ0-9\s\.,\?!-]{2,})[\'\"»”]'
        r'|\(([a-zA-ZäöüõÄÖÜÕšžŠŽ0-9\s\.,\?!-]{2,})\)',
        re.DOTALL
    )

    matches: List[Tuple[int, int, str]] = []
    for m in pattern.finditer(text):
        tag_val = m.group(1)
        quote_val = m.group(2)
        paren_val = m.group(3)

        if tag_val is not None:
            clean = tag_val.strip()
            if clean:
                matches.append((m.start(), m.end(), clean))
        elif quote_val is not None:
            val = quote_val.strip()
            if val and not _is_pure_english_brand_or_key(val):
                matches.append((m.start(), m.end(), val))
        elif paren_val is not None:
            val = paren_val.strip()
            if val and not _is_pure_english_brand_or_key(val):
                matches.append((m.start(), m.end(), val))

    if not matches:
        return [(text.strip(), DEFAULT_VOICE)]

    raw_segments: List[Tuple[str, str]] = []
    last_idx = 0

    for start, end, est_content in matches:
        if start > last_idx:
            prefix = text[last_idx:start]
            clean_prefix = prefix.rstrip(' ([«"“„')
            if clean_prefix:
                raw_segments.append((clean_prefix, DEFAULT_VOICE))

        clean_est = normalize_text_for_estonian_tts(est_content)
        if clean_est:
            raw_segments.append((clean_est, ESTONIAN_VOICE))

        trailing_wrapper = re.match(r'^[\s)\]»"”„]*', text[end:])
        if trailing_wrapper:
            last_idx = end + trailing_wrapper.end()
        else:
            last_idx = end

    if last_idx < len(text):
        suffix = text[last_idx:]
        clean_suffix = suffix.strip(' .')
        if clean_suffix:
            raw_segments.append((clean_suffix, DEFAULT_VOICE))

    return _stitch_and_clean_segments(raw_segments, text)


def _escape_ssml(text: str) -> str:
    """Экранирует специальные символы XML для корректного SSML."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def build_ssml(text: str, voice: str = DEFAULT_VOICE, bilingual: bool = False) -> str:
    """
    Формирует единый SSML-документ для одного запроса к Azure Speech Services:
    - Голос по умолчанию: ru-RU-SvetlanaNeural.
    - Эстонские фрагменты (слова, термины, предложения на эстонском) оборачиваются в <lang xml:lang="et-EE">...</lang>.
    - Числительные внутри эстонского контекста оборачиваются в <say-as interpret-as="cardinal">...</say-as>.
    - Английские термины и названия брендов (Lego Mindstorms, Minecraft и т.д.) оборачиваются в <lang xml:lang="en-US">...</lang>.
    - Клавиши управления / аббревиатуры (WASD, W, A, S, D) оборачиваются в <say-as interpret-as="characters">W A S D</say-as>.
    - Если voice explicitly Estonian ("et" или "et-EE..."), синтезируется голос et-EE-AnuNeural.
    """
    clean_text = clean_text_for_speech(text)
    if not clean_text:
        return ""

    has_est_tag = bool(re.search(r'<\s*est(?:\s+[^>]*)?>', clean_text, re.IGNORECASE))

    if bilingual or has_est_tag:
        segments = parse_bilingual_segments(clean_text)
    elif "et-EE" in voice or voice == "et":
        if re.search(r'[а-яА-ЯёЁ]', clean_text) and not re.search(r'[a-zA-ZäöüõÄÖÜÕšžŠŽ]', clean_text):
            norm_text = normalize_text_for_speech(clean_text, is_russian_context=True)
            segments = [(norm_text, DEFAULT_VOICE)]
        elif re.search(r'[а-яА-ЯёЁ]', clean_text):
            segments = parse_bilingual_segments(clean_text)
        else:
            clean_est = normalize_text_for_estonian_tts(clean_text)
            segments = [(clean_est, ESTONIAN_VOICE)]
    else:
        if not re.search(r'[а-яА-ЯёЁ]', clean_text) and not _is_pure_english_brand_or_key(clean_text):
            clean_est = normalize_text_for_estonian_tts(clean_text)
            segments = [(clean_est, ESTONIAN_VOICE)]
        else:
            norm_text = normalize_text_for_speech(clean_text, is_russian_context=True)
            segments = [(norm_text, DEFAULT_VOICE)]

    is_all_est = all("et-EE" in v or v == "et" for _, v in segments)

    # Если весь документ чисто эстонский (например, быстрый переводчик или чисто эстонский текст)
    if is_all_est and ("et-EE" in voice or voice == "et" or not re.search(r'[а-яА-ЯёЁ]', clean_text)):
        root_voice = ESTONIAN_VOICE
        root_lang = "et-EE"
        body_parts = []
        for seg_text, _ in segments:
            s_clean = seg_text.strip()
            if not s_clean:
                continue
            s_clean = re.sub(r'(?<=[a-zA-ZõäöüÕÄÖÜšžŠŽ0-9])\s*/\s*(?=[a-zA-ZõäöüÕÄÖÜšžŠŽ0-9])', ' või ', s_clean)
            s_clean = re.sub(r'\s+/\s+', ' või ', s_clean)
            esc = _escape_ssml(s_clean)
            esc = re.sub(
                r'\b(\d+)\b(?!\s*-(?:ga|ni|st|le|lt|sse|s|l|ks|na|ta)\b)',
                r'<say-as interpret-as="cardinal">\1</say-as>',
                esc,
            )
            body_parts.append(esc)
        inner_content = add_ssml_sentence_breaks(" ".join(body_parts))
        return (
            '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
            'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="et-EE">\n'
            f'  <voice name="{root_voice}">{inner_content}</voice>\n'
            '</speak>'
        )

    # Иначе: двуязычный / русский документ с явным переключением <voice> между ru-RU и et-EE
    root_lang = "ru-RU"

    # Выделяем ключевые эстонские термины из русских фрагментов в отдельные блоки эстонского диктора
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

    final_segments = _stitch_and_clean_segments(expanded_segments, clean_text)

    voice_blocks: List[str] = []
    for seg_text, seg_voice in final_segments:
        s_clean = seg_text.strip()
        if not s_clean:
            continue

        if "et-EE" in seg_voice or seg_voice == "et":
            # Эстонский фрагмент -> et-EE-AnuNeural
            s_clean = re.sub(r'(?<=[a-zA-ZõäöüÕÄÖÜšžŠŽ0-9])\s*/\s*(?=[a-zA-ZõäöüÕÄÖÜšžŠŽ0-9])', ' või ', s_clean)
            s_clean = re.sub(r'\s+/\s+', ' või ', s_clean)
            esc = _escape_ssml(s_clean)
            # Эстонские числительные: <say-as interpret-as="cardinal">
            esc = re.sub(
                r'\b(\d+)\b(?!\s*-(?:ga|ni|st|le|lt|sse|s|l|ks|na|ta)\b)',
                r'<say-as interpret-as="cardinal">\1</say-as>',
                esc,
            )
            esc = add_ssml_sentence_breaks(esc)
            voice_blocks.append(f'  <voice name="{ESTONIAN_VOICE}"><lang xml:lang="et-EE">{esc}</lang></voice>')
        else:
            # Русский фрагмент -> ru-RU-SvetlanaNeural
            s_clean = re.sub(r'(?<=[а-яА-ЯёЁ0-9a-zA-Z])\s*/\s*(?=[а-яА-ЯёЁ0-9a-zA-Z])', ' или ', s_clean)
            s_clean = re.sub(r'\s+/\s+', ' или ', s_clean)
            s_norm = prepare_speech_text(s_clean)
            esc = _escape_ssml(s_norm)

            # Оборачиваем английские бренды в <lang xml:lang="en-US">
            for brand in ENGLISH_BRANDS:
                p_brand = re.compile(rf'\b{re.escape(brand)}\b', re.IGNORECASE)
                esc = p_brand.sub(f'<lang xml:lang="en-US">{brand}</lang>', esc)

            # Оборачиваем клавиши WASD в <say-as interpret-as="characters">W A S D</say-as>
            p_wasd = re.compile(r'\b(?:WASD|W,\s*A,\s*S,\s*D|W\s+A\s+S\s+D)\b', re.IGNORECASE)
            esc = p_wasd.sub('<say-as interpret-as="characters">W A S D</say-as>', esc)

            esc = add_ssml_sentence_breaks(esc)
            voice_blocks.append(f'  <voice name="{DEFAULT_VOICE}">{esc}</voice>')

    if voice_blocks and re.search(r'[.!?:]\s*$', clean_text):
        last_b = voice_blocks[-1]
        if not re.search(r'<break\b[^>]*\/>\s*<\/voice>$', last_b):
            voice_blocks[-1] = re.sub(r'<\/voice>$', r'. <break time="500ms" /></voice>', last_b)

    joined_voices = "\n".join(voice_blocks)
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="{root_lang}">\n'
        f'{joined_voices}\n'
        f'</speak>'
    )


def _synthesize_azure_ssml(ssml: str) -> bytes:
    """Синхронный вызов Azure Speech SDK speak_ssml_async().get() для выполнения в отдельном потоке."""
    if speechsdk is None:
        raise RuntimeError("azure-cognitiveservices-speech package is not installed.")

    key = settings.AZURE_SPEECH_KEY
    if not key:
        raise RuntimeError("AZURE_SPEECH_KEY is not configured in environment.")

    region = settings.AZURE_SPEECH_REGION or "northeurope"

    speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio16Khz128KBitRateMonoMp3
    )

    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    # Ensure Azure API receives canonical voice identifier if requested via Multilingual alias
    azure_ssml = ssml.replace("ru-RU-SvetlanaMultilingualNeural", "ru-RU-SvetlanaNeural")
    result = synthesizer.speak_ssml_async(azure_ssml).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
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


async def get_or_synthesize_audio(
    text: str,
    voice: str = DEFAULT_VOICE,
    bilingual: bool = False,
) -> bytes:
    """
    Получает готовый байтовый буфер аудио (MP3) с локальным файловым кэшированием на диске
    (static/audio/cache/{md5}.mp3), оперативным кэшем и дедупликацией одновременных in-flight запросов.
    Генерация выполняется за один запрос к Azure SpeechSynthesizer через SSML.
    """
    clean_text = text.strip()
    if not clean_text:
        return b""

    # Строим итоговый SSML
    ssml = build_ssml(clean_text, voice=voice, bilingual=bilingual)
    ssml_hash = hashlib.md5(ssml.encode("utf-8")).hexdigest()

    # 1. Быстрый возврат из оперативной памяти
    if ssml_hash in _TTS_STREAM_CACHE:
        logger.info(f"Serving TTS from RAM cache (md5={ssml_hash[:10]}...)")
        return _TTS_STREAM_CACHE[ssml_hash]

    # 2. Проверка локального файлового кэша на диске
    cache_file = AUDIO_CACHE_DIR / f"{ssml_hash}.mp3"
    if cache_file.is_file():
        try:
            cached_size = cache_file.stat().st_size
            if cached_size < MIN_VALID_AUDIO_BYTES:
                logger.warning(
                    f"Purging corrupted/truncated audio cache file {cache_file} (size={cached_size} bytes)"
                )
                cache_file.unlink(missing_ok=True)
            else:
                cached_bytes = cache_file.read_bytes()
                if len(cached_bytes) >= MIN_VALID_AUDIO_BYTES:
                    logger.info(f"Serving TTS from disk cache: {cache_file} (md5={ssml_hash[:10]}...)")
                    _store_in_memory_cache(_TTS_STREAM_CACHE, ssml_hash, cached_bytes)
                    return cached_bytes
        except Exception as read_err:
            logger.warning(f"Failed reading cache file {cache_file}: {read_err}")

    # 3. Дедупликация: если для этого SSML уже запущен запрос, ожидаем текущую задачу
    if ssml_hash in _IN_FLIGHT_TASKS:
        logger.info(f"Awaiting in-flight Azure Speech task for md5={ssml_hash[:10]}...")
        try:
            return await _IN_FLIGHT_TASKS[ssml_hash]
        except Exception:
            pass

    # 4. Синтез через Azure Speech SDK в фоновом пуле потоков
    async def _worker() -> bytes:
        logger.info(f"Synthesizing audio via Azure Speech SDK (md5={ssml_hash[:10]}...)")
        audio_bytes = await asyncio.to_thread(_synthesize_azure_ssml, ssml)
        if audio_bytes and len(audio_bytes) >= MIN_VALID_AUDIO_BYTES:
            # Сохраняем в кэш на диск
            try:
                AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache_file.write_bytes(audio_bytes)
                logger.info(f"Cached audio to disk: {cache_file} ({len(audio_bytes)} bytes)")
            except Exception as write_err:
                logger.warning(f"Failed to write audio cache file {cache_file}: {write_err}")

            # Сохраняем в память
            _store_in_memory_cache(_TTS_STREAM_CACHE, ssml_hash, audio_bytes)
        return audio_bytes

    task = asyncio.create_task(_worker())
    _IN_FLIGHT_TASKS[ssml_hash] = task

    try:
        audio_result = await task
        return audio_result
    finally:
        _IN_FLIGHT_TASKS.pop(ssml_hash, None)


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
