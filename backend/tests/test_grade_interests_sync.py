import pytest
from app.models.page_analysis import UserProfile, AgeTier, AGE_TIER_DEFAULT_INTERESTS
from app.prompts.tutor_prompt import build_tutor_user_prompt


def test_grade_3_primary_interests():
    profile = UserProfile(grade=3, interests=["Minecraft", "LEGO", "Roblox"])
    assert profile.tier == AgeTier.PRIMARY
    assert profile.interests == ["Minecraft", "LEGO", "Roblox"]
    prompt = build_tutor_user_prompt(profile)
    assert "3 класс" in prompt
    assert "Minecraft, LEGO, Roblox" in prompt


def test_grade_6_middle_sanitizes_legacy_primary_defaults():
    # If legacy client sends primary defaults to grade 6
    profile = UserProfile(grade=6, interests=["Minecraft", "LEGO", "Roblox"])
    assert profile.tier == AgeTier.MIDDLE
    # Must be replaced with age-appropriate middle tier defaults
    assert profile.interests == AGE_TIER_DEFAULT_INTERESTS[AgeTier.MIDDLE][:3]
    prompt = build_tutor_user_prompt(profile)
    assert "6 класс" in prompt
    user_int_section = prompt.split("user_interests):")[1].split("\n")[0]
    assert "LEGO" not in user_int_section
    assert "Roblox" not in user_int_section
    assert "Футбол и спорт" in user_int_section


def test_grade_12_gymnasium_sanitizes_legacy_primary_defaults():
    # If legacy client sends primary defaults to grade 12
    profile = UserProfile(grade=12, interests=["Minecraft", "LEGO", "Roblox"])
    assert profile.tier == AgeTier.GYMNASIUM
    # Must be replaced with age-appropriate gymnasium tier defaults
    assert profile.interests == AGE_TIER_DEFAULT_INTERESTS[AgeTier.GYMNASIUM][:3]
    prompt = build_tutor_user_prompt(profile)
    assert "12 класс" in prompt
    user_int_section = prompt.split("user_interests):")[1].split("\n")[0]
    assert "Minecraft" not in user_int_section
    assert "Roblox" not in user_int_section
    assert "LEGO" not in user_int_section
    assert "Современные технологии и IT" in user_int_section


def test_custom_user_interests_preserved():
    # Custom interests like astronomy or finance should be kept
    profile = UserProfile(grade=12, interests=["Астрофизика", "Финансы и стартапы"])
    assert profile.tier == AgeTier.GYMNASIUM
    assert profile.interests == ["Астрофизика", "Финансы и стартапы"]
    prompt = build_tutor_user_prompt(profile)
    assert "Астрофизика, Финансы и стартапы" in prompt


def test_grade_12_purges_childish_toys_from_mixed_list():
    # If mixed with toys for a 12th grader, toys are purged
    profile = UserProfile(grade=12, interests=["IT", "Roblox", "LEGO", "Биология"])
    assert profile.tier == AgeTier.GYMNASIUM
    assert "Roblox" not in profile.interests
    assert "LEGO" not in profile.interests
    assert "IT" in profile.interests
    assert "Биология" in profile.interests
