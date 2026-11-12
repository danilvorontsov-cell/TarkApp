"""
Unit tests for the Phonetic QA-Linter (validate_and_fix_russian_tts)
Verifying all 5 QA checks, edge cases, Estonian tag preservation, and latency.
"""

import logging
import time
import pytest
from app.services.tts_qa_validator import (
    validate_and_fix_russian_tts,
    validate_silero_stress_syntax,
    expand_unexpanded_digits_and_symbols,
)


def test_core_case_step_and_brand():
    """
    Кейс 1: "Шаг второй: представь, что ты строишь базу LEGO." -> "Шаг втор+ой: представь, что ты строишь базу Л+его."
    """
    raw = "Шаг второй: представь, что ты строишь базу LEGO."
    result = validate_and_fix_russian_tts(raw)
    assert result == "Шаг втор+ой: представь, что ты строишь базу Л+его."


def test_core_case_numbers_homographs_yo():
    """
    Кейс 2: "В магазине 3 больших мешка и еще одна коробка." -> "В магазине три больших мешк+а и ещё одна кор+обка."
    """
    raw = "В магазине 3 больших мешка и еще одна коробка."
    result = validate_and_fix_russian_tts(raw)
    assert result == "В магазине три больших мешк+а и ещё одна кор+обка."


def test_core_case_broken_stress_syntax():
    """
    Кейс 3: "про+ве+рка сло+ва+" -> "проверка слова"
    (без висячих плюсов на конце, без плюсов перед согласными)
    """
    raw = "про+ве+рка сло+ва+"
    result = validate_and_fix_russian_tts(raw)
    assert result == "проверка слова"


def test_duplicate_vowel_stress_kept_only_first():
    """
    Если в слове два плюса перед гласными — оставлять только первый.
    """
    raw = "пр+ов+ерка сло+ва"
    result = validate_and_fix_russian_tts(raw)
    assert result == "пр+оверка слова"


def test_leading_and_trailing_plus():
    """
    Плюс перед согласной удаляется, плюс перед гласной сохраняется, плюс в конце удаляется.
    """
    assert validate_and_fix_russian_tts("+слово") == "слово"
    assert validate_and_fix_russian_tts("слово+") == "слово"
    assert validate_and_fix_russian_tts("+апельсин") == "+апельсин"
    assert validate_and_fix_russian_tts("п+есня") == "п+есня"


def test_gaming_brands_transliteration():
    """
    Проверка словаря брендов: Minecraft, Roblox, YouTube.
    """
    raw = "Мы играем в Minecraft и Roblox, смотря YouTube."
    result = validate_and_fix_russian_tts(raw)
    assert "Майнкр+афт" in result
    assert "Р+облокс" in result
    assert "Ют+уб" in result


def test_isolated_latin_words_transliterated():
    """
    Неизвестные латинские слова не должны вырезаться Silero, а транслитерироваться в кириллицу.
    """
    raw = "Это супер gamer уровень и booster тест."
    result = validate_and_fix_russian_tts(raw)
    assert "gamer" not in result
    assert "booster" not in result
    assert "г+еймер" in result.lower() or "геймер" in result.replace("+", "").lower()
    assert "бустер" in result.lower()


def test_preservation_of_estonian_tags():
    """
    Guardrail 4: Эстонские фрагменты в тегах <est>...</est> не должны кириллизоваться или ломаться.
    """
    raw = "Шаг второй: покажи <est>oranž termostass</est> классу."
    result = validate_and_fix_russian_tts(raw)
    assert result == "Шаг втор+ой: покажи <est>oranž termostass</est> классу."


def test_is_estonian_flag_bypass():
    """
    Если сегмент помечен как эстонский, он возвращается без изменений.
    """
    raw = "See on minu pinal ja see on kollane."
    result = validate_and_fix_russian_tts(raw, is_estonian=True)
    assert result == raw


def test_math_operators_and_percents_expansion():
    """
    Проверка раскрытия математических знаков: +, =, ×, ÷, %.
    """
    raw = "5 + 3 = 8, 4 * 2, скидка 10%"
    result = validate_and_fix_russian_tts(raw)
    assert "плюс" in result
    assert "равно" in result
    assert "умножить на" in result
    assert "процентов" in result


def test_capitalization_preserved_in_stress_dict():
    """
    Регистр первой буквы в начале предложения должен сохраняться.
    """
    raw = "Второй пример и Еще одна задача. Мешка не было."
    result = validate_and_fix_russian_tts(raw)
    assert result.startswith("Втор+ой")
    assert "Ещё" in result
    assert "Мешк+а" in result


def test_performance_benchmark_under_2ms():
    """
    Замер времени выполнения на тексте из ~100 слов:
    Среднее время выполнения должно быть строго < 2.0 мс (Guardrail 3).
    """
    sample_100_words = (
        "Шаг первый: представь, что ты строишь базу LEGO в Minecraft или Roblox на YouTube. "
        "В магазине 3 больших мешка и еще одна коробка. "
        "Второй шаг: посчитай, сколько стоит товар, если скидка 5 процентов. "
        "Третий шаг: проверь правильность решения задачи. "
        "Четвертый шаг: запиши ответ аккуратно в тетрадь. "
        "Седьмой и восьмой примеры реши самостоятельно. "
        "про+ве+рка сло+ва+ не должна ломать синтез речи. "
    ) * 2

    # Warm-up call
    validate_and_fix_russian_tts(sample_100_words)

    # Benchmark 100 runs (mute logging handlers during timing to measure pure string processing latency)
    qa_logger = logging.getLogger("app.services.tts_qa_validator")
    prev_level = qa_logger.level
    qa_logger.setLevel(logging.ERROR)
    try:
        times = []
        for _ in range(100):
            t0 = time.perf_counter()
            validate_and_fix_russian_tts(sample_100_words)
            times.append((time.perf_counter() - t0) * 1000)
    finally:
        qa_logger.setLevel(prev_level)

    avg_time_ms = sum(times) / len(times)
    assert avg_time_ms < 2.0, f"Average execution time {avg_time_ms:.3f} ms exceeds the 2.0 ms guardrail!"
