import pytest
from app.models.translate import QuickTranslateRequest
from app.routers.translate import quick_translate
from app.services.gemini_service import gemini_tutor_service


@pytest.fixture
def anyio_backend():
    return 'asyncio'


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
async def test_quick_translate_estonian_phrase():
    req = QuickTranslateRequest(text="Liitmine ja lahutamine", source_lang="et", target_lang="ru")
    res = await quick_translate(req)
    assert res.original_text == "Liitmine ja lahutamine"
    assert "Сложение и вычитание" in res.translated_text
    assert "liitmine" in res.base_forms
    assert res.context_note is not None


@pytest.mark.anyio
async def test_quick_translate_single_word_algvormid():
    req = QuickTranslateRequest(text="kolmnurk", source_lang="et", target_lang="ru")
    res = await quick_translate(req)
    assert "Треугольник" in res.translated_text
    assert "kolmnurk, kolmnurga, kolmnurka" in res.base_forms
    assert "Геометрия" in res.context_note


@pytest.mark.anyio
async def test_quick_translate_russian_to_estonian():
    req = QuickTranslateRequest(text="сложение", source_lang="ru", target_lang="et")
    res = await quick_translate(req)
    assert "Liitmine" in res.translated_text
    assert "liitmine, liitmise, liitmist" in res.base_forms


@pytest.mark.anyio
async def test_quick_translate_empty_payload():
    from fastapi import HTTPException
    req = QuickTranslateRequest(text="", image_base64="")
    with pytest.raises(HTTPException) as exc_info:
        await quick_translate(req)
    assert exc_info.value.status_code == 400


@pytest.mark.anyio
async def test_quick_translate_invalid_base64():
    from fastapi import HTTPException
    req = QuickTranslateRequest(image_base64="!!!not_valid_b64!!!")
    with pytest.raises(HTTPException) as exc_info:
        await quick_translate(req)
    assert exc_info.value.status_code == 400

