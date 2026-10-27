import pytest
import httpx
from app.main import app

@pytest.mark.anyio
async def test_tts_russian_endpoint():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/voice/tts", params={
            "text": "Привет! Это проверка надежности озвучки.",
            "lang": "ru"
        })
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mpeg"
        assert len(response.content) > 1000

@pytest.mark.anyio
async def test_tts_estonian_endpoint():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/voice/tts", params={
            "text": "Tere tulemast kooli!",
            "lang": "et"
        })
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mpeg"
        assert len(response.content) > 1000

@pytest.mark.anyio
async def test_tts_bilingual_endpoint():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/voice/tts", params={
            "text": "Запомни эстонское слово «ohutus». Повтори: «ohutus».",
            "lang": "ru",
            "bilingual": "true"
        })
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mpeg"
        assert len(response.content) > 1000
