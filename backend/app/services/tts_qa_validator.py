"""
Фонетический валидатор и QA-линтер перед синтезом речи Silero TTS v5.

Запускается строго после основного нормализатора перед подачей сегментов
в русскую модель Silero v5, предотвращая пропуск латиницы, сбои ударений,
омографы и нераскрытые символы с задержкой < 2 мс.

Архитектура проверок:
1. Отлов необработанной латиницы (Anti-Drop Filter): бренды (LEGO -> Л+его) и транслитерация.
2. Словарь «красных флагов» и орфоэпии (Stress & Homograph Guard): принудительный '+' перед ударной гласной.
3. Контроль нераскрытых цифр и спецсимволов: числительные и математические знаки.
4. Валидация синтаксиса ударений Silero: '+' строго перед гласной, без дубликатов в одном слове.
5. Телеметрия и лог-аудит (Self-Learning Log) с префиксом [TTS-QA].
"""

import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.tts_normalizer import int_to_russian_cardinal, transliterate_latin_word

try:
    from num2words import num2words  # type: ignore
except ImportError:
    num2words = None

logger = logging.getLogger(__name__)

RUSSIAN_VOWELS = set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")

# ==============================================================================
# ЗАГРУЗКА И КЭШИРОВАНИЕ СЛОВАРЯ УДАРЕНИЙ
# ==============================================================================

_STRESS_DICT_DATA: Optional[Dict[str, Any]] = None
_COMPILED_BRANDS: Optional[List[Tuple[re.Pattern, str]]] = None
_COMPILED_STRESS_RULES: Optional[List[Tuple[re.Pattern, str, str]]] = None


