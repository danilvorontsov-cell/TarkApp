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

import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ==============================================================================
# 0. КОНФИГУРАЦИОННЫЙ СЛОВАРЬ (tts_lexicon.json)
# ==============================================================================

_LEXICON_DATA: Optional[Dict[str, Dict[str, str]]] = None
_COMPILED_ESTONIAN_UNITS: Optional[List[Tuple[re.Pattern, str]]] = None
_COMPILED_RUSSIAN_HOMOGRAPHS: Optional[List[Tuple[re.Pattern, str]]] = None
_COMPILED_BRAND_FALLBACKS: Optional[List[Tuple[re.Pattern, str]]] = None


def get_tts_lexicon() -> Dict[str, Dict[str, str]]:
    """Возвращает кэшированный словарь tts_lexicon.json."""
    return _load_tts_lexicon()


def _load_tts_lexicon() -> Dict[str, Dict[str, str]]:
    """
    Загружает правила из tts_lexicon.json при старте и кэширует скомпилированные регулярки в памяти.
    """
    global _LEXICON_DATA, _COMPILED_ESTONIAN_UNITS, _COMPILED_RUSSIAN_HOMOGRAPHS, _COMPILED_BRAND_FALLBACKS

    if _LEXICON_DATA is not None:
        return _LEXICON_DATA

    candidate_paths = [
        Path(__file__).resolve().parent.parent / "config" / "tts_lexicon.json",
        Path("backend/app/config/tts_lexicon.json"),
        Path("app/config/tts_lexicon.json"),
    ]

    loaded_data: Dict[str, Any] = {}
    for p in candidate_paths:
        if p.exists() and p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    loaded_data = json.load(f)
                break
            except Exception as e:
                logger.warning(f"Failed to read tts_lexicon.json from {p}: {e}")

    _LEXICON_DATA = loaded_data or {}

    # 1. Estonian Units
    compiled_est: List[Tuple[re.Pattern, str]] = []
    for pattern_str, repl in _LEXICON_DATA.get("estonian_units", {}).items():
        try:
            compiled_est.append((re.compile(pattern_str, re.IGNORECASE), repl))
        except Exception as e:
            logger.warning(f"Failed to compile estonian unit regex '{pattern_str}': {e}")
    _COMPILED_ESTONIAN_UNITS = compiled_est

    # 2. Brand Fallbacks
    compiled_brands: List[Tuple[re.Pattern, str]] = []
    for pattern_str, repl in _LEXICON_DATA.get("brand_fallbacks", {}).items():
        try:
            compiled_brands.append((re.compile(pattern_str), repl))
        except Exception as e:
            logger.warning(f"Failed to compile brand fallback regex '{pattern_str}': {e}")
    _COMPILED_BRAND_FALLBACKS = compiled_brands

    # 3. Russian Stress Homographs
    compiled_homo: List[Tuple[re.Pattern, str]] = []
    for pattern_str, repl in _LEXICON_DATA.get("russian_stress_homographs", {}).items():
        try:
            compiled_homo.append((re.compile(pattern_str, re.IGNORECASE), repl))
        except Exception as e:
            logger.warning(f"Failed to compile homograph regex '{pattern_str}': {e}")
    _COMPILED_RUSSIAN_HOMOGRAPHS = compiled_homo

    return _LEXICON_DATA


def apply_phonetic_substitutions(text: str, is_estonian: bool = False) -> str:
    """
    Двухконтурная нормализация по правилам tts_lexicon.json:
    - Если текст эстонский (is_estonian=True):
      Применяет normalize_estonian_measurement_units (учет падежей ед.ч./партитива,
      страницы lk, привязка к цифрам) и правила estonian_units из tts_lexicon.json.
    - Если текст русский (is_estonian=False):
      а) brand_fallbacks: замена иностранных брендов на русскую фонетику с ударением (Roblox -> Ро́блокс, Minecraft -> Ма́йнкрафт и т.д.).
      б) russian_stress_homographs: расстановка знака ударения \u0301 над омографами (вычита́ем, прибавля́ем, де́лим, велопутеше́ствие, в два ша́га, зна́ком, со зна́ком и т.д.).
    """
    if not text:
        return ""

    _load_tts_lexicon()
    t = text

    if is_estonian:
        t = normalize_estonian_measurement_units(t)
        if _COMPILED_ESTONIAN_UNITS:
            for pattern, repl in _COMPILED_ESTONIAN_UNITS:
                t = pattern.sub(repl, t)
        return t

    # Русский контекст:
    # 1. Brand fallbacks
    if _COMPILED_BRAND_FALLBACKS:
        for pattern, repl in _COMPILED_BRAND_FALLBACKS:
            t = pattern.sub(repl, t)

    # 2. Russian stress homographs
    if _COMPILED_RUSSIAN_HOMOGRAPHS:
        for pattern, repl in _COMPILED_RUSSIAN_HOMOGRAPHS:
            def _repl_homo(m, r=repl):
                orig = m.group(0)
                if '\\1' in r or '\\g<' in r:
                    res = m.expand(r)
                else:
                    res = r
                if orig and orig[0].isupper():
                    return res[0].upper() + res[1:]
                return res[0].lower() + res[1:]
            t = pattern.sub(_repl_homo, t)

    # Подстраховка омографа «шага» (на 2 шага / 2 шага / в 2 шага -> ша́га)
    def _repl_shaga_local(m):
        prefix = m.group(1)
        word = m.group(2)
        shaga_stressed = "Ша\u0301га" if (word and word[0].isupper()) else "ша\u0301га"
        return f"{prefix}{shaga_stressed}"

    t = re.sub(
        r'(?i)\b((?:(?:в|во|за|на|до|через|всего|ровно)\s+)?(?:два|две|три|четыре|два-три|2|3|4)\s+)(шага)\b',
        _repl_shaga_local,
        t,
    )

    # Дополнительная подстраховка: со зна́ком / знако́м с темой, зна́к, по три́, в два кувши́на, пёсик, раздели́, раздели́те
    t = _apply_znakom_homograph(t)
    t = re.sub(r'(?i)\bзнак(?![\u0301])\b', 'зна\u0301к', t)
    t = re.sub(r'(?i)\bпо\s+тр[её]х\b', 'по три\u0301', t)
    t = re.sub(r'(?i)\bв\s+две\s+кувшина\b', 'в два кувши\u0301на', t)
    t = re.sub(r'(?i)\bпесик([а-яё]*)\b', r'пёсик\1', t)
    t = re.sub(r'(?i)\bраздели(?![\u0301])\b', lambda m: "Раздели\u0301" if m.group(0)[0].isupper() else "раздели\u0301", t)
    t = re.sub(r'(?i)\bразделите(?![\u0301])\b', lambda m: "Раздели\u0301те" if m.group(0)[0].isupper() else "раздели\u0301те", t)

    # Дедупликация символов ударения
    t = re.sub(r'\u0301+', '\u0301', t)

    # Исправление ошибочной формы «четырёх» для неодушевленных существительных -> «четыре»
    def _repl_chetyre(m):
        orig = m.group(0)
        noun = m.group(1)
        word = "Четыре" if orig[0].isupper() else "четыре"
        return f"{word} {noun}"

    t = re.sub(
        r'(?i)\bчетыр[её]х\s+(кувшин[а-я]*|банк[а-я]*|яблок[а-я]*|мешк[а-я]*|предмет[а-я]*|кубик[а-я]*|угол[а-я]*|сторон[а-я]*|групп[а-я]*)\b',
        _repl_chetyre,
        t,
    )

    return t


def _apply_znakom_homograph(text: str) -> str:
    """
    Разрешает омограф «знаком» в зависимости от контекста:
    - Математический знак (творительный падеж от «знак»): «со зна́ком», «перед зна́ком», «зна́ком плюс/минус» -> зна́ком.
    - Краткое прилагательное («знаком с темой», «ты уже знаком»): ударение на второй слог -> знако́м.
    Строго идемпотентна (не перезаписывает уже расставленное ударение \\u0301).
    """
    if not text:
        return ""

    def _cap(orig_word: str, target_lower: str) -> str:
        return target_lower[0].upper() + target_lower[1:] if orig_word[0].isupper() else target_lower

    _znakom_sign = "зна\u0301ком"
    _znakom_adj = "знако\u0301м"
    t = text

    # 1. Предлоги творительного падежа перед словом «знаком» -> зна́ком
    t = re.sub(
        r'(?i)\b(со|под|над|перед|за|между)\s+(знаком)(?![\u0301])\b',
        lambda m: f"{m.group(1)} {_cap(m.group(2), _znakom_sign)}",
        t,
    )

    # 2. Определения при существительном «знаком» -> зна́ком
    t = re.sub(
        r'(?i)\b(математическим|арифметическим|противоположным|обратным|таким|этим|каким|нужным|другим|тем\s+же)\s+(знаком)(?![\u0301])\b',
        lambda m: f"{m.group(1)} {_cap(m.group(2), _znakom_sign)}",
        t,
    )

    # 3. «знаком» перед названием математического знака или символом -> зна́ком
    t = re.sub(
        r'(?i)\b(знаком)(?![\u0301])\b(?=\s+(?:плюс|минус|равно|умножения|умножить|умно\u0301жить|деления|разделить|сложения|вычитания|равенства|неравенства|больше|меньше|корня|вопроса|восклицания|[+\-−=<>:÷·•*×«"“]))',
        lambda m: _cap(m.group(1), _znakom_sign),
        t,
    )

    # 4. Краткое прилагательное «знаком с ...» / «уже знаком» -> знако́м
    t = re.sub(
        r'(?i)\b(знаком)(?![\u0301])\b(?=\s+(?:с|со|ли|нам|вам|тебе|мне|ему|ей|им)\b)',
        lambda m: _cap(m.group(1), _znakom_adj),
        t,
    )
    t = re.sub(
        r'(?i)\b(ты|вы|он|не|уже|хорошо|близко|давно|лично)\s+(знаком)(?![\u0301])\b',
        lambda m: f"{m.group(1)} {_cap(m.group(2), _znakom_adj)}",
        t,
    )

    return t


def is_chemical_formula_or_acronym(text: str) -> bool:
    """
    Определяет химические формулы и научно-технические аббревиатуры (CO2, H2O, O2, NaCl, H2SO4, DNA, ATP),
    чтобы исключить их ложное автоопределение как эстонского языка.
    """
    if not text:
        return False
    cleaned = text.strip().strip("()[]{}\"'«»“”„")
    if not cleaned or re.search(r'[а-яА-ЯёЁõäöüšžÕÄÖÜŠŽ]', cleaned):
        return False

    tokens = [tok.strip(".,;:!?") for tok in cleaned.split() if tok.strip(".,;:!?")]
    if not tokens:
        return False

    for tok in tokens:
        is_chem = bool(
            re.fullmatch(r'\d*(?:[A-Z][a-z]?\d*[₀-₉²³⁺⁻]*){1,6}', tok)
            and (re.search(r'[0-9₀-₉²³⁺⁻]', tok) or len(re.findall(r'[A-Z]', tok)) >= 2)
        )
        is_acronym = bool(re.fullmatch(r'[A-Z]{2,6}|pH', tok))
        if not (is_chem or is_acronym):
            return False

    return True


