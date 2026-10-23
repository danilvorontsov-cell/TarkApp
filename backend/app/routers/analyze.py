import base64
import logging
from typing import Optional, Union, List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.config import settings
from app.models.page_analysis import (
    AgeTier,
    AnalyzePageJsonRequest,
    PageAnalysisResponse,
    UserProfile,
)
from app.services.gemini_service import gemini_tutor_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Analysis"])

ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/jpg",
}


@router.post(
    "/analyze-page",
    response_model=PageAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Анализ страницы эстонского учебника и адаптация под ученика",
    description=(
        "Принимает фотографию страницы учебника/тетради (Opiq, Koolibri, Avita) "
        "и параметры профиля ребенка (класс, звено, увлечения). "
        "Возвращает структурированный разбор на русском языке с эстонским словарем и каркасом ответа."
    ),
)
async def analyze_page(
    file: UploadFile = File(..., description="Файл изображения страницы (JPEG/PNG)"),
    grade: int = Form(default=3, ge=1, le=12, description="Класс от 1 до 12"),
    tier: Optional[AgeTier] = Form(default=None, description="Возрастное звено (primary, middle, gymnasium)"),
    interests: Optional[str] = Form(
        default=None,
        description="Любимые темы и увлечения ученика через запятую (напр. 'Minecraft, LEGO, футбол')"
    ),
    theme_interest: Optional[str] = Form(
        default=None,
        description="Для обратной совместимости со старыми клиентами (одиночная тема)"
    ),
    nickname: Optional[str] = Form(default="Друг", description="Имя ученика для персонализации"),
) -> PageAnalysisResponse:
    # Validate MIME type
    content_type = file.content_type or "image/jpeg"
    if content_type.lower() not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Неподдерживаемый формат изображения: {content_type}. Поддерживаются: {', '.join(ALLOWED_MIME_TYPES)}",
        )

    # Read image contents
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Файл изображения пуст.",
        )

    max_size_bytes = settings.MAX_IMAGE_SIZE_MB * 1024 * 1024
    if len(image_bytes) > max_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Размер файла превышает лимит {settings.MAX_IMAGE_SIZE_MB} МБ.",
        )

    # Auto-resolve tier if not explicitly passed
    resolved_tier = tier or AgeTier.from_grade(grade)

    raw_interests = interests or theme_interest or ""
    profile = UserProfile(
        grade=grade,
        tier=resolved_tier,
        interests=raw_interests,
        nickname=nickname or "Друг",
    )

    try:
        return await gemini_tutor_service.analyze_page(
            image_bytes=image_bytes,
            mime_type=content_type,
            profile=profile,
        )
    except Exception as e:
        logger.error(f"Error analyzing page: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка обработки страницы: {str(e)}",
        )


@router.post(
    "/analyze-page/json",
    response_model=PageAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Анализ страницы через Base64 JSON payload",
    description="Альтернативный эндпоинт для клиентов, передающих base64 строку вместо multipart/form-data.",
)
async def analyze_page_json(request: AnalyzePageJsonRequest) -> PageAnalysisResponse:
    try:
        image_bytes = base64.b64decode(request.image_base64)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Некорректная Base64 строка: {e}",
        )

    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Декодированное изображение пусто.",
        )

    resolved_tier = request.tier or AgeTier.from_grade(request.grade)
    raw_interests = request.interests or request.theme_interest or []
    profile = UserProfile(
        grade=request.grade,
        tier=resolved_tier,
        interests=raw_interests,
        nickname=request.nickname or "Друг",
    )

    try:
        return await gemini_tutor_service.analyze_page(
            image_bytes=image_bytes,
            mime_type=request.mime_type,
            profile=profile,
        )
    except Exception as e:
        logger.error(f"Error analyzing page via JSON: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка обработки страницы: {str(e)}",
        )
