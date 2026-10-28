import asyncio
import pytest
import edge_tts
from app.main import app


class _MockEdgeCommunicate:
    """Fast deterministic mock for edge_tts.Communicate to prevent real WebSocket hangs in offline/sandbox tests."""

    def __init__(self, text: str, voice: str = "", volume: str = "+0%", **kwargs):
        self.text = text
        self.voice = voice
        self.volume = volume

    async def stream(self):
        await asyncio.sleep(0.01)
        payload = (b"\xff\xfb\x90\x44" * 350) + self.text.encode("utf-8")[:200]
        yield {"type": "audio", "data": payload}


@pytest.fixture(autouse=True)
def mock_edge_tts_communicate(monkeypatch):
    """Prevents unit tests from opening external WebSockets to speech.platform.bing.com."""
    monkeypatch.setattr(edge_tts, "Communicate", _MockEdgeCommunicate)


@pytest.fixture(autouse=True)
def reset_rate_limit_storage():
    """Ensures each pytest unit test runs with fresh rate limit quotas."""
    if hasattr(app.state, "limiter"):
        app.state.limiter.reset()
    yield
    if hasattr(app.state, "limiter"):
        app.state.limiter.reset()
