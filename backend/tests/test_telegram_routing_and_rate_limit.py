import time
from unittest.mock import patch, AsyncMock, MagicMock
import pytest
from httpx import Response

from app.config import settings
from app.services.telegram_alert import (
    send_telegram_message,
    send_telegram_alert,
    send_telegram_feedback,
    clear_alert_history,
    compute_error_hash,
    _ALERT_HISTORY,
)
from app.services.telegram_alerts import (
    send_telegram_message as send_telegram_message_alias,
    send_telegram_alert as send_telegram_alert_alias,
)


@pytest.fixture(autouse=True)
def reset_history():
    clear_alert_history()
    yield
    clear_alert_history()


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
async def test_send_telegram_message_with_topic():
    with patch.object(settings, "TELEGRAM_BOT_TOKEN", "mock_bot_token"), \
         patch.object(settings, "TELEGRAM_CHAT_ID", "-1001234567890"):

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = Response(200, json={"ok": True})

            result = await send_telegram_message(
                text="Test message in topic",
                parse_mode="HTML",
                message_thread_id=12,
            )

            assert result is True
            assert mock_post.called
            call_kwargs = mock_post.call_args.kwargs
            json_payload = call_kwargs.get("json", {})

            assert json_payload["chat_id"] == "-1001234567890"
            assert json_payload["text"] == "Test message in topic"
            assert json_payload["parse_mode"] == "HTML"
            assert json_payload["message_thread_id"] == 12


@pytest.mark.anyio
async def test_send_telegram_message_without_topic():
    with patch.object(settings, "TELEGRAM_BOT_TOKEN", "mock_bot_token"), \
         patch.object(settings, "TELEGRAM_CHAT_ID", "-1001234567890"):

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = Response(200, json={"ok": True})

            result = await send_telegram_message(
                text="Test message in general chat",
            )

            assert result is True
            assert mock_post.called
            json_payload = mock_post.call_args.kwargs.get("json", {})
            assert json_payload["chat_id"] == "-1001234567890"
            assert "message_thread_id" not in json_payload


@pytest.mark.anyio
async def test_feedback_routes_to_bugs_topic():
    with patch.object(settings, "TELEGRAM_BOT_TOKEN", "mock_token"), \
         patch.object(settings, "TELEGRAM_CHAT_ID", "-10012345"), \
         patch.object(settings, "TELEGRAM_TOPIC_BUGS", 12), \
         patch.object(settings, "TELEGRAM_TOPIC_FEATURES", 14):

        with patch("app.services.telegram_alert.send_telegram_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            payload = {
                "category": "bug",
                "message": "Кнопка не нажимается на странице 10",
                "contact": "@tester",
                "current_grade": 4,
            }
            res = await send_telegram_feedback(payload)

            assert res is True
            assert mock_send.called
            _, kwargs = mock_send.call_args
            assert kwargs.get("message_thread_id") == 12
            assert "🐞 ОШИБКА" in kwargs.get("text", "")


@pytest.mark.anyio
async def test_feedback_routes_to_features_topic():
    with patch.object(settings, "TELEGRAM_BOT_TOKEN", "mock_token"), \
         patch.object(settings, "TELEGRAM_CHAT_ID", "-10012345"), \
         patch.object(settings, "TELEGRAM_TOPIC_BUGS", 12), \
         patch.object(settings, "TELEGRAM_TOPIC_FEATURES", 14):

        with patch("app.services.telegram_alert.send_telegram_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            payload = {
                "category": "feature",
                "message": "Сделайте возможность сохранять закладки",
            }
            res = await send_telegram_feedback(payload)

            assert res is True
            assert mock_send.called
            _, kwargs = mock_send.call_args
            assert kwargs.get("message_thread_id") == 14
            assert "💡 ПОЖЕЛАНИЕ" in kwargs.get("text", "")


