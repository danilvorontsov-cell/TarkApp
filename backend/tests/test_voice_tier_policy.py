import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_tts_disabled_for_grades_7_to_12(client):
    response = client.get(
        "/api/v1/voice/tts",
        params={
            "text": "Это длинная подсказка с объяснением темы урока для старшеклассника на русском языке.",
            "lang": "ru",
            "grade": 8,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("audio_disabled") is True


def test_tts_disabled_for_gymnasium_tier(client):
    response = client.get(
        "/api/v1/voice/tts",
        params={
            "text": "Длинный текст конспекта по биологии или физике для гимназиста.",
            "lang": "ru",
            "tier": "gymnasium",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("audio_disabled") is True


@patch("app.routers.voice.get_or_synthesize_audio", new_callable=AsyncMock)
def test_tts_enabled_for_primary_grade(mock_synthesize, client):
    mock_synthesize.return_value = b"\xff\xfb\x90\x44"  # Mock MP3 header bytes
    response = client.get(
        "/api/v1/voice/tts",
        params={
            "text": "Привет! Давай решим пример вместе.",
            "lang": "ru",
            "grade": 2,
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"


@patch("app.routers.voice.get_or_synthesize_audio", new_callable=AsyncMock)
def test_speak_endpoint_for_vocabulary(mock_synthesize, client):
    mock_synthesize.return_value = b"\xff\xfb\x90\x44"
    response = client.get(
        "/api/v1/voice/speak",
        params={
            "text": "fotosüntees",
            "lang": "et",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
