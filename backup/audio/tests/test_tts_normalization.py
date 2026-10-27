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

