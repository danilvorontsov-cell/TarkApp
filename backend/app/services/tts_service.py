import asyncio
import hashlib
import logging
import re
from typing import AsyncGenerator, Dict, List, Optional, Tuple
import edge_tts

logger = logging.getLogger(__name__)

# Supported voice mappings
# ru-RU-SvetlanaMultilingualNeural: чистый русский голос с нативной поддержкой английских слов и терминов
# et-EE-KertNeural: четкий мужской эстонский голос (+20% громкости)
VOICE_MAP = {
    "ru": "ru-RU-SvetlanaMultilingualNeural",
    "et": "et-EE-KertNeural",
}

DEFAULT_VOICE = "ru-RU-SvetlanaMultilingualNeural"
ESTONIAN_VOICE = "et-EE-KertNeural"

# Карта резервных голосов для отказоустойчивости при сетевых сбоях Edge-TTS
VOICE_FALLBACK_MAP = {
    "ru-RU-SvetlanaMultilingualNeural": "ru-RU-SvetlanaNeural",
    "ru-RU-SvetlanaNeural": "ru-RU-DmitryNeural",
    "ru-RU-DmitryNeural": "ru-RU-SvetlanaMultilingualNeural",
    "et-EE-KertNeural": "et-EE-AnuNeural",
    "et-EE-AnuNeural": "et-EE-KertNeural",
}

# Семафор для параллельных WebSocket-запросов к Microsoft Edge-TTS (до 4 одновременных сокетов)
# Заменяет жесткий одиночный Lock(), ускоряя склейку двуязычных фрагментов в 8-10 раз
_tts_semaphore: Optional[asyncio.Semaphore] = None


def _get_tts_semaphore() -> asyncio.Semaphore:
    global _tts_semaphore
    if _tts_semaphore is None:
        _tts_semaphore = asyncio.Semaphore(4)
    return _tts_semaphore

# Серверные кэши синтезированного аудио в оперативной памяти (LRU-ограничение)
_TTS_STREAM_CACHE: Dict[str, bytes] = {}
_TTS_SEGMENT_CACHE: Dict[str, bytes] = {}
MAX_CACHE_ENTRIES = 500

# Реестр активных in-flight задач для дедупликации одновременных одинаковых запросов
_IN_FLIGHT_TASKS: Dict[str, asyncio.Task[bytes]] = {}


