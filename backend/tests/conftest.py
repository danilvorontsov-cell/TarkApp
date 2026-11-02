import pytest
from app.main import app
from app.database import init_db
from app.services import tts_service
from app.auth import get_current_user, CurrentUser

# Initialize database tables for all test runs
init_db()


@pytest.fixture(autouse=True)
def mock_azure_speech_synthesizer(monkeypatch):
    """Mocks Azure Speech SDK SSML synthesis to prevent external network calls in unit tests."""
    def fake_synthesize(ssml: str) -> bytes:
        return (b"\xff\xfb\x90\x44" * 350) + ssml.encode("utf-8")[:200]

    monkeypatch.setattr(tts_service, "_synthesize_azure_ssml", fake_synthesize)


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
