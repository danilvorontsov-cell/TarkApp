import io
import base64
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app.main import app
from app.models.page_analysis import (
    AgeTier,
    ThemeInterest,
    UserProfile,
    PageAnalysisResponse,
    VocabularyItem,
)
from app.services.gemini_service import GeminiTutorService


@pytest.fixture(autouse=True)
def mock_gemini_service():
    """Ensures deterministic fast unit tests using pedagogical mock generator."""
    from app.services.gemini_service import gemini_tutor_service
    original_client = gemini_tutor_service._client
    gemini_tutor_service._client = None
    yield
    gemini_tutor_service._client = original_client


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_image_bytes():
    """Generates a minimal valid JPEG image in memory for testing."""
    img = Image.new("RGB", (100, 100), color=(73, 109, 137))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def sample_base64_image(sample_image_bytes):
    return base64.b64encode(sample_image_bytes).decode("utf-8")


# --- Test Health Endpoints ---

def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "service" in data
    assert "gemini_model" in data


def test_api_v1_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


# --- Test Voice TTS Endpoints ---

def test_voice_tts_ru(client):
    response = client.get("/api/v1/voice/tts?text=Привет&lang=ru")
    assert response.status_code == 200
    assert "audio/mpeg" in response.headers.get("content-type", "")
    assert len(response.content) > 0


def test_voice_tts_et(client):
    response = client.get("/api/v1/voice/tts?text=Tere&lang=et")
    assert response.status_code == 200
    assert "audio/mpeg" in response.headers.get("content-type", "")
    assert len(response.content) > 0


def test_voice_tts_empty_text(client):
    response = client.get("/api/v1/voice/tts?text=&lang=ru")
    assert response.status_code in (400, 422)


# --- Test Models & Schemas ---

def test_age_tier_from_grade():
    assert AgeTier.from_grade(1) == AgeTier.PRIMARY
    assert AgeTier.from_grade(4) == AgeTier.PRIMARY
    assert AgeTier.from_grade(5) == AgeTier.MIDDLE
    assert AgeTier.from_grade(9) == AgeTier.MIDDLE
    assert AgeTier.from_grade(10) == AgeTier.GYMNASIUM
    assert AgeTier.from_grade(12) == AgeTier.GYMNASIUM

    with pytest.raises(ValueError):
        AgeTier.from_grade(0)
    with pytest.raises(ValueError):
        AgeTier.from_grade(13)


def test_user_profile_interests_normalization():
    p1 = UserProfile(grade=3, interests="Minecraft, LEGO, футбол")
    assert p1.interests == ["Minecraft", "LEGO", "футбол"]

    p2 = UserProfile(grade=5, interests=["Brawl Stars", "Roblox"])
    assert p2.interests == ["Brawl Stars", "Roblox"]

    p3 = UserProfile(grade=2, interests=None)
    assert p3.interests == []

    # Legacy support
    p4 = UserProfile.model_validate({"grade": 3, "theme_interest": "minecraft"})
    assert "minecraft" in p4.interests


