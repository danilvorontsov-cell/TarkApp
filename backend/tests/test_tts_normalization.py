import pytest
from app.services.tts_service import (
    DEFAULT_VOICE,
    ESTONIAN_VOICE,
    normalize_text_for_estonian_tts,
    normalize_roman_numerals,
    normalize_math_expressions,
    normalize_text_for_speech,
    parse_bilingual_segments,
)

def test_normalize_crosses_and_multiplication():
    # Eliminates crosses and multiplication symbols
    assert normalize_text_for_estonian_tts("12 \u00d7 2") == "12 2"
    assert normalize_text_for_estonian_tts("12 \u2715") == "12"
    assert normalize_text_for_estonian_tts("12 \u2716") == "12"
    assert normalize_text_for_estonian_tts("12 * 2") == "12 2"

def test_normalize_brackets():
    # Eliminates brackets and braces
    assert normalize_text_for_estonian_tts("[12]") == "12"
    assert normalize_text_for_estonian_tts("Vastus on [12].") == "Vastus on 12"

def test_normalize_dot_after_integer_prevents_ordinal():
    # 12. -> 12 so that cardinal kaksteist is spoken instead of ordinal kaheteistkumnes
    assert normalize_text_for_estonian_tts("Vastus on 12.") == "Vastus on 12"
    assert normalize_text_for_estonian_tts("Minul on 12.") == "Minul on 12"
    assert normalize_text_for_estonian_tts("12.") == "12"
    assert normalize_text_for_estonian_tts("12 .") == "12"

def test_normalize_punctuation_in_contact():
    # Separates punctuation in direct contact with digits
    assert normalize_text_for_estonian_tts("12,") == "12 ,"
    assert normalize_text_for_estonian_tts("12!") == "12 !"
    assert normalize_text_for_estonian_tts("12?") == "12 ?"
    assert normalize_text_for_estonian_tts("12-ne") == "12 ne"


def test_estonian_numeral_case_suffixes_preserve_hyphen():
    # Preserves hyphens for Estonian numeral case endings so Edge-TTS inflects the numeral (e.g. 5-ga -> viiega)
    assert normalize_text_for_estonian_tts("Korruta 5-ga") == "Korruta 5-ga"
    assert normalize_text_for_estonian_tts("Loenda 10-ni") == "Loenda 10-ni"
    assert normalize_text_for_estonian_tts("Lahuta 3-st") == "Lahuta 3-st"
    assert normalize_text_for_estonian_tts("Liida 2-le") == "Liida 2-le"
    assert normalize_text_for_estonian_tts("4-lt ja 1-sse") == "4-lt ja 1-sse"
    assert normalize_text_for_estonian_tts("5-s, 6-l, 7-ks, 8-na, 9-ta") == "5-s, 6-l, 7-ks, 8-na, 9-ta"
    # En-dash before case suffix is normalized to standard hyphen
    assert normalize_text_for_estonian_tts("Korruta 5–ga") == "Korruta 5-ga"
    # Numeric range still separates dashes
    assert normalize_text_for_estonian_tts("10-12") == "10 12"

def test_empty_string():
    assert normalize_text_for_estonian_tts("") == ""
    assert normalize_text_for_estonian_tts("   ") == ""


# --- Тесты нормализации римских цифр и математических выражений ---

def test_roman_numerals_normalization():
    text = "В XXI веке и в III тысячелетии ученые открыли..."
    norm = normalize_text_for_speech(text)
    assert norm == "В двадцать первом веке и в третьем тысячелетии ученые открыли..."

    # Проверка полной озвучки русским голосом без ошибочного разделения
    segments = parse_bilingual_segments(text)
    assert len(segments) == 1
    assert segments[0][1] == DEFAULT_VOICE
    assert "двадцать первом веке" in segments[0][0]
    assert "третьем тысячелетии" in segments[0][0]


def test_math_expressions_normalization():
    text = "Чему равен x, если x + y = 15?"
    norm = normalize_text_for_speech(text)
    assert norm == "Чему равен икс, если икс плюс игрек равно 15?"

    # Проверка озвучки русским голосом
    segments = parse_bilingual_segments(text)
    assert len(segments) == 1
    assert segments[0][1] == DEFAULT_VOICE
    assert "икс плюс игрек равно 15" in segments[0][0]


