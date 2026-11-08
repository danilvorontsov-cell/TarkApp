import asyncio
import base64
import html
import logging
from typing import Optional, Union, List, Tuple

import anyio.to_thread
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.limiter import safe_limit, get_device_or_ip, get_remote_address
from app.models.page_analysis import (
    AgeTier,
    AnalyzePageJsonRequest,
    AppendPageJsonRequest,
    MoreExamplesRequest,
    MoreExamplesResponse,
    PageAnalysisResponse,
    UserProfile,
)
from app.services.gemini_service import gemini_tutor_service, GeminiServiceError
from app.services.telegram_alert import send_telegram_message
from app.services import license_service
from app.services.lesson_session_service import lesson_session_service
from app.services.analysis_cache import (
    compute_analysis_cache_key,
    get_cached_analysis,
    store_cached_analysis,
)
from app.routers.license import verify_device_access, verify_review_access
from app.auth import get_current_user, CurrentUser

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

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB per image
MAX_REQUEST_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB per request
MAX_B64_CHARS_PER_IMAGE = int(MAX_FILE_SIZE_BYTES * 4 / 3) + 1024  # ~13.3 MB base64 chars


def _check_content_length(request: Optional[Request], max_bytes: int = MAX_REQUEST_SIZE_BYTES) -> None:
    """Pre-check request Content-Length header BEFORE reading request stream into memory."""
    if not request:
        return
    cl = request.headers.get("content-length")
    if cl and cl.isdigit():
        if int(cl) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Размер запроса ({int(cl)} байт) превышает допустимый лимит {max_bytes // (1024 * 1024)} МБ.",
            )


async def _read_upload_file_bounded(f: UploadFile, max_bytes: int = MAX_FILE_SIZE_BYTES) -> bytes:
    """Reads UploadFile in chunks with hard byte limit to prevent RAM DoS before buffer allocation."""
    if hasattr(f, "size") and f.size is not None and f.size > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Размер файла '{f.filename}' ({f.size} байт) превышает лимит {max_bytes // (1024 * 1024)} МБ.",
        )
    chunks = []
    total = 0
    chunk_size = 64 * 1024
    while True:
        chunk = await f.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Размер файла '{f.filename}' превышает допустимый лимит {max_bytes // (1024 * 1024)} МБ.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _decode_b64_bounded(b64_str: str, max_bytes: int = MAX_FILE_SIZE_BYTES, label: str = "изображения") -> bytes:
    """Validates base64 string length BEFORE b64decode to prevent RAM allocation attacks."""
    if not b64_str:
        return b""
    clean_b64 = b64_str.split(",", 1)[1] if "," in b64_str else b64_str
    if len(clean_b64) > MAX_B64_CHARS_PER_IMAGE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Размер {label} превышает лимит {max_bytes // (1024 * 1024)} МБ.",
        )
    try:
        data = base64.b64decode(clean_b64, validate=True)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Некорректная Base64 строка в данных {label}: {e}",
        )
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Размер {label} ({len(data)} байт) превышает лимит {max_bytes // (1024 * 1024)} МБ.",
        )
    return data


def _extract_device_id(raw_val: object) -> str:
    if isinstance(raw_val, str):
        return raw_val.strip()
    return ""


async def _dispatch_gemini_alert(e: GeminiServiceError, endpoint: str) -> None:
    """Dispatches high-priority Telegram alert when Gemini API fails."""
    if settings.TELEGRAM_BOT_TOKEN and settings.telegram_chat_id:
        try:
            alert_text = (
                f"🚨 <b>Сбой нейросети Gemini AI!</b>\n"
                f"📍 Эндпоинт: <code>{endpoint}</code>\n"
                f"⚠️ Тип: <b>{'ИСТОЩЕНИЕ КРЕДИТОВ / БАЛАНСА (402 RESOURCE_EXHAUSTED)' if e.is_quota_error else 'Ошибка сервиса AI'}</b>\n"
                f"💬 Ошибка: <code>{html.escape(str(e))[:300]}</code>\n\n"
                f"💡 <b>Действие:</b>\n"
                + (
                    "Пополните баланс на <a href='https://ai.studio/projects'>ai.studio/projects</a> или обновите <code>GEMINI_API_KEY</code> в <code>backend/.env</code>."
                    if e.is_quota_error
                    else "Проверьте логи бэкенда и статус Google AI."
                )
            )
            asyncio.create_task(
                send_telegram_message(
                    text=alert_text,
                    parse_mode="HTML",
                    message_thread_id=settings.TELEGRAM_TOPIC_ALERTS,
                )
            )
        except Exception as tel_err:
            logger.warning(f"Could not dispatch telegram alert for Gemini error: {tel_err}")


