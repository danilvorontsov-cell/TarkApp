import logging
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response

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
        "а также двуязычную склейку (bilingual=true) для блоков с эстонскими цитатами в кавычках."
    ),
    response_class=Response,
    responses={
        200: {
            "content": {"audio/mpeg": {}},
            "description": "MP3-аудиопоток с точным Content-Length",
        }
    },
)
async def text_to_speech(
    text: str = Query(..., min_length=1, max_length=2000, description="Текст для озвучивания"),
    lang: str = Query(default="ru", description="Язык: 'ru' (русский), 'et' (эстонский) или 'bilingual'"),
    bilingual: bool = Query(default=False, description="Включить двуязычную склейку для фраз в кавычках"),
):
    clean_text = text.strip()
    if not clean_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Параметр 'text' не может быть пустым.",
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
