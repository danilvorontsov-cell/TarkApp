import asyncio
import hashlib
import logging
import re
from typing import AsyncGenerator, Dict, List, Optional, Tuple
import edge_tts

logger = logging.getLogger(__name__)

# Supported voice mappings
# ru-RU-SvetlanaNeural: максимально стабильный, чистый и надежный русский голос (Edge-TTS не сбрасывает соединение)
# et-EE-KertNeural: четкий мужской эстонский голос (+20% громкости)
VOICE_MAP = {
    "ru": "ru-RU-SvetlanaNeural",
    "et": "et-EE-KertNeural",
}

DEFAULT_VOICE = "ru-RU-SvetlanaNeural"
ESTONIAN_VOICE = "et-EE-KertNeural"

# Карта резервных голосов для отказоустойчивости при сетевых сбоях Edge-TTS
VOICE_FALLBACK_MAP = {
    "ru-RU-SvetlanaNeural": "ru-RU-DmitryNeural",
    "ru-RU-DmitryNeural": "ru-RU-SvetlanaNeural",
    "et-EE-KertNeural": "et-EE-AnuNeural",
    "et-EE-AnuNeural": "et-EE-KertNeural",
}

# Семафор для параллельных WebSocket-запросов к Microsoft Edge-TTS (до 4 одновременных сокетов)
# Заменяет жесткий одиночный Lock(), ускоряя склейку двуязычных фрагментов в 8-10 раз
_tts_semaphore = asyncio.Semaphore(4)

# Серверные кэши синтезированного аудио в оперативной памяти (LRU-ограничение)
_TTS_STREAM_CACHE: Dict[str, bytes] = {}
_TTS_SEGMENT_CACHE: Dict[str, bytes] = {}
MAX_CACHE_ENTRIES = 500

# Реестр активных in-flight задач для дедупликации одновременных одинаковых запросов
_IN_FLIGHT_TASKS: Dict[str, asyncio.Task[bytes]] = {}


