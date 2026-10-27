import pytest
from app.services.tts_service import normalize_text_for_estonian_tts

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
