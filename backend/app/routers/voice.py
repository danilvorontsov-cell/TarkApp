import logging
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.services.tts_service import (
    DEFAULT_VOICE,
    VOICE_MAP,
    generate_speech_stream,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/voice", tags=["Voice TTS"])


@router.get(
    "/tts",
    summary="Потоковый синтез речи (Edge-TTS In-Memory)",
    description=(
        "Синтезирует аудио на лету без сохранения временных файлов на диск. "
        "Поддерживает русский язык (ru-RU-DmitryNeural) для подсказок и "
        "эстонский язык (et-EE-KertNeural) для терминов учебника."
    ),
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"audio/mpeg": {}},
            "description": "Потоковый MP3-аудиопоток",
        }
    },
)
async def text_to_speech(
    text: str = Query(..., min_length=1, max_length=2000, description="Текст для озвучивания"),
    lang: str = Query(default="ru", description="Язык: 'ru' (русский) или 'et' (эстонский)"),
):
    clean_text = text.strip()
    if not clean_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Параметр 'text' не может быть пустым.",
        )

    # Выбираем соответствующий голос
    voice = VOICE_MAP.get(lang.lower(), DEFAULT_VOICE)

    try:
        audio_stream = generate_speech_stream(clean_text, voice=voice)
        return StreamingResponse(
            audio_stream,
            media_type="audio/mpeg",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Disposition": 'inline; filename="tts.mp3"',
                "Cache-Control": "public, max-age=3600",
            },
        )
    except Exception as e:
        logger.error(f"TTS endpoint error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка генерации речи: {str(e)}",
        )