@router.post(
    "/analyze-page",
    response_model=PageAnalysisResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_review_access), Depends(get_current_user)],
    summary="Анализ страницы эстонского учебника и адаптация под ученика",
    description=(
        "Принимает одну или несколько фотографий страниц учебника/тетради (Opiq, Koolibri, Avita) "
        "и параметры профиля ребенка (класс, звено, увлечения). "
        "Возвращает структурированный разбор на русском языке с эстонским словарем и каркасом ответа."
    ),
)
@safe_limit("10/minute", key_func=get_device_or_ip)
@safe_limit("20/minute", key_func=get_remote_address)
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
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PageAnalysisResponse:
    _check_content_length(request, MAX_REQUEST_SIZE_BYTES)

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

    if len(target_files) > 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="В сессию разворота разрешено загружать максимум 2 страницы (max 2 страницы).",
        )

    total_request_bytes = 0
    images_data: List[Tuple[bytes, str]] = []

    for f in target_files:
        content_type = f.content_type or "image/jpeg"
        if content_type.lower() not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Неподдерживаемый формат изображения: {content_type}. Поддерживаются: {', '.join(ALLOWED_MIME_TYPES)}",
            )
        data = await _read_upload_file_bounded(f, MAX_FILE_SIZE_BYTES)
        if not data:
            continue
        total_request_bytes += len(data)
        if total_request_bytes > MAX_REQUEST_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Суммарный размер файлов превышает лимит {MAX_REQUEST_SIZE_BYTES // (1024 * 1024)} МБ.",
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
        nickname=((nickname if nickname and nickname != "Друг" else (current_user.nickname or "Друг")).strip() or "Друг")[:50],
    )

    dev_id = _extract_device_id(x_device_id) or ("dev-test-device-0001" if settings.APP_ENV in ("development", "test") else "")

    # Check cache for identical image content and pedagogical profile
    cache_key = compute_analysis_cache_key([b for b, _ in images_data], profile)
    cached_result = get_cached_analysis(cache_key)
    if cached_result and cached_result.is_acceptable is not False:
        if dev_id and isinstance(db, Session):
            await anyio.to_thread.run_sync(license_service.deduct_review_attempt, dev_id, db)
        session = lesson_session_service.create_session(
            device_id=dev_id,
            profile=profile,
            images=images_data,
            analysis=cached_result,
        )
        cached_result.lesson_id = session.lesson_id
        cached_result.page_count = session.page_count
        cached_result.can_append_page = session.can_append
        cached_result.session_expires_at = session.expires_at
        cached_result.session_seconds_remaining = session.seconds_remaining
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
                await anyio.to_thread.run_sync(license_service.deduct_review_attempt, dev_id, db)
        session = lesson_session_service.create_session(
            device_id=dev_id,
            profile=profile,
            images=images_data,
            analysis=result,
        )
        result.lesson_id = session.lesson_id
        result.page_count = session.page_count
        result.can_append_page = session.can_append
        result.session_expires_at = session.expires_at
        result.session_seconds_remaining = session.seconds_remaining
        return result
    except GeminiServiceError as e:
        logger.error(f"GeminiServiceError analyzing page: {e}")
        await _dispatch_gemini_alert(e, "POST /api/v1/analyze-page")
        raise HTTPException(
            status_code=e.status_code,
            detail=(
                "Сервис AI-разбора временно недоступен: исчерпан баланс токенов нейросети (Google AI Studio). Администратор уже оповещён."
                if e.is_quota_error
                else f"Сервис AI-разбора временно недоступен: {str(e)}"
            ),
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
    dependencies=[Depends(verify_review_access), Depends(get_current_user)],
    summary="Анализ страницы через Base64 JSON payload",
    description="Альтернативный эндпоинт для клиентов, передающих base64 строку вместо multipart/form-data. Поддерживает одиночные и множественные страницы.",
)
@safe_limit("10/minute", key_func=get_device_or_ip)
@safe_limit("20/minute", key_func=get_remote_address)
async def analyze_page_json(
    payload: AnalyzePageJsonRequest,
    request: Request = None,
    x_device_id: Optional[str] = Header(None, alias="X-Device-ID"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PageAnalysisResponse:
    _check_content_length(request, MAX_REQUEST_SIZE_BYTES)
    images_data: List[Tuple[bytes, str]] = []
    total_request_bytes = 0

    # 1. Проверяем список изображений
    if payload.images_base64 and len(payload.images_base64) > 0:
        if len(payload.images_base64) > 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="В сессию разворота разрешено передавать максимум 2 страницы.",
            )
        for idx, b64_str in enumerate(payload.images_base64):
            ib = _decode_b64_bounded(b64_str, MAX_FILE_SIZE_BYTES, f"изображения #{idx + 1}")
            if ib:
                total_request_bytes += len(ib)
                if total_request_bytes > MAX_REQUEST_SIZE_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Суммарный размер изображений превышает лимит {MAX_REQUEST_SIZE_BYTES // (1024 * 1024)} МБ.",
                    )
                mtype = "image/jpeg"
                if payload.mime_types and idx < len(payload.mime_types):
                    mtype = payload.mime_types[idx]
                elif payload.mime_type:
                    mtype = payload.mime_type
                images_data.append((ib, mtype))

    # 2. Фолбэк на одиночное изображение (для обратной совместимости)
    elif payload.image_base64:
        image_bytes = _decode_b64_bounded(payload.image_base64, MAX_FILE_SIZE_BYTES, "изображения")
        if image_bytes:
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
        nickname=((payload.nickname if payload.nickname and payload.nickname != "Друг" else (current_user.nickname or "Друг")).strip() or "Друг")[:50],
    )

    dev_id = _extract_device_id(x_device_id) or ("dev-test-device-0001" if settings.APP_ENV in ("development", "test") else "")

    # Проверяем, передана ли активная сессия урока для добавления разворота
    active_session = None
    if payload.lesson_id:
        active_session = lesson_session_service.get_session(payload.lesson_id)
        if not active_session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "SESSION_NOT_FOUND", "message": "Сессия урока не найдена или завершена."},
            )
        if active_session.is_expired:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail={"error": "SESSION_EXPIRED", "message": "Время бесплатного дополнения урока (10 минут) истекло. Пожалуйста, начните новый урок."},
            )
        if not active_session.can_append:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "PAGE_LIMIT_REACHED", "message": "В сессию урока уже добавлено максимальное количество страниц (2 страницы) или истекло окно добавления."},
            )
        if not dev_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "DEVICE_REQUIRED", "message": "Заголовок X-Device-ID обязателен для работы с сессией."},
            )
        if active_session.device_id and active_session.device_id != dev_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "DEVICE_MISMATCH", "message": "Сессия урока принадлежит другому устройству."},
            )

    is_session_append = active_session is not None

    # Check cache for identical image content and pedagogical profile (only for new lessons)
    cache_key = compute_analysis_cache_key([b for b, _ in images_data], profile)
    if not is_session_append:
        cached_result = get_cached_analysis(cache_key)
        if cached_result and cached_result.is_acceptable is not False:
            if dev_id and isinstance(db, Session):
                await anyio.to_thread.run_sync(license_service.deduct_review_attempt, dev_id, db)
            session = lesson_session_service.create_session(
                device_id=dev_id,
                profile=profile,
                images=images_data,
                analysis=cached_result,
            )
            cached_result.lesson_id = session.lesson_id
            cached_result.page_count = session.page_count
            cached_result.can_append_page = session.can_append
            cached_result.session_expires_at = session.expires_at
            cached_result.session_seconds_remaining = session.seconds_remaining
            return cached_result

    try:
        result = await gemini_tutor_service.analyze_page(
            profile=profile,
            images=images_data,
        )

        if is_session_append and active_session:
            # Для существующей сессии очки баланса НЕ списываются
            active_session.page_count = len(images_data)
            lesson_session_service.update_analysis(active_session.lesson_id, result)
            result.lesson_id = active_session.lesson_id
            result.page_count = len(images_data)
            result.can_append_page = False
            result.session_expires_at = active_session.expires_at
            result.session_seconds_remaining = active_session.seconds_remaining
            return result

        # Новая сессия: сохраняем в кэш и списываем ровно 1 очко
        if result.is_acceptable is not False:
            store_cached_analysis(cache_key, result)
            if dev_id and isinstance(db, Session):
                await anyio.to_thread.run_sync(license_service.deduct_review_attempt, dev_id, db)
        session = lesson_session_service.create_session(
            device_id=dev_id,
            profile=profile,
            images=images_data,
            analysis=result,
        )
        result.lesson_id = session.lesson_id
        result.page_count = session.page_count
        result.can_append_page = session.can_append
        result.session_expires_at = session.expires_at
        result.session_seconds_remaining = session.seconds_remaining
        return result
    except GeminiServiceError as e:
        logger.error(f"GeminiServiceError analyzing page via JSON: {e}")
        await _dispatch_gemini_alert(e, "POST /api/v1/analyze-page/json")
        raise HTTPException(
            status_code=e.status_code,
            detail=(
                "Сервис AI-разбора временно недоступен: исчерпан баланс токенов нейросети (Google AI Studio). Администратор уже оповещён."
                if e.is_quota_error
                else f"Сервис AI-разбора временно недоступен: {str(e)}"
            ),
        )
    except Exception as e:
        logger.error(f"Error analyzing page via JSON: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка обработки страницы: {str(e)}",
        )


