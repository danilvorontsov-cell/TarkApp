"""
Estonian Reference Number (Viitenumber) Generation and Validation
Standard 7-3-1 algorithm as defined by the Estonian Banking Association (Eesti Pangaliit).
Weights (7, 3, 1) are applied from right to left, modulo 10.
"""

import re
from typing import Union


def calculate_estonian_check_digit(base_number: Union[int, str]) -> int:
    """
    Calculates the 7-3-1 check digit for an Estonian reference number.
    
    Rules (Eesti Pangaliit):
    1. Base number must contain only digits (1 to 19 digits).
    2. Weights 7, 3, 1 are assigned from right to left (last digit gets 7, 2nd gets 3, 3rd gets 1, etc.).
    3. Each digit is multiplied by its weight and all products are summed.
    4. Check digit is the difference between the sum and the next multiple of 10.
       If sum is an exact multiple of 10, check digit is 0.
    """
    raw_str = re.sub(r"\D", "", str(base_number)).lstrip("0")
    if not raw_str:
        # If input was 0 or contained no digits, default base to "0"
        raw_str = "0"

    weights = [7, 3, 1]
    total_sum = 0

    for i, digit_char in enumerate(reversed(raw_str)):
        weight = weights[i % 3]
        total_sum += int(digit_char) * weight

    remainder = total_sum % 10
    check_digit = (10 - remainder) % 10
    return check_digit


def generate_estonian_reference_number(base_number: Union[int, str]) -> str:
    """
    Generates a full Estonian reference number (Viitenumber) by appending
    the 7-3-1 check digit to the base number.
    
    Example:
        generate_estonian_reference_number("2026001") -> "20260011"
        generate_estonian_reference_number("123456") -> "1234567" (example)
    """
    raw_str = re.sub(r"\D", "", str(base_number)).lstrip("0")
    if not raw_str:
        raw_str = "1"
    check_digit = calculate_estonian_check_digit(raw_str)
    return f"{raw_str}{check_digit}"


def validate_estonian_reference_number(reference_number: Union[int, str]) -> bool:
    """
    Validates an Estonian reference number (Viitenumber).
    Must be 2 to 20 digits total, with the last digit matching the 7-3-1 check digit.
    """
    ref_str = re.sub(r"\D", "", str(reference_number))
    if len(ref_str) < 2 or len(ref_str) > 20:
        return False

    base_part = ref_str[:-1]
    expected_check = calculate_estonian_check_digit(base_part)
    return int(ref_str[-1]) == expected_check
