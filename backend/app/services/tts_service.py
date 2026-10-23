import logging
from typing import AsyncGenerator
import edge_tts

logger = logging.getLogger(__name__)

# Supported voice mappings
VOICE_MAP = {
    "ru": "ru-RU-DmitryNeural",   # Дружелюбный мужской голос для подсказок и объяснений
    "et": "et-EE-KertNeural",      # Четкий голос для эстонских академических терминов
}

DEFAULT_VOICE = "ru-RU-DmitryNeural"


async def generate_speech_stream(
    text: str,
    voice: str = DEFAULT_VOICE,
) -> AsyncGenerator[bytes, None]:
    """
    Streams synthesized speech chunks directly from memory without saving temporary files to disk.
    Zero-Disk In-Memory Streaming via Edge-TTS.
    """
    if not text or not text.strip():
        logger.warning("generate_speech_stream called with empty text")
        return

    clean_text = text.strip()
    volume = "+20%" if "et-EE" in voice else "+0%"
    logger.info(
        f"Generating TTS stream with voice '{voice}', volume '{volume}' for text ({len(clean_text)} chars)"
    )

    try:
        communicate = edge_tts.Communicate(text=clean_text, voice=voice, volume=volume)
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                data = chunk.get("data")
                if data:
                    yield data
    except Exception as e:
        logger.error(f"Error streaming TTS with voice {voice}: {e}", exc_info=True)
        raise
