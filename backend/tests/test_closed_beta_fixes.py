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


def test_dev_test_device_bypass_blocked_in_production(client):
    """Verifies that 'dev-test-device' does not receive automatic PRO bypass when APP_ENV=production."""
    from app.database import SessionLocal
    from app.models.license import Device
    from app.services.license_service import check_device_access

    with patch("app.config.settings.APP_ENV", "production"):
        # Missing X-Device-ID header must be rejected in production
        resp_missing = client.get("/api/v1/license/status")
        assert resp_missing.status_code == 400

        # Passing 'default-dev-device' in production must NOT grant DEV-KEY-TEST
        db = SessionLocal()
        try:
            db.query(Device).filter(Device.device_id == "default-dev-device").delete()
            db.commit()
            status_prod = check_device_access("default-dev-device", db)
            assert status_prod["has_key"] is False
            assert status_prod["activated_key"] is None
            assert status_prod["days_left"] <= 14
        finally:
            db.query(Device).filter(Device.device_id == "default-dev-device").delete()
            db.commit()
            db.close()


def test_telegram_webhook_secret_and_no_key_leakage(client):
    """Verifies that /api/v1/telegram/webhook checks secret header and never leaks generated keys in HTTP body."""
    update_payload = {
        "message": {
            "from": {"id": 777888999},
            "chat": {"id": 777888999},
            "text": "/gen 2 30",
        }
    }

    with patch("app.config.settings.ADMIN_TELEGRAM_ID", "777888999"), \
         patch("app.config.settings.TELEGRAM_WEBHOOK_SECRET", "super_secret_token_123"), \
         patch("app.services.telegram_alert.send_telegram_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True

        # 1. Without secret token -> 403 Forbidden
        forbidden_resp = client.post("/api/v1/telegram/webhook", json=update_payload)
        assert forbidden_resp.status_code == 403

        # 2. With valid secret token -> 200 OK, but 'keys' and 'reply' are stripped from HTTP response
        ok_resp = client.post(
            "/api/v1/telegram/webhook",
            json=update_payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": "super_secret_token_123"},
        )
        assert ok_resp.status_code == 200
        body = ok_resp.json()
        assert body["ok"] is True
        assert body["result"]["command"] == "gen"
        assert "keys" not in body["result"]
        assert "reply" not in body["result"]


def test_more_examples_allowed_when_zero_free_reviews_left(client):
    """Verifies that a trial user who spent their 5th free review can still click 'More examples' on that lesson."""
    from app.database import SessionLocal
    from app.models.license import Device

    device_id = "test-zero-reviews-more-examples-dev"
    db = SessionLocal()
    try:
        client.get("/api/v1/license/status", headers={"X-Device-ID": device_id})
        dev = db.query(Device).filter(Device.device_id == device_id).first()
        dev.free_reviews_left = 0
        db.commit()

        resp = client.post(
            "/api/v1/more-examples",
            json={
                "task_title": "Liitmine",
                "theme_explanation": "Сложение чисел",
                "vocabulary": [{"est": "summa", "ru": "сумма", "example": "Summa on 10"}],
                "current_template": "Summa on [10].",
                "grade": 3,
            },
            headers={"X-Device-ID": device_id},
        )
        assert resp.status_code == 200
        assert "templates" in resp.json()
    finally:
        db.close()