@pytest.mark.anyio
async def test_critical_alert_routes_to_alerts_topic():
    with patch.object(settings, "TELEGRAM_BOT_TOKEN", "mock_token"), \
         patch.object(settings, "TELEGRAM_CHAT_ID", "-10012345"), \
         patch.object(settings, "TELEGRAM_TOPIC_ALERTS", 16):

        with patch("app.services.telegram_alert.send_telegram_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            res = await send_telegram_alert(
                endpoint="/api/v1/analyze-page",
                exc=RuntimeError("Database connection dropped"),
                status_code=500,
            )

            assert res is True
            assert mock_send.called
            _, kwargs = mock_send.call_args
            assert kwargs.get("message_thread_id") == 16
            assert "Database connection dropped" in kwargs.get("text", "")


@pytest.mark.anyio
async def test_client_error_4xx_never_sends_telegram_alert():
    with patch.object(settings, "TELEGRAM_BOT_TOKEN", "mock_token"), \
         patch.object(settings, "TELEGRAM_CHAT_ID", "-10012345"):

        with patch("app.services.telegram_alert.send_telegram_message", new_callable=AsyncMock) as mock_send:
            res = await send_telegram_alert(
                endpoint="/api/v1/analyze-page",
                exc=ValueError("Invalid grade"),
                status_code=400,
            )

            assert res is False
            assert not mock_send.called


@pytest.mark.anyio
async def test_rate_limit_suppresses_repeated_500_errors():
    with patch.object(settings, "TELEGRAM_BOT_TOKEN", "mock_token"), \
         patch.object(settings, "TELEGRAM_CHAT_ID", "-10012345"), \
         patch.object(settings, "TELEGRAM_TOPIC_ALERTS", 16):

        with patch("app.services.telegram_alert.send_telegram_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            exc = ZeroDivisionError("division by zero in math analyzer")

            # 1. First trigger should successfully send to Telegram
            res1 = await send_telegram_alert("/api/v1/math", exc, 500)
            assert res1 is True
            assert mock_send.call_count == 1

            # 2. Second trigger with identical error and endpoint should be suppressed
            res2 = await send_telegram_alert("/api/v1/math", exc, 500)
            assert res2 is False
            # Still 1, no second call made to Telegram!
            assert mock_send.call_count == 1

            # 3. Third trigger with a different error type on same endpoint should NOT be suppressed
            res3 = await send_telegram_alert("/api/v1/math", TimeoutError("Gemini timed out"), 500)
            assert res3 is True
            assert mock_send.call_count == 2

            # 4. Fourth trigger with same original error but on a DIFFERENT endpoint should NOT be suppressed
            res4 = await send_telegram_alert("/api/v1/voice/tts", exc, 500)
            assert res4 is True
            assert mock_send.call_count == 3


@pytest.mark.anyio
async def test_rate_limit_expires_after_30_minutes():
    with patch.object(settings, "TELEGRAM_BOT_TOKEN", "mock_token"), \
         patch.object(settings, "TELEGRAM_CHAT_ID", "-10012345"):

        with patch("app.services.telegram_alert.send_telegram_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            exc = RuntimeError("Fatal GPU out of memory")

            # Initial alert at t0
            t0 = 1000000.0
            with patch("time.time", return_value=t0):
                res1 = await send_telegram_alert("/api/v1/gpu", exc, 500)
                assert res1 is True
                assert mock_send.call_count == 1

            # Duplicate at t0 + 10 minutes (600s) -> suppressed
            with patch("time.time", return_value=t0 + 600.0):
                res2 = await send_telegram_alert("/api/v1/gpu", exc, 500)
                assert res2 is False
                assert mock_send.call_count == 1

            # Duplicate at t0 + 31 minutes (1860s) -> allowed again!
            with patch("time.time", return_value=t0 + 1860.0):
                res3 = await send_telegram_alert("/api/v1/gpu", exc, 500)
                assert res3 is True
                assert mock_send.call_count == 2


def test_telegram_alerts_module_alias():
    assert send_telegram_message_alias is send_telegram_message
    assert send_telegram_alert_alias is send_telegram_alert
