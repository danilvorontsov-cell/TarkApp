"""
Модуль системной пред-нормализации текста для Azure Speech Services.
Реализует строгое разделение визуального (Display Layer) и голосового (Speech Layer) слоев.

Архитектура конвейера:
1. Защита и изоляция эстонских фрагментов (<est>...</est>, термины в скобках/кавычках).
2. Фонетическая адаптация англицизмов, брендов и аббревиатур (Roblox -> Роблокс, Minecraft -> Майнкрафт, LEGO -> Лего, YouTube -> Ютуб, IT -> АйТи).
3. Нормализация времени (09:00 -> девять ноль-ноль, 14:30 -> четырнадцать тридцать).
4. Нормализация чисел, диапазонов и математических выражений («четыре и три», «девять плюс три», «от 1 до 9»).
5. Устранение коллизий омографов (расстановка явных ударений \u0301: «в два ша́га») и восстановление буквы «ё».
6. Формирование билингвального SSML-документа с переключением дикторов между ru-RU и et-EE.
"""

import re
from typing import Dict, List, Optional, Tuple


# ==============================================================================
# 1. ТЕРМИНОЛОГИЧЕСКИЙ СЛОВАРЬ (Loanword & Terminology Map)
# ==============================================================================

TERMINOLOGY_MAP: Dict[str, str] = {
    # Популярные игры, бренды и платформы
    "roblox": "Роблокс",
    "minecraft": "Майнкрафт",
    "lego": "Лего",
    "youtube": "Ютуб",
    "brawl stars": "Бравл Старс",
    "brawlstars": "Бравл Старс",
    "fortnite": "Фортнайт",
    "tiktok": "ТикТок",
    "tik tok": "ТикТок",
    "discord": "Дискорд",
    "steam": "Стим",
    "playstation": "Плейстейшн",
    "xbox": "Иксбокс",
    "scratch": "Скретч",
    "google": "Гугл",
    "apple": "Эппл",

    # Аббревиатуры и технологии
    "it": "АйТи",
    "ai": "ЭйАй",
    "pc": "ПиСи",
    "wi-fi": "Вай-Фай",
    "wifi": "Вай-Фай",
    "python": "Пайтон",

    # Клавиши управления и периферия
    "wasd": "В А С Д",
    "enter": "Энтер",
    "shift": "Шифт",
    "space": "Пробел",
    "esc": "Эскейп",
    "escape": "Эскейп",
    "ctrl": "Контрол",
    "alt": "Альт",
}

# Поддерживаемые англоязычные бренды (для сохранения совместимости)
ENGLISH_BRANDS = [
    "Lego Mindstorms", "Mindstorms", "Minecraft", "Roblox", "Scratch", "Python"
]