def test_analyze_page_free_form_interests(client, sample_image_bytes):
    response = client.post(
        "/api/v1/analyze-page",
        files={"file": ("page.jpg", sample_image_bytes, "image/jpeg")},
        data={
            "grade": "3",
            "tier": "primary",
            "interests": "LEGO, роботы, космос",
            "nickname": "Тимур",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "task_title" in data
    assert "vocabulary" in data
    assert len(data["vocabulary"]) >= 2


def test_page_analysis_response_schema():
    payload = {
        "task_title": "Liitmine ja tehete komponendid",
        "theme_explanation": "Суть простыми словами через блоки Minecraft",
        "vocabulary": [
            {
                "est": "liidetav",
                "ru": "слагаемое",
                "example": "9 on esimene liidetav"
            },
            {
                "est": "summa",
                "ru": "сумма",
                "example": "Summa on 16"
            }
        ],
        "how_to_answer": "1. Сложи числа\n2. Запиши ответ",
        "answer_template": "Summa on ___",
        "voice_prompt_script": "Привет, Алекс! Давай решим этот пример!"
    }
    model = PageAnalysisResponse.model_validate(payload)
    assert model.task_title == "Liitmine ja tehete komponendid"
    assert len(model.vocabulary) == 2
    assert model.vocabulary[0].est == "liidetav"


# --- Test /api/v1/analyze-page (Multipart) ---

def test_analyze_page_primary_minecraft(client, sample_image_bytes):
    response = client.post(
        "/api/v1/analyze-page",
        files={"file": ("page.jpg", sample_image_bytes, "image/jpeg")},
        data={
            "grade": "3",
            "tier": "primary",
            "theme_interest": "minecraft",
            "nickname": "Алекс",
        },
    )
    assert response.status_code == 200
    data = response.json()

    # Validate strict response schema fields
    assert "task_title" in data
    assert "theme_explanation" in data
    assert "vocabulary" in data
    assert "how_to_answer" in data
    assert "answer_template" in data
    assert "voice_prompt_script" in data

    # Content checks
    assert len(data["vocabulary"]) >= 2
    assert any("liidetav" in v["est"].lower() for v in data["vocabulary"])
    assert "Minecraft" in data["theme_explanation"] or "minecraft" in data["theme_explanation"].lower()
    assert "___" in data["answer_template"]


def test_analyze_page_middle_tier(client, sample_image_bytes):
    response = client.post(
        "/api/v1/analyze-page",
        files={"file": ("page.jpg", sample_image_bytes, "image/jpeg")},
        data={
            "grade": "7",
            "theme_interest": "roblox",
            "nickname": "Даниил",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "fotosüntees" in data["task_title"].lower() or len(data["vocabulary"]) > 0
    assert "Даниил" in data["theme_explanation"]


def test_analyze_page_gymnasium_tier(client, sample_image_bytes):
    response = client.post(
        "/api/v1/analyze-page",
        files={"file": ("page.png", sample_image_bytes, "image/png")},
        data={
            "grade": "11",
            "theme_interest": "tech",
            "nickname": "София",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["vocabulary"]) >= 2
    assert "___" in data["answer_template"]


def test_analyze_page_invalid_mime_type(client):
    response = client.post(
        "/api/v1/analyze-page",
        files={"file": ("notes.txt", b"some text", "text/plain")},
        data={"grade": "3"},
    )
    assert response.status_code == 400
    assert "Неподдерживаемый формат" in response.json()["detail"]


def test_analyze_page_invalid_grade(client, sample_image_bytes):
    response = client.post(
        "/api/v1/analyze-page",
        files={"file": ("page.jpg", sample_image_bytes, "image/jpeg")},
        data={"grade": "99"},
    )
    assert response.status_code == 422


# --- Test /api/v1/analyze-page/json ---

def test_analyze_page_json_success(client, sample_base64_image):
    payload = {
        "image_base64": sample_base64_image,
        "mime_type": "image/jpeg",
        "grade": 4,
        "theme_interest": "sports",
        "nickname": "Марк",
    }
    response = client.post("/api/v1/analyze-page/json", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "task_title" in data
    assert "Марк" in data["theme_explanation"] or "Марк" in data["voice_prompt_script"]


def test_analyze_page_json_invalid_base64(client):
    payload = {
        "image_base64": "not-valid-base64-content!@#$%",
        "mime_type": "image/jpeg",
        "grade": 3,
    }
    response = client.post("/api/v1/analyze-page/json", json=payload)
    # Could be 400 or handled gracefully
    assert response.status_code in [400, 422]


# --- Test Gemini Tutor Service parsing ---

def test_gemini_service_json_parsing():
    service = GeminiTutorService(api_key="mock")
    markdown_wrapped_json = """```json
    {
      "task_title": "Pindala ja ümbermõõt",
      "theme_explanation": "Площадь как чанки в Minecraft",
      "vocabulary": [
        {
          "est": "pindala",
          "ru": "площадь",
          "example": "Ristküliku pindala on 24 cm²"
        }
      ],
      "how_to_answer": "Умножь длину на ширину",
      "answer_template": "Pindala on ___ cm²",
      "voice_prompt_script": "Давай посчитаем площадь!"
    }
    ```"""
    parsed = service._parse_json_response(markdown_wrapped_json)
    assert parsed.task_title == "Pindala ja ümbermõõt"
    assert parsed.vocabulary[0].est == "pindala"