def _resolve_stress_dict_path() -> Path:
    candidates = [
        Path(__file__).resolve().parent.parent / "data" / "tts_stress_dict.json",
        Path("backend/app/data/tts_stress_dict.json"),
        Path("app/data/tts_stress_dict.json"),
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            return p
    return candidates[0]


def _load_stress_dict() -> Dict[str, Any]:
    global _STRESS_DICT_DATA, _COMPILED_BRANDS, _COMPILED_STRESS_RULES

    if _STRESS_DICT_DATA is not None and _COMPILED_BRANDS is not None and _COMPILED_STRESS_RULES is not None:
        return _STRESS_DICT_DATA

    dict_path = _resolve_stress_dict_path()
    loaded_data: Dict[str, Any] = {}
    if dict_path.exists() and dict_path.is_file():
        try:
            with open(dict_path, "r", encoding="utf-8") as f:
                loaded_data = json.load(f)
        except Exception as e:
            logger.warning(f"[TTS-QA] Failed to load {dict_path}: {e}")

    _STRESS_DICT_DATA = loaded_data or {}

    # 1. Compile Brands
    compiled_brands: List[Tuple[re.Pattern, str]] = []
    brands_map: Dict[str, str] = _STRESS_DICT_DATA.get("brands", {})
    # Fallback defaults if dict missing or incomplete
    default_brands = {
        "LEGO": "Л+его",
        "Minecraft": "Майнкр+афт",
        "Roblox": "Р+облокс",
        "YouTube": "Ют+уб",
        "Steve": "Ст+ив",
    }
    all_brands = {**default_brands, **brands_map}
    for b_key, b_repl in all_brands.items():
        pat = re.compile(rf"\b{re.escape(b_key)}\b", re.IGNORECASE)
        compiled_brands.append((pat, b_repl))
    _COMPILED_BRANDS = compiled_brands

    # 2. Compile Stress Rules (ordinals + homographs)
    compiled_rules: List[Tuple[re.Pattern, str, str]] = []
    default_ordinals = {
        "второй": "втор+ой",
        "первый": "п+ервый",
        "третий": "тр+етий",
        "четвертый": "четвёртый",
        "четвёртый": "четв+ёртый",
        "седьмой": "седьм+ой",
        "восьмой": "восьм+ой",
    }
    default_homographs = {
        "мешки": "мешк+и",
        "мешка": "мешк+а",
        "мешков": "мешк+ов",
        "коробки": "кор+обки",
        "коробка": "кор+обка",
        "стоит": "ст+оит",
        "большая": "больш+ая",
        "еще": "ещё",
        "стив": "ст+ив",
        "стива": "ст+ива",
        "стиву": "ст+иву",
        "стивом": "ст+ивом",
        "стиве": "ст+иве",
        "шерсти": "ш+ерсти",
        "шерсть": "ш+ерсть",
        "шерстью": "ш+ерстью",
    }

    ordinals_map = {**default_ordinals, **_STRESS_DICT_DATA.get("ordinals", {})}
    homographs_map = {**default_homographs, **_STRESS_DICT_DATA.get("homographs", {})}
    all_stress_words = {**ordinals_map, **homographs_map}

    for word_key, target in all_stress_words.items():
        if not word_key:
            continue
        first = word_key[0]
        rest = word_key[1:]
        # (?<![\w+]) ensures we don't match if word already has stress or letters attached
        # (?![\w+]) ensures word boundary even when '+' is in target
        pat = re.compile(rf"(?<![\w+])([{first.upper()}{first.lower()}]{re.escape(rest)})(?![\w+])")
        compiled_rules.append((pat, word_key, target))

    _COMPILED_STRESS_RULES = compiled_rules
    return _STRESS_DICT_DATA


def _format_context(text: str, start: int, end: int, window: int = 35) -> str:
    ctx_start = max(0, start - window)
    ctx_end = min(len(text), end + window)
    return text[ctx_start:ctx_end].replace("\n", " ").strip()


# ==============================================================================
# ПРОВЕРКА 4: ВАЛИДАЦИЯ СИНТАКСИСА УДАРЕНИЙ SILERO
# ==============================================================================

def validate_silero_stress_syntax(text: str) -> str:
    """
    Проверка 4: Валидация синтаксиса знака ударения '+'.
    - Убедиться, что знак ударения '+' стоит строго ПЕРЕД русской гласной.
    - Если '+' попал перед согласной, пробелом или в конец слова — удалить некорректный '+'.
    - Если в одном слове оказалось два знака '+' — оставить только первый валидный перед гласной.
    """
    if "+" not in text:
        return text

    def _fix_word_stress(m: re.Match) -> str:
        word = m.group(0)
        if "+" not in word:
            return word

        chars = list(word)
        out: List[str] = []
        has_vowel_stress = False
        n = len(chars)

        for i, ch in enumerate(chars):
            if ch == "+":
                # Check if followed by Russian vowel
                if i + 1 < n and chars[i + 1] in RUSSIAN_VOWELS:
                    if not has_vowel_stress:
                        out.append("+")
                        has_vowel_stress = True
                    # else: duplicate stress in word, drop it
                # else: '+' not before vowel (consonant, space, symbol, end of word), drop it
            else:
                out.append(ch)

        fixed = "".join(out)
        if fixed != word:
            logger.warning(
                f"[TTS-QA] Fixed stress syntax in token: '{word}' -> '{fixed}' | context: '{_format_context(text, m.start(), m.end())}'"
            )
        return fixed

    return re.sub(r"[\w+]+", _fix_word_stress, text)


# ==============================================================================
# ПРОВЕРКА 3: КОНТРОЛЬ НЕРАСКРЫТЫХ ЦИФР И СПЕЦСИМВОЛОВ
# ==============================================================================

def expand_unexpanded_digits_and_symbols(text: str) -> str:
    """
    Проверка 3: Раскрытие оставшихся цифр и математических операторов вне тегов ударений.
    """
    # 1. Spaced or equation math symbols
    # Operator '+' between digits or with spaces:
    def _repl_plus(m: re.Match) -> str:
        orig = m.group(0)
        logger.warning(f"[TTS-QA] Unexpanded digit/symbol detected: '{orig}' -> ' плюс '")
        return " плюс "

    text = re.sub(r"(?<=\d)\s*\+\s*(?=\d)", _repl_plus, text)
    text = re.sub(r"\s+\+\s+", _repl_plus, text)

    # Operator '=':
    def _repl_eq(m: re.Match) -> str:
        orig = m.group(0)
        logger.warning(f"[TTS-QA] Unexpanded digit/symbol detected: '{orig}' -> ' равно '")
        return " равно "

    text = re.sub(r"\s*=\s*", _repl_eq, text)

    # Operators '×' and '*' (between digits):
    def _repl_mult(m: re.Match) -> str:
        orig = m.group(0)
        logger.warning(f"[TTS-QA] Unexpanded digit/symbol detected: '{orig}' -> ' умножить на '")
        return " умножить на "

    text = re.sub(r"(?<=\d)\s*[×*]\s*(?=\d)", _repl_mult, text)

    # Operator '÷' (between digits):
    def _repl_div(m: re.Match) -> str:
        orig = m.group(0)
        logger.warning(f"[TTS-QA] Unexpanded digit/symbol detected: '{orig}' -> ' разделить на '")
        return " разделить на "

    text = re.sub(r"(?<=\d)\s*÷\s*(?=\d)", _repl_div, text)

    # 2. Percents (%):
    def _repl_percent(m: re.Match) -> str:
        num_str = m.group(1)
        num = int(num_str)
        words = int_to_russian_cardinal(num)
        last100 = num % 100
        last10 = num % 10
        if 11 <= last100 <= 14:
            suf = "процентов"
        elif last10 == 1:
            suf = "процент"
        elif 2 <= last10 <= 4:
            suf = "процента"
        else:
            suf = "процентов"
        res = f"{words} {suf}"
        logger.warning(f"[TTS-QA] Unexpanded digit/symbol detected: '{m.group(0)}' -> '{res}'")
        return res

    text = re.sub(r"\b(\d+)\s*%", _repl_percent, text)

    # 3. Remaining unexpanded integers (\b\d+\b)
    def _repl_digit(m: re.Match) -> str:
        num_str = m.group(0)
        num_val = int(num_str)
        if num2words is not None:
            try:
                words = num2words(num_val, lang="ru")
            except Exception:
                words = int_to_russian_cardinal(num_val)
        else:
            words = int_to_russian_cardinal(num_val)

        logger.warning(f"[TTS-QA] Unexpanded digit/symbol detected: '{num_str}' -> '{words}'")
        logger.warning(
            f"[TTS-QA] Fixed token: '{num_str}' -> '{words}' | context: '{_format_context(text, m.start(), m.end())}'"
        )
        return words

    text = re.sub(r"\b\d+\b", _repl_digit, text)
    return text


# ==============================================================================
# ГЛАВНАЯ ФУНКЦИЯ ВАЛИДАЦИИ (TTS QA-ЛИНТЕР)
# ==============================================================================

def validate_and_fix_russian_tts(text: str, is_estonian: bool = False) -> str:
    """
    Выполняет 5 последовательных проверок для русскоязычных сегментов перед Silero v5:
    1. Anti-Drop Filter: бренды (LEGO -> Л+его, Roblox -> Р+облокс) и автоматическая транслитерация латиницы.
    2. Stress & Homograph Guard: расстановка знака '+' перед ударной гласной в омографах и шагах/числах.
    3. Контроль нераскрытых цифр и спецсимволов: числительные и мат. операторы.
    4. Валидация синтаксиса ударений: '+' строго перед русской гласной, удаление дублей и битых плюсов.
    5. Телеметрия и лог-аудит с префиксом [TTS-QA].
    """
    if not text or not text.strip():
        return text

    if is_estonian:
        return text

    # Защита эстонских тегов <est>...</est> от кириллизации (Guardrail 4)
    est_tags: List[str] = []

    def _mask_est(m: re.Match) -> str:
        est_tags.append(m.group(0))
        return f"__ЭСТ_ТЕГ_{len(est_tags)-1}__"

    processed = re.sub(r"<est(?: [^>]*)?>.*?</est>", _mask_est, text, flags=re.DOTALL | re.IGNORECASE)

    # Конвертация Combining Acute (\u0301) в '+' перед ударной гласной
    processed = re.sub(r"([аеёиоуыэюяАЕЁИОУЫЭЮЯ])[\u0301\u00b4\u02ca]", r"+\1", processed)

    _load_stress_dict()

    # --------------------------------------------------------------------------
    # Проверка 1: Отлов необработанной латиницы (Anti-Drop Filter)
    # --------------------------------------------------------------------------
    if _COMPILED_BRANDS:
        for pat, brand_repl in _COMPILED_BRANDS:
            def _repl_brand(m: re.Match, r=brand_repl) -> str:
                old_val = m.group(0)
                logger.warning(f"[TTS-QA] Fixed raw latin token: '{old_val}' -> '{r}'")
                logger.warning(
                    f"[TTS-QA] Fixed token: '{old_val}' -> '{r}' | context: '{_format_context(processed, m.start(), m.end())}'"
                )
                return r

            processed = pat.sub(_repl_brand, processed)

    # Любые другие оставшиеся латинские слова -> транслитерация
    def _repl_remaining_latin(m: re.Match) -> str:
        token = m.group(0)
        cyr = transliterate_latin_word(token)
        logger.warning(f"[TTS-QA] Fixed raw latin token: '{token}' -> '{cyr}'")
        logger.warning(
            f"[TTS-QA] Fixed token: '{token}' -> '{cyr}' | context: '{_format_context(processed, m.start(), m.end())}'"
        )
        return cyr

    processed = re.sub(r"\b[a-zA-Z]+\b", _repl_remaining_latin, processed)

    # --------------------------------------------------------------------------
    # Проверка 2: Словарь «красных флагов» и орфоэпии (Stress & Homograph Guard)
    # --------------------------------------------------------------------------
    if _COMPILED_STRESS_RULES:
        for pat, word_key, target in _COMPILED_STRESS_RULES:
            def _repl_stress(m: re.Match, tgt=target) -> str:
                orig = m.group(1)
                # Сохраняем регистр первой буквы
                is_upper = orig[0].isupper()
                if tgt.startswith("+"):
                    lead = orig[0].upper() if is_upper else orig[0].lower()
                    res = "+" + lead + tgt[2:]
                else:
                    lead = orig[0].upper() if is_upper else orig[0].lower()
                    res = lead + tgt[1:]
                if res != orig:
                    logger.warning(
                        f"[TTS-QA] Fixed token: '{orig}' -> '{res}' | context: '{_format_context(processed, m.start(), m.end())}'"
                    )
                return res

            processed = pat.sub(_repl_stress, processed)

    # --------------------------------------------------------------------------
    # Проверка 3: Контроль нераскрытых цифр и спецсимволов
    # --------------------------------------------------------------------------
    processed = expand_unexpanded_digits_and_symbols(processed)

    # --------------------------------------------------------------------------
    # Проверка 4: Валидация синтаксиса ударений Silero
    # --------------------------------------------------------------------------
    processed = validate_silero_stress_syntax(processed)

    # --------------------------------------------------------------------------
    # Восстановление защищенных эстонских тегов
    # --------------------------------------------------------------------------
    for idx, tag in enumerate(est_tags):
        processed = processed.replace(f"__ЭСТ_ТЕГ_{idx}__", tag)

    return processed