def normalize_loanwords_and_brands(text: str) -> str:
    """
    Фонетически адаптирует популярные англоязычные бренды, игры и аббревиатуры
    в естественную русскую транскрипцию для русскоязычного диктора Azure TTS:
    Roblox -> Роблокс, Minecraft -> Майнкрафт, LEGO -> Лего, YouTube -> Ютуб, IT -> АйТи.
    Сохраняет русские падежные окончания (например, Minecraft'а -> Майнкрафта).
    """
    if not text:
        return ""

    t = text

    # 1. Составные термины (Brawl Stars, TikTok, Wi-Fi и т.д.)
    compound_terms = [
        ("lego mindstorms", "Лего Майндстормс"),
        ("brawl stars", "Бравл Старс"),
        ("brawlstars", "Бравл Старс"),
        ("tik tok", "ТикТок"),
        ("play station", "Плейстейшн"),
        ("wi-fi", "Вай-Фай"),
    ]
    for term, rep in compound_terms:
        t = re.sub(rf'(?i)\b{re.escape(term)}\b', rep, t)

    # 2. Аббревиатуры: IT, AI, PC
    t = re.sub(r'\bIT(?=[–\-][а-яёА-ЯЁ]+|\b)', 'АйТи', t)
    t = re.sub(r'\bAI(?=[–\-][а-яёА-ЯЁ]+|\b)', 'ЭйАй', t)
    t = re.sub(r'\bPC(?=[–\-][а-яёА-ЯЁ]+|\b)', 'ПиСи', t)

    # 2.1. Клавиши WASD
    t = re.sub(r'\b(?:WASD|W,\s*A,\s*S,\s*D|W\s+A\s+S\s+D)\b', 'В А С Д', t, flags=re.IGNORECASE)

    # 3. Одиночные бренды с поддержкой русских падежных окончаний:
    # Minecraft'а / Майнкрафте / Roblox'е / YouTube'а / LEGO
    def repl_brand(m):
        base_orig = m.group(1)
        base = base_orig.lower()
        ending = m.group(2) or ""
        rep = TERMINOLOGY_MAP.get(base, base_orig)
        if base == "lego":
            # «Лего» не склоняется
            return rep
        return f"{rep}{ending}"

    brand_pattern = re.compile(
        r'\b(roblox|роблокс|minecraft|майнкрафт|lego|лего|youtube|ютуб|fortnite|tiktok|тикток|discord|steam|playstation|xbox|scratch|python|google|гугл|apple|эппл|enter|shift|space|esc|escape|ctrl|alt)'
        r'(?:[’\'-]?([а-яё]+))?\b',
        re.IGNORECASE
    )
    t = brand_pattern.sub(repl_brand, t)
    return t


# ==============================================================================
# 2. НОРМАЛИЗАЦИЯ ВРЕМЕНИ (Time Normalization)
# ==============================================================================

HOURS_WORDS: Dict[int, str] = {
    0: "ноль", 1: "один", 2: "два", 3: "три", 4: "четыре", 5: "пять",
    6: "шесть", 7: "семь", 8: "восемь", 9: "девять", 10: "десять",
    11: "одиннадцать", 12: "двенадцать", 13: "тринадцать", 14: "четырнадцать",
    15: "пятнадцать", 16: "шестнадцать", 17: "семнадцать", 18: "восемнадцать",
    19: "девятнадцать", 20: "двадцать", 21: "двадцать один",
    22: "двадцать два", 23: "двадцать три"
}


def normalize_time_expressions(text: str) -> str:
    """
    Преобразует временные метки в естественную русскую речь:
    09:00 -> 'девять ноль-ноль', 14:30 -> 'четырнадцать тридцать', 10:05 -> 'десять ноль пять'.
    Исключает математическое деление (15 : 3 = 5).
    """
    if not text:
        return ""

    def repl_time(m):
        h = int(m.group(1))
        min_str = m.group(2)
        m_val = int(min_str)
        h_word = HOURS_WORDS.get(h, str(h))

        if min_str == "00":
            return f"{h_word} ноль-ноль"
        elif m_val < 10:
            digit_word = HOURS_WORDS.get(m_val, str(m_val))
            return f"{h_word} ноль {digit_word}"
        else:
            m_word = int_to_russian_cardinal(m_val)
            return f"{h_word} {m_word}"

    # Сопоставляем HH:MM, если за ним НЕ следует знак равенства или арифметический оператор
    pattern = re.compile(r'\b([01]?\d|2[0-3]):([0-5]\d)\b(?!\s*(=|[+\-*\/÷·×]))')
    return pattern.sub(repl_time, text)


# ==============================================================================
# 3. ЧИСЛА, АРИФМЕТИКА И ДИАПАЗОНЫ (Numbers & Math)
# ==============================================================================

RUSSIAN_UNITS = [
    "ноль", "один", "два", "три", "четыре", "пять",
    "шесть", "семь", "восемь", "девять", "десять",
    "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
    "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"
]

RUSSIAN_TENS = [
    "", "", "двадцать", "тридцать", "сорок", "пятьдесят",
    "шестьдесят", "семьдесят", "восемьдесят", "девяносто"
]

RUSSIAN_HUNDREDS = [
    "", "сто", "двести", "триста", "четыреста", "пятьсот",
    "шестьсот", "семьсот", "восемьсот", "девятьсот"
]


