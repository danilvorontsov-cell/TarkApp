import asyncio
import time
import pytest
from app.services import tts_service
from app.services.tts_service import (
    get_or_synthesize_audio,
    _TTS_STREAM_CACHE,
    _IN_FLIGHT_TASKS,
    DEFAULT_VOICE,
)

@pytest.fixture(autouse=True)
def mock_azure_synth(monkeypatch):
    def fake_synthesize(ssml: str) -> bytes:
        time.sleep(0.05)
        return b"ID3" + b"\x00" * 2000

    monkeypatch.setattr(tts_service, "_synthesize_azure_ssml", fake_synthesize)

@pytest.mark.anyio
async def test_tts_cache_and_deduplication():
    test_text = "Тест скорости кэширования для TarkApp."
    
    # First call: synthesis
    t0 = time.time()
    audio1 = await get_or_synthesize_audio(test_text, voice=DEFAULT_VOICE, bilingual=False)
    elapsed1 = time.time() - t0
    assert len(audio1) > 1000

    # Second call: from in-memory cache
    t1 = time.time()
    audio2 = await get_or_synthesize_audio(test_text, voice=DEFAULT_VOICE, bilingual=False)
    elapsed2 = time.time() - t1
    
    assert audio1 == audio2
    assert elapsed2 < 0.05, f"Expected cache hit in <50ms, got {elapsed2:.4f}s"
    print(f"\nFirst call: {elapsed1:.2f}s, Cached call: {elapsed2*1000:.2f}ms")

@pytest.mark.anyio
async def test_tts_concurrent_deduplication():
    test_text = "Одновременный запрос озвучки от префетча и клика пользователя."
    
    # Launch two simultaneous requests
    t0 = time.time()
    task1 = asyncio.create_task(get_or_synthesize_audio(test_text, voice=DEFAULT_VOICE, bilingual=False))
    task2 = asyncio.create_task(get_or_synthesize_audio(test_text, voice=DEFAULT_VOICE, bilingual=False))
    
    res1, res2 = await asyncio.gather(task1, task2)
    elapsed = time.time() - t0
    
    assert res1 == res2
    assert len(res1) > 1000
    print(f"\nTwo concurrent calls finished together in: {elapsed:.2f}s (single Azure call)")


@pytest.mark.anyio
async def test_tts_disk_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(tts_service, "AUDIO_CACHE_DIR", tmp_path)
    test_text = "Тест дискового кэша."
    audio = await get_or_synthesize_audio(test_text)
    assert len(audio) > 1000

    files = list(tmp_path.glob("*.mp3"))
    assert len(files) == 1
    assert files[0].read_bytes() == audio

    # Clear RAM cache to force disk read
    tts_service._TTS_STREAM_CACHE.clear()

    audio_cached = await get_or_synthesize_audio(test_text)
    assert audio_cached == audio