@router.post(
    "/lessons/{lesson_id}/append-page",
    response_model=PageAnalysisResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(get_current_user)],
    summary="Добавление второй страницы (разворота) в активную сессию урока",
    description="Добавляет страницу 2 к уроку в течение 10 минут. Повторно очки сканирований не списываются.",
)
@safe_limit("10/minute", key_func=get_device_or_ip)
@safe_limit("20/minute", key_func=get_remote_address)
async def append_page_to_lesson(
    lesson_id: str,
    request: Request,
    payload: Optional[AppendPageJsonRequest] = None,
    x_device_id: Optional[str] = Header(None, alias="X-Device-ID"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PageAnalysisResponse:
    _check_content_length(request, MAX_REQUEST_SIZE_BYTES)
    dev_id = _extract_device_id(x_device_id) or ("dev-test-device-0001" if settings.APP_ENV in ("development", "test") else "")
    if not dev_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "DEVICE_REQUIRED", "message": "Заголовок X-Device-ID обязателен для работы с сессией."},
        )

    session = lesson_session_service.get_session(lesson_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "SESSION_NOT_FOUND", "message": "Сессия урока не найдена или завершена."},
        )

    if session.device_id and session.device_id != dev_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "DEVICE_MISMATCH", "message": "Сессия урока принадлежит другому устройству."},
        )

    if session.is_expired:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"error": "SESSION_EXPIRED", "message": "Время бесплатного дополнения урока (10 минут) истекло. Пожалуйста, начните новый урок."},
        )

    if not session.can_append or session.page_count >= 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "PAGE_LIMIT_REACHED", "message": "В сессию урока можно добавить максимум 2 страницы (разворот)."},
        )

    image_bytes = None
    mime_type = "image/jpeg"
    content_type = (request.headers.get("content-type") or "").lower()

    if "multipart/form-data" in content_type:
        form = await request.form()
        uploaded = form.get("file")
        if uploaded and hasattr(uploaded, "read"):
            mime_type = uploaded.content_type or "image/jpeg"
            if mime_type.lower() not in ALLOWED_MIME_TYPES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Неподдерживаемый формат изображения: {mime_type}.",
                )
            image_bytes = await _read_upload_file_bounded(uploaded, MAX_FILE_SIZE_BYTES)
    else:
        # JSON payload handling
        clean_b64 = None
        if payload and payload.image_base64:
            clean_b64 = payload.image_base64
            mime_type = payload.mime_type or "image/jpeg"
        else:
            try:
                body_json = await request.json()
                clean_b64 = body_json.get("image_base64")
                if "mime_type" in body_json:
                    mime_type = body_json["mime_type"]
            except Exception:
                pass

        if clean_b64:
            image_bytes = _decode_b64_bounded(clean_b64, MAX_FILE_SIZE_BYTES, "второй страницы")

    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не передано изображение второй страницы для добавления.",
        )

    # 1. Прикрепляем вторую страницу к сессии урока
    lesson_session_service.append_image(lesson_id, image_bytes, mime_type)

    # 2. Вызываем мультимодальный анализ Gemini для объединения контекста обеих страниц
    try:
        updated_result = await gemini_tutor_service.analyze_page(
            profile=session.profile,
            images=session.images,
        )
        updated_result.lesson_id = session.lesson_id
        updated_result.page_count = session.page_count
        updated_result.can_append_page = False
        updated_result.session_expires_at = session.expires_at
        updated_result.session_seconds_remaining = 0
        lesson_session_service.update_analysis(lesson_id, updated_result)
        # ВАЖНО: лицензия/квота НЕ списывается повторно! (1 очко за сессию)
        return updated_result
    except GeminiServiceError as e:
        logger.error(f"GeminiServiceError appending page to lesson {lesson_id}: {e}")
        await _dispatch_gemini_alert(e, f"POST /api/v1/lessons/{lesson_id}/append-page")
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except Exception as e:
        logger.error(f"Error appending page to lesson {lesson_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка обработки второй страницы урока: {str(e)}",
        )


legacy_lessons_router = APIRouter(
    prefix="/api/lessons",
    tags=["Analysis"],
)


@legacy_lessons_router.post(
    "/{lesson_id}/append-page",
    response_model=PageAnalysisResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(get_current_user)],
    summary="Алиас для добавления второй страницы (разворота) в активную сессию урока",
)
@safe_limit("10/minute", key_func=get_device_or_ip)
@safe_limit("20/minute", key_func=get_remote_address)
async def append_page_legacy_alias(
    lesson_id: str,
    request: Request,
    payload: Optional[AppendPageJsonRequest] = None,
    x_device_id: Optional[str] = Header(None, alias="X-Device-ID"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PageAnalysisResponse:
    return await append_page_to_lesson(
        lesson_id=lesson_id,
        request=request,
        payload=payload,
        x_device_id=x_device_id,
        current_user=current_user,
        db=db,
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
@safe_limit("30/minute", key_func=get_remote_address)
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

