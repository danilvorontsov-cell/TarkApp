import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse, Response

from app.models.page_analysis import AgeTier, is_full_audio_enabled
from app.services.tts_service import (
    DEFAULT_VOICE,
    VOICE_MAP,
    get_or_synthesize_audio,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/voice", tags=["Voice TTS"])


@router.get(
    "/tts",
    summary="Синтез речи (Edge-TTS с мгновенным кэшированием и поддержкой двуязычной склейки)",
    description=(
        "Синтезирует аудио на лету с кэшированием в памяти и дедупликацией in-flight запросов. "
        "Поддерживает русский язык (ru-RU-SvetlanaNeural с автоматическим fallback) для подсказок, "
        "эстонский язык (et-EE-KertNeural / et-EE-AnuNeural) для терминов учебника, "
        "а также двуязычную склейку (bilingual=true) для блоков с эстонскими цитатами в кавычках. "
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
async def text_to_speech(
    text: str = Query(..., min_length=1, max_length=2000, description="Текст для озвучивания"),
    lang: str = Query(default="ru", description="Язык: 'ru' (русский), 'et' (эстонский) или 'bilingual'"),
    bilingual: bool = Query(default=False, description="Включить двуязычную склейку для фраз в кавычках"),
    grade: Optional[int] = Query(default=None, description="Класс ученика (1-12)"),
    tier: Optional[AgeTier] = Query(default=None, description="Звено обучения (primary, middle, high, gymnasium)"),
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
        # Длинные тексты на русском и двуязычные подсказки отключаются
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

    try:
        if is_bilingual:
            audio_bytes = await get_or_synthesize_audio(clean_text, voice=DEFAULT_VOICE, bilingual=True)
        else:
            voice = VOICE_MAP.get(lang.lower(), DEFAULT_VOICE)
            audio_bytes = await get_or_synthesize_audio(clean_text, voice=voice, bilingual=False)

        if not audio_bytes:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Не удалось синтезировать аудиопоток.",
            )

        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(audio_bytes)),
                "Content-Disposition": 'inline; filename="tts.mp3"',
                "Cache-Control": "public, max-age=86400",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS endpoint error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка генерации речи: {str(e)}",
        )


@router.get(
    "/speak",
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
async def speak_word(
    text: str = Query(..., min_length=1, max_length=300, description="Слово или короткая фраза"),
    lang: str = Query(default="et", description="Язык произношения ('et' или 'ru')"),
):
    clean_text = text.strip()
    if not clean_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Параметр 'text' не может быть пустым.",
        )

    try:
        voice = VOICE_MAP.get(lang.lower(), VOICE_MAP["et"])
        audio_bytes = await get_or_synthesize_audio(clean_text, voice=voice, bilingual=False)

        if not audio_bytes:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Не удалось озвучить слово.",
            )

        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(audio_bytes)),
                "Content-Disposition": 'inline; filename="speak.mp3"',
                "Cache-Control": "public, max-age=86400",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Speak endpoint error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка произношения слова: {str(e)}",
        )
