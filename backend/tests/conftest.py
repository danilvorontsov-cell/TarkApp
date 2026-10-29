import pytest
from app.main import app
from app.database import init_db
from app.services import tts_service

# Initialize database tables for all test runs
init_db()


@pytest.fixture(autouse=True)
def mock_azure_speech_synthesizer(monkeypatch):
    """Mocks Azure Speech SDK SSML synthesis to prevent external network calls in unit tests."""
    def fake_synthesize(ssml: str) -> bytes:
        return (b"\xff\xfb\x90\x44" * 350) + ssml.encode("utf-8")[:200]

    monkeypatch.setattr(tts_service, "_synthesize_azure_ssml", fake_synthesize)


@pytest.fixture(autouse=True)
def reset_rate_limit_storage():
    """Ensures each pytest unit test runs with fresh rate limit quotas."""
    if hasattr(app.state, "limiter"):
        app.state.limiter.reset()
    yield
    if hasattr(app.state, "limiter"):
        app.state.limiter.reset()