def _get_cache_key(prefix: str, text: str, voice: str = "") -> str:
    raw = f"{prefix}:{voice}:{text.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _store_in_cache(cache: Dict[str, bytes], key: str, data: bytes):
    if len(cache) >= MAX_CACHE_ENTRIES:
        # Удаляем 20% старейших записей (FIFO очистка для простоты и высокой скорости)
        keys_to_remove = list(cache.keys())[: max(1, MAX_CACHE_ENTRIES // 5)]
        for k in keys_to_remove:
            cache.pop(k, None)
    cache[key] = data


# Словарь эстонских порядковых числительных: (nominative, inessive, genitive)
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
    Нормализует эстонский текст для Edge-TTS:
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

        # Inessive: klassis, harjutuses, ülesandes, osas (ends with 'is', 'es', 'des', 'as' but not 'ss')
        if noun_l.endswith(('is', 'es', 'des', 'as')) and not noun_l.endswith('ss'):
            w = forms[1]
        elif noun_l.endswith(('i', 'e')) and noun_l != 'ülesanne':
            w = forms[2]
        else:
            w = forms[0]
        return f"{w} {noun}"

    t = est_ord_pattern.sub(repl_est_ord, text)

    # 2. Очистка символов и срез точки у оставшихся одиночных номеров (напр. Harjutus 5. -> Harjutus 5)
    t = re.sub(r'[\u00d7\u2715\u2716*]', ' ', t)
    t = re.sub(r'[\[\]{}()]', ' ', t)
    t = re.sub(r'[/\\|]', ' ', t)
    t = re.sub(r'(\b\d+)\s*\.(?!\d)', r'\1 ', t)
    t = re.sub(r'(\d+)([,!?;:])', r'\1 \2', t)
    t = re.sub(r'([,!?;:])(\d+)', r'\1 \2', t)
    # Сохраняем дефис для эстонских падежных окончаний числительных (5-ga, 10-ni, 3-st, 2-le, 4-lt, 1-sse, 5-s, 6-l, 7-ks, 8-na, 9-ta)
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
    - Деление: знак : (двоеточие) и ÷ -> разделить на (вместо чтения как 'соотношение')
    - Умножение: *, ·, × -> умножить на
    - Словесные описания: 'знак :' -> 'знак «разделить»', 'знак *' -> 'знак «умножить»'
    - Защищает стандартные форматы времени (напр. 'в 14:30').
    Не затрагивает чистый эстонский текст (слова без кириллицы и без мат. знаков).
    """
    if not text:
        return ""

    has_cyrillic = bool(re.search(r'[а-яА-ЯёЁ]', text))
    has_math_ops = bool(re.search(r'[=+*\/÷·×:]|(?<=[0-9a-zA-Z])\s*[-−]\s*(?=[0-9a-zA-Z])', text))
    if not (has_cyrillic or has_math_ops):
        return text

    t = text

    # Временно защищаем время HH:MM (напр. 14:30, 08:15)
    time_placeholders = []
    def mask_time(m):
        idx = len(time_placeholders)
        time_placeholders.append(m.group(0))
        return f"___TIME_STAMP_{idx}___"

    t = re.sub(r'\b([01]?\d|2[0-3]):([0-5]\d)\b(?!\s*(=|[+\-*\/÷·×]))', mask_time, t)

    # 1. Словесные описания знаков
    t = re.sub(r'(?i)знак\s*[«"“„]?\s*[:÷]\s*[»"”]?|(?<=\()[:÷](?=\))', 'знак «разделить» ', t)
    t = re.sub(r'(?i)знак\s*[«"“„]?\s*[*·×]\s*[»"”]?|(?<=\()[*·×](?=\))', 'знак «умножить» ', t)
    t = re.sub(r'(?i)знак\s*[«"“„]?\s*\+\s*[»"”]?|(?<=\()\+(?=\))', 'знак «плюс» ', t)
    t = re.sub(r'(?i)знак\s*[«"“„]?\s*[-−]\s*[»"”]?|(?<=\()[-−](?=\))', 'знак «минус» ', t)

    # 2. Деление: двоеточие : или символ ÷ между операндами (числа, переменные, скобки)
    t = re.sub(r'(?<=[0-9a-zA-Z\)])\s*[:÷]\s*(?=[0-9a-zA-Z\(])', ' разделить на ', t)

    # 3. Умножение: *, ·, × между операндами
    t = re.sub(r'(?<=[0-9a-zA-Z\)])\s*[*·×]\s*(?=[0-9a-zA-Z\(])', ' умножить на ', t)

    # 4. Знаки действий: +, =, -
    t = re.sub(r'(?<=[0-9a-zA-Zа-яА-ЯёЁ])\s*\+\s*(?=[0-9a-zA-Zа-яА-ЯёЁ])|\s+\+\s+', ' плюс ', t)
    t = re.sub(r'\s*=\s*', ' равно ', t)
    t = re.sub(r'(?<=[0-9a-zA-Z])\s*[-−]\s*(?=[0-9a-zA-Z])|\s+[-−]\s+', ' минус ', t)

    # 5. Одиночные переменные x, y, z, b, c
    for var, rep in MATH_VAR_MAP.items():
        t = re.sub(r'\b' + var + r'\b', rep, t)

    # 6. Переменная 'a' / 'A' в математическом окружении
    t = re.sub(r'\b(плюс|минус|равно|разделить на|умножить на)\s+[aA]\b', r'\1 а', t)
    t = re.sub(r'\b[aA]\s+(плюс|минус|равно|разделить на|умножить на)\b', r'а \1', t)
    t = re.sub(r'\b(переменная|переменную|переменной|буква|букву|буквой)\s+[aA]\b', r'\1 а', t)

    # Восстанавливаем время
    for idx, orig_time in enumerate(time_placeholders):
        t = t.replace(f"___TIME_STAMP_{idx}___", orig_time)

    t = re.sub(r'\s+', ' ', t).strip()
    return t


def normalize_russian_ordinals_with_dot(text: str) -> str:
    """
    Нормализует порядковые числительные и пронумерованные примеры в русском контексте:
    - 4. класс -> четвертый класс
    - в 4. классе -> в четвертом классе
    - 2. задание -> второе задание
    - во 2. задании -> во втором задании
    - 1. шаг / 1. действие -> первое действие / первый шаг
    - 2. шаг -> второе действие / второй шаг
    - 1. пример / в 1. примере -> первый пример / в первом примере
    - Пример 1 / Пример № 1: -> Первый пример:
    - Шаг 1: -> Первый шаг:
    - Задание 1: -> Первое задание:
    - Отдельно стоящие номера в списках (1. Сложи числа -> Первое: Сложи числа, 1) -> Первое:),
      гарантируя озвучивание порядковых номеров и устраняя паузы на точках в Edge-TTS.
    """
    if not text:
        return ""

    # 1. Число с точкой перед ключевым существительным: (\d+)\.\s*(класс|задание|действие|шаг|пункт|век|глава|часть|пример|упражнение)
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

        # Средний род: задание, действие, упражнение
        if "задани" in noun_l or "действи" in noun_l or "упражнени" in noun_l:
            if prep_l in ("в", "во", "о", "об") or noun_l.endswith("и"):
                form_idx = 2  # prep_m_n: втором
            elif prep_l in ("до", "с", "со", "от", "после") or noun_l.endswith("я"):
                form_idx = 1  # gen_m_n: второго
            else:
                form_idx = 3  # nom_n: второе, первое
        # Женский род: глава, часть
        elif "глав" in noun_l or "част" in noun_l:
            if prep_l in ("в", "во", "на", "о", "об") or noun_l.endswith(("е", "и")):
                form_idx = 5  # f_other: четвертой
            else:
                form_idx = 4  # nom_f: четвертая, первая
        # Мужской род: класс, шаг, пункт, век, пример
        else:
            if prep_l in ("в", "во", "на", "о", "об") or noun_l.endswith("е"):
                form_idx = 2  # prep_m: четвертом / первом
            elif prep_l in ("до", "с", "со", "от", "после") or noun_l.endswith(("а", "у")):
                form_idx = 1  # gen_m: четвертого / первого
            else:
                form_idx = 0  # nom_m: четвертый, первый

        word = forms[form_idx]
        if prep:
            return f"{prep} {word} {noun}"
        return f"{word} {noun}"

    t = pattern.sub(repl, text)

    # 2. Существительное перед числом: Пример 1:, Пример № 1, Шаг 2:, Задание 3:, Упражнение 1
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

    # 3. Отдельно стоящие номера в списках (напр. '1. ', '1) ', '2. ', '2) ')
    # в порядковые числительные 'Первое: ', 'Второе: '
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
    Комплексная предварительная нормализация текста перед синтезом речи:
    - Порядковые числительные с точкой (в 4. классе -> в четвертом классе, 2. задание -> второе задание)
    - Очистка лишних точек в списках для устранения неестественных пауз
    - Римские цифры (XXI век -> двадцать первый век, III тысячелетие -> третье тысячелетие)
    - Математические переменные и знаки (x + y = 15 -> икс плюс игрек равно 15)
    """
    if not text:
        return ""
    if not is_russian_context:
        return text

    # Защищаем явные теги <est>...</est> и фразы в кавычках перед нормализацией
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
        segments.append((fallback_text.strip(), DEFAULT_VOICE))

    return segments


def parse_bilingual_segments(text: str) -> List[Tuple[str, str]]:
    """
    Разбивает двуязычный текст на последовательные сегменты (текст, голос):
    - Фрагменты внутри тегов <est>...</est> отправляются эстонскому диктору (et-EE-KertNeural / et-EE-AnuNeural),
      теги удаляются перед синтезом.
    - Весь остальной текст вне тегов <est> (русский язык + свободная английская латиница вроде
      Minecraft, Roblox, YouTube, W/A/S/D) озвучивается русским мультиязычным голосом
      (ru-RU-SvetlanaMultilingualNeural).
    - Если тегов <est> в тексте нет, и в тексте нет кириллицы (чистый эстонский термин или фраза),
      текст целиком отправляется эстонскому диктору.
    - В противном случае весь текст без тегов озвучивается русским диктором единым блоком без склеек.
    """
    if not text or not text.strip():
        return [(text or "", DEFAULT_VOICE)]

    # Предварительная нормализация римских цифр и математических переменных в русском контексте
    text = normalize_text_for_speech(text, is_russian_context=True)

    est_tag_pattern = re.compile(r'<\s*est(?:\s+[^>]*)?>(.*?)<\s*/\s*est\s*>', re.IGNORECASE | re.DOTALL)

    # 1. Если присутствуют теги <est>...</est>, выполняем строгое разделение по тегам
    if est_tag_pattern.search(text):
        raw_segments: List[Tuple[str, str]] = []
        last_idx = 0

        for match in est_tag_pattern.finditer(text):
            start, end = match.span()
            if start > last_idx:
                prefix = text[last_idx:start]
                # Срезаем одиночные открывающие скобки/кавычки в конце префикса, если они оборачивали <est>
                clean_prefix = prefix.rstrip(' ([«"“„')
                if clean_prefix:
                    raw_segments.append((clean_prefix, DEFAULT_VOICE))

            inner = match.group(1).strip()
            clean_est = normalize_text_for_estonian_tts(inner)
            if clean_est:
                raw_segments.append((clean_est, ESTONIAN_VOICE))

            # Проверяем, если сразу после тега идет закрывающая скобка/кавычка, сдвигаем last_idx
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

    # 2. Если тегов <est> нет:
    # 2a. Чистый эстонский текст (без кириллических букв — например, отдельные слова словаря)
    if not re.search(r'[а-яА-ЯёЁ]', text):
        clean_est = normalize_text_for_estonian_tts(text.strip())
        return [(clean_est or text.strip(), ESTONIAN_VOICE)]

    # 2b. Текст на русском языке без тегов <est> (свободная латиница Minecraft, Roblox, W/A/S/D и т.д.)
    # Полностью и без лишних склеек читается русским мультиязычным диктором ru-RU-SvetlanaMultilingualNeural
    return [(text.strip(), DEFAULT_VOICE)]


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
                async with _get_tts_semaphore():
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
                async with _get_tts_semaphore():
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


async def _synthesize_bilingual_audio_bytes(clean_text: str) -> Tuple[bytes, bool]:
    """Синтезирует и склеивает двуязычные фрагменты. Возвращает (audio_bytes, is_complete)."""
    segments = parse_bilingual_segments(clean_text)
    has_estonian = any(v == ESTONIAN_VOICE for _, v in segments)

    if not has_estonian:
        audio = await _synthesize_mono_audio_bytes(clean_text, DEFAULT_VOICE)
        return audio, bool(audio)

    logger.info(
        f"Bilingual TTS: {len(segments)} segments parsed for text ({len(clean_text)} chars). Fetching concurrently..."
    )

    # Параллельный запрос фрагментов с шагом 0.02s через семафор
    tasks = [
        synthesize_segment(seg_text, seg_voice, delay=i * 0.02)
        for i, (seg_text, seg_voice) in enumerate(segments)
    ]
    audio_parts: List[bytes] = await asyncio.gather(*tasks)

    all_succeeded = all(bool(part) for part in audio_parts)
    stitched_audio = b"".join(part for part in audio_parts if part)
    if not stitched_audio:
        logger.warning("Bilingual segments returned empty audio. Falling back to mono.")
        mono_audio = await _synthesize_mono_audio_bytes(clean_text, DEFAULT_VOICE)
        return mono_audio, False

    return stitched_audio, all_succeeded


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
            audio, is_complete = await _synthesize_bilingual_audio_bytes(clean_text)
        else:
            audio = await _synthesize_mono_audio_bytes(clean_text, voice)
            is_complete = bool(audio)
        if audio and is_complete:
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
