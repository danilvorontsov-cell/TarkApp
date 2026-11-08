import hashlib
import inspect
import logging
from pathlib import Path
from typing import Literal, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.limiter import safe_limit, get_device_or_ip, get_remote_address
from app.models.license import Device
from app.models.page_analysis import AgeTier, is_full_audio_enabled
from app.services import license_service
from app.services.tts_service import (
    DEFAULT_VOICE,
    MIN_VALID_AUDIO_BYTES,
    VOICE_MAP,
    get_or_synthesize_audio,
)

logger = logging.getLogger(__name__)

AUDIO_STATIC_DIR = Path("static/audio")
try:
    AUDIO_STATIC_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

router = APIRouter(prefix="/api/v1/voice", tags=["Voice TTS"])


class VoiceRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, description="Текст для озвучивания")
    lang: Literal["ru", "et"] = Field(default="ru", description="Язык: 'ru' (русский) или 'et' (эстонский)")
    bilingual: bool = Field(default=False, description="Включить двуязычную склейку для фраз в кавычках")
    grade: int = Field(default=1, ge=1, le=12, description="Класс ученика (от 1 до 12)")
    tier: str = Field(default="primary", max_length=50, description="Возрастное звено (primary, middle, gymnasium)")
    is_speech_text: bool = Field(default=False, description="Флаг прямого синтеза готового речевого слоя")


async def _call_synthesize_safely(
    synth_func,
    clean_text: str,
    voice: str,
    bilingual: bool,
    grade: Optional[int],
    tier: Optional[str] = None,
    is_speech_text: bool = False,
) -> bytes:
    try:
        sig = inspect.signature(synth_func)
        if "is_speech_text" in sig.parameters or any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
            return await synth_func(
                clean_text,
                voice=voice,
                bilingual=bilingual,
                grade=grade,
                tier=tier,
                is_speech_text=is_speech_text,
            )
    except Exception:
        pass
    return await synth_func(
        clean_text,
        voice=voice,
        bilingual=bilingual,
        grade=grade,
        tier=tier,
    )


async def verify_voice_device_access(
    device_id: Optional[str] = Query(default=None, description="ID устройства (для нативного аудио-стриминга)"),
    x_device_id: Optional[str] = Header(default=None, alias="X-Device-ID"),
    db: Session = Depends(get_db),
):
    """
    Проверяет валидность устройства (через query-параметр device_id или заголовок X-Device-ID)
    и наличие активного триала / подписки в БД перед запуском платного синтеза Azure Neural TTS.
    """
    resolved_id = (device_id or x_device_id or "").strip()
    if not resolved_id:
        if settings.APP_ENV in ("development", "test"):
            resolved_id = "dev-test-device-0001"
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "DEVICE_ID_REQUIRED",
                    "message": "Для синтеза речи необходим параметр device_id или заголовок X-Device-ID.",
                },
            )

    existing_device = db.query(Device).filter(Device.device_id == resolved_id).first()
    if not existing_device and settings.APP_ENV not in ("development", "test"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "DEVICE_NOT_REGISTERED",
                "message": "Устройство не зарегистрировано. Перезапустите приложение.",
            },
        )

    check_res = license_service.check_device_access(resolved_id, db)
    if not check_res["allowed"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "TRIAL_EXPIRED",
                "message": "Срок действия пробного периода завершен.",
            },
        )
    return check_res