# Предварительная загрузка лексикона при старте модуля
_load_tts_lexicon()


# ==============================================================================
# 1. ТЕРМИНОЛОГИЧЕСКИЙ СЛОВАРЬ (Loanword & Terminology Map)
# ==============================================================================

TERMINOLOGY_MAP: Dict[str, str] = {
    # Популярные игры, бренды и платформы
    "roblox": "Ро\u0301блокс",
    "роблокс": "Ро\u0301блокс",
    "minecraft": "Майнкрафт",
    "lego": "Ле\u0301го",
    "лего": "Ле\u0301го",
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
    "game": "Гейм",
    "level": "Левел",
    "online": "Онлайн",
    "offline": "Офлайн",
    "quest": "Квест",
    "skin": "Скин",
    "boss": "Босс",
    "player": "Плейер",

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

# ==============================================================================
# 1.1. ПРИОРИТЕТНЫЙ СЛОВАРЬ ТОЧНОЙ ФОНЕТИКИ (Custom Phonetic Map)
# ==============================================================================

CUSTOM_PHONETIC_MAP: Dict[str, str] = {
    # Сложные слова и омографы (форсированное ударение \u0301)
    "велопутешествие": "велопутеше\u0301ствие",
    "велопутешествия": "велопутеше\u0301ствия",
    "велопутешествию": "велопутеше\u0301ствию",
    "велопутешествием": "велопутеше\u0301ствием",
    "велопутешествии": "велопутеше\u0301ствии",
    "велопутешествий": "велопутеше\u0301ствий",
    "велопутешествиям": "велопутеше\u0301ствиям",
    "велопутешествиями": "велопутеше\u0301ствиями",
    "велопутешествиях": "велопутеше\u0301ствиях",

    # Математические действия: «вычитаем» (форсированное ударение \u0301)
    "вычитаем": "вычита\u0301ем",
    "вычитаемый": "вычита\u0301емый",
    "вычитаемая": "вычита\u0301емая",
    "вычитаемое": "вычита\u0301емое",
    "вычитаемого": "вычита\u0301емого",
    "вычитаемому": "вычита\u0301емому",
    "вычитаемым": "вычита\u0301емым",
    "вычитаемом": "вычита\u0301емом",
    "вычитаемые": "вычита\u0301емые",
    "вычитаемых": "вычита\u0301емых",

    # Иностранные бренды: ударение на первую букву
    "roblox": "Ро\u0301блокс",
    "роблокс": "Ро\u0301блокс",
    "роблокса": "Ро\u0301блокса",
    "роблоксу": "Ро\u0301блоксу",
    "роблоксом": "Ро\u0301блоксом",
    "роблоксе": "Ро\u0301блоксе",
}


def apply_custom_phonetic_map(text: str) -> str:
    """
    Применяет явный приоритетный словарь фонетических замен перед отправкой в Azure TTS:
    - «велопутешествие» -> «велопутеше́ствие»
    - «вычитаем» -> «вычита́ем»
    - «Roblox» / «Роблокс» -> «Ро́блокс» (ударение на первую гласную)
    Сохраняет регистр первой буквы (Заглавная / строчная).
    """
    if not text:
        return ""

    t = text

    # 1. Полнословные и регулярные паттерны
    # Велопутешествие и падежные формы
    def repl_velo(m):
        w = m.group(0)
        stem = "Велопутеше\u0301ств" if w[0].isupper() else "велопутеше\u0301ств"
        return f"{stem}{m.group(1)}"

    t = re.sub(r'(?i)\bвелопутешеств([а-яё]+)\b', repl_velo, t)

    # Вычитаем / вычитаемое
    def repl_vych(m):
        w = m.group(0)
        stem = "Вычита\u0301" if w[0].isupper() else "вычита\u0301"
        return f"{stem}{m.group(1)}"

    t = re.sub(r'(?i)\bвычита([ею][а-яё]*)\b', repl_vych, t)

    # Roblox / Роблокс с ударением на 'о́'
    def repl_roblox(m):
        ending = m.group(1) or ""
        return f"Ро\u0301блокс{ending}"

    t = re.sub(r'(?i)\b(?:roblox|роблокс)([а-яё]*)\b', repl_roblox, t)

    # 2. Прямые совпадения из словаря CUSTOM_PHONETIC_MAP
    for word_lower, replacement in CUSTOM_PHONETIC_MAP.items():
        pattern = re.compile(rf'\b{re.escape(word_lower)}\b', re.IGNORECASE)
        def repl_exact(m, rep=replacement):
            if m.group(0)[0].isupper():
                return rep[0].upper() + rep[1:]
            return rep[0].lower() + rep[1:]
        t = pattern.sub(repl_exact, t)

    return t


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


RUSSIAN_STRESSED_NUMERALS: Dict[int, str] = {
    0: "ноль",
    1: "оди\u0301н",
    2: "два",
    3: "три",
    4: "четы\u0301ре",
    5: "пять",
    6: "шесть",
    7: "семь",
    8: "во\u0301семь",
    9: "де\u0301вять",
    10: "де\u0301сять",
    11: "оди\u0301ннадцать",
    12: "двена\u0301дцать",
    13: "трина\u0301дцать",
    14: "четы\u0301рнадцать",
    15: "пятна\u0301дцать",
    16: "шестна\u0301дцать",
    17: "семна\u0301дцать",
    18: "восемна\u0301дцать",
    19: "девятна\u0301дцать",
    20: "два\u0301дцать",
    30: "три\u0301дцать",
    40: "со\u0301рок",
    50: "пятьдеся\u0301т",
    60: "шестьдеся\u0301т",
    70: "се\u0301мьдесят",
    80: "во\u0301семьдесят",
    90: "девяно\u0301сто",
    100: "сто",
}


def int_to_russian_stressed_nominative(n: int) -> str:
    """Возвращает число 0-100 в именительном падеже с корректно расставленными знаками ударения."""
    if n in RUSSIAN_STRESSED_NUMERALS:
        return RUSSIAN_STRESSED_NUMERALS[n]
    if 21 <= n <= 99:
        tens = (n // 10) * 10
        units = n % 10
        if units == 0:
            return RUSSIAN_STRESSED_NUMERALS.get(tens, str(tens))
        return f"{RUSSIAN_STRESSED_NUMERALS.get(tens, '')} {RUSSIAN_STRESSED_NUMERALS.get(units, '')}".strip()
    return int_to_russian_cardinal(n)


MATH_VAR_MAP = {
    "x": "икс", "X": "икс",
    "y": "игрек", "Y": "игрек",
    "z": "зет", "Z": "зет",
    "b": "бэ", "B": "бэ",
    "c": "цэ", "C": "цэ",
}

RUSSIAN_FRACTION_DENOMINATORS: Dict[int, Tuple[str, str]] = {
    2: ("вторая", "вторых"),
    3: ("третья", "третьих"),
    4: ("четвертая", "четвертых"),
    5: ("пятая", "пятых"),
    6: ("шестая", "шестых"),
    7: ("седьмая", "седьмых"),
    8: ("восьмая", "восьмых"),
    9: ("девятая", "девятых"),
    10: ("десятая", "десятых"),
    11: ("одиннадцатая", "одиннадцатых"),
    12: ("двенадцатая", "двенадцатых"),
    15: ("пятнадцатая", "пятнадцатых"),
    16: ("шестнадцатая", "шестнадцатых"),
    20: ("двадцатая", "двадцатых"),
    25: ("двадцать пятая", "двадцать пятых"),
    50: ("пятидесятая", "пятидесятых"),
    100: ("сотая", "сотых"),
    1000: ("тысячная", "тысячных"),
}


def _russian_decimal_to_words(whole_str: str, frac_str: str) -> str:
    """Преобразует десятичную дробь (3,5 -> три целых пять десятых) в корректную русскую форму."""
    try:
        whole = int(whole_str)
        frac = int(frac_str)
    except ValueError:
        return f"{whole_str} запятая {frac_str}"

    if whole > 999999 or len(frac_str) > 3:
        return f"{whole_str} запятая {frac_str}"

    whole_unit = "целая" if (whole % 10 == 1 and whole % 100 != 11) else "целых"
    whole_words = f"{int_to_russian_cardinal(whole, 'f')} {whole_unit}"

    denom_map = {
        1: ("десятая", "десятых"),
        2: ("сотая", "сотых"),
        3: ("тысячная", "тысячных"),
    }
    sg_form, pl_form = denom_map[len(frac_str)]
    frac_unit = sg_form if (frac % 10 == 1 and frac % 100 != 11) else pl_form
    frac_words = f"{int_to_russian_cardinal(frac, 'f')} {frac_unit}"
    return f"{whole_words} {frac_words}"


def normalize_celsius_expressions(text: str) -> str:
    """
    Нормализует температуру в градусах Цельсия в русском контексте:
    '-5 °C' -> 'минус пять градусов Цельсия', '1 °C' -> 'один градус Цельсия', '+20 °C' -> 'плюс двадцать градусов Цельсия'.
    Поддерживает как латинскую 'C', так и кириллическую 'С'.
    """
    if not text or "°" not in text:
        return text or ""

    def _sign_prefix(sign_str: Optional[str]) -> str:
        if not sign_str:
            return ""
        return "минус " if sign_str in ("-", "−") else "плюс "

    def _repl_dec_c(m):
        prefix = _sign_prefix(m.group(1))
        dec_words = _russian_decimal_to_words(m.group(2), m.group(3))
        return f"{prefix}{dec_words} градуса Цельсия"

    t = re.sub(
        r'(?<![0-9a-zA-Zа-яА-ЯёЁ])([+\-−])?\s*(\d{1,4}),(\d{1,3})\s*°\s*[CС](?![a-zA-Zа-яА-ЯёЁ])',
        _repl_dec_c,
        text,
    )

    def _repl_int_c(m):
        prefix = _sign_prefix(m.group(1))
        n = int(m.group(2))
        num_words = int_to_russian_cardinal(n, "m")
        last_two = n % 100
        last_one = n % 10
        if last_one == 1 and last_two != 11:
            deg_word = "градус"
        elif 2 <= last_one <= 4 and not (12 <= last_two <= 14):
            deg_word = "градуса"
        else:
            deg_word = "градусов"
        return f"{prefix}{num_words} {deg_word} Цельсия"

    t = re.sub(
        r'(?<![0-9a-zA-Zа-яА-ЯёЁ])([+\-−])?\s*(\d{1,4})\s*°\s*[CС](?![a-zA-Zа-яА-ЯёЁ])',
        _repl_int_c,
        t,
    )
    return t


def normalize_russian_decimals(text: str) -> str:
    """
    Защищает и озвучивает десятичные дроби до запуска пунктуационных регулярок:
    '3,5' -> 'три целых пять десятых', '0,25' -> 'ноль целых двадцать пять сотых'.
    """
    if not text:
        return ""

    # Обеспечиваем пробелы вокруг бинарного минуса/плюса рядом с десятичной дробью (3,5-2,5 -> 3,5 - 2,5)
    t = re.sub(r'(?<=\d,\d)\s*([+\-−=])\s*(?=\d)', r' \1 ', text)
    t = re.sub(r'(?<=\d)\s*([+\-−=])\s*(?=\d+,\d)', r' \1 ', t)

    return re.sub(
        r'(?<![0-9,])(\d{1,6}),(\d{1,6})(?![0-9,])',
        lambda m: _russian_decimal_to_words(m.group(1), m.group(2)),
        t,
    )


def normalize_russian_fractions(text: str) -> str:
    """
    Озвучивает компактные обыкновенные дроби до запуска слэш-регулярок:
    '1/2' -> 'одна вторая', '1/4' -> 'одна четвертая', '3/4' -> 'три четвертых'.
    Не затрагивает уравнения деления с пробелами или знаком '=' ('10 / 2 = 5').
    """
    if not text or "/" not in text:
        return text or ""

    def _repl_frac(m):
        num = int(m.group(1))
        denom = int(m.group(2))
        if num == 0 or denom < 2:
            return m.group(0)
        forms = RUSSIAN_FRACTION_DENOMINATORS.get(denom)
        if not forms:
            ord_forms = ORDINAL_FORMS.get(denom)
            if ord_forms and num % 10 == 1 and num % 100 != 11:
                return f"{int_to_russian_cardinal(num, 'f')} {ord_forms[4]}"
            return m.group(0)
        denom_word = forms[0] if (num % 10 == 1 and num % 100 != 11) else forms[1]
        return f"{int_to_russian_cardinal(num, 'f')} {denom_word}"

    return re.sub(
        r'(?<![:/\w\d.])\b(\d{1,2})/(\d{1,4})\b(?![:/\w\d.])(?!\s*=)',
        _repl_frac,
        text,
    )


def normalize_math_expressions(text: str) -> str:
    """
    Нормализует математические формулы, изолированные цифры и знаки в русском контексте:
    - Десятичные и обыкновенные дроби: '3,5' -> 'три целых пять десятых', '1/2' -> 'одна вторая'.
    - Температура: '-5 °C' -> 'минус пять градусов Цельсия'.
    - Сложение изолированных чисел: '9 + 3' -> 'девять плюс три'.
    - Перечисление цифр через союз 'и': '4 и 3' -> 'четыре и три'.
    - Деление двоеточием: '15 : 3 = 5' -> '15 разделить на 3 равно 5'.
    - Вычитание и сравнение: '9 - 3 = 6', '5 > 3' -> 'больше', '2 < 7' -> 'меньше'.
    - Защищает стандартные временные метки (14:30).
    """
    if not text:
        return ""

    has_cyrillic = bool(re.search(r'[а-яА-ЯёЁ]', text))
    has_math_ops = bool(
        re.search(
            r'[=+*\/÷·×:<>≤≥°]|(?<=\d),(?=\d)|(?<=[0-9a-zA-Z])\s*[-−]\s*(?=[0-9a-zA-Z])',
            text,
        )
    )
    if not (has_cyrillic or has_math_ops):
        return text

    t = text

    # Защищаем XML/SSML/est теги при прямом вызове функции
    protected_tags = []
    def _mask_tag(m):
        idx = len(protected_tags)
        protected_tags.append(m.group(0))
        return f"___MATH_TAG_{idx}___"

    t = re.sub(r'</?(?:est|sub|say-as|lang|voice|break)\b[^>]*>', _mask_tag, t, flags=re.IGNORECASE)

    time_placeholders = []
    def mask_time(m):
        idx = len(time_placeholders)
        time_placeholders.append(m.group(0))
        return f"___TIME_STAMP_{idx}___"

    t = re.sub(r'\b([01]?\d|2[0-3]):([0-5]\d)\b(?!\s*(=|[+\-*\/÷·×]))', mask_time, t)

    # Предварительная защита градусов Цельсия, обыкновенных и десятичных дробей
    t = normalize_celsius_expressions(t)
    t = normalize_russian_fractions(t)
    t = normalize_russian_decimals(t)

    # 0. Умножение чисел и выражений: dot ·, bullet •, *, ×, ✕, ✖
    # 0.1. Умножение с равенством («4 · 5 = 20» -> «четы́ре умно́жить на пять равно́ два́дцать»)
    def repl_mult_equation(m):
        n1 = int(m.group(1))
        n2 = int(m.group(2))
        n3 = int(m.group(3))
        w1 = int_to_russian_stressed_nominative(n1)
        w2 = int_to_russian_stressed_nominative(n2)
        w3 = int_to_russian_stressed_nominative(n3)
        return f"{w1} умно́жить на {w2} равно́ {w3}"

    t = re.sub(r'\b(\d{1,3})\s*[·•*×✕✖]\s*(\d{1,3})\s*=\s*(\d{1,4})\b', repl_mult_equation, t)

    # 0.2. Умножение без знака равенства («4 · 5» -> «четы́ре умно́жить на пять»)
    def repl_mult_expr(m):
        n1 = int(m.group(1))
        n2 = int(m.group(2))
        w1 = int_to_russian_stressed_nominative(n1)
        w2 = int_to_russian_stressed_nominative(n2)
        return f"{w1} умно́жить на {w2}"

    t = re.sub(r'\b(\d{1,3})\s*[·•*×✕✖]\s*(\d{1,3})\b', repl_mult_expr, t)
    t = re.sub(r'(\d+)\s*[·•*×✕✖]\s*(\d+)', r'\1 умно́жить на \2', t)
    t = re.sub(r'(?i)\b(ноль|один|два|две|три|четыре|пять|шесть|семь|восемь|девять|десять|\d+)\s*[·•*×✕✖]\s*(\d+)\b', r'\1 умно́жить на \2', t)
    t = re.sub(r'(?<=[0-9a-zA-Z\)])\s*[*·•×✕✖]\s*(?=[0-9a-zA-Z\(])', ' умно́жить на ', t)

    # 0.3. Явная замена операндов перед умножить / разделить в именительный падеж
    t = re.sub(r'\b4\s+умно[́\u0301]?жить\b', 'четы́ре умно́жить', t)
    t = re.sub(r'\b4\s+раздели[́\u0301]?ть\b', 'четы́ре разделить', t)
    t = re.sub(r'\b(\d{1,2})\s+умно[́\u0301]?жить\b', lambda m: f"{int_to_russian_stressed_nominative(int(m.group(1)))} умно́жить", t)

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

    t = re.sub(r'\b(\d{1,4}),\s*(\d{1,4})\s+и\s+(\d{1,4})\b(?!\s*(?:умножить|умно́жить|разделить|плюс|минус|[+\-*\/=·•×]))', repl_digits_and_3, t)

    def repl_digits_and(m):
        n1 = int(m.group(1))
        n2 = int(m.group(2))
        return f"{int_to_russian_cardinal(n1)} и {int_to_russian_cardinal(n2)}"

    t = re.sub(r'\b(\d{1,4})\s+и\s+(\d{1,4})\b(?!\s*(?:умножить|умно́жить|разделить|плюс|минус|[+\-*\/=·•×]))', repl_digits_and, t)

    # 3. Словесные описания знаков операций
    t = re.sub(r'(?i)знак\s*[«"“„]?\s*[:÷]\s*[»"”]?|(?<=\()[:÷](?=\))', 'знак «разделить» ', t)
    t = re.sub(r'(?i)знак\s*[«"“„]?\s*[*·•×✕✖]\s*[»"”]?|(?<=\()[*·•×✕✖](?=\))', 'знак «умно́жить» ', t)
    t = re.sub(r'(?i)знак\s*[«"“„]?\s*\+\s*[»"”]?|(?<=\()\+(?=\))', 'знак «плюс» ', t)
    t = re.sub(r'(?i)знак\s*[«"“„]?\s*[-−]\s*[»"”]?|(?<=\()[-−](?=\))', 'знак «минус» ', t)

    t = re.sub(r'(?<=[0-9a-zA-Z\)])\s*÷\s*(?=[0-9a-zA-Z\(])', ' разделить на ', t)
    t = re.sub(r'(\d+)\s*/\s*(\d+)(?=\s*=)', r'\1 разделить на \2', t)
    t = re.sub(r'(\d+)\s+/\s+(\d+)', r'\1 разделить на \2', t)

    # 4. Деление двоеточием между операндами
    t = re.sub(r'(\d+)\s*:\s*(\d+)', r'\1 разделить на \2', t)
    t = re.sub(r'(\b[a-zA-Z]\b)\s*:\s*(\d+|\b[a-zA-Z]\b)', r'\1 разделить на \2', t)
    t = re.sub(r'(\d+)\s*:\s*(\b[a-zA-Z]\b)', r'\1 разделить на \2', t)

    # 4.1. Математические знаки сравнения (<=, >=, ≤, ≥, <, >)
    t = re.sub(r'(?<=[0-9a-zA-Zа-яА-ЯёЁ\u0301\)])\s*(?:<=|≤)\s*(?=[+\-−]?[0-9a-zA-Zа-яА-ЯёЁ\(])', ' меньше или равно ', t)
    t = re.sub(r'(?<=[0-9a-zA-Zа-яА-ЯёЁ\u0301\)])\s*(?:>=|≥)\s*(?=[+\-−]?[0-9a-zA-Zа-яА-ЯёЁ\(])', ' больше или равно ', t)
    t = re.sub(r'(?<=[0-9a-zA-Zа-яА-ЯёЁ\u0301\)])\s*<\s*(?=[+\-−]?[0-9a-zA-Zа-яА-ЯёЁ\(])|\s+<\s+', ' меньше ', t)
    t = re.sub(r'(?<=[0-9a-zA-Zа-яА-ЯёЁ\u0301\)])\s*>\s*(?=[+\-−]?[0-9a-zA-Zа-яА-ЯёЁ\(])|\s+>\s+', ' больше ', t)

    # 5. Текстовое двоеточие в списках и перечислениях заменяем на запятую
    # Защищаем двоеточие после меток шагов (Шаг второй:, Шаг 1:) для естественной паузы
    step_colons: List[str] = []
    def _mask_step_colon(m):
        idx = len(step_colons)
        step_colons.append(m.group(0))
        return f"__STEP_COLON_{idx}__"

    t = re.sub(r'(?i)\bшаг\s+(?:[а-яёА-ЯЁ0-9\u0301\+]+)\s*:', _mask_step_colon, t)
    t = re.sub(r',?[ \t]*:[ \t]*(?!\n)', ', ', t)
    t = re.sub(r',?[ \t]*:[ \t]*(?=\n)', ',', t)
    t = re.sub(r'[ \t]+,', ',', t)
    t = re.sub(r',[ \t]*,', ',', t)
    for idx, orig_colon in enumerate(step_colons):
        t = t.replace(f"__STEP_COLON_{idx}__", orig_colon)

    t = re.sub(r'(?<=[0-9a-zA-Zа-яА-ЯёЁ\u0301])\s*\+\s*(?=[0-9a-zA-Zа-яА-ЯёЁ])|\s+\+\s+', ' плюс ', t)
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
        t = re.sub(r'(?<!°)(?<!°\s)\b' + var + r'\b', rep, t)

    t = re.sub(r'\b(плюс|минус|равно|разделить на|умножить на|умно\u0301жить на)\s+[aA]\b', r'\1 а', t)
    t = re.sub(r'\b[aA]\s+(плюс|минус|равно|разделить на|умножить на|умно\u0301жить на)\b', r'а \1', t)
    t = re.sub(r'\b(переменная|переменную|переменной|буква|букву|буквой)\s+[aA]\b', r'\1 а', t)

    for idx, orig_time in enumerate(time_placeholders):
        t = t.replace(f"___TIME_STAMP_{idx}___", orig_time)

    for idx, orig_tag in enumerate(protected_tags):
        t = t.replace(f"___MATH_TAG_{idx}___", orig_tag)

    t = re.sub(r'\s+', ' ', t).strip()
    return t


def normalize_number_ranges(text: str) -> str:
    """
    Нормализует диапазоны чисел: '1-9' -> 'от 1 до 9'.
    Исключает знаки вычитания, дроби и равенства (например, '9 - 3 = 6', '3,2 - 5,1').
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

    pattern = re.compile(r'(?<![,./\d\-−])\b(\d+)\s*[-–—]\s*(\d+)\b(?![,./\d])(?!\s*=)')
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

    # Восстановление буквы «ё»: песик -> пёсик
    t = re.sub(r'(?i)\bпесик([а-яё]*)\b', r'пёсик\1', t)

    # Исправление падежной ошибки модели: «по трёх» -> «по три́»
    t = re.sub(r'(?i)\bпо\s+тр[её]х\b', 'по три́', t)

    # Исправление согласования: «в две кувшина» -> «в два кувши́на»
    t = re.sub(r'(?i)\bв\s+две\s+кувшина\b', 'в два кувши́на', t)

    # Фиксация ударения: контекстный омограф «со зна́ком» vs «знако́м с темой», «знак» -> «зна́к»
    t = _apply_znakom_homograph(t)
    t = re.sub(r'(?i)\bзнак(?![\u0301])\b', lambda m: 'Зна\u0301к' if m.group(0)[0].isupper() else 'зна\u0301к', t)

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

    # Сохраняем знак ударения \u0301 только на гласных буквах
    t = re.sub(r'(?<![аеёиоуыэюяАЕЁИОУЫЭЮЯ])\u0301', '', t)
    t = apply_custom_phonetic_map(t)
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


ESTONIAN_UNIT_FORMS: Dict[str, Dict[str, str]] = {
    "km²": {"nom": "ruutkilomeeter", "part": "ruutkilomeetrit", "stem": "ruutkilomeetri"},
    "m²": {"nom": "ruutmeeter", "part": "ruutmeetrit", "stem": "ruutmeetri"},
    "dm²": {"nom": "ruutdetsimeeter", "part": "ruutdetsimeetrit", "stem": "ruutdetsimeetri"},
    "cm²": {"nom": "ruutsentimeeter", "part": "ruutsentimeetrit", "stem": "ruutsentimeetri"},
    "mm²": {"nom": "ruutmillimeeter", "part": "ruutmillimeetrit", "stem": "ruutmillimeetri"},
    "km³": {"nom": "kuupkilomeeter", "part": "kuupkilomeetrit", "stem": "kuupkilomeetri"},
    "m³": {"nom": "kuupmeeter", "part": "kuupmeetrit", "stem": "kuupmeetri"},
    "dm³": {"nom": "kuupdetsimeeter", "part": "kuupdetsimeetrit", "stem": "kuupdetsimeetri"},
    "cm³": {"nom": "kuupsentimeeter", "part": "kuupsentimeetrit", "stem": "kuupsentimeetri"},
    "mm³": {"nom": "kuupmillimeeter", "part": "kuupmillimeetrit", "stem": "kuupmillimeetri"},
    "km": {"nom": "kilomeeter", "part": "kilomeetrit", "stem": "kilomeetri"},
    "m": {"nom": "meeter", "part": "meetrit", "stem": "meetri"},
    "cm": {"nom": "sentimeeter", "part": "sentimeetrit", "stem": "sentimeetri"},
    "mm": {"nom": "millimeeter", "part": "millimeetrit", "stem": "millimeetri"},
    "dm": {"nom": "detsimeeter", "part": "detsimeetrit", "stem": "detsimeetri"},
    "kg": {"nom": "kilogramm", "part": "kilogrammi", "stem": "kilogrammi"},
    "g": {"nom": "gramm", "part": "grammi", "stem": "grammi"},
    "l": {"nom": "liiter", "part": "liitrit", "stem": "liitri"},
    "t": {"nom": "tonn", "part": "tonni", "stem": "tonni"},
    "s": {"nom": "sekund", "part": "sekundit", "stem": "sekundi"},
    "sek": {"nom": "sekund", "part": "sekundit", "stem": "sekundi"},
    "min": {"nom": "minut", "part": "minutit", "stem": "minuti"},
    "h": {"nom": "tund", "part": "tundi", "stem": "tunni"},
    "tk": {"nom": "tükk", "part": "tükki", "stem": "tüki"},
    "kr": {"nom": "kroon", "part": "krooni", "stem": "krooni"},
    "snt": {"nom": "sent", "part": "senti", "stem": "sendi"},
    "lk": {"nom": "lehekülg", "part": "lehekülge", "stem": "lehekülje"},
}

ESTONIAN_ONES: Dict[int, str] = {
    0: "null", 1: "üks", 2: "kaks", 3: "kolm", 4: "neli", 5: "viis",
    6: "kuus", 7: "seitse", 8: "kaheksa", 9: "üheksa"
}

ESTONIAN_TEENS: Dict[int, str] = {
    10: "kümme", 11: "üksteist", 12: "kaksteist", 13: "kolmteist", 14: "neliteist",
    15: "viisteist", 16: "kuusteist", 17: "seitseteist", 18: "kaheksateist",
    19: "üheksateist"
}

ESTONIAN_TENS: Dict[int, str] = {
    20: "kakskümmend", 30: "kolmkümmend", 40: "nelikümmend", 50: "viiskümmend",
    60: "kuuskümmend", 70: "seitsekümmend", 80: "kaheksakümmend", 90: "üheksakümmend"
}

ESTONIAN_CARDINAL_WORDS: Dict[int, str] = {
    0: "null", 1: "üks", 2: "kaks", 3: "kolm", 4: "neli", 5: "viis",
    6: "kuus", 7: "seitse", 8: "kaheksa", 9: "üheksa", 10: "kümme",
    11: "üksteist", 12: "kaksteist", 13: "kolmteist", 14: "neliteist",
    15: "viisteist", 16: "kuusteist", 17: "seitseteist", 18: "kaheksateist",
    19: "üheksateist", 20: "kakskümmend",
}

def int_to_estonian_cardinal(n: int) -> str:
    """
    Преобразует целое неотрицательное число (0..999999) в эстонское количественное числительное:
    4 -> 'neli', 8 -> 'kaheksa', 12 -> 'kaksteist', 25 -> 'kakskümmend viis', 100 -> 'sada'.
    """
    if n < 0:
        return f"miinus {int_to_estonian_cardinal(-n)}"
    if n in ESTONIAN_ONES:
        return ESTONIAN_ONES[n]
    if n in ESTONIAN_TEENS:
        return ESTONIAN_TEENS[n]
    if n in ESTONIAN_TENS:
        return ESTONIAN_TENS[n]
    if 20 < n < 100:
        tens = (n // 10) * 10
        rem = n % 10
        return f"{ESTONIAN_TENS[tens]} {ESTONIAN_ONES[rem]}"
    if n == 100:
        return "sada"
    if 100 < n < 1000:
        hundreds = n // 100
        rem = n % 100
        h_prefix = "sada" if hundreds == 1 else f"{ESTONIAN_ONES[hundreds]}sada"
        if rem == 0:
            return h_prefix
        return f"{h_prefix} {int_to_estonian_cardinal(rem)}"
    if n == 1000:
        return "tuhat"
    if 1000 < n < 1000000:
        thousands = n // 1000
        rem = n % 1000
        t_prefix = "tuhat" if thousands == 1 else f"{int_to_estonian_cardinal(thousands)} tuhat"
        if rem == 0:
            return t_prefix
        return f"{t_prefix} {int_to_estonian_cardinal(rem)}"
    return str(n)


def verbalize_estonian_cardinal_numbers(text: str) -> str:
    """
    Преобразует арабские цифры в эстонском тексте в количественные числительные словами:
    '8 ja 4.' -> 'kaheksa ja neli.'
    'Summa on 12.' -> 'Summa on kaksteist.'
    Защищает дефисные падежные формы (5-ga, 10-ni, 3-st) и время (14:30).
    """
    if not text:
        return ""

    hyphen_masked: List[str] = []
    def _mask_hyphen(m: re.Match) -> str:
        idx = len(hyphen_masked)
        hyphen_masked.append(m.group(0))
        return f"__ESTHYPHEN_{idx}__"

    # 1. Защищаем падежные окончания чисел через дефис (5-ga, 10-ni, 3-st, 2-le...)
    t = re.sub(
        r'\b\d+[-–—]+(?:ga|ni|st|le|lt|sse|s|l|ks|na|ta)\b',
        _mask_hyphen,
        text,
        flags=re.IGNORECASE,
    )

    # 2. Числа с точкой на конце предложения или перед пробелом (4. -> neli.)
    # Предотвращает ошибочное произношение порядкового ('neljas') вместо количественного ('neli')
    def _repl_num_dot(m: re.Match) -> str:
        try:
            num = int(m.group(1))
            return f"{int_to_estonian_cardinal(num)}."
        except ValueError:
            return m.group(0)

    t = re.sub(r'\b(\d+)\.(?!\d)', _repl_num_dot, t)

    # 3. Одиночные числительные без точки
    def _repl_num(m: re.Match) -> str:
        try:
            num = int(m.group(1))
            return int_to_estonian_cardinal(num)
        except ValueError:
            return m.group(0)

    t = re.sub(r'\b(\d+)\b', _repl_num, t)

    for idx, orig in enumerate(hyphen_masked):
        t = t.replace(f"__ESTHYPHEN_{idx}__", orig)

    return t

ESTONIAN_FRACTION_DENOMINATORS: Dict[int, Tuple[str, str]] = {
    2: ("kahendik", "kahendikku"),
    3: ("kolmandik", "kolmandikku"),
    4: ("neljandik", "neljandikku"),
    5: ("viiendik", "viiendikku"),
    6: ("kuuendik", "kuuendikku"),
    7: ("seitsmendik", "seitsmendikku"),
    8: ("kaheksandik", "kaheksandikku"),
    9: ("üheksandik", "üheksandikku"),
    10: ("kümnendik", "kümnendikku"),
    12: ("kaheteistkümnendik", "kaheteistkümnendikku"),
    20: ("kahekümnendik", "kahekümnendikku"),
    100: ("sajandik", "sajandikku"),
}


def normalize_estonian_fractions(text: str) -> str:
    """
    Озвучивает обыкновенные дроби в эстонском тексте:
    '1/2' -> 'üks kahendik', '1/4' -> 'üks neljandik', '3/4' -> 'kolm neljandikku'.
    Не затрагивает уравнения деления ('10 / 2 = 5').
    """
    if not text or "/" not in text:
        return text or ""

    def _repl_est_frac(m):
        num = int(m.group(1))
        denom = int(m.group(2))
        if num == 0 or denom < 2:
            return m.group(0)
        forms = ESTONIAN_FRACTION_DENOMINATORS.get(denom)
        if not forms:
            return m.group(0)
        num_word = ESTONIAN_CARDINAL_WORDS.get(num, str(num))
        denom_word = forms[0] if num == 1 else forms[1]
        return f"{num_word} {denom_word}"

    return re.sub(
        r'(?<![:/\w\d.])\b(\d{1,2})/(\d{1,3})\b(?![:/\w\d.])(?!\s*=)',
        _repl_est_frac,
        text,
    )


def normalize_estonian_math_signs(text: str) -> str:
    """
    Явно озвучивает знаки операций в эстонском режиме (lang=et):
    '+' -> 'pluss', '-' -> 'miinus' (сохраняя падежные дефисы 5-ga, 10-ni), '=' -> 'võrdub'.
    """
    if not text:
        return ""

    t = text
    t = re.sub(r'\s*\+\s*', ' pluss ', t)
    t = re.sub(r'\s*=\s*', ' võrdub ', t)

    # Бинарный минус с пробелами (9 - 3, m - 5) или в уравнении
    t = re.sub(r'(?<=\S)\s+[-−]\s+(?=\S)', ' miinus ', t)
    t = re.sub(
        r'(\b\d+(?:\s+koma\s+\d+)?)\s*[-−]\s*(\d+(?:\s+koma\s+\d+)?)(?=\s*(?:võrdub|=))',
        r'\1 miinus \2',
        t,
    )
    # Унарный минус перед числом (-5 -> miinus 5)
    t = re.sub(r'(?:^|(?<=[\s(]))[-−](?=\d)', 'miinus ', t)

    return re.sub(r'\s+', ' ', t).strip()


def normalize_estonian_core_units(text: str) -> str:
    """
    Позиционно-независимая замена базовых сокращений единиц измерения в эстонском тексте:
    kg, km, m, l, g, cm, mm, dm, tk, snt, kr.
    Учитывает падеж:
    - число оканчивается на 1 (кроме 11): именительный падеж (kilogramm, kilomeeter, meeter, liiter, gramm...).
    - остальные числа: партитив (kilogrammi, kilomeetrit, meetrit, liitrit, grammi...).
    Работает перед словами в середине предложения: '20 kg pirne' -> '20 kilogrammi pirne'.
    """
    if not text:
        return ""

    core_units_map = {
        "kg": ("kilogramm", "kilogrammi"),
        "km": ("kilomeeter", "kilomeetrit"),
        "cm": ("sentimeeter", "sentimeetrit"),
        "mm": ("millimeeter", "millimeetrit"),
        "dm": ("detsimeeter", "detsimeetrit"),
        "tk": ("tükk", "tükki"),
        "snt": ("sent", "senti"),
        "kr": ("kroon", "krooni"),
        "m": ("meeter", "meetrit"),
        "l": ("liiter", "liitrit"),
        "g": ("gramm", "grammi"),
    }

    t = text
    for u, (nom, part) in core_units_map.items():
        pattern = rf'(\d+)\s*{re.escape(u)}\.?(?=\s|[.,!?:]|$)'
        def _repl(m, n=nom, p=part):
            num = int(m.group(1))
            form = n if (num % 10 == 1 and num % 100 != 11) else p
            return f"{m.group(1)} {form}"
        t = re.sub(pattern, _repl, t, flags=re.IGNORECASE)
    return t


def normalize_estonian_measurement_units(text: str) -> str:
    """
    Нормализует сокращения единиц измерения в эстонском тексте:
    - Поддерживает единицы площади и объема: m² -> ruutmeeter / ruutmeetrit, cm³ -> kuupsentimeetrit.
    - Строгая привязка линейных единиц к предшествующим цифрам (?<=\\d)\\s*.
    - Учет грамматического падежа:
      • после 1 (или оканчивающихся на 1, кроме 11): именительный падеж ед.ч.
      • после остальных чисел: партитив.
    - Нумерация страниц: lk 42, lk. 42 -> lehekülg 42; 42 lk -> 42 lehekülge.
    - Переменные формул без предшествующих цифр (s = v · t, m + 5 = 10) не заменяются.
    - Падежные окончания чисел (6-l, 5-s) защищены от подмены на литры/секунды.
    """
    if not text:
        return ""

    t = text
    # Канонизируем ^2 / ^3 для метрических единиц в ² / ³
    t = re.sub(r'\b(km|cm|mm|dm|m)\^2\b', r'\1²', t, flags=re.IGNORECASE)
    t = re.sub(r'\b(km|cm|mm|dm|m)\^3\b', r'\1³', t, flags=re.IGNORECASE)

    # 1. Нумерация страниц: lk 42, lk. 42 -> lehekülg 42
    t = re.sub(r'\blk\.?\s*(\d+)', r'lehekülg \1', t, flags=re.IGNORECASE)

    area_vol_order = 'km²|cm²|mm²|dm²|m²|km³|cm³|mm³|dm³|m³'
    linear_units_order = 'km|cm|mm|dm|kg|sek|min|snt|kr|tk|lk|m|g|l|t|s|h'
    units_order = f'{area_vol_order}|{linear_units_order}'

    # 2. Единицы измерения с падежными окончаниями через дефис: 5 km-st, 1 m-ga, 2 kg-le
    def repl_case(m):
        num = m.group(1)
        unit = m.group(2).lower()
        suffix = m.group(3)
        forms = ESTONIAN_UNIT_FORMS.get(unit)
        if forms:
            return f"{num} {forms['stem']}{suffix}"
        return m.group(0)

    t = re.sub(
        rf'\b(\d+)\s*({units_order})-(ga|st|sse|le|lt|s|na|ks|ni|ta)\b',
        repl_case,
        t,
        flags=re.IGNORECASE,
    )

    # 2.1. Базовые единицы измерения (kg, km, m, l, g, cm, mm, dm, tk, snt, kr) перед словами/знаками
    t = normalize_estonian_core_units(t)

    # 3. Единицы измерения, привязанные к предшествующему числу
    def repl_unit(m):
        num_str = m.group(1)
        unit = m.group(2).lower()
        num = int(num_str)
        forms = ESTONIAN_UNIT_FORMS.get(unit)
        if not forms:
            return m.group(0)
        # Именительный ед.ч. после 1 (1, 21, 31, кроме 11), иначе партитив
        if num % 10 == 1 and num % 100 != 11:
            form = forms["nom"]
        else:
            form = forms["part"]
        return f"{num_str} {form}"

    t = re.sub(
        rf'\b(\d+)\s*({units_order})\.?(?![a-zA-ZõäöüÕÄÖÜšžŠŽ0-9\-²³\u00b2\u00b3])',
        repl_unit,
        t,
        flags=re.IGNORECASE,
    )

    # 4. Вопросительные и словарные конструкции с multi-letter единицами и единицами площади/объема
    def repl_mitu(m):
        prefix = m.group(1)
        unit = m.group(2).lower()
        forms = ESTONIAN_UNIT_FORMS.get(unit)
        if forms:
            return f"{prefix}{forms['part']}"
        return m.group(0)

    t = re.sub(rf'(?i)\b(mitu\s+)({area_vol_order}|km|cm|mm|dm|kg|g|l|tk)(?![a-zA-Z0-9])', repl_mitu, t)
    t = re.sub(
        rf'(?i)\b(ühik:\s*)({area_vol_order}|cm|mm|dm|km|kg)(?![a-zA-Z0-9])',
        lambda m: f"{m.group(1)}{ESTONIAN_UNIT_FORMS[m.group(2).lower()]['part']}",
        t,
    )

    # Изолированные единицы площади/объема с явной степенью ² / ³ (m² -> ruutmeeter, cm³ -> kuupsentimeetrit)
    def _repl_standalone_area_vol(m):
        u = m.group(1).lower()
        forms = ESTONIAN_UNIT_FORMS.get(u)
        if not forms:
            return m.group(0)
        return forms["nom"] if u == "m²" else forms["part"]

    t = re.sub(rf'(?<![a-zA-Z0-9])\b({area_vol_order})(?![a-zA-Z0-9])', _repl_standalone_area_vol, t, flags=re.IGNORECASE)

    return t


def normalize_text_for_estonian_tts(
    text: str,
    verbalize_math_signs: bool = False,
    verbalize_numbers: bool = False,
) -> str:
    """
    Нормализует эстонский текст:
    - Десятичные дроби (3,5 -> 3 koma 5) и обыкновенные дроби (1/2 -> üks kahendik).
    - Время (14:30) изолируется от деления и пунктуационных разрывов.
    - Единицы измерения (km -> kilomeetrit, m² -> ruutmeeter / ruutmeetrit, cm³ -> kuupsentimeetrit).
    - Порядковые числительные (1. klass -> esimene klass; 15. harjutus сохраняет точку для SSML ordinal).
    - Для номеров в конце предложения без существительного (Vastus on 12.) срезает точку -> Vastus on 12.
    - Заменяет математические знаки умножения (·, •, *, ×) на korda.
    - В режиме verbalize_math_signs=True озвучивает + -> pluss, - -> miinus, = -> võrdub.
    - В режиме verbalize_numbers=True вербализует арабские цифры в эстонские количественные числительные
      (8 ja 4. -> kaheksa ja neli.), предотвращая произношение порядкового 'neljas' вместо 'neli'.
    - Сохраняет дефисы для падежных окончаний чисел (5-ga, 10-ni).
    """
    if not text:
        return ""

    # 1. До пунктуационных и математических регулярок защищаем время, десятичные и обыкновенные дроби
    time_est: List[str] = []
    def _mask_est_time(m):
        idx = len(time_est)
        time_est.append(m.group(0))
        return f"ESTTIMEPLACEHOLDER{idx}ESTTIME"

    t = re.sub(r'\b([01]?\d|2[0-3]):([0-5]\d)\b(?!\s*(=|[+\-*\/÷·×]))', _mask_est_time, text)

    # Десятичные дроби: 3,5 -> 3 koma 5
    t = re.sub(r'(?<![0-9,])(\d+),(\d+)(?![0-9,])', r'\1 koma \2', t)

    # Обыкновенные дроби: 1/2 -> üks kahendik, 1/4 -> üks neljandik, 3/4 -> kolm neljandikku
    t = normalize_estonian_fractions(t)

    # Единицы измерения и лексикон
    t = normalize_estonian_measurement_units(t)
    t = apply_phonetic_substitutions(t, is_estonian=True)

    # Градусы Цельсия в эстонском контексте
    t = re.sub(
        r'\b(\d+)\s*°\s*[CС](?![a-zA-ZõäöüÕÄÖÜšžŠŽ])',
        lambda m: f"{m.group(1)} {'kraad' if (int(m.group(1)) % 10 == 1 and int(m.group(1)) % 100 != 11) else 'kraadi'} Celsiust",
        t,
    )

    # Замена знаков умножения на korda в эстонском контексте
    t = re.sub(r'(\d+)\s*[·•*×✕✖]\s*(\d+)', r'\1 korda \2', t)
    t = re.sub(r'(?<=\d)\s*[\u2715\u2716](?!\s*\d)', '', t)
    t = re.sub(r'[\u2715\u2716]', '', t)

    # Замена знаков деления на jagatud в эстонском контексте
    t = re.sub(r'(\d+|\b[a-zA-Z]\b)\s*[:/÷]\s*(\d+|\b[a-zA-Z]\b)', r'\1 jagatud \2', t)

    if verbalize_math_signs:
        t = normalize_estonian_math_signs(t)

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

    t = est_ord_pattern.sub(repl_est_ord, t)

    t = re.sub(r'[\[\]{}()]', ' ', t)
    t = re.sub(r'(?<=[a-zA-ZõäöüÕÄÖÜšžŠŽ0-9])\s*/\s*(?=[a-zA-ZõäöüÕÄÖÜšžŠŽ0-9])', ' või ', t)
    t = re.sub(r'\s+/\s+', ' või ', t)
    t = re.sub(r'[/\\|]', ' ', t)
    if verbalize_numbers:
        t = verbalize_estonian_cardinal_numbers(t)
    else:
        # Сохраняем точку у порядковых числительных перед строчным эстонским существительным (15. harjutus)
        t = re.sub(r'(\b\d+)\s*\.(?!\d|\s+[a-zõäöüšž]{2,})', r'\1 ', t)
        t = re.sub(r'(\d+)([,!?;:])', r'\1 \2', t)
        t = re.sub(r'([,!?;:])(\d+)', r'\1 \2', t)
        t = re.sub(r'(\d+)[-–—]+(?=(?:ga|ni|st|le|lt|sse|s|l|ks|na|ta)\b)', r'\1-', t, flags=re.IGNORECASE)
        t = re.sub(r'(\d+)[-–—]+(?!(?:ga|ni|st|le|lt|sse|s|l|ks|na|ta)\b)', r'\1 ', t, flags=re.IGNORECASE)
        t = re.sub(r'[-–—]+(\d+)', r' \1', t)

    # Восстанавливаем маски времени в самом конце, чтобы 14:30 не разбивалось на 14 : 30
    for idx, orig_tm in enumerate(time_est):
        t = t.replace(f"ESTTIMEPLACEHOLDER{idx}ESTTIME", orig_tm)

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

    sub_tags = []
    def mask_sub_tag(match):
        idx = len(sub_tags)
        sub_tags.append(match.group(0))
        return f"SSMLSUBTAGPLACEHOLDER{idx}SSMLSUBTAG"

    t = re.sub(
        r'<sub(?:\s+[^>]*)?>.*?<\s*/\s*sub\s*>',
        mask_sub_tag,
        t,
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

    # Защита знаков умножения при очистке Markdown
    t = re.sub(r'(?<=[0-9a-zA-Z\)])\s*[*·•×✕✖]\s*(?=[0-9a-zA-Z\(])', ' ___MULT_STAR___ ', t)
    t = re.sub(r'\*+', ' ', t)
    t = t.replace('___MULT_STAR___', ' * ')

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

    for idx, orig_sub in enumerate(sub_tags):
        t = t.replace(f"SSMLSUBTAGPLACEHOLDER{idx}SSMLSUBTAG", orig_sub)

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

    sub_tags = []
    def mask_sub_tag(match):
        idx = len(sub_tags)
        sub_tags.append(match.group(0))
        return f"SSMLSUBTAGPLACEHOLDER{idx}SSMLSUBTAG"

    t = re.sub(
        r'<sub(?:\s+[^>]*)?>.*?<\s*/\s*sub\s*>',
        mask_sub_tag,
        t,
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

    t = normalize_celsius_expressions(t)
    t = normalize_russian_fractions(t)
    t = normalize_russian_decimals(t)
    t = normalize_russian_ordinals_with_dot(t)
    t = normalize_roman_numerals(t)
    t = normalize_number_ranges(t)
    t = normalize_math_expressions(t)

    for idx, orig_q in enumerate(est_quotes):
        t = t.replace(f"ESTQUOTEPLACEHOLDER{idx}ESTQUOTE", orig_q)

    for idx, orig_sub in enumerate(sub_tags):
        t = t.replace(f"SSMLSUBTAGPLACEHOLDER{idx}SSMLSUBTAG", orig_sub)

    for idx, orig_t in enumerate(est_tags):
        t = t.replace(f"ESTTAGPLACEHOLDER{idx}ESTTAG", orig_t)

    return re.sub(r'\s+', ' ', t).strip()


CARD_HEADER_REGEX = re.compile(
    r'^(?:(?:пример\s+решения(?:\s+(?:с\s+другими\s+числами|\(näidis\)|\(наидис\)))?)|'
    r'(?:образец(?:\s+решения)?)|'
    r'(?:näidis(?:\s+lahendus)?))\s*[:.\-—]?\s*',
    re.IGNORECASE
)


def filter_card_headers_from_speech(text: str) -> str:
    """
    Исключает заголовок карточки («Пример решения», «Образец», «Näidis»,
    «Пример решения с другими числами») из текста озвучки.
    """
    if not text:
        return ""
    t = CARD_HEADER_REGEX.sub('', text.strip())
    # Если заголовок стоял отдельной строкой или перед точкой/двоеточием
    t = re.sub(
        r'^(?:пример\s+решения(?:\s+с\s+другими\s+числами)?|образец(?:\s+решения)?|näidis)\s*[.!?:;—\-]?\s+',
        '',
        t,
        flags=re.IGNORECASE
    )
    return t.strip()


ESTONIAN_DETECT_WORDS = {
    # Core grammar & math keywords
    "liidetav", "liidetavad", "liidetavat", "liidetava", "liidetavale",
    "vähendatav", "vähendatavat", "vähendatava", "vähendatavale",
    "vähendaja", "vähendajat", "vähendajale",
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
    # Task vocabulary & verbs
    "jagas", "jagama", "jaga", "jagasid", "jaganud",
    "võrdselt", "lemmikloomad", "lemmikloom", "lemmiklooma",
    "mitu", "mitmel", "mitme",
    "kapsad", "kapsast", "kapsaid", "kass", "koer", "loomad", "loom",
    "on", "oli", "olid", "pole", "olnud",
    "ja", "ning", "või", "kui", "palju", "kokku", "alles",
    "arvuta", "lahenda", "kirjuta", "loe", "leia", "joonesta", "vaata",
    "korda", "tükki", "meetrit", "sentimeetrit", "kilogrammi",
    "toodi", "kauplus", "kauplusesse", "pirne", "pirnid", "õunad", "õunu", "suhkur", "suhkrut",
}

ENGLISH_BRAND_WORDS = {
    "roblox", "minecraft", "lego", "mindstorms", "youtube", "tiktok", "tik", "tok",
    "brawl", "stars", "fortnite", "google", "apple", "discord", "steam",
    "playstation", "xbox", "scratch", "it", "ai", "wifi", "wi-fi", "python",
    "wasd", "w", "a", "s", "d", "shift", "space", "enter", "ctrl", "alt", "esc", "escape"
}


def auto_tag_estonian_phrases(text: str) -> str:
    """
    Автоматически обнаруживает эстонские слова и словосочетания без тегов в русском тексте
    (по эстонским буквам õ, ä, ö, ü, š, ž и словарным совпадениям вне brand_fallbacks)
    и оборачивает их в теги <est>...</est> для маршрутизации в эстонский голос et-EE-AnuNeural.
    """
    if not text:
        return ""

    # Если во всем тексте нет кириллицы (чисто эстонский или английский текст), не оборачиваем
    if not re.search(r'[а-яА-ЯёЁ]', text):
        return text

    # Защищаем уже существующие теги <est>...</est>
    existing_tags = []
    def mask_existing(m):
        idx = len(existing_tags)
        existing_tags.append(m.group(0))
        return f"__EXISTING_EST_TAG_{idx}__"

    t = re.sub(r'<\s*est(?:\s+[^>]*)?>.*?<\s*/\s*est\s*>', mask_existing, text, flags=re.IGNORECASE | re.DOTALL)

    # Защищаем цитаты и круглые скобки (они уже маршрутизируются парсером сегментов)
    existing_quotes = []
    def mask_quotes(m):
        idx = len(existing_quotes)
        existing_quotes.append(m.group(0))
        return f"__EXISTING_QUOTE_{idx}__"

    t = re.sub(r'([\'\"«“][^\'\"»”]+[\'\"»”])', mask_quotes, t)
    t = re.sub(r'(\([^\)]+\))', mask_quotes, t)

    # Ищем последовательности латинских слов (включая эстонские диакритики)
    pattern = re.compile(r'\b[a-zA-ZäöüõÄÖÜÕšžŠŽ0-9]+(?:\s+[a-zA-ZäöüõÄÖÜÕšžŠŽ0-9]+)*\b')

    def repl_est_phrase(m):
        phrase = m.group(0)
        words = phrase.split()
        if not words:
            return phrase

        # Исключаем химические формулы и аббревиатуры (CO2, H2O, DNA, ATP)
        if is_chemical_formula_or_acronym(phrase):
            return phrase

        # Проверяем, не является ли вся фраза английскими брендами / клавишами
        if all(w.lower() in ENGLISH_BRAND_WORDS for w in words):
            return phrase

        # Одиночные буквы переменных (x, y, z, a, b, c) не трогаем
        if len(words) == 1 and words[0].lower() in {"x", "y", "z", "a", "b", "c"}:
            return phrase

        # Проверяем наличие специфических эстонских букв
        has_est_chars = bool(re.search(r'[õäöüšžÕÄÖÜŠŽ]', phrase))

        # Проверяем наличие известных эстонских слов
        has_est_word = any(w.lower() in ESTONIAN_DETECT_WORDS for w in words)

        if has_est_chars or has_est_word:
            return f"<est>{phrase}</est>"

        return phrase

    t = pattern.sub(repl_est_phrase, t)

    for idx, orig in enumerate(existing_quotes):
        t = t.replace(f"__EXISTING_QUOTE_{idx}__", orig)

    for idx, orig in enumerate(existing_tags):
        t = t.replace(f"__EXISTING_EST_TAG_{idx}__", orig)

    return t


def prepare_speech_text(display_text: str, is_russian_context: bool = True) -> str:
    """
    Главная точка входа для трансформации Display Text -> Speech Text (линейный идемпотентный пайплайн):
    1. Изоляция эстонских фрагментов <est>...</est>, неразмеченных эстонских цитат/скобок и автоматическое тегирование.
    2. Защита чисел, десятичных/обыкновенных дробей, времени и градусов Цельсия до пунктуационных регулярок.
    3. Базовая очистка и замена математических операций и знаков (·, •, *, ×, :, +, -, =, <, > в слова).
    4. Единая словарная замена англицизмов/брендов без дублей (Roblox -> Ро́блокс, Minecraft -> Ма́йнкрафт и т.д.).
    5. Русская грамматика и омографы (со зна́ком vs знако́м с темой, в два ша́га, вычита́ем, велопутеше́ствие).
    6. Восстановление эстонских фрагментов и их нормализация по правилам эстонского языка.
    Строго идемпотентна: prepare_speech_text(prepare_speech_text(x)) == prepare_speech_text(x).
    """
    if not display_text:
        return ""

    has_cyrillic = bool(re.search(r'[а-яА-ЯёЁ]', display_text))
    has_latin = bool(re.search(r'[a-zA-ZäöüõÄÖÜÕšžŠŽ]', display_text))

    if not is_russian_context:
        return normalize_text_for_estonian_tts(display_text)
    elif not has_cyrillic and has_latin:
        # Если в тексте нет кириллицы, но есть латинские слова, проверяем не является ли он чисто английскими брендами
        raw_words = re.sub(r'[^a-zA-Z0-9\s-]', '', display_text).split()
        if not (raw_words and all(w.lower() in ENGLISH_BRAND_WORDS for w in raw_words)):
            return normalize_text_for_estonian_tts(display_text)

    # ШАГ 1: Обнаружение и изоляция эстонских фрагментов
    t = auto_tag_estonian_phrases(display_text)

    est_tags = []
    def mask_est_tag(match):
        idx = len(est_tags)
        est_tags.append(match.group(0))
        return f"ESTTAGPLACEHOLDER{idx}ESTTAG"

    t = re.sub(
        r'<\s*est(?:\s+[^>]*)?>.*?<\s*/\s*est\s*>',
        mask_est_tag,
        t,
        flags=re.IGNORECASE | re.DOTALL,
    )

    sub_tags = []
    def mask_sub_tag(match):
        idx = len(sub_tags)
        sub_tags.append(match.group(0))
        return f"SSMLSUBTAGPLACEHOLDER{idx}SSMLSUBTAG"

    t = re.sub(
        r'<sub(?:\s+[^>]*)?>.*?<\s*/\s*sub\s*>',
        mask_sub_tag,
        t,
        flags=re.IGNORECASE | re.DOTALL,
    )

    t = filter_card_headers_from_speech(t)

    # Защищаем эстонские цитаты и скобки (без кириллицы, брендов, формул и матем. знаков)
    est_wrappers: List[str] = []
    def _mask_est_wrapper(m):
        full = m.group(0)
        inner = full[1:-1].strip()
        if (
            len(inner) >= 2
            and re.search(r'[a-zA-ZäöüõÄÖÜÕšžŠŽ]{2,}', inner)
            and not re.search(r'[а-яА-ЯёЁ=+*÷·×<>°]|ESTTAGPLACEHOLDER|SSMLSUBTAGPLACEHOLDER', inner)
            and not is_chemical_formula_or_acronym(inner)
            and not all(w.lower() in ENGLISH_BRAND_WORDS for w in re.sub(r'[^a-zA-Z0-9\s-]', '', inner).split())
        ):
            idx = len(est_wrappers)
            est_wrappers.append(full)
            return f"ESTWRAPPLACEHOLDER{idx}ESTWRAP"
        return full

    t = re.sub(r'([\'\"«“„][^\'\"»”]+[\'\"»”])|(\([^\)]+\))', _mask_est_wrapper, t)

    # ШАГ 2: Защита градусов Цельсия и дробей до пунктуационных/диапазонных/слэш-регулярок
    t = normalize_celsius_expressions(t)
    t = normalize_russian_fractions(t)
    t = normalize_russian_decimals(t)

    # ШАГ 3: Базовая очистка и замена математических операций и знаков
    t = clean_text_for_speech(t)
    t = normalize_russian_ordinals_with_dot(t)
    t = normalize_roman_numerals(t)
    t = normalize_number_ranges(t)
    t = normalize_time_expressions(t)
    t = normalize_math_expressions(t)

    # ШАГ 4: Единая словарная замена англицизмов и брендов
    t = normalize_loanwords_and_brands(t)
    t = apply_custom_phonetic_map(t)

    # ШАГ 5: Русская грамматика, ударения омографов и буква ё
    t = normalize_russian_accents_and_yo(t)
    t = apply_phonetic_substitutions(t, is_estonian=False)
    t = re.sub(r'\u0301+', '\u0301', t)

    # ШАГ 6: Восстановление эстонских фрагментов и их нормализация
    for idx, orig_w in enumerate(est_wrappers):
        t = t.replace(f"ESTWRAPPLACEHOLDER{idx}ESTWRAP", orig_w)

    for idx, orig_sub in enumerate(sub_tags):
        t = t.replace(f"SSMLSUBTAGPLACEHOLDER{idx}SSMLSUBTAG", orig_sub)

    for idx, orig_t in enumerate(est_tags):
        m_tag = re.match(r'<\s*est(?:\s+[^>]*)?>(.*?)<\s*/\s*est\s*>', orig_t, flags=re.IGNORECASE | re.DOTALL)
        if m_tag:
            inner_est = m_tag.group(1).strip()
            norm_est = normalize_text_for_estonian_tts(
                inner_est, verbalize_math_signs=True, verbalize_numbers=True
            )
            t = t.replace(f"ESTTAGPLACEHOLDER{idx}ESTTAG", f"<est>{norm_est}</est>")
        else:
            t = t.replace(f"ESTTAGPLACEHOLDER{idx}ESTTAG", orig_t)

    return re.sub(r'\s+', ' ', t).strip()


def prepare_worked_example_speech(worked_example) -> str:
    """Формирует слитный Speech Text для образца решения (Näidis) БЕЗ озвучивания заголовка карточки."""
    if not worked_example:
        return ""

    given = getattr(worked_example, "given", "") or ""
    steps = getattr(worked_example, "steps", []) or []
    note = getattr(worked_example, "note", "") or ""

    clean_given = filter_card_headers_from_speech(given)

    valid_steps = [str(s).strip() for s in steps if s and str(s).strip()]

    formatted_steps = []
    ordinals = {1: "Первое", 2: "Второе", 3: "Третье", 4: "Четвертое", 5: "Пятое"}
    for idx, s in enumerate(valid_steps, 1):
        clean_step = re.sub(r'^\d+[\.\)]\s*', '', str(s)).strip()
        if clean_step:
            prefix = ordinals.get(idx, f"{idx}-е")
            formatted_steps.append(f"{prefix}: {clean_step}")

    parts = []
    if clean_given:
        parts.append(clean_given)
    if formatted_steps:
        parts.append(f"Шаги решения: {'. '.join(formatted_steps)}")
    if note:
        parts.append(note)

    full_text = ". ".join(parts).strip()
    return prepare_speech_text(full_text)


def _escape_xml_chars(text: str) -> str:
    """Экранирует специальные символы XML (&, <, >, \", ')."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def apply_ssml_sub_alias(text: str, word: str, alias: str) -> str:
    """
    Оборачивает слово в тег SSML <sub alias="...">слово</sub> в тексте
    для явного форсирования произношения Azure TTS.
    Защищает существующие теги <sub ...>...</sub> от повторного оборачивания.
    """
    sub_tags = []
    def mask_sub(m):
        idx = len(sub_tags)
        sub_tags.append(m.group(0))
        return f"__SSML_SUB_MASK_{idx}__"

    t = re.sub(r'<sub\b[^>]*>.*?<\/sub>', mask_sub, text, flags=re.IGNORECASE | re.DOTALL)

    clean_w = word.replace('\u0301', '')
    pattern_str = r'\b' + ''.join(re.escape(c) + r'\u0301?' for c in clean_w) + r'\b'
    pattern = re.compile(pattern_str, re.IGNORECASE)

    esc_alias = _escape_xml_chars(alias)
    def repl(m):
        return f'<sub alias="{esc_alias}">{m.group(0)}</sub>'

    t = pattern.sub(repl, t)

    for idx, orig_sub in enumerate(sub_tags):
        t = t.replace(f"__SSML_SUB_MASK_{idx}__", orig_sub)

    return t


def apply_russian_ssml_sub_aliases(text: str) -> str:
    """
    Оборачивает слова с нестабильным ударением в SSML <sub alias="...">слово</sub>:
    1. «Велопутешествие» (и все падежные словоформы): устраняет побочное ударение на «ве́ло» в ru-RU-SvetlanaNeural,
       принудительно устанавливая единое ударение через дефисный алиас «вело-путеше́ствие».
    2. «Вычитаем» (и все формы: вычитает, вычитайте, вычитаемое, вычитай...): жестко фиксирует ударение
       на гласной «а́» (<sub alias="вычита́ем">вычитаем</sub>).
    """
    sub_tags = []
    def mask_sub(m):
        idx = len(sub_tags)
        sub_tags.append(m.group(0))
        return f"__SSML_SUB_MASK_{idx}__"

    # Защищаем уже существующие теги <sub ...>...</sub>
    t = re.sub(r'<sub\b[^>]*>.*?<\/sub>', mask_sub, text, flags=re.IGNORECASE | re.DOTALL)

    # 1. Велопутешествие и словоформы
    def repl_velo(m: re.Match) -> str:
        orig = m.group(0)
        prefix = m.group(1)
        ending = m.group(2).replace('\u0301', '')
        alias = f"{prefix}-путеше\u0301стви{ending}"
        return f'<sub alias="{alias}">{orig}</sub>'

    p_velo = re.compile(r'\b([Вв]ело)[‑\-]?путеше\u0301?стви([а-яё\u0301]*)\b')
    t = p_velo.sub(repl_velo, t)

    # 2. Вычитаем, вычитает, вычитайте, вычитаемое и др. глагольные формы
    def repl_vychit(m: re.Match) -> str:
        orig = m.group(0)
        prefix = m.group(1)
        ending = m.group(2).replace('\u0301', '')
        alias = f"{prefix}а\u0301{ending}"
        return f'<sub alias="{alias}">{orig}</sub>'

    p_vychit = re.compile(
        r'\b([Вв]ычит)а\u0301?(ем[а-яё\u0301]*|ет[а-яё\u0301]*|йт[а-яё\u0301]*|й|ют|ете|ешь|л[а-яё\u0301]*|ть|я)\b'
    )
    t = p_vychit.sub(repl_vychit, t)

    # Восстанавливаем защищенные теги
    for idx, orig_sub in enumerate(sub_tags):
        t = t.replace(f"__SSML_SUB_MASK_{idx}__", orig_sub)

    return t


# ==============================================================================
# 9. ДВУХУРОВНЕВЫЙ НОРМАЛИЗАТОР УДАРЕНИЙ (SILERO STRESS OVERRIDES & UI SANITIZER)
# ==============================================================================

FIXED_STRESS_OVERRIDES: Dict[str, str] = {
    # Орфоэпия Silero: порядковые числительные и шаги решения
    r'\bвторой\b': 'вто+рой',
    r'\bвторая\b': 'втор+ая',
    r'\bвторое\b': 'втор+ое',
    r'\bвторые\b': 'втор+ые',
    r'\bвторого\b': 'втор+ого',
    r'\bвторому\b': 'втор+ому',
    r'\bвтором\b': 'втор+ом',
    r'\bвторую\b': 'втор+ую',
    r'\bвторым\b': 'втор+ым',
    r'\bвторых\b': 'втор+ых',
    r'\bвторыми\b': 'втор+ыми',
    r'\bпервый\b': 'п+ервый',
    r'\bпервая\b': 'п+ервая',
    r'\bпервое\b': 'п+ервое',
    r'\bпервые\b': 'п+ервые',
    r'\bпервого\b': 'п+ервого',
    r'\bпервому\b': 'п+ервому',
    r'\bпервом\b': 'п+ервом',
    r'\bпервую\b': 'п+ервую',
    r'\bпервым\b': 'п+ервым',
    r'\bпервых\b': 'п+ервых',
    r'\bтретий\b': 'тр+етий',
    r'\bтретья\b': 'тр+етья',
    r'\bтретье\b': 'тр+етье',
    r'\bтретьи\b': 'тр+етьи',
    r'\bтретьего\b': 'тр+етьего',
    r'\bтретьему\b': 'тр+етьему',
    r'\bтретьем\b': 'тр+етьем',
    r'\bтретью\b': 'тр+етью',
    r'\bтретьим\b': 'тр+етьим',
    r'\bтретьих\b': 'тр+етьих',
    r'\bчетв[её]ртый\b': 'четв+ёртый',
    r'\bчетв[её]ртая\b': 'четв+ёртая',
    r'\bчетв[её]ртое\b': 'четв+ёртое',
    r'\bчетв[её]ртые\b': 'четв+ёртые',
    r'\bчетв[её]ртого\b': 'четв+ёртого',
    r'\bчетв[её]ртому\b': 'четв+ёртому',
    r'\bчетв[её]ртом\b': 'четв+ёртом',
    r'\bчетв[её]ртую\b': 'четв+ёртую',
    r'\bчетв[её]ртым\b': 'четв+ёртым',
    r'\bчетв[её]ртых\b': 'четв+ёртых',
    r'\bпятый\b': 'п+ятый',
    r'\bпятая\b': 'п+ятая',
    r'\bпятое\b': 'п+ятое',
    r'\bпятые\b': 'п+ятые',
    r'\bшестой\b': 'шест+ой',
    r'\bшестая\b': 'шест+ая',
    r'\bшестое\b': 'шест+ое',
    r'\bшестые\b': 'шест+ые',
    r'\bседьмой\b': 'седьм+ой',
    r'\bседьмая\b': 'седьм+ая',
    r'\bседьмое\b': 'седьм+ое',
    r'\bседьмые\b': 'седьм+ые',
    r'\bвосьмой\b': 'восьм+ой',
    r'\bвосьмая\b': 'восьм+ая',
    r'\bвосьмое\b': 'восьм+ое',
    r'\bвосьмые\b': 'восьм+ые',
    r'\bдевятый\b': 'дев+ятый',
    r'\bдевятая\b': 'дев+ятая',
    r'\bдевятое\b': 'дев+ятое',
    r'\bдевятые\b': 'дев+ятые',
    r'\bдесятый\b': 'дес+ятый',
    r'\bдесятая\b': 'дес+ятая',
    r'\bдесятое\b': 'дес+ятое',
    r'\bдесятые\b': 'дес+ятые',

    # Популярные детские бренды и игры
    r'\b(lego|лего)\b': 'л+его',
    r'\b(roblox|роблокс)\b': 'р+облокс',
    r'\b(minecraft|майнкрафт)\b': 'майнкр+афт',
    r'\b(youtube|ютуб)\b': 'ют+уб',
    r'\b(tiktok|тикток)\b': 'тикт+ок',

    # Специальные термины
    r'\bсуперпрыжк[иеа-я]*\b': 'супер-прыжк+и',
    r'\bмарсоход[а-я]*\b': 'марсох+ода',
    r'\bшасси\b': 'шасс+и',
    r'\bисследовател[а-я]*\b': 'иссл+едователь',
}


LATIN_TO_CYRILLIC_DIPHTHONGS: List[Tuple[str, str]] = [
    ("sch", "щ"), ("shch", "щ"), ("sh", "ш"), ("ch", "ч"),
    ("th", "т"), ("ph", "ф"), ("kh", "х"), ("ts", "ц"),
    ("zh", "ж"), ("ya", "я"), ("yu", "ю"), ("yo", "ё"),
    ("ye", "е"), ("je", "е"), ("ja", "я"), ("ju", "ю"),
    ("ck", "к"), ("oo", "у"), ("ee", "и"), ("qu", "кв"),
]

LATIN_TO_CYRILLIC_CHARS: Dict[str, str] = {
    'a': 'а', 'b': 'б', 'c': 'к', 'd': 'д', 'e': 'е', 'f': 'ф',
    'g': 'г', 'h': 'х', 'i': 'и', 'j': 'дж', 'k': 'к', 'l': 'л',
    'm': 'м', 'n': 'н', 'o': 'о', 'p': 'п', 'q': 'к', 'r': 'р',
    's': 'с', 't': 'т', 'u': 'у', 'v': 'в', 'w': 'в', 'x': 'кс',
    'y': 'й', 'z': 'з',
}


def transliterate_latin_word(word: str) -> str:
    """
    Транслитерирует изолированное латинское слово в русскую кириллицу.
    Защищает токенизатор Silero v5 от вырезания неизвестных латинских слов.
    """
    if not word or not re.search(r'[a-zA-Z]', word):
        return word

    clean = word.lower().strip(".,;:!?\"'«»")
    if clean in TERMINOLOGY_MAP:
        rep = TERMINOLOGY_MAP[clean]
        return rep.capitalize() if word[0].isupper() else rep

    is_upper = word.isupper()
    is_title = word[0].isupper()

    w = word.lower()
    for lat, cyr in LATIN_TO_CYRILLIC_DIPHTHONGS:
        w = w.replace(lat, cyr)

    res_chars = [LATIN_TO_CYRILLIC_CHARS.get(ch, ch) for ch in w]
    res = "".join(res_chars)

    if is_upper and len(res) <= 4:
        return res.upper()
    elif is_title or is_upper:
        return res.capitalize()
    return res


def transliterate_isolated_latin_words(text: str) -> str:
    """
    Транслитерирует одиночные латинские слова внутри русского текста,
    исключая XML/HTML теги (<est>...</est>, <sub...>), эстонские диакритики и научные формулы.
    """
    if not text:
        return ""

    protected_tokens: List[str] = []
    def _mask_tag(m: re.Match) -> str:
        idx = len(protected_tokens)
        protected_tokens.append(m.group(0))
        return f"__PROT_TAG_{idx}__"

    t = re.sub(r'<[^>]+>', _mask_tag, text)

    def _repl_word(m: re.Match) -> str:
        token = m.group(0)
        if is_chemical_formula_or_acronym(token):
            return token
        if re.search(r'[õäöüšžÕÄÖÜŠŽ]', token):
            return token
        return transliterate_latin_word(token)

    t = re.sub(r'\b[a-zA-Z]{2,}\b', _repl_word, t)

    for idx, orig_tok in enumerate(protected_tokens):
        t = t.replace(f"__PROT_TAG_{idx}__", orig_tok)

    return t


def apply_stress_overrides(text: str) -> str:
    """
    Применяет словарную подстановку для порядковых числительных (второ́й -> вто+рой),
    неологизмов и брендов (LEGO -> л+его), устраняя фонетические искажения Silero v5.
    """
    if not text:
        return text

    res = text
    # Конвертация Combining Acute (\u0301) в '+' перед ударной гласной, если пришло из старых источников
    res = re.sub(r'([аеёиоуыэюяАЕЁИОУЫЭЮЯ])[\u0301\u00b4\u02ca]', r'+\1', res)

    for pattern_str, replacement in FIXED_STRESS_OVERRIDES.items():
        def _repl(m: re.Match) -> str:
            word = m.group(0)
            if '+' in word:
                return word
            target = replacement
            if word[0].isupper():
                target = target[0].upper() + target[1:]
            return target

        res = re.sub(pattern_str, _repl, res, flags=re.IGNORECASE)

    # Транслитерируем любые оставшиеся латинские слова для Silero
    res = transliterate_isolated_latin_words(res)
    return res


def clean_display_text(text: str) -> str:
    """
    Очищает текст для клиентского экрана (UI) от технических плюсов (+),
    сохраняя оригинальную стандартную орфографию.
    """
    if not text:
        return text
    # Удаляем '+' если он стоит перед буквой или внутри слова
    clean = re.sub(r'\+(?=[а-яА-ЯёЁa-zA-Z])', '', text)
    return clean

