import base64
import logging
from fastapi import APIRouter, Depends, HTTPException, status

from app.models.translate import QuickTranslateRequest, QuickTranslateResponse
from app.services.gemini_service import gemini_tutor_service
from app.routers.license import verify_device_access

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/translate",
    tags=["Translate"],
    dependencies=[Depends(verify_device_access)],
)


@router.post(
    "/quick",
    response_model=QuickTranslateResponse,
    status_code=status.HTTP_200_OK,
    summary="Быстрый школьный переводчик (текст или фото фрагмента)",
    description=(
        "Моментально переводит школьный термин, фразу или абзац между эстонским и русским языками. "
        "Адаптирован под учебную терминологию Эстонии (математика, природоведение, история). "
        "Для отдельных эстонских слов возвращает 3 основные словарные формы (algvormid)."
    ),
)
async def quick_translate(request: QuickTranslateRequest) -> QuickTranslateResponse:
    clean_text = (request.text or "").strip()
    image_bytes = None

    if request.image_base64:
        try:
            b64_clean = request.image_base64
            if "," in b64_clean:
                b64_clean = b64_clean.split(",", 1)[1]
            image_bytes = base64.b64decode(b64_clean)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Некорректная Base64 строка изображения: {e}",
            )

    if not clean_text and not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Необходимо передать либо текст ('text'), либо изображение ('image_base64').",
        )

    try:
        result = await gemini_tutor_service.quick_translate(
            text=clean_text or None,
            image_bytes=image_bytes,
            mime_type=request.mime_type or "image/jpeg",
            source_lang=request.source_lang or "auto",
            target_lang=request.target_lang or "ru",
        )
        return result
    except Exception as e:
        logger.error(f"Error in quick_translate: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка перевода: {str(e)}",
        )
