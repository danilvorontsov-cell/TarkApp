import os
import io
import pytest
import httpx
from sqlalchemy import text
from app.main import app
from app.database import engine, get_db
from app.models.page_analysis import UserProfile, PageAnalysisResponse
from app.services.analysis_cache import (
    compute_analysis_cache_key,
    get_cached_analysis,
    store_cached_analysis,
    clear_analysis_cache,
    _ANALYSIS_CACHE,
    MAX_ANALYSIS_CACHE_ENTRIES,
)


def make_mock_analysis(title: str = "Test Lesson") -> PageAnalysisResponse:
    return PageAnalysisResponse(
        task_title=title,
        theme_explanation="Theme explanation",
        vocabulary=[],
        how_to_answer="Step 1, step 2",
        answer_template="Summa on ___",
        voice_prompt_script="Tubli! Teeme koos ära.",
    )


def test_analysis_cache_key_generation():
    profile1 = UserProfile(grade=4, tier="primary", interests=["minecraft", "lego"], nickname="Alex")
    profile2 = UserProfile(grade=4, tier="primary", interests=["minecraft", "lego"], nickname="Alex")
    profile3 = UserProfile(grade=7, tier="middle", interests=["minecraft", "lego"], nickname="Alex")

    image_data1 = b"sample_jpeg_image_bytes_12345"
    image_data2 = b"sample_jpeg_image_bytes_67890"

    key1 = compute_analysis_cache_key([image_data1], profile1)
    key2 = compute_analysis_cache_key([image_data1], profile2)
    key3 = compute_analysis_cache_key([image_data1], profile3)
    key4 = compute_analysis_cache_key([image_data2], profile1)

    # Identical images and profile -> identical cache key
    assert key1 == key2
    # Different grade/tier -> different cache key
    assert key1 != key3
    # Different image -> different cache key
    assert key1 != key4


def test_analysis_cache_store_and_retrieve():
    clear_analysis_cache()
    profile = UserProfile(grade=5, tier="middle", interests=["robotics"], nickname="Ivan")
    image_bytes = b"sample_page_content"
    key = compute_analysis_cache_key([image_bytes], profile)

    mock_analysis = make_mock_analysis("Test Lesson")

    # Miss before storing
    assert get_cached_analysis(key) is None

    # Store
    store_cached_analysis(key, mock_analysis)

    # Hit after storing
    cached = get_cached_analysis(key)
    assert cached is not None
    assert cached.task_title == "Test Lesson"
    assert cached.answer_template == "Summa on ___"

    clear_analysis_cache()
    assert get_cached_analysis(key) is None


def test_analysis_cache_lru_eviction():
    clear_analysis_cache()
    profile = UserProfile(grade=3, tier="primary")

    # Fill beyond capacity
    for i in range(MAX_ANALYSIS_CACHE_ENTRIES + 10):
        key = f"key_{i}"
        resp = make_mock_analysis(f"Lesson {i}")
        store_cached_analysis(key, resp)

    assert len(_ANALYSIS_CACHE) <= MAX_ANALYSIS_CACHE_ENTRIES
    # Earliest items should be evicted
    assert get_cached_analysis("key_0") is None
    # Latest item should exist
    assert get_cached_analysis(f"key_{MAX_ANALYSIS_CACHE_ENTRIES + 9}") is not None
    clear_analysis_cache()


def test_sqlite_wal_pragmas():
    with engine.connect() as conn:
        journal_mode = conn.execute(text("PRAGMA journal_mode;")).scalar()
        synchronous = conn.execute(text("PRAGMA synchronous;")).scalar()
        busy_timeout = conn.execute(text("PRAGMA busy_timeout;")).scalar()

        # In SQLite WAL mode, journal_mode is 'wal'
        assert str(journal_mode).lower() == "wal"
        # synchronous NORMAL is 1
        assert synchronous in (1, "1", "NORMAL")
        # busy_timeout should be 15000 ms
        assert busy_timeout == 15000


from unittest.mock import patch

@pytest.mark.anyio
async def test_tts_static_audio_delivery_and_cache_headers():
    fake_mp3 = b"\xff\xfb\x90\x00" * 50  # valid fake MP3 frame bytes
    with patch("app.routers.voice.get_or_synthesize_audio", return_value=fake_mp3):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/voice/tts", params={
                "text": "Тест статической раздачи и кеширования аудио.",
                "lang": "ru"
            })
            assert response.status_code == 200
            assert response.headers.get("cache-control") == "public, max-age=604800, immutable"
            static_url = response.headers.get("x-static-audio-url")
            assert static_url is not None
            assert static_url.startswith("/static/audio/")
            assert static_url.endswith(".mp3")

            # Verify static file can be retrieved directly via mounted /static route
            static_resp = await ac.get(static_url)
            assert static_resp.status_code == 200
            assert static_resp.content == fake_mp3
