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


# Поддерживаемые англоязычные бренды и термины для разметки <lang xml:lang="en-US">
ENGLISH_BRANDS = [
    "Lego Mindstorms", "Mindstorms", "Minecraft", "Roblox", "Scratch", "Python"
]

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
    "küсимus", "küsimuse", "küsimust", "küsimusele",
    "sadad", "kümned", "ühelised", "arvud", "arv",
    "tere", "aitäh", "palun", "näide", "näited",
    "tehe", "tehted", "lahutamine", "liitmine", "korrutamine", "jagamine",
}

# Фонетическая замена для диктора (словарик подмен популярных брендов/игр/клавиш)
PHONETIC_REPLACEMENTS = [
    (re.compile(r'\b(?:майнкрафт)(?:[’\'-]?([а-яё]+))?\b', re.IGNORECASE), lambda m: 'Майнкрафт' + (m.group(1) or '') if m.group(1) else 'Майнкрафт'),
    (re.compile(r'\b(?:роблокс)(?:[’\'-]?([а-яё]+))?\b', re.IGNORECASE), lambda m: 'Роблокс' + (m.group(1) or '') if m.group(1) else 'Роблокс'),
    (re.compile(r'\b(?:youtube|ютуб)(?:[’\'-]?([а-яё]+))?\b', re.IGNORECASE), lambda m: 'Ютуб' + (m.group(1) or '') if m.group(1) else 'Ютуб'),
    (re.compile(r'\b(?:google|гугл)(?:[’\'-]?([а-яё]+))?\b', re.IGNORECASE), lambda m: 'Гугл' + (m.group(1) or '') if m.group(1) else 'Гугл'),
    (re.compile(r'\benter\b', re.IGNORECASE), 'Энтер'),
    (re.compile(r'\bspace\b', re.IGNORECASE), 'Пробел'),
    (re.compile(r'\bshift\b', re.IGNORECASE), 'Шифт'),
]