def int_to_russian_cardinal(n: int, gender: str = "m") -> str:
    """Преобразует целое число от 0 до 999999 в русские слова в именительном падеже."""
    if n < 0:
        return f"минус {int_to_russian_cardinal(-n, gender)}"
    if n == 0:
        return "ноль"

    parts = []
    thousands = n // 1000
    remainder = n % 1000

    if thousands > 0:
        if thousands == 1:
            parts.append("одна тысяча")
        elif thousands == 2:
            parts.append("две тысячи")
        elif 3 <= thousands <= 4:
            parts.append(f"{int_to_russian_cardinal(thousands, 'f')} тысячи")
        elif 5 <= thousands <= 20:
            parts.append(f"{int_to_russian_cardinal(thousands, 'm')} тысяч")
        else:
            last_digit = thousands % 10
            last_two = thousands % 100
            if 11 <= last_two <= 19:
                suffix = "тысяч"
            elif last_digit == 1:
                suffix = "тысяча"
            elif 2 <= last_digit <= 4:
                suffix = "тысячи"
            else:
                suffix = "тысяч"
            th_word = int_to_russian_cardinal(thousands, "f" if suffix in ("тысяча", "тысячи") else "m")
            parts.append(f"{th_word} {suffix}")

    if remainder > 0 or not parts:
        hundreds = remainder // 100
        tens_units = remainder % 100

        if hundreds > 0:
            parts.append(RUSSIAN_HUNDREDS[hundreds])

        if tens_units > 0:
            if tens_units < 20:
                if tens_units == 1 and gender == "f":
                    parts.append("одна")
                elif tens_units == 2 and gender == "f":
                    parts.append("две")
                else:
                    parts.append(RUSSIAN_UNITS[tens_units])
            else:
                t = tens_units // 10
                u = tens_units % 10
                parts.append(RUSSIAN_TENS[t])
                if u > 0:
                    if u == 1 and gender == "f":
                        parts.append("одна")
                    elif u == 2 and gender == "f":
                        parts.append("две")
                    else:
                        parts.append(RUSSIAN_UNITS[u])

    return " ".join(parts).strip()


def int_to_russian_nominative(n: int) -> str:
    """Возвращает число 0-999999 в именительном падеже русскими словами (совместимый алиас)."""
    return int_to_russian_cardinal(n, gender="m")


MATH_VAR_MAP = {
    "x": "икс", "X": "икс",
    "y": "игрек", "Y": "игрек",
    "z": "зет", "Z": "зет",
    "b": "бэ", "B": "бэ",
    "c": "цэ", "C": "цэ",
}


