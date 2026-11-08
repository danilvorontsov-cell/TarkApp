import _thread
import threading
import pytest
from app.config import settings

settings.APP_ENV = "test"
if not settings.TELEGRAM_WEBHOOK_SECRET:
    settings.TELEGRAM_WEBHOOK_SECRET = "test-webhook-secret"

from app.main import app
from app.database import init_db
from app.services import tts_service, telegram_alert
import app.main as app_main
from app.auth import get_current_user, CurrentUser

# Initialize database tables for all test runs
init_db()


def pytest_addoption(parser):
    """Registers --timeout CLI option when pytest-timeout plugin is not installed."""
    try:
        parser.addoption(
            "--timeout",
            action="store",
            type=float,
            default=None,
            help="Per-test execution timeout in seconds (offline builtin fallback).",
        )
    except ValueError:
        # Option already registered by pytest-timeout plugin
        pass


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    """Enforces per-test --timeout when specified on the command line."""
    timeout_sec = item.config.getoption("--timeout", default=None)
    timer = None
    if timeout_sec and timeout_sec > 0:
        timer = threading.Timer(float(timeout_sec), _thread.interrupt_main)
        timer.daemon = True
        timer.start()
    try:
        yield
    finally:
        if timer is not None:
            timer.cancel()


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
    """Mocks Azure Speech SDK SSML synthesis with a valid MP3 buffer (> 800 bytes, ID3 + MPEG sync frames)."""
    def fake_synthesize(ssml: str) -> bytes:
        id3_header = b"ID3\x04\x00\x00\x00\x00\x00\x00"
        mpeg_frames = b"\xff\xfb\x90\x44" * 350
        return id3_header + mpeg_frames + ssml.encode("utf-8")[:200]

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
    from datetime import datetime, timezone
    from app.database import SessionLocal
    from app.models.license import Device
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    db = SessionLocal()
    try:
        db.query(Device).update({"free_reviews_left": 20, "last_review_date": today_str})
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.query(Device).update({"free_reviews_left": 20, "last_review_date": today_str})
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