def clean_text_for_speech(text: str) -> str:
    """
    Санитизирует текст перед озвучкой:
    1. Заменяет стрелки и псевдографику ('->', '-->', '=>', '==>') на ' затем ',
       а '<-', '<--', '<==', '<=' (в стрелочном контексте) на ' ранее '.
    2. Удаляет служебные символы разметки Markdown (**, *, #, _, ~, `, [, ]).
    3. Сохраняет одиночные математические знаки '>' и '<' для сравнения чисел.
    4. Применяет фонетическую замену англоязычных брендов и клавиш (Minecraft -> Майнкрафт).
    Не затрагивает содержимое внутри тегов <est>...</est>.
    """
    if not text:
        return ""

    # 1. Защищаем теги <est>...</est> (без спецсимволов маркдауна в плейсхолдере)
    est_tags: List[str] = []
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

    # 2. Markdown ссылки: [текст](url) -> текст
    t = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', t)

    # 2.1. Заменяем слэш '/' между кириллическими словами на ' или '
    t = re.sub(r'(?<=[а-яА-ЯёЁ])\s*/\s*(?=[а-яА-ЯёЁ0-9])|(?<=[а-яА-ЯёЁ0-9])\s*/\s*(?=[а-яА-ЯёЁ])', ' или ', t)

    # 3. Стрелки и псевдографика:
    # 3.1. Правые стрелки -> затем
    t = re.sub(r'(?:==>|-->|=>|->|→|⇒)', ' затем ', t)

    # 3.2. Левые стрелки -> ранее
    t = re.sub(r'(?:<==|<--|<-|←|⇐)', ' ранее ', t)

    # 3.3. Стрелка <= vs математическое <= (меньше или равно):
    # Если <= между числами или мат. переменными (x <= 5, 5 <= 10) - заменяем на "меньше или равно"
    t = re.sub(r'(?<=[0-9a-zA-Zа-яА-ЯёЁ])\s*<=\s*(?=[0-9a-zA-Zа-яА-ЯёЁ])', ' меньше или равно ', t)
    # Если >= между операндами:
    t = re.sub(r'(?<=[0-9a-zA-Zа-яА-ЯёЁ])\s*>=\s*(?=[0-9a-zA-Zа-яА-ЯёЁ])', ' больше или равно ', t)
    # Оставшиеся стрелочные <=
    t = re.sub(r'<=\s*', ' ранее ', t)

    # Дедупликация повторов "затем затем" / "ранее ранее"
    t = re.sub(r'\b(затем|ранее)\s+\1\b', r'\1', t, flags=re.IGNORECASE)

    # 4. Удаление служебных символов разметки Markdown:
    # Заголовки (#, ##, ###)
    t = re.sub(r'#+', ' ', t)
    # Звездочки жирного/курсива (**) и одиночные (*)
    t = re.sub(r'\*+', ' ', t)
    # Нижние подчеркивания (__ и _)
    t = re.sub(r'_+', ' ', t)
    # Тильды (~) и обратные кавычки (`)
    t = re.sub(r'[~`]+', ' ', t)
    # Квадратные скобки ([ и ])
    t = re.sub(r'[\[\]]', ' ', t)

    # 5. Фонетическая замена для диктора (только в русском контексте)
    for pattern, repl in PHONETIC_REPLACEMENTS:
        if callable(repl):
            t = pattern.sub(repl, t)
        else:
            t = pattern.sub(repl, t)

    # 6. Восстанавливаем теги <est>...</est>
    for idx, orig_t in enumerate(est_tags):
        t = t.replace(f"ESTTAGPLACEHOLDER{idx}ESTTAG", orig_t)

    # 7. Устраняем лишние пробелы перед знаками препинания после удаления разметки
    t = re.sub(r'\s+([,!?;:])', r'\1', t)
    return re.sub(r'[ \t]+', ' ', t).strip()


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

    # Находим знаки конца предложения: точки, восклицательные, вопросительные
    pattern = re.compile(r'([.!?\u2026]+)(?!\s*<break\b)')
    def repl(m):
        return f'{m.group(1)} <break time="500ms" /> '

    t = pattern.sub(repl, t)

    for idx, orig in enumerate(masked):
        t = t.replace(f"NUMTIMEPLACEHOLDER{idx}NUMTIME", orig)

    for idx, orig_tag in enumerate(xml_tags):
        t = t.replace(f"__XML_TAG_{idx}__", orig_tag)

    # Предотвращаем дублирование тегов break
    t = re.sub(r'(?:<break\s+time="[^"]+"\s*\/?>\s*){2,}', '<break time="500ms" /> ', t)
    return re.sub(r'[ \t]+', ' ', t).strip()


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
    # Заменяем слэш '/' в эстонском тексте на ' või '
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