@router.get(
    "",
    dependencies=[Depends(verify_voice_device_access)],
    summary="Синтез речи (GET алиас)",
    include_in_schema=False,
    response_class=Response,
    responses={
        200: {
            "content": {"audio/mpeg": {}, "application/json": {}},
            "description": "MP3-аудиопоток или JSON-статус audio_disabled: true",
        }
    },
)
@router.get(
    "/tts",
    dependencies=[Depends(verify_voice_device_access)],
    summary="Синтез речи (Azure Neural TTS с единым дисковым/RAM кэшированием и двуязычной склейкой)",
    description=(
        "Синтезирует аудио через Azure Speech Services с кэшированием в static/audio/cache/ и дедупликацией in-flight запросов. "
        "Поддерживает русский язык (ru-RU-SvetlanaNeural) для подсказок, "
        "эстонский язык (et-EE-AnuNeural) для терминов учебника, "
        "а также двуязычный SSML (bilingual=true). "
        "Для 7–12 классов длинная озвучка блокируется со статусом audio_disabled: true."
    ),
    response_class=Response,
    responses={
        200: {
            "content": {"audio/mpeg": {}, "application/json": {}},
            "description": "MP3-аудиопоток или JSON-статус audio_disabled: true",
        }
    },
)
@safe_limit("60/minute", key_func=get_device_or_ip)
@safe_limit("120/minute", key_func=get_remote_address)
async def text_to_speech(
    request: Request,
    text: str = Query(..., min_length=1, max_length=2000, description="Текст для озвучивания"),
    lang: str = Query(default="ru", description="Язык: 'ru' (русский), 'et' (эстонский) или 'bilingual'"),
    bilingual: bool = Query(default=False, description="Включить двуязычную склейку для фраз в кавычках"),
    grade: Optional[int] = Query(default=None, description="Класс ученика (1-12)"),
    tier: Optional[AgeTier] = Query(default=None, description="Звено обучения (primary, middle, high, gymnasium)"),
    is_speech_text: bool = Query(default=False, description="Флаг прямого синтеза готового речевого слоя"),
):
    clean_text = text.strip()
    if not clean_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Параметр 'text' не может быть пустым.",
        )

    # Проверка политики озвучки для старших звеньев (7-12 классы)
    resolved_tier = tier or (AgeTier.from_grade(grade) if grade else None)
    if resolved_tier and not is_full_audio_enabled(resolved_tier):
        if lang.lower() == "ru" or bilingual or len(clean_text) > 80:
            logger.info(
                f"TTS disabled by tier policy for tier={resolved_tier}, grade={grade}. Returning audio_disabled: true."
            )
            return JSONResponse(
                content={
                    "audio_disabled": True,
                    "detail": "Озвучка длинных блоков отключена для 7–12 классов.",
                },
                status_code=status.HTTP_200_OK,
            )

    is_bilingual = bilingual or lang.lower() == "bilingual"
    voice = "bilingual" if is_bilingual else VOICE_MAP.get(lang.lower(), DEFAULT_VOICE)
    tier_str = resolved_tier.value if resolved_tier else None

    try:
        audio_bytes = await _call_synthesize_safely(
            get_or_synthesize_audio,
            clean_text,
            voice=DEFAULT_VOICE if is_bilingual else voice,
            bilingual=is_bilingual,
            grade=grade,
            tier=tier_str,
            is_speech_text=is_speech_text,
        )

        if not audio_bytes:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Не удалось синтезировать аудиопоток.",
            )

        audio_hash = hashlib.sha256(f"{voice}:{clean_text.lower()}".encode("utf-8")).hexdigest()
        file_path = AUDIO_STATIC_DIR / f"{audio_hash}.mp3"
        try:
            if not file_path.exists() or file_path.stat().st_size != len(audio_bytes):
                file_path.write_bytes(audio_bytes)
        except Exception as write_err:
            logger.warning(f"Could not write static audio file: {write_err}")

        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(audio_bytes)),
                "Content-Disposition": 'inline; filename="tts.mp3"',
                "Cache-Control": "public, max-age=604800, immutable",
                "X-Static-Audio-URL": f"/static/audio/{audio_hash}.mp3",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS endpoint error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка генерации речи. Попробуйте позже.",
        )


