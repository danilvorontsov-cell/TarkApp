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
DEFAULT_VOICE = "ru-RU-SvetlanaMultilingualNeural"
ESTONIAN_VOICE = "et-EE-AnuNeural"

VOICE_MAP: Dict[str, str] = {
    "ru": DEFAULT_VOICE,
    "et": ESTONIAN_VOICE,
}

# Disk and memory caching
AUDIO_CACHE_DIR = Path("static/audio/cache")
try:
    AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

_TTS_STREAM_CACHE: Dict[str, bytes] = {}
MAX_CACHE_ENTRIES = 500

# Registry of active in-flight tasks for deduplication of simultaneous requests
_IN_FLIGHT_TASKS: Dict[str, asyncio.Task[bytes]] = {}


def _store_in_memory_cache(cache: Dict[str, bytes], key: str, data: bytes) -> None:
    if len(cache) >= MAX_CACHE_ENTRIES:
        # FIFO eviction of oldest 20%
        keys_to_remove = list(cache.keys())[: max(1, MAX_CACHE_ENTRIES // 5)]
        for k in keys_to_remove:
            cache.pop(k, None)
    cache[key] = data


# Dictionary of Estonian ordinal numbers: (nominative, inessive, genitive)
EST_ORDINALS: Dict[int, Tuple[str, str, str]] = {
    1: ("esimene", "esimeses", "esimese"),
    2: ("teine", "teises", "teise"),
    3: ("kolmas", "kolmandas", "kolmanda"),
    4: ("neljas", "neljandas", "neljanda"),
    5: ("viies", "viiendas", "viienda"),
    6: ("kuues", "kuuendas", "kuuenda"),
    7: ("seitsmes", "seitsmendas", "seitsmenda"),
    8: ("kaheksas", "kaheksandas", "kaheksanda"),
    9: ("üheksas", "üheksandas", "üheksanda"),
    10: ("kümnes", "kümnendas", "kümnenda"),
    11: ("üheteistkümnes", "üheteistkümnendas", "üheteistkümnenda"),
    12: ("kaheteistkümnes", "kaheteistkümnendas", "kaheteistkümnenda"),
    21: ("kahekümne esimene", "kahekümne esimeses", "kahekümne esimese"),
}


def normalize_text_for_estonian_tts(text: str) -> str:
    """
    Нормализует эстонский текст:
    - Конвертирует порядковые числительные с точкой (1. klass -> esimene klass, 4. klassis -> neljandas klassis,
      2. harjutus -> teine harjutus, 2. ülesandes -> teises ülesandes).
    - Для номеров без привязанных существительных (Harjutus 5.) срезает точку -> Harjutus 5.
    - Удаляет крестики и спецсимволы умножения (×, ✕, ✖, *).
    - Удаляет скобки [ ], { }, ( ).
    - Разделяет пробелом знаки препинания и дефисы встык с числами.
    """
    if not text:
        return ""

    # 1. Порядковые числительные с точкой перед ключевыми существительными
    est_ord_pattern = re.compile(
        r'\b(\d+)\.\s*(klass[a-zõäöü]*|harjutus[a-zõäöü]*|ülesan[a-zõäöü]*|osa[a-zõäöü]*)\b',
        re.IGNORECASE,
    )

    def repl_est_ord(m):
        num = int(m.group(1))
        noun = m.group(2)
        noun_l = noun.lower()
        forms = EST_ORDINALS.get(num)
        if not forms:
            return m.group(0)

        if noun_l.endswith(('is', 'es', 'des', 'as')) and not noun_l.endswith('ss'):
            w = forms[1]
        elif noun_l.endswith(('i', 'e')) and noun_l != 'ülesanne':
            w = forms[2]
        else:
            w = forms[0]
        return f"{w} {noun}"

    t = est_ord_pattern.sub(repl_est_ord, text)

    # 2. Очистка символов и срез точки у оставшихся одиночных номеров
    t = re.sub(r'[\u00d7\u2715\u2716*]', ' ', t)
    t = re.sub(r'[\[\]{}()]', ' ', t)
    t = re.sub(r'[/\\|]', ' ', t)
    t = re.sub(r'(\b\d+)\s*\.(?!\d)', r'\1 ', t)
    t = re.sub(r'(\d+)([,!?;:])', r'\1 \2', t)
    t = re.sub(r'([,!?;:])(\d+)', r'\1 \2', t)
    t = re.sub(r'(\d+)[-–—]+(?=(?:ga|ni|st|le|lt|sse|s|l|ks|na|ta)\b)', r'\1-', t, flags=re.IGNORECASE)
    t = re.sub(r'(\d+)[-–—]+(?!(?:ga|ni|st|le|lt|sse|s|l|ks|na|ta)\b)', r'\1 ', t, flags=re.IGNORECASE)
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
    Конвертирует римские цифры в русском контексте в словесный русский эквивалент.
    """
    if not text:
        return ""

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
        elif "тысячелети" in noun_l:
            if prep_l in ("в", "во", "о", "об") or noun_l.endswith("и") or suffix in ("м", "ом", "ем"):
                form_idx = 2
            elif prep_l in ("до", "с", "со", "от", "после") or noun_l.endswith("я") or suffix in ("го", "ого"):
                form_idx = 1
            else:
                form_idx = 3
            actual_noun = noun
        elif "класс" in noun_l:
            if prep_l in ("в", "во") or noun_l.endswith("е") or suffix in ("м", "ом", "ем"):
                form_idx = 2
            elif noun_l.endswith("а") or suffix in ("го", "ого"):
                form_idx = 1
            else:
                form_idx = 0
            actual_noun = noun
        elif "глав" in noun_l:
            if noun_l == "глава" and suffix not in ("й", "ой"):
                form_idx = 4
            else:
                form_idx = 5
            actual_noun = noun
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
    Нормализует математические переменные и знаки в русском контексте.
    """
    if not text:
        return ""

    has_cyrillic = bool(re.search(r'[а-яА-ЯёЁ]', text))
    has_math_ops = bool(re.search(r'[=+*\/÷·×:]|(?<=[0-9a-zA-Z])\s*[-−]\s*(?=[0-9a-zA-Z])', text))
    if not (has_cyrillic or has_math_ops):
        return text

    t = text

    time_placeholders = []
    def mask_time(m):
        idx = len(time_placeholders)
        time_placeholders.append(m.group(0))
        return f"___TIME_STAMP_{idx}___"

    t = re.sub(r'\b([01]?\d|2[0-3]):([0-5]\d)\b(?!\s*(=|[+\-*\/÷·×]))', mask_time, t)

    t = re.sub(r'(?i)знак\s*[«"“„]?\s*[:÷]\s*[»"”]?|(?<=\()[:÷](?=\))', 'знак «разделить» ', t)
    t = re.sub(r'(?i)знак\s*[«"“„]?\s*[*·×]\s*[»"”]?|(?<=\()[*·×](?=\))', 'знак «умножить» ', t)
    t = re.sub(r'(?i)знак\s*[«"“„]?\s*\+\s*[»"”]?|(?<=\()\+(?=\))', 'знак «плюс» ', t)
    t = re.sub(r'(?i)знак\s*[«"“„]?\s*[-−]\s*[»"”]?|(?<=\()[-−](?=\))', 'знак «минус» ', t)

    t = re.sub(r'(?<=[0-9a-zA-Z\)])\s*[:÷]\s*(?=[0-9a-zA-Z\(])', ' разделить на ', t)
    t = re.sub(r'(?<=[0-9a-zA-Z\)])\s*[*·×]\s*(?=[0-9a-zA-Z\(])', ' умножить на ', t)
    t = re.sub(r'(?<=[0-9a-zA-Zа-яА-ЯёЁ])\s*\+\s*(?=[0-9a-zA-Zа-яА-ЯёЁ])|\s+\+\s+', ' плюс ', t)
    t = re.sub(r'\s*=\s*', ' равно ', t)
    t = re.sub(r'(?<=[0-9a-zA-Z])\s*[-−]\s*(?=[0-9a-zA-Z])|\s+[-−]\s+', ' минус ', t)

    for var, rep in MATH_VAR_MAP.items():
        t = re.sub(r'\b' + var + r'\b', rep, t)

    t = re.sub(r'\b(плюс|минус|равно|разделить на|умножить на)\s+[aA]\b', r'\1 а', t)
    t = re.sub(r'\b[aA]\s+(плюс|минус|равно|разделить на|умножить на)\b', r'а \1', t)
    t = re.sub(r'\b(переменная|переменную|переменной|буква|букву|буквой)\s+[aA]\b', r'\1 а', t)

    for idx, orig_time in enumerate(time_placeholders):
        t = t.replace(f"___TIME_STAMP_{idx}___", orig_time)

    t = re.sub(r'\s+', ' ', t).strip()
    return t


def normalize_russian_ordinals_with_dot(text: str) -> str:
    """
    Нормализует порядковые числительные и пронумерованные примеры в русском контексте.
    """
    if not text:
        return ""

    pattern = re.compile(
        r'(?i)(?:(\bв|во|на|о|об|к|ко|до|с|со|от|после|около)\s+)?'
        r'\b(\d+)\.\s*'
        r'\b(класс[а-яё]*|задани[а-яё]*|действи[а-яё]*|шаг[а-яё]*|пункт[а-яё]*|век[а-яё]*|глав[а-яё]*|част[а-яё]*|пример[а-яё]*|упражнени[а-яё]*)'
    )

    def repl(m):
        prep = m.group(1) or ""
        num = int(m.group(2))
        noun = m.group(3)
        forms = ORDINAL_FORMS.get(num)
        if not forms:
            return m.group(0)

        prep_l = prep.lower()
        noun_l = noun.lower()

        if "задани" in noun_l or "действи" in noun_l or "упражнени" in noun_l:
            if prep_l in ("в", "во", "о", "об") or noun_l.endswith("и"):
                form_idx = 2
            elif prep_l in ("до", "с", "со", "от", "после") or noun_l.endswith("я"):
                form_idx = 1
            else:
                form_idx = 3
        elif "глав" in noun_l or "част" in noun_l:
            if prep_l in ("в", "во", "на", "о", "об") or noun_l.endswith(("е", "и")):
                form_idx = 5
            else:
                form_idx = 4
        else:
            if prep_l in ("в", "во", "на", "о", "об") or noun_l.endswith("е"):
                form_idx = 2
            elif prep_l in ("до", "с", "со", "от", "после") or noun_l.endswith(("а", "у")):
                form_idx = 1
            else:
                form_idx = 0

        word = forms[form_idx]
        if prep:
            return f"{prep} {word} {noun}"
        return f"{word} {noun}"

    t = pattern.sub(repl, text)

    pattern_noun_num = re.compile(
        r'(?i)\b(пример|шаг|пункт|действие|задание|упражнение)\s*(?:№\s*)?(\d+)\b(\s*[:.)])?'
    )

    def repl_noun_num(m):
        noun = m.group(1)
        num = int(m.group(2))
        punct = m.group(3) or ""
        forms = ORDINAL_FORMS.get(num)
        if not forms:
            return m.group(0)

        noun_l = noun.lower()
        if noun_l in ("действие", "задание", "упражнение"):
            ord_word = forms[3].capitalize()
        else:
            ord_word = forms[0].capitalize()

        suffix = ": " if (":" in punct or "." in punct or ")" in punct) else " "
        return f"{ord_word} {noun_l}{suffix}"

    t = pattern_noun_num.sub(repl_noun_num, t)

    pattern_list_item = re.compile(
        r'(^|[\n\r]|(?<=[.!?:;])\s*)\b(\d+)[\.\)]\s+(?=[А-Яа-яЁёA-Za-z0-9«"“„])'
    )

    def repl_list_item(m):
        prefix = m.group(1) or ""
        if prefix and not prefix.endswith(('\n', '\r', ' ')):
            prefix += " "
        elif not prefix and m.start() > 0:
            prefix = " "
        num = int(m.group(2))
        forms = ORDINAL_FORMS.get(num)
        if forms:
            ord_word = forms[3].capitalize()
        else:
            ord_word = f"{num}-е"
        return f"{prefix}{ord_word}: "

    t = pattern_list_item.sub(repl_list_item, t)
    return t


def normalize_text_for_speech(text: str, is_russian_context: bool = True) -> str:
    """
    Комплексная предварительная нормализация текста перед синтезом речи.
    """
    if not text:
        return ""
    if not is_russian_context:
        return text

    est_tags: List[str] = []

    def mask_est_tag(match):
        idx = len(est_tags)
        est_tags.append(match.group(0))
        return f"___EST_TAG_{idx}___"

    masked_text = re.sub(
        r'<\s*est(?:\s+[^>]*)?>.*?<\s*/\s*est\s*>',
        mask_est_tag,
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    est_quotes: List[str] = []

    def mask_est_quote(match):
        q = match.group(0)
        inner = q[1:-1].strip()
        if not re.search(r'[а-яА-ЯёЁ=+*]', inner):
            idx = len(est_quotes)
            est_quotes.append(q)
            return f"___EST_QUOTE_{idx}___"
        return q

    masked_text = re.sub(r'([«"“„][^»"”]+[»"”])', mask_est_quote, masked_text)
    norm_text = normalize_russian_ordinals_with_dot(masked_text)
    norm_text = normalize_roman_numerals(norm_text)
    norm_text = normalize_math_expressions(norm_text)

    for idx, orig_q in enumerate(est_quotes):
        norm_text = norm_text.replace(f"___EST_QUOTE_{idx}___", orig_q)

    for idx, orig_t in enumerate(est_tags):
        norm_text = norm_text.replace(f"___EST_TAG_{idx}___", orig_t)

    return norm_text


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
    Формирует SSML разметку для одного запроса к Azure Speech Services:
    - Теги <est>...</est> и эстонские термины оборачиваются в <voice name="et-EE-AnuNeural">
    - Русский и смешанный текст оборачивается в <voice name="ru-RU-SvetlanaMultilingualNeural">
    - Поддерживает моно-эстонский и моно-русский текст.
    """
    clean_text = text.strip()
    if not clean_text:
        return ""

    has_est_tag = bool(re.search(r'<\s*est(?:\s+[^>]*)?>', clean_text, re.IGNORECASE))

    if bilingual or has_est_tag:
        segments = parse_bilingual_segments(clean_text)
    elif "et-EE" in voice or voice == "et":
        clean_est = normalize_text_for_estonian_tts(clean_text)
        segments = [(clean_est, ESTONIAN_VOICE)]
    else:
        # Если во всем тексте нет кириллицы и это не английский термин — озвучиваем эстонским
        if not re.search(r'[а-яА-ЯёЁ]', clean_text) and not _is_pure_english_brand_or_key(clean_text):
            clean_est = normalize_text_for_estonian_tts(clean_text)
            segments = [(clean_est, ESTONIAN_VOICE)]
        else:
            norm_text = normalize_text_for_speech(clean_text, is_russian_context=True)
            segments = [(norm_text, DEFAULT_VOICE)]

    is_all_est = all("et-EE" in v or v == "et" for _, v in segments)
    root_lang = "et-EE" if is_all_est else "ru-RU"

    voice_blocks: List[str] = []
    for seg_text, seg_voice in segments:
        s_clean = seg_text.strip()
        if not s_clean:
            continue
        v_name = ESTONIAN_VOICE if ("et-EE" in seg_voice or seg_voice == "et") else DEFAULT_VOICE
        escaped_content = _escape_ssml(s_clean)
        voice_blocks.append(f'  <voice name="{v_name}">{escaped_content}</voice>')

    if not voice_blocks:
        voice_blocks.append(f'  <voice name="{DEFAULT_VOICE}">{_escape_ssml(clean_text)}</voice>')

    inner_xml = "\n".join(voice_blocks)
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="{root_lang}">\n'
        f'{inner_xml}\n'
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
    result = synthesizer.speak_ssml_async(ssml).get()

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
    if cache_file.is_file() and cache_file.stat().st_size > 0:
        logger.info(f"Serving TTS from disk cache: {cache_file} (md5={ssml_hash[:10]}...)")
        try:
            cached_bytes = cache_file.read_bytes()
            if cached_bytes:
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
        if audio_bytes:
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