def normalize_number_ranges(text: str) -> str:
    """
    Нормализует диапазоны чисел: '1-9' -> 'от 1 до 9'.
    Если n1 < n2 и нет последующего '=' (не математическое выражение), заменяет на диапазон.
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


def int_to_russian_nominative(n: int) -> str:
    """Возвращает число 0-999 в именительном падеже русскими словами."""
    if n < 0:
        return f"минус {int_to_russian_nominative(-n)}"
    if n < 20:
        return RUSSIAN_UNITS[n]
    if n < 100:
        ten = n // 10
        rem = n % 10
        if rem == 0:
            return RUSSIAN_TENS[ten]
        return f"{RUSSIAN_TENS[ten]} {RUSSIAN_UNITS[rem]}"
    if n < 1000:
        hundred = n // 100
        rem = n % 100
        if rem == 0:
            return RUSSIAN_HUNDREDS[hundred]
        return f"{RUSSIAN_HUNDREDS[hundred]} {int_to_russian_nominative(rem)}"
    return str(n)


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

    # Нормализация сложения изолированных чисел (например, "9 + 3" -> "девять плюс три")
    def repl_addition(m):
        n1 = int(m.group(1))
        n2 = int(m.group(2))
        return f"{int_to_russian_nominative(n1)} плюс {int_to_russian_nominative(n2)}"

    t = re.sub(r'\b(\d{1,3})\s*\+\s*(\d{1,3})\b', repl_addition, t)

    # Нормализация изолированных перечислений цифр через "и" ("4 и 3", "2, 3 и 4") в именительный падеж
    def repl_digits_and_3(m):
        n1 = int(m.group(1))
        n2 = int(m.group(2))
        n3 = int(m.group(3))
        return f"{int_to_russian_nominative(n1)}, {int_to_russian_nominative(n2)} и {int_to_russian_nominative(n3)}"

    t = re.sub(r'\b(\d{1,3}),\s*(\d{1,3})\s+и\s+(\d{1,3})\b', repl_digits_and_3, t)

    def repl_digits_and(m):
        n1 = int(m.group(1))
        n2 = int(m.group(2))
        return f"{int_to_russian_nominative(n1)} и {int_to_russian_nominative(n2)}"

    t = re.sub(r'\b(\d{1,3})\s+и\s+(\d{1,3})\b', repl_digits_and, t)


    t = re.sub(r'(?i)знак\s*[«"“„]?\s*[:÷]\s*[»"”]?|(?<=\()[:÷](?=\))', 'знак «разделить» ', t)
    t = re.sub(r'(?i)знак\s*[«"“„]?\s*[*·×]\s*[»"”]?|(?<=\()[*·×](?=\))', 'знак «умножить» ', t)
    t = re.sub(r'(?i)знак\s*[«"“„]?\s*\+\s*[»"”]?|(?<=\()\+(?=\))', 'знак «плюс» ', t)
    t = re.sub(r'(?i)знак\s*[«"“„]?\s*[-−]\s*[»"”]?|(?<=\()[-−](?=\))', 'знак «минус» ', t)

    t = re.sub(r'(?<=[0-9a-zA-Z\)])\s*÷\s*(?=[0-9a-zA-Z\(])', ' разделить на ', t)

    # 1. Математическое деление двоеточием строго между числами или однобуквенными переменными (например, "10 : 2" или "6:3")
    t = re.sub(r'(\d+)\s*:\s*(\d+)', r'\1 разделить на \2', t)
    t = re.sub(r'(\b[a-zA-Z]\b)\s*:\s*(\d+|\b[a-zA-Z]\b)', r'\1 разделить на \2', t)
    t = re.sub(r'(\d+)\s*:\s*(\b[a-zA-Z]\b)', r'\1 разделить на \2', t)

    # 2. Текстовое/пунктуационное двоеточие (все остальные случаи):
    # Любое другое двоеточие (после скобок "):", после слов, в списках и перечислениях) заменяем на запятую ","
    t = re.sub(r',?[ \t]*:[ \t]*(?!\n)', ', ', t)
    t = re.sub(r',?[ \t]*:[ \t]*(?=\n)', ',', t)
    t = re.sub(r'[ \t]+,', ',', t)
    t = re.sub(r',[ \t]*,', ',', t)
    t = re.sub(r'(?<=[0-9a-zA-Z\)])\s*[*·×]\s*(?=[0-9a-zA-Z\(])', ' умножить на ', t)
    t = re.sub(r'(?<=[0-9a-zA-Zа-яА-ЯёЁ])\s*\+\s*(?=[0-9a-zA-Zа-яА-ЯёЁ])|\s+\+\s+', ' плюс ', t)
    t = re.sub(r'\s*=\s*', ' равно ', t)
    t = re.sub(r'(?<=[0-9a-zA-Z])\s*[-−]\s*(?=[0-9a-zA-Z])|\s+[-−]\s+', ' минус ', t)

    for var, rep in MATH_VAR_MAP.items():
        t = re.sub(r'\b' + var + r'\b', rep, t)

    # Изолированные цифры после "плюс" во избежание родительного падежа ("плюс трёх")
    t = re.sub(
        r'\b(плюс)\s+(\d{1,3})\b',
        lambda m: f"{m.group(1)} {int_to_russian_nominative(int(m.group(2)))}",
        t
    )

    # Нормализация цифр после арифметических терминов и глаголов ("складывать 4", "слагаемые 4 и 3")
    t = re.sub(
        r'(?i)\b(складыва[а-яё]*|прибавля[а-яё]*|вычита[а-яё]*|умножа[а-яё]*|дели[а-яё]*|числа|чисел|цифры|цифр|слагаемые|слагаемых|множители|множителей)\s+(\d{1,3})\b',
        lambda m: f"{m.group(1)} {int_to_russian_nominative(int(m.group(2)))}",
        t
    )


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



# Словарь контекстной расстановки ударений (combining acute \u0301) и восстановления буквы 'ё'
# для естественного и педагогически корректного звучания Azure Speech SDK (ru-RU-SvetlanaNeural).
RUSSIAN_ACCENT_WORDS: Dict[str, str] = {
    # 1. Восстановление буквы 'ё'
    "еще": "ещё",
    "Еще": "Ещё",
    "четный": "чётный",
    "Четный": "Чётный",
    "четная": "чётная",
    "Четная": "Чётная",
    "четное": "чётное",
    "Четное": "Чётное",
    "четные": "чётные",
    "Четные": "Чётные",
    "четных": "чётных",
    "нечетный": "нечётный",
    "Нечетный": "Нечётный",
    "нечетная": "нечётная",
    "Нечетная": "Нечётная",
    "нечетное": "нечётное",
    "Нечетное": "Нечётное",
    "нечетные": "нечётные",
    "Нечетные": "Нечётные",
    "нечетных": "нечётных",
    "счет": "счёт",
    "Счет": "Счёт",
    "перенес": "перенёс",
    "Перенес": "Перенёс",
    "перенесем": "перенесём",
    "Перенесем": "Перенесём",
    "объем": "объём",
    "Объем": "Объём",
    "объема": "объёма",
    "трех": "трёх",
    "четырех": "четырёх",
    "берем": "берём",
    "Берем": "Берём",
    "найдем": "найдём",
    "Найдем": "Найдём",
    "поймешь": "поймёшь",
    "Поймешь": "Поймёшь",
    "узнаешь": "узнаёшь",
    "чертеж": "чертёж",
    "Чертеж": "Чертёж",
}

_RUSSIAN_ACCENT_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(k) for k in RUSSIAN_ACCENT_WORDS.keys()) + r')\b'
)


def normalize_russian_accents_and_yo(text: str) -> str:
    """
    Нормализует русский текст строго для аудиопотока Azure Speech:
    - Восстанавливает букву 'ё' в омографах и школьных словах (еще -> ещё, счет -> счёт, четный -> чётный).
    - Расставляет явные знаки ударения (combining acute \u0301) на ударные гласные в терминах и глаголах.
    - Обрабатывает фразовые контексты ('со счёта', 'прежде всего́', 'вот и всё', 'всё верно').
    """
    if not text:
        return ""
    t = _RUSSIAN_ACCENT_PATTERN.sub(lambda m: RUSSIAN_ACCENT_WORDS.get(m.group(0), m.group(0)), text)
    t = re.sub(r'(?i)\bсо\s+счет([аеуом]|ом)?\b', r'со счёт\1', t)
    t = re.sub(r'(?i)\bпрежде\s+всего\b', 'прежде всего', t)
    t = re.sub(r'(?i)\bвот\s+и\s+все\b', 'вот и всё', t)
    t = re.sub(r'(?i)\bвсе\s+(готово|верно|правильно|получилось|сходится)\b', r'всё \1', t)
    # Омограф «шага»: «в два ша́га», «за три ша́га», «в 2 ша́га»
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
    # ПОЛНОЕ УДАЛЕНИЕ принудительных знаков ударения (\u0301), кроме 'ша́га'
    t = re.sub(r'(?<![шШ][аА])\u0301', '', t)
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
    norm_text = normalize_number_ranges(norm_text)
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
            voice_blocks.append(f'  <voice name="{ESTONIAN_VOICE}">{esc}</voice>')
        else:
            # Русский фрагмент -> ru-RU-SvetlanaNeural
            s_clean = re.sub(r'(?<=[а-яА-ЯёЁ0-9a-zA-Z])\s*/\s*(?=[а-яА-ЯёЁ0-9a-zA-Z])', ' или ', s_clean)
            s_clean = re.sub(r'\s+/\s+', ' или ', s_clean)
            s_norm = normalize_russian_accents_and_yo(s_clean)
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
