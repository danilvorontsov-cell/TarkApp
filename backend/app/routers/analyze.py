import base64
import logging
from typing import Optional, Union, List, Tuple

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.limiter import safe_limit, get_device_or_ip
from app.models.page_analysis import (
    AgeTier,
    AnalyzePageJsonRequest,
    MoreExamplesRequest,
    MoreExamplesResponse,
    PageAnalysisResponse,
    UserProfile,
)
from app.services.gemini_service import gemini_tutor_service
from app.services import license_service
from app.services.analysis_cache import (
    compute_analysis_cache_key,
    get_cached_analysis,
    store_cached_analysis,
)
from app.routers.license import verify_device_access, verify_review_access

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1",
    tags=["Analysis"],
)

ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/jpg",
}


def _extract_device_id(raw_val: object) -> str:
    if isinstance(raw_val, str):
        return raw_val.strip()
    return ""


@router.post(
    "/analyze-page",
    response_model=PageAnalysisResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_review_access)],
    summary="Анализ страницы эстонского учебника и адаптация под ученика",
    description=(
        "Принимает одну или несколько фотографий страниц учебника/тетради (Opiq, Koolibri, Avita) "
        "и параметры профиля ребенка (класс, звено, увлечения). "
        "Возвращает структурированный разбор на русском языке с эстонским словарем и каркасом ответа."
    ),
)
@safe_limit("10/minute", key_func=get_device_or_ip)
async def analyze_page(
    request: Request,
    files: Optional[List[UploadFile]] = File(default=None, description="Список файлов страниц (JPEG/PNG)"),
    file: Optional[UploadFile] = File(default=None, description="Одиночный файл изображения (для обратной совместимости)"),
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
    x_device_id: Optional[str] = Header(None, alias="X-Device-ID"),
    db: Session = Depends(get_db),
) -> PageAnalysisResponse:
    target_files: List[UploadFile] = []
    if files:
        target_files.extend(files)
    if file:
        target_files.append(file)

    if not target_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не передано ни одного файла изображения.",
        )

    max_size_bytes = settings.MAX_IMAGE_SIZE_MB * 1024 * 1024
    images_data: List[Tuple[bytes, str]] = []

    for f in target_files:
        content_type = f.content_type or "image/jpeg"
        if content_type.lower() not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Неподдерживаемый формат изображения: {content_type}. Поддерживаются: {', '.join(ALLOWED_MIME_TYPES)}",
            )
        data = await f.read()
        if not data:
            continue
        if len(data) > max_size_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Размер файла '{f.filename}' превышает лимит {settings.MAX_IMAGE_SIZE_MB} МБ.",
            )
        images_data.append((data, content_type))

    if not images_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Файл изображения пуст.",
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

    dev_id = _extract_device_id(x_device_id) or ("dev-test-device" if settings.APP_ENV in ("development", "test") else "")

    # Check cache for identical image content and pedagogical profile
    cache_key = compute_analysis_cache_key([b for b, _ in images_data], profile)
    cached_result = get_cached_analysis(cache_key)
    if cached_result and cached_result.is_acceptable is not False:
        if dev_id and isinstance(db, Session):
            license_service.deduct_review_attempt(dev_id, db)
        return cached_result

    try:
        result = await gemini_tutor_service.analyze_page(
            profile=profile,
            images=images_data,
        )
        # Store in cache and deduct 1 review attempt ONLY if the image was acceptable (not an emergency fallback)
        if result.is_acceptable is not False:
            store_cached_analysis(cache_key, result)
            if dev_id and isinstance(db, Session):
                license_service.deduct_review_attempt(dev_id, db)
        return result
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
    dependencies=[Depends(verify_review_access)],
    summary="Анализ страницы через Base64 JSON payload",
    description="Альтернативный эндпоинт для клиентов, передающих base64 строку вместо multipart/form-data. Поддерживает одиночные и множественные страницы.",
)
@safe_limit("10/minute", key_func=get_device_or_ip)
async def analyze_page_json(
    payload: AnalyzePageJsonRequest,
    request: Request = None,
    x_device_id: Optional[str] = Header(None, alias="X-Device-ID"),
    db: Session = Depends(get_db),
) -> PageAnalysisResponse:
    max_size_bytes = settings.MAX_IMAGE_SIZE_MB * 1024 * 1024
    images_data: List[Tuple[bytes, str]] = []

    # 1. Проверяем список изображений
    if payload.images_base64 and len(payload.images_base64) > 0:
        for idx, b64_str in enumerate(payload.images_base64):
            try:
                clean_b64 = b64_str.split(",", 1)[1] if "," in b64_str else b64_str
                ib = base64.b64decode(clean_b64, validate=True)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Некорректная Base64 строка в изображении #{idx + 1}: {e}",
                )
            if ib:
                if len(ib) > max_size_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Размер изображения #{idx + 1} превышает лимит {settings.MAX_IMAGE_SIZE_MB} МБ.",
                    )
                mtype = "image/jpeg"
                if payload.mime_types and idx < len(payload.mime_types):
                    mtype = payload.mime_types[idx]
                elif payload.mime_type:
                    mtype = payload.mime_type
                images_data.append((ib, mtype))

    # 2. Фолбэк на одиночное изображение (для обратной совместимости)
    elif payload.image_base64:
        try:
            clean_b64 = (
                payload.image_base64.split(",", 1)[1]
                if "," in payload.image_base64
                else payload.image_base64
            )
            image_bytes = base64.b64decode(clean_b64, validate=True)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Некорректная Base64 строка: {e}",
            )
        if image_bytes:
            if len(image_bytes) > max_size_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Размер изображения превышает лимит {settings.MAX_IMAGE_SIZE_MB} МБ.",
                )
            images_data.append((image_bytes, payload.mime_type or "image/jpeg"))

    if not images_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не передано ни одного корректного изображения для анализа.",
        )

    resolved_tier = payload.tier or AgeTier.from_grade(payload.grade)
    raw_interests = payload.interests or payload.theme_interest or []
    profile = UserProfile(
        grade=payload.grade,
        tier=resolved_tier,
        interests=raw_interests,
        nickname=payload.nickname or "Друг",
    )

    dev_id = _extract_device_id(x_device_id) or ("dev-test-device" if settings.APP_ENV in ("development", "test") else "")

    # Check cache for identical image content and pedagogical profile
    cache_key = compute_analysis_cache_key([b for b, _ in images_data], profile)
    cached_result = get_cached_analysis(cache_key)
    if cached_result and cached_result.is_acceptable is not False:
        if dev_id and isinstance(db, Session):
            license_service.deduct_review_attempt(dev_id, db)
        return cached_result

    try:
        result = await gemini_tutor_service.analyze_page(
            profile=profile,
            images=images_data,
        )
        # Store in cache and deduct 1 review attempt ONLY if the image was acceptable
        if result.is_acceptable is not False:
            store_cached_analysis(cache_key, result)
            if dev_id and isinstance(db, Session):
                license_service.deduct_review_attempt(dev_id, db)
        return result
    except Exception as e:
        logger.error(f"Error analyzing page via JSON: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка обработки страницы: {str(e)}",
        )


@router.post(
    "/more-examples",
    response_model=MoreExamplesResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_device_access)],
    summary="Генерация дополнительных эстонских речевых примеров для тренировки",
    description="Создает новые эстонские примеры предложений с пропусками для интерактивного конструктора ответа.",
)
@safe_limit("15/minute", key_func=get_device_or_ip)
async def get_more_examples(
    payload: MoreExamplesRequest,
    request: Request = None,
) -> MoreExamplesResponse:
    try:
        templates = await gemini_tutor_service.generate_more_examples(
            task_title=payload.task_title,
            theme_explanation=payload.theme_explanation or "",
            vocabulary=payload.vocabulary,
            current_template=payload.current_template,
            grade=payload.grade,
            tier=payload.tier,
        )
        return MoreExamplesResponse(templates=templates)
    except Exception as e:
        logger.error(f"Error generating more examples: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка генерации дополнительных примеров: {str(e)}",
        )

