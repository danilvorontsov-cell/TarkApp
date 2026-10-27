import base64
import pytest
from app.models.page_analysis import AnalyzePageJsonRequest, UserProfile, AgeTier
from app.services.gemini_service import gemini_tutor_service
from app.routers.analyze import analyze_page_json

@pytest.fixture(autouse=True)
def mock_gemini():
    orig_client = gemini_tutor_service._client
    orig_key = gemini_tutor_service.api_key
    gemini_tutor_service._client = None
    gemini_tutor_service.api_key = "mock"
    yield
    gemini_tutor_service._client = orig_client
    gemini_tutor_service.api_key = orig_key

@pytest.mark.anyio
async def test_multi_image_json_request():
    dummy_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    
    req = AnalyzePageJsonRequest(
        images_base64=[dummy_b64, dummy_b64],
        mime_types=["image/png", "image/png"],
        grade=11,
        tier=AgeTier.GYMNASIUM,
        nickname="Данил",
        interests=["IT", "технологии"],
    )
    
    res = await analyze_page_json(req)
    assert res is not None
    assert res.task_title is not None
    assert len(res.vocabulary) > 0
    print("\nMulti-image analysis test passed: task_title =", res.task_title)