def normalize_math_expressions(text: str) -> str:
    """
    Нормализует математические формулы, изолированные цифры и знаки в русском контексте:
    - Сложение изолированных чисел: '9 + 3' -> 'девять плюс три'.
    - Перечисление цифр через союз 'и': '4 и 3' -> 'четыре и три'.
    - Деление двоеточием: '15 : 3 = 5' -> '15 разделить на 3 равно 5'.
    - Вычитание: '9 - 3 = 6' -> '9 минус 3 равно 6'.
    - Защищает стандартные временные метки (14:30).
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

    # 1. Сложение изолированных чисел («9 + 3» -> «девять плюс три»)
    def repl_addition(m):
        n1 = int(m.group(1))
        n2 = int(m.group(2))
        return f"{int_to_russian_cardinal(n1)} плюс {int_to_russian_cardinal(n2)}"

    t = re.sub(r'\b(\d{1,4})\s*\+\s*(\d{1,4})\b', repl_addition, t)

    # 2. Перечисление изолированных цифр («4 и 3», «2, 3 и 4») в именительный падеж
    def repl_digits_and_3(m):
        n1 = int(m.group(1))
        n2 = int(m.group(2))
        n3 = int(m.group(3))
        return f"{int_to_russian_cardinal(n1)}, {int_to_russian_cardinal(n2)} и {int_to_russian_cardinal(n3)}"

    t = re.sub(r'\b(\d{1,4}),\s*(\d{1,4})\s+и\s+(\d{1,4})\b', repl_digits_and_3, t)

    def repl_digits_and(m):
        n1 = int(m.group(1))
        n2 = int(m.group(2))
        return f"{int_to_russian_cardinal(n1)} и {int_to_russian_cardinal(n2)}"

    t = re.sub(r'\b(\d{1,4})\s+и\s+(\d{1,4})\b', repl_digits_and, t)

    # 3. Словесные описания знаков операций
    t = re.sub(r'(?i)знак\s*[«"“„]?\s*[:÷]\s*[»"”]?|(?<=\()[:÷](?=\))', 'знак «разделить» ', t)
    t = re.sub(r'(?i)знак\s*[«"“„]?\s*[*·×]\s*[»"”]?|(?<=\()[*·×](?=\))', 'знак «умножить» ', t)
    t = re.sub(r'(?i)знак\s*[«"“„]?\s*\+\s*[»"”]?|(?<=\()\+(?=\))', 'знак «плюс» ', t)
    t = re.sub(r'(?i)знак\s*[«"“„]?\s*[-−]\s*[»"”]?|(?<=\()[-−](?=\))', 'знак «минус» ', t)

    t = re.sub(r'(?<=[0-9a-zA-Z\)])\s*÷\s*(?=[0-9a-zA-Z\(])', ' разделить на ', t)

    # 4. Деление двоеточием между операндами
    t = re.sub(r'(\d+)\s*:\s*(\d+)', r'\1 разделить на \2', t)
    t = re.sub(r'(\b[a-zA-Z]\b)\s*:\s*(\d+|\b[a-zA-Z]\b)', r'\1 разделить на \2', t)
    t = re.sub(r'(\d+)\s*:\s*(\b[a-zA-Z]\b)', r'\1 разделить на \2', t)

    # 5. Текстовое двоеточие в списках и перечислениях заменяем на запятую
    t = re.sub(r',?[ \t]*:[ \t]*(?!\n)', ', ', t)
    t = re.sub(r',?[ \t]*:[ \t]*(?=\n)', ',', t)
    t = re.sub(r'[ \t]+,', ',', t)
    t = re.sub(r',[ \t]*,', ',', t)

    t = re.sub(r'(?<=[0-9a-zA-Z\)])\s*[*·×]\s*(?=[0-9a-zA-Z\(])', ' умножить на ', t)
    t = re.sub(r'(?<=[0-9a-zA-Zа-яА-ЯёЁ])\s*\+\s*(?=[0-9a-zA-Zа-яА-ЯёЁ])|\s+\+\s+', ' плюс ', t)
    t = re.sub(r'\s*=\s*', ' равно ', t)
    t = re.sub(r'(?<=[0-9a-zA-Z])\s*[-−]\s*(?=[0-9a-zA-Z])|\s+[-−]\s+', ' минус ', t)

    # 6. Цифры после знака "плюс" и арифметических терминов
    t = re.sub(
        r'\b(плюс)\s+(\d{1,4})\b',
        lambda m: f"{m.group(1)} {int_to_russian_cardinal(int(m.group(2)))}",
        t
    )

    t = re.sub(
        r'(?i)\b(складыва[а-яё]*|прибавля[а-яё]*|вычита[а-яё]*|умножа[а-яё]*|дели[а-яё]*|числа|чисел|цифры|цифр|слагаемые|слагаемых|множители|множителей)\s+(\d{1,4})\b',
        lambda m: f"{m.group(1)} {int_to_russian_cardinal(int(m.group(2)))}",
        t
    )

    for var, rep in MATH_VAR_MAP.items():
        t = re.sub(r'\b' + var + r'\b', rep, t)

    t = re.sub(r'\b(плюс|минус|равно|разделить на|умножить на)\s+[aA]\b', r'\1 а', t)
    t = re.sub(r'\b[aA]\s+(плюс|минус|равно|разделить на|умножить на)\b', r'а \1', t)
    t = re.sub(r'\b(переменная|переменную|переменной|буква|букву|буквой)\s+[aA]\b', r'\1 а', t)

    for idx, orig_time in enumerate(time_placeholders):
        t = t.replace(f"___TIME_STAMP_{idx}___", orig_time)

    t = re.sub(r'\s+', ' ', t).strip()
    return t


def normalize_number_ranges(text: str) -> str:
    """
    Нормализует диапазоны чисел: '1-9' -> 'от 1 до 9'.
    Исключает знаки вычитания и равенства (например, '9 - 3 = 6').
    """
    if not text:
        return ""

    def repl(m):
        prefix = text[:m.start()]
        if re.search(r'=\s*$', prefix):
            return m.group(0)
        n1 = int(m.group(1))
        n2 = int(m.group(2))
        if n1 < n2:
            return f"от {n1} до {n2}"
        return m.group(0)

    pattern = re.compile(r'\b(\d+)\s*[-–—]\s*(\d+)\b(?!\s*=)')
    return pattern.sub(repl, text)


# ==============================================================================
# 4. РИМСКИЕ И ПОРЯДКОВЫЕ ЧИСЛИТЕЛЬНЫЕ (Roman & Ordinals)
# ==============================================================================

ROMAN_TO_INT = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
    "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
    "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15,
    "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20,
    "XXI": 21, "XXII": 22, "XXIII": 23, "XXIV": 24, "XXV": 25,
    "XXVI": 26, "XXVII": 27, "XXVIII": 28, "XXIX": 29, "XXX": 30,
}

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


def normalize_roman_numerals(text: str) -> str:
    """Конвертирует римские цифры в русском контексте в словесный русский эквивалент."""
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


def normalize_russian_ordinals_with_dot(text: str) -> str:
    """Нормализует порядковые числительные и пронумерованные примеры в русском контексте."""
    if not text:
        return ""

    time_placeholders = []
    def mask_time(m):
        idx = len(time_placeholders)
        time_placeholders.append(m.group(0))
        return f"TIMETEMP{idx}TIMETEMP"

    text = re.sub(r'\b([01]?\d|2[0-3]):([0-5]\d)\b(?!\s*(=|[+\-*\/÷·×]))', mask_time, text)

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
        r'(?i)\b(пример|шаг|пункт|действие|задание|упражнение)\s*(?:№\s*)?(\d+)\b(?!\s*[+\-*\/÷·×=])(\s*[:.)])?'
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

    for idx, orig_time in enumerate(time_placeholders):
        t = t.replace(f"TIMETEMP{idx}TIMETEMP", orig_time)

    return t


# ==============================================================================
# 5. ОМОГРАФЫ И ЗНАКИ УДАРЕНИЯ (Homographs & Accents)
# ==============================================================================

RUSSIAN_ACCENT_WORDS: Dict[str, str] = {
    "еще": "ещё", "Еще": "Ещё",
    "четный": "чётный", "Четный": "Чётный",
    "четная": "чётная", "Четная": "Чётная",
    "четное": "чётное", "Четное": "Чётное",
    "четные": "чётные", "Четные": "Чётные",
    "четных": "чётных",
    "нечетный": "нечётный", "Нечетный": "Нечётный",
    "нечетная": "нечётная", "Нечетная": "Нечётная",
    "нечетное": "нечётное", "Нечетное": "Нечётное",
    "нечетные": "нечётные", "Нечетные": "Нечётные",
    "нечетных": "нечётных",
    "счет": "счёт", "Счет": "Счёт",
    "перенес": "перенёс", "Перенес": "Перенёс",
    "перенесем": "перенесём", "Перенесем": "Перенесём",
    "объем": "объём", "Объем": "Объём",
    "объема": "объёма",
    "трех": "трёх", "четырех": "четырёх",
    "берем": "берём", "Берем": "Берём",
    "найдем": "найдём", "Найдем": "Найдём",
    "поймешь": "поймёшь", "Поймешь": "Поймёшь",
    "узнаешь": "узнаёшь",
    "чертеж": "чертёж", "Чертеж": "Чертёж",
}

_RUSSIAN_ACCENT_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(k) for k in RUSSIAN_ACCENT_WORDS.keys()) + r')\b'
)


def normalize_russian_accents_and_yo(text: str) -> str:
    """
    Нормализует русский текст для аудиопотока Azure Speech:
    - Восстанавливает букву 'ё' в омографах и школьных словах (еще -> ещё, счет -> счёт, четный -> чётный).
    - Расставляет знаки ударения (combining acute \u0301) для омографов («в два ша́га», «за три ша́га»).
    - Обрабатывает фразовые контексты ('со счёта', 'прежде всего́', 'вот и всё', 'всё верно').
    - Удаляет случайные принудительные ударения, сохраняя знак ударения только на 'ша́га'.
    """
    if not text:
        return ""

    t = _RUSSIAN_ACCENT_PATTERN.sub(lambda m: RUSSIAN_ACCENT_WORDS.get(m.group(0), m.group(0)), text)
    t = re.sub(r'(?i)\bсо\s+счет([аеуом]|ом)?\b', r'со счёт\1', t)
    t = re.sub(r'(?i)\bпрежде\s+всего\b', 'прежде всего', t)
    t = re.sub(r'(?i)\bвот\s+и\s+все\b', 'вот и всё', t)
    t = re.sub(r'(?i)\bвсе\s+(готово|верно|правильно|получилось|сходится)\b', r'всё \1', t)

    # Омограф «шага»: устойчивые выражения «в два ша́га», «за три ша́га», «в 2 ша́га»
    def repl_shaga(m):
        prefix = m.group(1)
        word = m.group(2)
        prefix = re.sub(r'\b2\b', 'два', prefix)
        prefix = re.sub(r'\b3\b', 'три', prefix)
        prefix = re.sub(r'\b4\b', 'четыре', prefix)
        capitalized = word[0].isupper()
        shaga_stressed = "Ша\u0301га" if capitalized else "ша\u0301га"
        return f"{prefix}{shaga_stressed}"

    t = re.sub(
        r'(?i)\b((?:(?:в|во|за|на|до|через|всего|ровно)\s+)?(?:два|две|три|четыре|два-три|2|3|4)\s+)(шага)\b',
        repl_shaga,
        t,
    )

    # Сохраняем знак ударения \u0301 только на 'ша́га'
    t = re.sub(r'(?<![шШ][аА])\u0301', '', t)
    return t


# ==============================================================================
# 6. ЭСТОНСКАЯ НОРМАЛИЗАЦИЯ (Estonian Text Normalization)
# ==============================================================================

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


def normalize_text_for_estonian_tts(text: str) -> str:
    """
    Нормализует эстонский текст:
    - Порядковые числительные с точкой (1. klass -> esimene klass, 4. klassis -> neljandas klassis).
    - Для номеров без существительных (Harjutus 5.) срезает точку -> Harjutus 5.
    - Удаляет крестики и спецсимволы умножения (×, ✕, ✖, *).
    - Удаляет скобки [ ], { }, ( ).
    - Сохраняет дефисы для падежных окончаний чисел (5-ga, 10-ni).
    """
    if not text:
        return ""

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

    t = re.sub(r'[\u00d7\u2715\u2716*]', ' ', t)
    t = re.sub(r'[\[\]{}()]', ' ', t)
    t = re.sub(r'(?<=[a-zA-ZõäöüÕÄÖÜšžŠŽ0-9])\s*/\s*(?=[a-zA-ZõäöüÕÄÖÜšžŠŽ0-9])', ' või ', t)
    t = re.sub(r'\s+/\s+', ' või ', t)
    t = re.sub(r'[/\\|]', ' ', t)
    t = re.sub(r'(\b\d+)\s*\.(?!\d)', r'\1 ', t)
    t = re.sub(r'(\d+)([,!?;:])', r'\1 \2', t)
    t = re.sub(r'([,!?;:])(\d+)', r'\1 \2', t)
    t = re.sub(r'(\d+)[-–—]+(?=(?:ga|ni|st|le|lt|sse|s|l|ks|na|ta)\b)', r'\1-', t, flags=re.IGNORECASE)
    t = re.sub(r'(\d+)[-–—]+(?!(?:ga|ni|st|le|lt|sse|s|l|ks|na|ta)\b)', r'\1 ', t, flags=re.IGNORECASE)
    t = re.sub(r'[-–—]+(\d+)', r' \1', t)
    return re.sub(r'\s+', ' ', t).strip()


# ==============================================================================
# 7. СКВОЗНОЙ КОНВЕЙЕР ПОДГОТОВКИ SPEECH-СЛОЯ (Speech Pipeline)
# ==============================================================================

def clean_text_for_speech(text: str) -> str:
    """Санитизирует текст: очищает markdown, стрелки, слэши."""
    if not text:
        return ""

    est_tags = []
    def mask_est_tag(match):
        idx = len(est_tags)
        est_tags.append(match.group(0))
        return f"ESTTAGPLACEHOLDER{idx}ESTTAG"

    t = re.sub(
        r'<\s*est(?:\s+[^>]*)?>.*?<\s*/\s*est\s*>',
        mask_est_tag,
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    t = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', t)
    t = re.sub(r'(?<=[а-яА-ЯёЁ])\s*/\s*(?=[а-яА-ЯёЁ0-9])|(?<=[а-яА-ЯёЁ0-9])\s*/\s*(?=[а-яА-ЯёЁ])', ' или ', t)
    t = re.sub(r'(?:==>|-->|=>|->|→|⇒)', ' затем ', t)
    t = re.sub(r'(?:<==|<--|<-|←|⇐)', ' ранее ', t)
    t = re.sub(r'(?<=[0-9a-zA-Zа-яА-ЯёЁ])\s*<=\s*(?=[0-9a-zA-Zа-яА-ЯёЁ])', ' меньше или равно ', t)
    t = re.sub(r'(?<=[0-9a-zA-Zа-яА-ЯёЁ])\s*>=\s*(?=[0-9a-zA-Zа-яА-ЯёЁ])', ' больше или равно ', t)
    t = re.sub(r'<=\s*', ' ранее ', t)
    t = re.sub(r'\b(затем|ранее)\s+\1\b', r'\1', t, flags=re.IGNORECASE)

    t = re.sub(r'#+', ' ', t)
    t = re.sub(r'\*+', ' ', t)
    t = re.sub(r'_+', ' ', t)
    t = re.sub(r'[~`]+', ' ', t)
    t = re.sub(r'[\[\]]', ' ', t)

    # Клавиши управления и сервисы в тексте
    t = re.sub(r'\benter\b', 'Энтер', t, flags=re.IGNORECASE)
    t = re.sub(r'\bspace\b', 'Пробел', t, flags=re.IGNORECASE)
    t = re.sub(r'\bshift\b', 'Шифт', t, flags=re.IGNORECASE)
    t = re.sub(r'\b(?:google|гугл)\b', 'Гугл', t, flags=re.IGNORECASE)
    t = re.sub(r'\b(?:youtube|ютуб)\b', 'Ютуб', t, flags=re.IGNORECASE)

    for idx, orig_t in enumerate(est_tags):
        t = t.replace(f"ESTTAGPLACEHOLDER{idx}ESTTAG", orig_t)

    t = re.sub(r'\s+([,!?;:])', r'\1', t)
    return re.sub(r'[ \t]+', ' ', t).strip()


def normalize_text_for_speech(text: str, is_russian_context: bool = True) -> str:
    """
    Базовая пред-нормализация текста для билингвальной сегментации:
    - Защищает теги <est>...</est> и эстонские цитаты в кавычках.
    - Очищает markdown и стрелки через clean_text_for_speech.
    - Нормализует порядковые числительные с точкой (4. классе).
    - Нормализует римские цифры (XXI век).
    - Нормализует числовые диапазоны (1-9).
    - Нормализует математические операции и изолированные числа (4 и 3, 9 + 3).
    - Сохраняет исходные англоязычные бренды (Minecraft, Roblox) для идентификации голоса.
    """
    if not text:
        return ""
    if not is_russian_context:
        return normalize_text_for_estonian_tts(text)

    est_tags = []
    def mask_est_tag(match):
        idx = len(est_tags)
        est_tags.append(match.group(0))
        return f"ESTTAGPLACEHOLDER{idx}ESTTAG"

    t = re.sub(
        r'<\s*est(?:\s+[^>]*)?>.*?<\s*/\s*est\s*>',
        mask_est_tag,
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    est_quotes = []
    def mask_est_quote(match):
        q = match.group(0)
        inner = q[1:-1].strip()
        if not re.search(r'[а-яА-ЯёЁ=+*]', inner):
            idx = len(est_quotes)
            est_quotes.append(q)
            return f"ESTQUOTEPLACEHOLDER{idx}ESTQUOTE"
        return q

    t = re.sub(r'([«"“„][^»"”]+[»"”])', mask_est_quote, t)

    t = normalize_russian_ordinals_with_dot(t)
    t = normalize_roman_numerals(t)
    t = normalize_number_ranges(t)
    t = normalize_math_expressions(t)

    for idx, orig_q in enumerate(est_quotes):
        t = t.replace(f"ESTQUOTEPLACEHOLDER{idx}ESTQUOTE", orig_q)

    for idx, orig_t in enumerate(est_tags):
        t = t.replace(f"ESTTAGPLACEHOLDER{idx}ESTTAG", orig_t)

    return re.sub(r'\s+', ' ', t).strip()


def prepare_speech_text(display_text: str, is_russian_context: bool = True) -> str:
    """
    Главная точка входа для трансформации Display Text -> Speech Text:
    - Защищает эстонские вставки (<est>...</est>).
    - Выполняет базовую нормализацию (числа, математика, очистка разметки).
    - Фонетически адаптирует англицизмы, бренды и аббревиатуры (Roblox -> Роблокс, Minecraft -> Майнкрафт, LEGO -> Лего, IT -> АйТи).
    - Преобразует время (09:00 -> девять ноль-ноль, 14:30 -> четырнадцать тридцать).
    - Расставляет знаки ударения для омографов («в два ша́га») и восстанавливает букву «ё».
    """
    if not display_text:
        return ""

    if not is_russian_context:
        return normalize_text_for_estonian_tts(display_text)

    est_tags = []
    def mask_est_tag(match):
        idx = len(est_tags)
        est_tags.append(match.group(0))
        return f"ESTTAGPLACEHOLDER{idx}ESTTAG"

    t = re.sub(
        r'<\s*est(?:\s+[^>]*)?>.*?<\s*/\s*est\s*>',
        mask_est_tag,
        display_text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    t = clean_text_for_speech(t)
    t = normalize_loanwords_and_brands(t)
    t = normalize_time_expressions(t)
    t = normalize_text_for_speech(t, is_russian_context=True)
    t = normalize_russian_accents_and_yo(t)

    for idx, orig_t in enumerate(est_tags):
        t = t.replace(f"ESTTAGPLACEHOLDER{idx}ESTTAG", orig_t)

    return re.sub(r'\s+', ' ', t).strip()


def prepare_worked_example_speech(worked_example) -> str:
    """Формирует слитный Speech Text для образца решения (Näidis)."""
    if not worked_example:
        return ""

    title = getattr(worked_example, "title", "Пример решения")
    given = getattr(worked_example, "given", "")
    steps = getattr(worked_example, "steps", [])
    note = getattr(worked_example, "note", "")

    formatted_steps = []
    ordinals = {1: "Первое", 2: "Второе", 3: "Третье", 4: "Четвертое", 5: "Пятое"}
    for idx, s in enumerate(steps, 1):
        clean_step = re.sub(r'^\d+[\.\)]\s*', '', str(s)).strip()
        prefix = ordinals.get(idx, f"{idx}-е")
        formatted_steps.append(f"{prefix}: {clean_step}")

    full_text = f"{title}. {given}. Шаги решения: {'. '.join(formatted_steps)}. {note}".strip()
    return prepare_speech_text(full_text)
