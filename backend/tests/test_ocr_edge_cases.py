import io
import base64
import pytest
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

from app.main import app
from app.services.gemini_service import gemini_tutor_service
from app.models.page_analysis import PageAnalysisResponse


@pytest.fixture
def client():
    return TestClient(app)


def create_blurry_black_image() -> bytes:
    """Generates a pitch black / dark blurry image representing camera occluded."""
    img = Image.new("RGB", (300, 300), color=(5, 5, 5))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=40)
    return buf.getvalue()


def create_blank_white_image() -> bytes:
    """Generates an entirely blank white sheet of paper with no readable text."""
    img = Image.new("RGB", (400, 400), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def create_upside_down_text_image() -> bytes:
    """Generates an image with upside-down (rotated 180 deg) text simulating inverted orientation."""
    img = Image.new("RGB", (400, 200), color=(245, 245, 245))
    draw = ImageDraw.Draw(img)
    draw.text((30, 80), "Eesti keele harjutus: 12 + 8 = 20", fill=(0, 0, 0))
    # Rotate 180 degrees
    upside_down = img.rotate(180)
    buf = io.BytesIO()
    upside_down.save(buf, format="JPEG")
    return buf.getvalue()


class TestOcrEdgeCases:
    """
    Stress tests for low-quality / unreadable / inverted camera shots.
    Verifies that the backend handles edge-case images gracefully without crashing with HTTP 500,
    and returns educational fallback advice or valid response structure.
    """

    def test_blurry_black_image_returns_graceful_response(self, client):
        img_bytes = create_blurry_black_image()
        files = {"files": ("black_blurry.jpg", img_bytes, "image/jpeg")}
        data = {
            "grade": 3,
            "nickname": "Тестер",
            "interests": "Minecraft",
        }

        response = client.post(
            "/api/v1/analyze-page",
            files=files,
            data=data,
            headers={"X-Device-ID": "test-ocr-device-1"},
        )

        assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}: {response.text}"
        result = response.json()
        assert "task_title" in result
        assert "theme_explanation" in result
        assert "vocabulary" in result
        assert "how_to_answer" in result
        # Check that response contains either educational text or is_acceptable flag
        assert len(result["theme_explanation"]) > 0

    def test_blank_white_sheet_returns_graceful_response(self, client):
        img_bytes = create_blank_white_image()
        files = {"files": ("blank_white.jpg", img_bytes, "image/jpeg")}
        data = {
            "grade": 4,
            "nickname": "Ученик",
        }

        response = client.post(
            "/api/v1/analyze-page",
            files=files,
            data=data,
            headers={"X-Device-ID": "test-ocr-device-2"},
        )

        assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}: {response.text}"
        result = response.json()
        assert "task_title" in result
        assert "theme_explanation" in result
        assert "answer_template" in result

    def test_upside_down_text_image_returns_graceful_response(self, client):
        img_bytes = create_upside_down_text_image()
        files = {"files": ("upside_down.jpg", img_bytes, "image/jpeg")}
        data = {
            "grade": 6,
            "nickname": "Алиса",
        }

        response = client.post(
            "/api/v1/analyze-page",
            files=files,
            data=data,
            headers={"X-Device-ID": "test-ocr-device-3"},
        )

        assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}: {response.text}"
        result = response.json()
        assert "task_title" in result
        assert "voice_prompt_script" in result

    def test_unreadable_image_triggers_emergency_fallback_with_acceptable_false(self, client, monkeypatch):
        """Simulates Gemini Vision returning unparseable or error payload for corrupted/unreadable image."""
        async def mock_failing_gemini(*args, **kwargs):
            # Simulate failure to parse OCR which leads to emergency fallback
            profile = kwargs.get("profile")
            return gemini_tutor_service._generate_emergency_fallback(profile)

        monkeypatch.setattr(gemini_tutor_service, "analyze_page", mock_failing_gemini)

        img_bytes = create_blurry_black_image()
        files = {"files": ("corrupted.jpg", img_bytes, "image/jpeg")}

        response = client.post(
            "/api/v1/analyze-page",
            files=files,
            data={"grade": 2, "nickname": "Даниил"},
            headers={"X-Device-ID": "test-ocr-fallback-dev"},
        )

        assert response.status_code == 200
        result = response.json()
        assert result.get("is_acceptable") is False
        assert "бликов" in result["theme_explanation"] or "повторный снимок" in result["theme_explanation"]
        assert "Памятка по фотосъёмке" in result["worked_example"]["title"]
