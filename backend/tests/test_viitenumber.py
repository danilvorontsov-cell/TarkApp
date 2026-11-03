import pytest
from app.utils.viitenumber import (
    calculate_estonian_check_digit,
    generate_estonian_reference_number,
    validate_estonian_reference_number,
)


def test_standard_estonian_viitenumber():
    # 2026001: 1*7 + 0*3 + 0*1 + 6*7 + 2*3 + 0*1 + 2*7 = 69 -> 1
    assert calculate_estonian_check_digit("2026001") == 1
    assert generate_estonian_reference_number("2026001") == "20260011"
    assert validate_estonian_reference_number("20260011") is True


def test_check_digit_zero():
    # Base "11": 1*7 + 1*3 = 10 -> check digit 0
    assert calculate_estonian_check_digit("11") == 0
    assert generate_estonian_reference_number("11") == "110"
    assert validate_estonian_reference_number("110") is True


def test_single_digit_base():
    # Base "1": 1*7 = 7 -> check digit 3
    assert calculate_estonian_check_digit("1") == 3
    assert generate_estonian_reference_number("1") == "13"
    assert validate_estonian_reference_number("13") is True

    # Base "7": 7*7 = 49 -> check digit 1
    assert calculate_estonian_check_digit("7") == 1
    assert generate_estonian_reference_number("7") == "71"
    assert validate_estonian_reference_number("71") is True


def test_integer_input():
    assert calculate_estonian_check_digit(2026001) == 1
    assert generate_estonian_reference_number(2026001) == "20260011"
    assert validate_estonian_reference_number(20260011) is True


def test_string_with_invoice_prefix():
    # Should strip non-digits and calculate check digit on numeric part
    ref = generate_estonian_reference_number("INV-2026-1001")
    assert ref.startswith("20261001")
    assert validate_estonian_reference_number(ref) is True


def test_validation_rejects_corrupted_reference_numbers():
    assert validate_estonian_reference_number("20260012") is False
    assert validate_estonian_reference_number("20260010") is False
    assert validate_estonian_reference_number("111") is False
    assert validate_estonian_reference_number("1") is False  # Too short (<2)
    assert validate_estonian_reference_number("123456789012345678901") is False  # Too long (>20)
