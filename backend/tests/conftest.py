import pytest
from app.config import settings

settings.APP_ENV = "test"

from app.main import app
from app.database import init_db
from app.services import tts_service, telegram_alert
import app.main as app_main
from app.auth import get_current_user, CurrentUser

# Initialize database tables for all test runs
init_db()


@pytest.fixture(autouse=True)
def mock_telegram_polling(monkeypatch):
    """Mocks background Telegram long-polling and alert dispatching to prevent hanging in tests."""
    async def fake_coro(*args, **kwargs):
        return None

    monkeypatch.setattr(telegram_alert, "start_telegram_polling", fake_coro)
    monkeypatch.setattr(telegram_alert, "send_telegram_alert", fake_coro)
    monkeypatch.setattr(telegram_alert, "send_telegram_feedback", fake_coro)
    monkeypatch.setattr(telegram_alert, "send_telegram_invoice_notification", fake_coro)
    monkeypatch.setattr(telegram_alert, "register_telegram_bot_commands", fake_coro)
    monkeypatch.setattr(telegram_alert, "answer_telegram_callback_query", fake_coro)
    if hasattr(app_main, "start_telegram_polling"):
        monkeypatch.setattr(app_main, "start_telegram_polling", fake_coro)


@pytest.fixture(autouse=True)
def mock_azure_speech_synthesizer(monkeypatch):
    """Mocks Azure Speech SDK SSML synthesis to prevent external network calls in unit tests."""
    def fake_synthesize(ssml: str) -> bytes:
        return (b"\xff\xfb\x90\x44" * 350) + ssml.encode("utf-8")[:200]

    monkeypatch.setattr(tts_service, "_synthesize_azure_ssml", fake_synthesize)


@pytest.fixture(autouse=True)
def mock_gemini_service():
    """Ensures deterministic fast unit tests using pedagogical mock generator unless explicitly testing live client."""
    from app.services.gemini_service import gemini_tutor_service
    original_key = gemini_tutor_service.api_key
    original_client = gemini_tutor_service._client
    gemini_tutor_service.api_key = "mock"
    gemini_tutor_service._client = None
    yield
    gemini_tutor_service.api_key = original_key
    gemini_tutor_service._client = original_client


@pytest.fixture(autouse=True)
def default_auth_override():
    """Provides a default authenticated CurrentUser for all endpoints using get_current_user."""
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="test-user-id",
        nickname="Ученик",
        token="test-user-id:Ученик",
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def reset_rate_limit_storage():
    """Ensures each pytest unit test runs with fresh rate limit quotas."""
    if hasattr(app.state, "limiter"):
        app.state.limiter.reset()
    yield
    if hasattr(app.state, "limiter"):
        app.state.limiter.reset()


@pytest.fixture(autouse=True)
def reset_test_device_quota():
    """Resets dev test device scan counters so test suite never exhausts daily quotas."""
    from app.database import SessionLocal
    from app.models.license import Device
    db = SessionLocal()
    try:
        db.query(Device).update({"free_scans_used": 0})
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.query(Device).update({"free_scans_used": 0})
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
