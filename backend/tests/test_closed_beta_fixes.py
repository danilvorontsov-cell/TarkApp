import pytest
import io
import base64
from unittest.mock import patch, AsyncMock
from PIL import Image
from fastapi.testclient import TestClient

from app.main import app
from app.prompts.tutor_prompt import ESTONIAN_TUTOR_SYSTEM_PROMPT, build_tutor_user_prompt
from app.models.page_analysis import UserProfile
from app.services.gemini_service import gemini_tutor_service
from app.services.telegram_alert import send_telegram_alert, send_telegram_message


@pytest.fixture
def client():
    return TestClient(app)


def test_gemini_prompt_anti_cheat_guardrails():
    """Verifies that the system prompt strictly prohibits direct homework answers."""
    assert "NO-LEAK" in ESTONIAN_TUTOR_SYSTEM_PROMPT
    assert "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО" in ESTONIAN_TUTOR_SYSTEM_PROMPT
    assert "ГДЗ" in ESTONIAN_TUTOR_SYSTEM_PROMPT
    assert "вымышленными числами" in ESTONIAN_TUTOR_SYSTEM_PROMPT.lower()

    profile = UserProfile(grade=4, nickname="Даниил")
    user_prompt = build_tutor_user_prompt(profile)
    assert "анти-чит" in user_prompt.lower() or "no-leak" in user_prompt.lower()


def test_gemini_emergency_fallback():
    """Verifies emergency fallback generates valid, friendly educational structure."""
    profile = UserProfile(grade=3, nickname="Маша")
    fallback = gemini_tutor_service._generate_emergency_fallback(profile)

    assert fallback is not None
    assert "Маша" in fallback.theme_explanation
    assert len(fallback.vocabulary) >= 2
    assert fallback.worked_example is not None
    assert "Попробовать снова" in fallback.worked_example.steps[2]


@pytest.mark.anyio
async def test_telegram_message_length_truncation():
    """Verifies that exceptionally long error messages or texts are truncated to avoid Telegram 400."""
    giant_text = "E" * 5000
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value.status_code = 200

        with patch("app.config.settings.TELEGRAM_BOT_TOKEN", "mock_bot_token"), \
             patch("app.config.settings.TELEGRAM_CHAT_ID", "-10012345678"):
            
            await send_telegram_message(giant_text)
            assert mock_post.called
            sent_payload = mock_post.call_args.kwargs.get("json", {})
            sent_text = sent_payload.get("text", "")
            assert len(sent_text) <= 4000
            assert "[truncated]" in sent_text


def test_rate_limiter_license_activate_blocks_excessive_attempts(client):
    """Verifies that brute-force attempts on /api/v1/license/activate are throttled at 5/minute."""
    # Reset limiter storage if available
    if hasattr(app.state, "limiter"):
        app.state.limiter.reset()

    headers = {"X-Device-ID": "test-ratelimit-device-activate"}

    # First 5 calls are permitted (even if returning 400 for bad key)
    for _ in range(5):
        resp = client.post(
            "/api/v1/license/activate",
            json={"key_code": "INVALID-KEY-CODE"},
            headers=headers,
        )
        assert resp.status_code in (400, 200), f"Expected 400, got {resp.status_code}"

    # 6th call should be blocked by slowapi with HTTP 429
    blocked_resp = client.post(
        "/api/v1/license/activate",
        json={"key_code": "INVALID-KEY-CODE"},
        headers=headers,
    )
    assert blocked_resp.status_code == 429
    data = blocked_resp.json()
    assert data.get("error") == "RATE_LIMIT_EXCEEDED"
    assert "Слишком много запросов" in data.get("message", "")