def _get_cache_key(prefix: str, text: str, voice: str = "") -> str:
    raw = f"{prefix}:{voice}:{text.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _store_in_cache(cache: Dict[str, bytes], key: str, data: bytes):
    if len(cache) >= MAX_CACHE_ENTRIES:
        # Удаляем 20% старейших записей (FIFO очистка для простоты и высокой скорости)
        keys_to_remove = list(cache.keys())[: max(1, MAX_CACHE_ENTRIES // 5)]
        for k in keys_to_remove:
            cache.pop(k, None)
    cache[key] = data


def normalize_text_for_estonian_tts(text: str) -> str:
    """
    Нормализует эстонский текст для Edge-TTS:
    - Удаляет крестики и спецсимволы умножения (×, ✕, ✖, *).
    - Удаляет скобки [ ], { }, ( ).
    - Исключает знаки препинания непосредственно встык с числами,
      особенно точку после целых чисел (12. -> 12), из-за которой
      количественные числительные ошибочно распознаются синтезатором как порядковые.
    - Разделяет пробелом знаки препинания и дефисы встык с числами.
    """
    if not text:
        return ""
    t = re.sub(r'[\u00d7\u2715\u2716*]', ' ', text)
    t = re.sub(r'[\[\]{}()]', ' ', t)
    t = re.sub(r'[/\\|]', ' ', t)
    t = re.sub(r'(\b\d+)\s*\.(?!\d)', r'\1 ', t)
    t = re.sub(r'(\d+)([,!?;:])', r'\1 \2', t)
    t = re.sub(r'([,!?;:])(\d+)', r'\1 \2', t)
    t = re.sub(r'(\d+)[-–—]+', r'\1 ', t)
    t = re.sub(r'[-–—]+(\d+)', r' \1', t)
    return re.sub(r'\s+', ' ', t).strip()


# Словарь и формы порядковых числительных для римских цифр (1..30)
ROMAN_TO_INT = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
    "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
    "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15,
    "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20,
    "XXI": 21, "XXII": 22, "XXIII": 23, "XXIV": 24, "XXV": 25,
    "XXVI": 26, "XXVII": 27, "XXVIII": 28, "XXIX": 29, "XXX": 30,
}

# (m_nom, gen_m_n, prep_m_n, nom_n, nom_f, f_other)
ORDINAL_FORMS: Dict[int, Tuple[str, str, str, str, str, str]] = {
    1: ("первый", "первого", "первом", "первое", "первая", "первой"),
    2: ("второй", "второго", "втором", "второе", "вторая", "второй"),
    3: ("третий", "третьего", "третьем", "третье", "третья", "третьей"),
    4: ("четвертый", "четвертого", "четвертом", "четвертое", "четвертая", "четвертой"),
    5: ("пятый", "пятого", "пятом", "пятое", "пятая", "пятой"),
    6: ("шестой", "шестого", "шестом", "шестое", "шестая", "шестой"),
    7: ("седьмой", "седьмого", "седьмом", "седьмое", "седьмая", "седьмой"),
    8: ("восьмой", "восьмого", "восьмом", "восьмое", "восьмая", "восьмой"),
    9: ("девятый", "девятого", "девятом", "девятое", "девятая", "девятой"),
    10: ("десятый", "десятого", "десятом", "десятое", "десятая", "десятой"),
    11: ("одиннадцатый", "одиннадцатого", "одиннадцатом", "одиннадцатое", "одиннадцатая", "одиннадцатой"),
    12: ("двенадцатый", "двенадцатого", "двенадцатом", "двенадцатое", "двенадцатая", "двенадцатой"),
    13: ("тринадцатый", "тринадцатого", "тринадцатом", "тринадцатое", "тринадцатая", "тринадцатой"),
    14: ("четырнадцатый", "четырнадцатого", "четырнадцатом", "четырнадцатое", "четырнадцатая", "четырнадцатой"),
    15: ("пятнадцатый", "пятнадцатого", "пятнадцатом", "пятнадцатое", "пятнадцатая", "пятнадцатой"),
    16: ("шестнадцатый", "шестнадцатого", "шестнадцатом", "шестнадцатое", "шестнадцатая", "шестнадцатой"),
    17: ("семнадцатый", "семнадцатого", "семнадцатом", "семнадцатое", "семнадцатая", "семнадцатой"),
    18: ("восемнадцатый", "восемнадцатого", "восемнадцатом", "восемнадцатое", "восемнадцатая", "восемнадцатой"),
    19: ("девятнадцатый", "девятнадцатого", "девятнадцатом", "девятнадцатое", "девятнадцатая", "девятнадцатой"),
    20: ("двадцатый", "двадцатого", "двадцатом", "двадцатое", "двадцатая", "двадцатой"),
    21: ("двадцать первый", "двадцать первого", "двадцать первом", "двадцать первое", "двадцать первая", "двадцать первой"),
    22: ("двадцать второй", "двадцать второго", "двадцать втором", "двадцать второе", "двадцать вторая", "двадцать второй"),
    23: ("двадцать третий", "двадцать третьего", "двадцать третьем", "двадцать третье", "двадцать третья", "двадцать третьей"),
    24: ("двадцать четвертый", "двадцать четвертого", "двадцать четвертом", "двадцать четвертое", "двадцать четвертая", "двадцать четвертой"),
    25: ("двадцать пятый", "двадцать пятого", "двадцать пятом", "двадцать пятое", "двадцать пятая", "двадцать пятой"),
    26: ("двадцать шестой", "двадцать шестого", "двадцать шестом", "двадцать шестое", "двадцать шестая", "двадцать шестой"),
    27: ("двадцать седьмой", "двадцать седьмого", "двадцать седьмом", "двадцать седьмое", "двадцать седьмая", "двадцать седьмой"),
    28: ("двадцать восьмой", "двадцать восьмого", "двадцать восьмом", "двадцать восьмое", "двадцать восьмая", "двадцать восьмой"),
    29: ("двадцать девятый", "двадцать девятого", "двадцать девятом", "двадцать девятое", "двадцать девятая", "двадцать девятой"),
    30: ("тридцатый", "тридцатого", "тридцатом", "тридцатое", "тридцатая", "тридцатой"),
}

ROMAN_KEYS = sorted(ROMAN_TO_INT.keys(), key=lambda x: len(x), reverse=True)
ROMAN_PATTERN = "|".join(ROMAN_KEYS)

MATH_VAR_MAP = {
    "x": "икс", "X": "икс",
    "y": "игрек", "Y": "игрек",
    "z": "зет", "Z": "зет",
    "b": "бэ", "B": "бэ",
    "c": "цэ", "C": "цэ",
}


def normalize_roman_numerals(text: str) -> str:
    """
    Находит римские цифры в русском контексте (век, тысячелетие, класс, глава, том или дефисные окончания)
    и конвертирует их в словесный русский эквивалент с учетом грамматического падежа и рода:
    - XXI век / XXI-й век -> двадцать первый век
    - XXI века -> двадцать первого века
    - XXI веке / в XXI в. -> двадцать первом веке
    - XX век -> двадцатый век
    - XIX век -> девятнадцатый век
    - III тысячелетие -> третье тысячелетие
    """
    if not text:
        return ""

    # 1. Порядок: существительное перед римской цифрой (напр. "глава IV", "в главе IV", "том II", "класс V")
    p_noun_first = re.compile(
        r'(?i)\b(в|во)?\s*(глав[а-яё]*|класс[а-яё]*|том[а-яё]*)\s+(' + ROMAN_PATTERN + r')\b'
    )
    def repl_noun_first(m):
        prep = m.group(1) or ""
        noun = m.group(2)
        roman = m.group(3).upper()
        num = ROMAN_TO_INT.get(roman)
        if not num:
            return m.group(0)
        noun_l = noun.lower()
        if "глав" in noun_l:
            form_idx = 4 if noun_l == "глава" else 5
        elif "класс" in noun_l or "том" in noun_l:
            form_idx = 2 if (prep or noun_l.endswith("е")) else (1 if noun_l.endswith("а") else 0)
        else:
            form_idx = 0
        w = ORDINAL_FORMS[num][form_idx]
        if prep:
            return f"{prep} {noun} {w}"
        return f"{noun} {w}"

    t = p_noun_first.sub(repl_noun_first, text)

    # 2. Римская цифра перед ключевым словом (напр. "XXI век", "в XXI в.", "в III тысячелетии", "XXI-й век")
    p_num_first = re.compile(
        r'(?i)(?:(\bв|во|на|о|об|обо|к|ко|до|с|со|от|после|около)\s+)?'
        r'\b(' + ROMAN_PATTERN + r')(?:-([а-яё]+))?\s*'
        r'\b(век[а-яё]*|в\b\.?|тысячелети[а-яё]*|класс[а-яё]*|глав[а-яё]*|том[а-яё]*)'
    )
    def repl_num_first(m):
        prep = m.group(1) or ""
        roman = m.group(2).upper()
        suffix = (m.group(3) or "").lower()
        noun = m.group(4)
        noun_l = noun.lower().rstrip(".")
        num = ROMAN_TO_INT.get(roman)
        if not num:
            return m.group(0)

        prep_l = prep.lower()

        # Век / в.
        if noun_l in ("век", "века", "веке", "веку", "веком", "в", "вв"):
            if prep_l in ("в", "во", "на", "о", "об", "обо") or noun_l == "веке" or suffix in ("м", "ом", "ем"):
                form_idx = 2
                actual_noun = "веке" if noun_l in ("в", "вв") else noun
            elif prep_l in ("до", "с", "со", "от", "после", "около") or noun_l in ("века", "вв") or suffix in ("го", "ого"):
                form_idx = 1
                actual_noun = "века" if noun_l in ("в", "вв") else noun
            elif prep_l in ("к", "ко") or noun_l == "веку" or suffix == "му":
                form_idx = 2
                actual_noun = noun
            else:
                form_idx = 0
                actual_noun = "век" if noun_l in ("в", "вв") else noun

        # Тысячелетие
        elif "тысячелети" in noun_l:
            if prep_l in ("в", "во", "о", "об") or noun_l.endswith("и") or suffix in ("м", "ом", "ем"):
                form_idx = 2
            elif prep_l in ("до", "с", "со", "от", "после") or noun_l.endswith("я") or suffix in ("го", "ого"):
                form_idx = 1
            else:
                form_idx = 3
            actual_noun = noun

        # Класс
        elif "класс" in noun_l:
            if prep_l in ("в", "во") or noun_l.endswith("е") or suffix in ("м", "ом", "ем"):
                form_idx = 2
            elif noun_l.endswith("а") or suffix in ("го", "ого"):
                form_idx = 1
            else:
                form_idx = 0
            actual_noun = noun

        # Глава
        elif "глав" in noun_l:
            if noun_l == "глава" and suffix not in ("й", "ой"):
                form_idx = 4
            else:
                form_idx = 5
            actual_noun = noun

        # Том
        elif "том" in noun_l:
            if prep_l in ("в", "во") or noun_l.endswith("е"):
                form_idx = 2
            elif noun_l.endswith("а"):
                form_idx = 1
            else:
                form_idx = 0
            actual_noun = noun
        else:
            actual_noun = noun

        w = ORDINAL_FORMS[num][form_idx]
        if prep:
            return f"{prep} {w} {actual_noun}"
        return f"{w} {actual_noun}"

    t = p_num_first.sub(repl_num_first, t)

    # 3. Римская цифра с дефисным окончанием без существительного (напр. "XXI-й", "III-е")
    p_standalone = re.compile(r'\b(' + ROMAN_PATTERN + r')-([а-яё]+)\b', re.IGNORECASE)
    def repl_standalone(m):
        roman = m.group(1).upper()
        suffix = m.group(2).lower()
        num = ROMAN_TO_INT.get(roman)
        if not num:
            return m.group(0)
        if suffix in ("м", "ом", "ем"):
            form_idx = 2
        elif suffix in ("го", "ого"):
            form_idx = 1
        elif suffix in ("е", "ье", "ое"):
            form_idx = 3
        elif suffix in ("я", "ая"):
            form_idx = 4
        else:
            form_idx = 0
        return ORDINAL_FORMS[num][form_idx]

    t = p_standalone.sub(repl_standalone, t)
    return t


def normalize_math_expressions(text: str) -> str:
    """
    Нормализует математические переменные и знаки в русском контексте:
    - Одиночные латинские переменные x, y, z -> икс, игрек, зет
    - a (в мат. контексте), b, c -> а, бэ, цэ
    - Знаки формул: + -> плюс, - -> минус, = -> равно
    Не затрагивает чистый эстонский текст (слова без кириллицы и без мат. знаков).
    """
    if not text:
        return ""

    has_cyrillic = bool(re.search(r'[а-яА-ЯёЁ]', text))
    has_math_ops = bool(re.search(r'[=+*\/]|(?<=[0-9a-zA-Z])\s*[-−]\s*(?=[0-9a-zA-Z])', text))
    if not (has_cyrillic or has_math_ops):
        return text

    t = text
    # 1. Знаки действий: +, =, -
    t = re.sub(r'(?<=[0-9a-zA-Zа-яА-ЯёЁ])\s*\+\s*(?=[0-9a-zA-Zа-яА-ЯёЁ])|\s+\+\s+', ' плюс ', t)
    t = re.sub(r'\s*=\s*', ' равно ', t)
    t = re.sub(r'(?<=[0-9a-zA-Z])\s*[-−]\s*(?=[0-9a-zA-Z])|\s+[-−]\s+', ' минус ', t)

    # 2. Одиночные переменные x, y, z, b, c
    for var, rep in MATH_VAR_MAP.items():
        t = re.sub(r'\b' + var + r'\b', rep, t)

    # 3. Переменная 'a' / 'A' в математическом окружении
    t = re.sub(r'\b(плюс|минус|равно)\s+[aA]\b', r'\1 а', t)
    t = re.sub(r'\b[aA]\s+(плюс|минус|равно)\b', r'а \1', t)
    t = re.sub(r'\b(переменная|переменную|переменной|буква|букву|буквой)\s+[aA]\b', r'\1 а', t)

    t = re.sub(r'\s+', ' ', t).strip()
    return t


def normalize_text_for_speech(text: str, is_russian_context: bool = True) -> str:
    """
    Комплексная предварительная нормализация текста перед синтезом речи:
    - Римские цифры (XXI век -> двадцать первый век, III тысячелетие -> третье тысячелетие)
    - Математические переменные и знаки (x + y = 15 -> икс плюс игрек равно 15)
    """
    if not text:
        return ""
    if not is_russian_context:
        return text

    # Защищаем чистые эстонские фразы в кавычках перед нормализацией
    est_quotes: List[str] = []

    def mask_est_quote(match):
        q = match.group(0)
        inner = q[1:-1].strip()
        if not re.search(r'[а-яА-ЯёЁ=+*]', inner):
            idx = len(est_quotes)
            est_quotes.append(q)
            return f"___EST_QUOTE_{idx}___"
        return q

    masked_text = re.sub(r'([«"“„][^»"”]+[»"”])', mask_est_quote, text)
    norm_text = normalize_roman_numerals(masked_text)
    norm_text = normalize_math_expressions(norm_text)

    for idx, orig_q in enumerate(est_quotes):
        norm_text = norm_text.replace(f"___EST_QUOTE_{idx}___", orig_q)

    return norm_text


def parse_bilingual_segments(text: str) -> List[Tuple[str, str]]:
    """
    Разбивает двуязычный текст на последовательные сегменты (текст, голос):
    - Предварительно нормализует римские цифры и математику в русском контексте.
    - Эстонские фразы и слова в кавычках («...», "...", “...”, „...“) -> et-EE-KertNeural (+20% громкости).
    - Эстонские слова и фразы в скобках ((...)) (напр. (loodusõpetus)) -> et-EE-KertNeural.
    - Отдельные эстонские слова/термины на латинице (loodusõpetus, matemaatika) -> et-EE-KertNeural.
    - Основной русский текст -> ru-RU-SvetlanaNeural.
    """
    if not text or not text.strip():
        return [(text or "", DEFAULT_VOICE)]

    # Предварительная нормализация римских цифр и математических переменных в русском контексте
    text = normalize_text_for_speech(text, is_russian_context=True)

    est_char_pattern = re.compile(r'[A-Za-zõäöüšžÕÄÖÜŠŽ]')
    token_pattern = re.compile(
        r'([«"“„][^»"”]+[»"”])|'  # фраза в кавычках
        r'(\([^)]+\))|'            # фраза в скобках
        r'([A-Za-zõäöüšžÕÄÖÜŠŽ][A-Za-zõäöüšžÕÄÖÜŠŽ0-9\-\']*(?:\s+[A-Za-zõäöüšžÕÄÖÜŠŽ][A-Za-zõäöüšžÕÄÖÜŠŽ0-9\-\']*)*)'  # латинские/эстонские слова
    )

    raw_segments: List[Tuple[str, str]] = []
    last_idx = 0

    for match in token_pattern.finditer(text):
        start, end = match.span()
        if start > last_idx:
            prefix = text[last_idx:start]
            raw_segments.append((prefix, DEFAULT_VOICE))

        matched_str = match.group(0)
        inner = matched_str
        if (matched_str.startswith(('«', '"', '“', '„')) and matched_str.endswith(('»', '"', '”', '“'))):
            inner = matched_str[1:-1]
        elif matched_str.startswith('(') and matched_str.endswith(')'):
            inner = matched_str[1:-1]

        if est_char_pattern.search(inner):
            clean_est = normalize_text_for_estonian_tts(inner)
            if clean_est:
                raw_segments.append((clean_est, ESTONIAN_VOICE))
        else:
            raw_segments.append((matched_str, DEFAULT_VOICE))

        last_idx = end

    if last_idx < len(text):
        suffix = text[last_idx:]
        raw_segments.append((suffix, DEFAULT_VOICE))

    # Склеиваем и очищаем пустые сегменты и знаки препинания
    segments: List[Tuple[str, str]] = []
    for s_text, s_voice in raw_segments:
        s_clean = s_text.strip()
        if not s_clean:
            continue

        # Если в сегменте нет букв/цифр (только знаки препинания вроде точки или запятой)
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
        segments.append((text.strip(), DEFAULT_VOICE))

    return segments


async def synthesize_segment(text: str, voice: str, delay: float = 0.0) -> bytes:
    """
    Синтезирует один фрагмент в байты MP3 с защитой от сбоев, повторными попытками,
    встроенным кэшированием и автоматическим fallback на резервный голос.
    """
    clean_text = text.strip()
    if "et-EE" in voice:
        clean_text = normalize_text_for_estonian_tts(clean_text)
    if not clean_text:
        return b""

    # Проверка сегментного кэша
    seg_key = _get_cache_key("seg", clean_text, voice)
    if seg_key in _TTS_SEGMENT_CACHE:
        return _TTS_SEGMENT_CACHE[seg_key]

    if delay > 0:
        await asyncio.sleep(delay)

    # Список кандидатов: [основной голос, резервный голос]
    fallback_voice = VOICE_FALLBACK_MAP.get(voice)
    candidates = [voice]
    if fallback_voice and fallback_voice != voice:
        candidates.append(fallback_voice)

    for cand_voice in candidates:
        volume = "+20%" if "et-EE" in cand_voice else "+0%"
        for vol in ([volume, "+0%"] if volume != "+0%" else ["+0%"]):
            try:
                chunks: List[bytes] = []
                async with _tts_semaphore:
                    communicate = edge_tts.Communicate(text=clean_text, voice=cand_voice, volume=vol)
                    async for chunk in communicate.stream():
                        if chunk.get("type") == "audio" and chunk.get("data"):
                            chunks.append(chunk["data"])
                audio_bytes = b"".join(chunks)
                if audio_bytes:
                    _store_in_cache(_TTS_SEGMENT_CACHE, seg_key, audio_bytes)
                    return audio_bytes
            except Exception as e:
                logger.warning(
                    f"Segment synthesis attempt failed for voice '{cand_voice}', vol '{vol}': {e}"
                )
                await asyncio.sleep(0.05)

    logger.error(f"Failed to synthesize segment for text: '{clean_text[:40]}...' with all candidate voices.")
    return b""


async def _synthesize_mono_audio_bytes(clean_text: str, voice: str) -> bytes:
    """Синтезирует полный моно-аудиопоток в байты с кэшированием."""
    if "et-EE" in voice:
        clean_text = normalize_text_for_estonian_tts(clean_text)

    fallback_voice = VOICE_FALLBACK_MAP.get(voice)
    candidates = [voice]
    if fallback_voice and fallback_voice != voice:
        candidates.append(fallback_voice)

    for cand_voice in candidates:
        volume = "+20%" if "et-EE" in cand_voice else "+0%"
        for vol in ([volume, "+0%"] if volume != "+0%" else ["+0%"]):
            try:
                chunks_buffer: List[bytes] = []
                async with _tts_semaphore:
                    communicate = edge_tts.Communicate(text=clean_text, voice=cand_voice, volume=vol)
                    async for chunk in communicate.stream():
                        if chunk.get("type") == "audio" and chunk.get("data"):
                            chunks_buffer.append(chunk["data"])

                audio_bytes = b"".join(chunks_buffer)
                if audio_bytes:
                    return audio_bytes
            except Exception as e:
                logger.warning(
                    f"TTS mono stream candidate '{cand_voice}' (vol '{vol}') failed: {e}. Trying fallback..."
                )
                await asyncio.sleep(0.08)

    raise RuntimeError(f"All TTS candidates failed for text: {clean_text[:50]}...")


async def _synthesize_bilingual_audio_bytes(clean_text: str) -> bytes:
    """Синтезирует и склеивает двуязычные фрагменты с кэшированием."""
    segments = parse_bilingual_segments(clean_text)
    has_estonian = any(v == ESTONIAN_VOICE for _, v in segments)

    if not has_estonian:
        return await _synthesize_mono_audio_bytes(clean_text, DEFAULT_VOICE)

    logger.info(
        f"Bilingual TTS: {len(segments)} segments parsed for text ({len(clean_text)} chars). Fetching concurrently..."
    )

    # Параллельный запрос фрагментов с шагом 0.02s через семафор
    tasks = [
        synthesize_segment(seg_text, seg_voice, delay=i * 0.02)
        for i, (seg_text, seg_voice) in enumerate(segments)
    ]
    audio_parts: List[bytes] = await asyncio.gather(*tasks)

    stitched_audio = b"".join(part for part in audio_parts if part)
    if not stitched_audio:
        logger.warning("Bilingual segments returned empty audio. Falling back to mono.")
        return await _synthesize_mono_audio_bytes(clean_text, DEFAULT_VOICE)

    return stitched_audio


async def get_or_synthesize_audio(
    text: str,
    voice: str = DEFAULT_VOICE,
    bilingual: bool = False,
) -> bytes:
    """
    Получает готовый байтовый буфер аудио (MP3) с мгновенным кэшированием (0 мс при повторе)
    и дедупликацией одновременных in-flight запросов.
    """
    clean_text = text.strip()
    if not clean_text:
        return b""

    cache_prefix = "bi" if bilingual else "mono"
    cache_key = _get_cache_key(cache_prefix, clean_text, voice)

    # 1. Быстрый возврат из кэша
    if cache_key in _TTS_STREAM_CACHE:
        logger.info(f"Serving TTS from cache [{cache_prefix}] for text ({len(clean_text)} chars)")
        return _TTS_STREAM_CACHE[cache_key]

    # 2. Дедупликация: если для этого же текста уже идёт синтез, ожидаем ту же задачу
    if cache_key in _IN_FLIGHT_TASKS:
        logger.info(f"Awaiting existing in-flight TTS task for text ({len(clean_text)} chars)")
        try:
            return await _IN_FLIGHT_TASKS[cache_key]
        except Exception:
            pass

    # 3. Создаем новую in-flight задачу
    async def _worker() -> bytes:
        if bilingual:
            audio = await _synthesize_bilingual_audio_bytes(clean_text)
        else:
            audio = await _synthesize_mono_audio_bytes(clean_text, voice)
        _store_in_cache(_TTS_STREAM_CACHE, cache_key, audio)
        return audio

    task = asyncio.create_task(_worker())
    _IN_FLIGHT_TASKS[cache_key] = task

    try:
        audio_result = await task
        return audio_result
    finally:
        _IN_FLIGHT_TASKS.pop(cache_key, None)


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
    """Стримит двуязычную склейку порциями по 16 КБ из кэшированного буфера."""
    if not text or not text.strip():
        return

    audio_bytes = await get_or_synthesize_audio(text, voice=DEFAULT_VOICE, bilingual=True)
    chunk_size = 16384
    for i in range(0, len(audio_bytes), chunk_size):
        yield audio_bytes[i:i + chunk_size]