def test_estonian_vocabulary_preserved():
    # Чистый эстонский текст не должен ломаться и озвучивается эстонским диктором
    est_sample = "üks"
    segments = parse_bilingual_segments(est_sample)
    assert len(segments) == 1
    assert segments[0][1] == ESTONIAN_VOICE
    assert segments[0][0] == "üks"

    est_sample2 = "kass"
    segments2 = parse_bilingual_segments(est_sample2)
    assert len(segments2) == 1
    assert segments2[0][1] == ESTONIAN_VOICE
    assert segments2[0][0] == "kass"


def test_russian_ordinals_with_dot():
    text = "Ребенок учится в 4. классе и делает 2. задание."
    norm = normalize_text_for_speech(text)
    assert norm == "Ребенок учится в четвертом классе и делает второе задание."

    segments = parse_bilingual_segments(text)
    assert len(segments) == 1
    assert segments[0][1] == DEFAULT_VOICE
    assert segments[0][0] == "Ребенок учится в четвертом классе и делает второе задание."


def test_estonian_ordinals_with_dot():
    # 4. klassis -> neljandas klassis
    text = "Ta õpib 4. klassis."
    norm = normalize_text_for_estonian_tts(text)
    assert norm == "Ta õpib neljandas klassis."

    # Harjutus 5. -> Harjutus 5
    assert normalize_text_for_estonian_tts("Harjutus 5.") == "Harjutus 5"
    assert normalize_text_for_estonian_tts("1. klass") == "esimene klass"
    assert normalize_text_for_estonian_tts("2. harjutus") == "teine harjutus"
    assert normalize_text_for_estonian_tts("2. ülesandes") == "teises ülesandes"


def test_list_numbering_dot_removal():
    text = "1. Сложи числа\n2. Запиши ответ"
    norm = normalize_text_for_speech(text)
    assert "1." not in norm
    assert "2." not in norm
    assert "Первое: Сложи числа" in norm
    assert "Второе: Запиши ответ" in norm


def test_math_division_colon_and_symbols():
    # 15 : 3 = 5 -> 15 разделить на 3 равно 5 (вместо 'соотношение')
    assert normalize_math_expressions("15 : 3 = 5") == "15 разделить на 3 равно 5"
    assert normalize_math_expressions("24:6") == "24 разделить на 6"
    assert normalize_math_expressions("x : 2 = 10") == "икс разделить на 2 равно 10"
    assert normalize_math_expressions("15 ÷ 3 = 5") == "15 разделить на 3 равно 5"

    # Словесное описание знака деления
    assert "знак «разделить»" in normalize_math_expressions("Посмотри на знак : в примере")

    # Сохранение стандартного времени (14:30 не превращается в деление)
    assert "14:30" in normalize_math_expressions("Встреча в 14:30")


def test_numbered_examples_and_steps_ordinal():
    # Пример 1, Пример 2 -> Первый пример:, Второй пример:
    text = "Пример 1: 15 : 3 = 5\nПример 2: 24 : 6 = 4"
    norm = normalize_text_for_speech(text)
    assert "Первый пример: 15 разделить на 3 равно 5" in norm
    assert "Второй пример: 24 разделить на 6 равно 4" in norm

    # Скобочная нумерация: 1), 2)
    text_paren = "1) 15 : 3 = 5\n2) 20 : 4 = 5"
    norm_paren = normalize_text_for_speech(text_paren)
    assert "Первое: 15 разделить на 3 равно 5" in norm_paren
    assert "Второе: 20 разделить на 4 равно 5" in norm_paren

    # Шаги решения с двоеточием перед списком
    text_steps = "Шаги решения: 1. Вычисли 15 : 3\n2. Запиши ответ"
    norm_steps = normalize_text_for_speech(text_steps)
    assert "Шаги решения: Первое: Вычисли 15 разделить на 3" in norm_steps
    assert "Второе: Запиши ответ" in norm_steps