@router.post(
    "",
    dependencies=[Depends(verify_voice_device_access)],
    summary="Синтез речи для длинных текстов (POST)",
    description=(
        "Принимает JSON-тело VoiceRequest (до 5000 символов) без ошибок 414 URI Too Large. "
        "Поддерживает русский и эстонский языки, двуязычную склейку, "
        "и адаптирует темп речи под младшие классы на основе параметров grade и tier."
    ),
    response_class=Response,
    responses={
        200: {
            "content": {"audio/mpeg": {}, "application/json": {}},
            "description": "MP3-аудиопоток или JSON-статус audio_disabled: true",
        }
    },
)
@router.post(
    "/tts",
    dependencies=[Depends(verify_voice_device_access)],
    summary="Синтез речи для длинных текстов (POST алиас)",
    include_in_schema=False,
    response_class=Response,
    responses={
        200: {
            "content": {"audio/mpeg": {}, "application/json": {}},
            "description": "MP3-аудиопоток или JSON-статус audio_disabled: true",
        }
    },
)
@safe_limit("60/minute", key_func=get_device_or_ip)
@safe_limit("120/minute", key_func=get_remote_address)
async def text_to_speech_post(
    request: Request,
    payload: VoiceRequest,
):
    clean_text = payload.text.strip()
    if not clean_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Параметр 'text' не может быть пустым.",
        )

    resolved_tier = None
    if payload.tier:
        try:
            resolved_tier = AgeTier(payload.tier.lower())
        except ValueError:
            pass
    if not resolved_tier and payload.grade:
        resolved_tier = AgeTier.from_grade(payload.grade)

    # Проверка политики озвучки для старших звеньев (7-12 классы)
    if resolved_tier and not is_full_audio_enabled(resolved_tier):
        if payload.lang.lower() == "ru" or payload.bilingual or len(clean_text) > 80:
            logger.info(
                f"TTS disabled by tier policy for tier={resolved_tier}, grade={payload.grade}. Returning audio_disabled: true."
            )
            return JSONResponse(
                content={
                    "audio_disabled": True,
                    "detail": "Озвучка длинных блоков отключена для 7–12 классов.",
                },
                status_code=status.HTTP_200_OK,
            )

    is_bilingual = payload.bilingual or payload.lang.lower() == "bilingual"
    voice = "bilingual" if is_bilingual else VOICE_MAP.get(payload.lang.lower(), DEFAULT_VOICE)
    tier_str = resolved_tier.value if resolved_tier else payload.tier

    try:
        audio_bytes = await _call_synthesize_safely(
            get_or_synthesize_audio,
            clean_text,
            voice=DEFAULT_VOICE if is_bilingual else voice,
            bilingual=is_bilingual,
            grade=payload.grade,
            tier=tier_str,
            is_speech_text=payload.is_speech_text,
        )

        if not audio_bytes:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Не удалось синтезировать аудиопоток.",
            )

        audio_hash = hashlib.sha256(f"{voice}:{clean_text.lower()}".encode("utf-8")).hexdigest()
        file_path = AUDIO_STATIC_DIR / f"{audio_hash}.mp3"
        try:
            if not file_path.exists() or file_path.stat().st_size != len(audio_bytes):
                file_path.write_bytes(audio_bytes)
        except Exception as write_err:
            logger.warning(f"Could not write static audio file: {write_err}")

        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(audio_bytes)),
                "Content-Disposition": 'inline; filename="tts.mp3"',
                "Cache-Control": "public, max-age=604800, immutable",
                "X-Static-Audio-URL": f"/static/audio/{audio_hash}.mp3",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS POST endpoint error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка генерации речи. Попробуйте позже.",
        )


@router.get(
    "/speak",
    dependencies=[Depends(verify_voice_device_access)],
    summary="Точечный синтез для эстонских терминов словаря",
    description="Выделенный быстрый эндпоинт для произношения отдельных слов словаря (vocabulary).",
    response_class=Response,
    responses={
        200: {
            "content": {"audio/mpeg": {}},
            "description": "MP3-аудиопоток термина",
        }
    },
)
@safe_limit("60/minute", key_func=get_device_or_ip)
@safe_limit("120/minute", key_func=get_remote_address)
async def speak_word(
    request: Request,
    text: str = Query(..., min_length=1, max_length=300, description="Слово или короткая фраза"),
    lang: str = Query(default="et", description="Язык произношения ('et' или 'ru')"),
    is_speech_text: bool = Query(default=False, description="Флаг: текст уже подготовлен для TTS"),
):
    clean_text = text.strip()
    if not clean_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Параметр 'text' не может быть пустым.",
        )

    try:
        voice = VOICE_MAP.get(lang.lower(), VOICE_MAP["et"])
        audio_bytes = await get_or_synthesize_audio(
            clean_text, voice=voice, bilingual=False, is_speech_text=is_speech_text
        )

        if not audio_bytes:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Не удалось озвучить слово.",
            )

        audio_hash = hashlib.sha256(f"{voice}:{is_speech_text}:{clean_text.lower()}".encode("utf-8")).hexdigest()
        file_path = AUDIO_STATIC_DIR / f"{audio_hash}.mp3"
        try:
            if not file_path.exists() or file_path.stat().st_size != len(audio_bytes):
                file_path.write_bytes(audio_bytes)
        except Exception as write_err:
            logger.warning(f"Could not write static audio file: {write_err}")

        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(audio_bytes)),
                "Content-Disposition": 'inline; filename="speak.mp3"',
                "Cache-Control": "public, max-age=604800, immutable",
                "X-Static-Audio-URL": f"/static/audio/{audio_hash}.mp3",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Speak endpoint error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка произношения слова. Попробуйте позже.",
        )
