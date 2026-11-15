import inspect
import io
import unittest
from collections import OrderedDict
from unittest.mock import patch, MagicMock
import numpy as np
import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.tts_audit import TTSAuditLog
from app.routers.voice import verify_voice_device_access, check_tts_tier_policy
from app.services import tts_service
from app.services.tts_service import (
    _get_speech_config,
    _decode_audio_sync,
    _encode_pcm_to_mp3_sync,
    _synthesize_single_line_stitched,
    _store_in_memory_cache,
    clear_tts_ram_cache,
    get_tts_ram_cache_bytes,
    MAX_RAM_CACHE_BYTES,
    log_tts_audit,
    is_valid_mp3_buffer,
)


@pytest.fixture
def test_db_session():
    """Isolated in-memory SQLite database session."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


def test_azure_tts_native_24khz_output_format():
    """Verifies that Azure Speech output format is set to native 24 kHz (Audio24Khz96KBitRateMonoMp3)."""
    mock_speechsdk = MagicMock()
    mock_cfg = MagicMock()
    mock_speechsdk.SpeechConfig.return_value = mock_cfg
    mock_speechsdk.SpeechSynthesisOutputFormat.Audio24Khz96KBitRateMonoMp3 = "Audio24Khz96KBitRateMonoMp3"

    with patch.object(tts_service, "speechsdk", mock_speechsdk), \
         patch.object(tts_service, "_SPEECH_CONFIG_SINGLETON", None), \
         patch.object(tts_service, "_SPEECH_CONFIG_KEY_REGION", None):

        cfg = _get_speech_config("mock_key", "mock_region")
        assert cfg is mock_cfg
        mock_cfg.set_speech_synthesis_output_format.assert_called_once_with(
            "Audio24Khz96KBitRateMonoMp3"
        )


def test_decode_and_encode_audio_helpers():
    """Verifies _decode_audio_sync and _encode_pcm_to_mp3_sync helpers."""
    # Generate 0.1s of 440Hz sine wave at 24000 Hz
    sr = 24000
    t = np.linspace(0, 0.1, int(sr * 0.1), endpoint=False, dtype=np.float32)
    sine_pcm = 0.5 * np.sin(2 * np.pi * 440 * t).astype(np.float32)

    # 1. Encode to MP3
    mp3_bytes = _encode_pcm_to_mp3_sync([sine_pcm], sample_rate=sr)
    assert len(mp3_bytes) > 0
    assert is_valid_mp3_buffer(mp3_bytes)

    # 2. Decode back to PCM float32
    decoded_pcm = _decode_audio_sync(mp3_bytes, target_sample_rate=sr)
    assert decoded_pcm is not None
    assert isinstance(decoded_pcm, np.ndarray)
    assert decoded_pcm.dtype == np.float32
    # Verify approximate duration (around 2400 samples)
    assert abs(len(decoded_pcm) - 2400) < 500


def test_ram_cache_volume_eviction_50mb():
    """Verifies hard 50 MB byte limit for _TTS_STREAM_CACHE with LRU eviction."""
    clear_tts_ram_cache()
    cache = tts_service._TTS_STREAM_CACHE

    # Valid MP3 dummy buffer (starts with ID3)
    chunk_1mb = b"ID3" + b"\x00" * (1024 * 1024 - 3)

    # Store 10 chunks of 1MB
    for i in range(10):
        _store_in_memory_cache(cache, f"key_{i}", chunk_1mb)

    assert len(cache) == 10
    assert get_tts_ram_cache_bytes() == 10 * 1024 * 1024

    # Simulate temporarily lowering MAX_RAM_CACHE_BYTES to 5 MB to test eviction
    with patch.object(tts_service, "MAX_RAM_CACHE_BYTES", 5 * 1024 * 1024):
        _store_in_memory_cache(cache, "new_key", chunk_1mb)
        # Should have evicted older entries to stay under 5 MB
        assert get_tts_ram_cache_bytes() <= 5 * 1024 * 1024
        assert "key_0" not in cache
        assert "new_key" in cache

    clear_tts_ram_cache()


def test_log_tts_audit_skips_cache_hits_and_masks_device(test_db_session):
    """
    Verifies that log_tts_audit:
    1. Skips writing to SQLite for RAM_HIT and DISK_HIT.
    2. Writes to SQLite for real synthesis (AZURE_SYNTHESIS).
    3. Masks device_id to format {device_id[:6]}...{device_id[-4:]}.
    """
    db = test_db_session

    with patch("app.services.tts_service.SessionLocal", return_value=db):
        # 1. RAM_HIT -> MUST NOT write to database
        log_tts_audit(
            raw_incoming_text="Test ram hit",
            cache_status="RAM_HIT",
            status="SUCCESS",
            device_id="device-abcdef12345678",
        )
        assert db.query(TTSAuditLog).count() == 0

        # 2. DISK_HIT -> MUST NOT write to database
        log_tts_audit(
            raw_incoming_text="Test disk hit",
            cache_status="DISK_HIT",
            status="SUCCESS",
            device_id="device-abcdef12345678",
        )
        assert db.query(TTSAuditLog).count() == 0

        # 3. AZURE_SYNTHESIS -> MUST write to database with masked device_id
        log_tts_audit(
            raw_incoming_text="Real synthesis text",
            cache_status="AZURE_SYNTHESIS",
            status="SUCCESS",
            device_id="device-abcdef12345678",
        )
        record = db.query(TTSAuditLog).first()
        assert record is not None
        assert record.device_id == "device...5678"
        assert record.incoming_text == "Real synthesis text"


def test_verify_voice_device_access_is_sync():
    """Verifies that verify_voice_device_access is a synchronous dependency function."""
    assert not inspect.iscoroutinefunction(verify_voice_device_access)


def test_age_tier_high_gymnasium_pure_estonian_allowed():
    """
    Verifies that for High (grades 7-9) and Gymnasium (grades 10-12):
    - Pure Estonian (lang="et", bilingual=False) up to 600 characters is ALLOWED (returns None).
    - Pure Estonian over 600 characters is DISABLED (returns audio_disabled: True).
    - Russian (lang="ru") is DISABLED.
    - Bilingual is DISABLED.
    - Younger grades (primary 1-4) are always allowed.
    """
    # 1. Grade 8 (High), Russian -> audio_disabled: True
    res_ru = check_tts_tier_policy(
        clean_text="Это длинный текст на русском языке для ученика восьмого класса.",
        lang="ru",
        bilingual=False,
        grade=8,
    )
    assert res_ru is not None
    assert res_ru.get("audio_disabled") is True

    # 2. Grade 8 (High), Bilingual (flag) -> audio_disabled: True
    res_bi = check_tts_tier_policy(
        clean_text="Слово «kass» означает кошка.",
        lang="ru",
        bilingual=True,
        grade=8,
    )
    assert res_bi is not None
    assert res_bi.get("audio_disabled") is True

    # 3. Grade 8 (High), Bilingual (lang="bilingual") -> audio_disabled: True
    res_bi_lang = check_tts_tier_policy(
        clean_text="Loomad — это животные.",
        lang="bilingual",
        bilingual=False,
        grade=8,
    )
    assert res_bi_lang is not None
    assert res_bi_lang.get("audio_disabled") is True

    # 4. Grade 10 (Gymnasium), Pure Estonian <= 600 chars -> ALLOWED (None)
    estonian_text = "See on eestikeelne tekst gümnasistidele, mis peab kõlama selgelt ja korrektselt."
    res_et = check_tts_tier_policy(
        clean_text=estonian_text,
        lang="et",
        bilingual=False,
        grade=10,
    )
    assert res_et is None

    # 5. Grade 10 (Gymnasium), Pure Estonian > 600 chars -> audio_disabled: True
    long_estonian = "Tere päevast! " * 50  # ~700 chars
    res_et_long = check_tts_tier_policy(
        clean_text=long_estonian,
        lang="et",
        bilingual=False,
        grade=10,
    )
    assert res_et_long is not None
    assert res_et_long.get("audio_disabled") is True

    # 6. Explicit tier="gymnasium", Pure Estonian <= 600 chars -> ALLOWED (None)
    res_tier_et = check_tts_tier_policy(
        clean_text=estonian_text,
        lang="et",
        bilingual=False,
        tier="gymnasium",
    )
    assert res_tier_et is None

    # 7. Explicit tier="gymnasium", Russian -> audio_disabled: True
    res_tier_ru = check_tts_tier_policy(
        clean_text="Русский конспект для гимназии",
        lang="ru",
        bilingual=False,
        tier="gymnasium",
    )
    assert res_tier_ru is not None
    assert res_tier_ru.get("audio_disabled") is True

    # 8. Grade 3 (Primary) -> ALWAYS ALLOWED (None) for Russian, Estonian, and Bilingual
    assert check_tts_tier_policy(clean_text="Урок для 3 класса", lang="ru", bilingual=False, grade=3) is None
    assert check_tts_tier_policy(clean_text="Tund 3. klassile", lang="et", bilingual=False, grade=3) is None
    assert check_tts_tier_policy(clean_text="Слово «kass»", lang="ru", bilingual=True, grade=3) is None
