import asyncio
import logging
import re
from typing import AsyncGenerator, List, Tuple
import edge_tts

logger = logging.getLogger(__name__)

# Supported voice mappings
VOICE_MAP = {
    "ru": "ru-RU-DmitryNeural",   # Дружелюбный мужской голос для подсказок и объяснений
    "et": "et-EE-KertNeural",      # Четкий голос для эстонских академических терминов
}

DEFAULT_VOICE = "ru-RU-DmitryNeural"
ESTONIAN_VOICE = "et-EE-KertNeural"


def normalize_text_for_estonian_tts(text: str) -> str:
    """
    Нормализует эстонский текст для Edge-TTS:
    - Удаляет крестики и спецсимволы умножения (×, ✕, ✖, *).
    - Удаляет скобки [ ], { }, ( ).
    - Исключает знаки препинания непосредственно встык с числами,
      особенно точку после целых чисел (12. -> 12), из-за которой
      количественные числительные ошибочно распознаются синтезатором как порядковые.
    - Разделяет пробелом знаки препинания и дефисы встык с числами.
    """
    if not text:
        return ""
    t = re.sub(r'[\u00d7\u2715\u2716*]', ' ', text)
    t = re.sub(r'[\[\]{}()]', ' ', t)
    t = re.sub(r'(\b\d+)\s*\.(?!\d)', r'\1 ', t)
    t = re.sub(r'(\d+)([,!?;:])', r'\1 \2', t)
    t = re.sub(r'([,!?;:])(\d+)', r'\1 \2', t)
    t = re.sub(r'(\d+)[-–—]+', r'\1 ', t)
    t = re.sub(r'[-–—]+(\d+)', r' \1', t)
    return re.sub(r'\s+', ' ', t).strip()


def parse_bilingual_segments(text: str) -> List[Tuple[str, str]]:
    """
    Разбивает текст на сегменты (фрагмент, голос):
    - Цитаты в кавычках («...», "...", “...”, „...“, „...“) озвучиваются голосом et-EE-KertNeural.
    - Основной русский текст вне кавычек озвучивается голосом ru-RU-DmitryNeural.
    """
    pattern = r'([«"“„][^»"”]+[»"”])'
    parts = re.split(pattern, text)
    segments: List[Tuple[str, str]] = []

    for part in parts:
        if not part:
            continue
        stripped = part.strip()
        if not stripped:
            continue

        # Проверяем, является ли фрагмент фразой в кавычках
        is_quoted = (
            (stripped.startswith('«') and stripped.endswith('»')) or
            (stripped.startswith('"') and stripped.endswith('"')) or
            (stripped.startswith('“') and stripped.endswith('”')) or
            (stripped.startswith('„') and (stripped.endswith('“') or stripped.endswith('”') or stripped.endswith('"')))
        )

        if is_quoted:
            inner_text = stripped[1:-1].strip()
            if inner_text:
                norm_est = normalize_text_for_estonian_tts(inner_text)
                if norm_est:
                    segments.append((norm_est, ESTONIAN_VOICE))
        else:
            # Если фрагмент содержит слова или буквы
            if re.search(r'\w', stripped):
                segments.append((stripped, DEFAULT_VOICE))
            elif segments and segments[-1][1] == DEFAULT_VOICE:
                # Если только пунктуация и предыдущий сегмент русский, прикрепляем
                prev_text, prev_voice = segments[-1]
                segments[-1] = (f"{prev_text}{stripped}", prev_voice)

    if not segments:
        segments.append((text.strip(), DEFAULT_VOICE))

    return segments


async def synthesize_segment(text: str, voice: str, delay: float = 0.0) -> bytes:
    """
    Синтезирует один фрагмент в байты MP3 с защитой от сбоев и возможностью паузы delay.
    """
    if delay > 0:
        await asyncio.sleep(delay)

    clean_text = text.strip()
    if "et-EE" in voice:
        clean_text = normalize_text_for_estonian_tts(clean_text)
    if not clean_text:
        return b""

    volume = "+20%" if "et-EE" in voice else "+0%"

    for attempt in range(2):
        try:
            communicate = edge_tts.Communicate(text=clean_text, voice=voice, volume=volume)
            chunks = []
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio":
                    data = chunk.get("data")
                    if data:
                        chunks.append(data)
            audio_bytes = b"".join(chunks)
            if audio_bytes:
                return audio_bytes

            # Если вернулось пусто с повышенной громкостью, пробуем со стандартной
            if volume != "+0%":
                communicate = edge_tts.Communicate(text=clean_text, voice=voice, volume="+0%")
                chunks = []
                async for chunk in communicate.stream():
                    if chunk.get("type") == "audio":
                        data = chunk.get("data")
                        if data:
                            chunks.append(data)
                return b"".join(chunks)

        except Exception as e:
            if attempt == 1:
                # Вторая попытка: пробуем с громкостью +0%
                try:
                    communicate = edge_tts.Communicate(text=clean_text, voice=voice, volume="+0%")
                    chunks = []
                    async for chunk in communicate.stream():
                        if chunk.get("type") == "audio":
                            data = chunk.get("data")
                            if data:
                                chunks.append(data)
                    return b"".join(chunks)
                except Exception:
                    logger.warning(f"Segment synthesis error for '{clean_text[:30]}...' ({voice}): {e}")
                    raise
            await asyncio.sleep(0.08)

    return b""


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
    if "et-EE" in voice:
        clean_text = normalize_text_for_estonian_tts(clean_text)
    volume = "+20%" if "et-EE" in voice else "+0%"
    logger.info(
        f"Generating TTS stream with voice '{voice}', volume '{volume}' for text ({len(clean_text)} chars)"
    )

    for attempt in range(2):
        try:
            communicate = edge_tts.Communicate(text=clean_text, voice=voice, volume=volume)
            has_audio = False
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio":
                    data = chunk.get("data")
                    if data:
                        has_audio = True
                        yield data
            if has_audio:
                return

            if volume != "+0%":
                volume = "+0%"
                continue
        except Exception as e:
            if attempt == 0:
                logger.warning(f"TTS stream attempt 1 failed: {e}. Retrying after 0.15s...")
                volume = "+0%"
                await asyncio.sleep(0.15)
                continue
            # Если эстонский голос не ответил, используем надежный fallback на голос Дмитрия
            if voice != DEFAULT_VOICE:
                logger.warning(f"Voice {voice} failed completely: {e}. Executing fallback to {DEFAULT_VOICE}")
                try:
                    communicate = edge_tts.Communicate(text=clean_text, voice=DEFAULT_VOICE, volume="+0%")
                    async for chunk in communicate.stream():
                        if chunk.get("type") == "audio" and chunk.get("data"):
                            yield chunk["data"]
                    return
                except Exception as fb_err:
                    logger.error(f"Fallback to {DEFAULT_VOICE} also failed: {fb_err}", exc_info=True)
            logger.error(f"Error streaming TTS with voice {voice}: {e}", exc_info=True)
            raise


async def generate_bilingual_speech_stream(
    text: str,
) -> AsyncGenerator[bytes, None]:
    """
    Серверная двуязычная склейка:
    Русский текст — голосом ru-RU-DmitryNeural.
    Эстонские фразы в кавычках («...», "...") — голосом et-EE-KertNeural (+20% громкости).
    Фрагменты генерируются через asyncio.gather и склеиваются в единый MP3-стрим.
    Fallback: при любой непредвиденной ошибке склейки отдаётся моно-озвучка голосом Дмитрия.
    """
    if not text or not text.strip():
        logger.warning("generate_bilingual_speech_stream called with empty text")
        return

    clean_text = text.strip()

    try:
        segments = parse_bilingual_segments(clean_text)
        logger.info(
            f"Bilingual TTS: {len(segments)} segments parsed for text ({len(clean_text)} chars)"
        )

        # Если в тексте не было кавычек с эстонскими фразами, сразу стримим голосом Дмитрия
        has_estonian = any(v == ESTONIAN_VOICE for _, v in segments)
        if not has_estonian:
            async for chunk in generate_speech_stream(clean_text, voice=DEFAULT_VOICE):
                yield chunk
            return

        # Запускаем генерацию фрагментов через asyncio.gather со ступенчатой задержкой
        tasks = [
            synthesize_segment(seg_text, seg_voice, delay=i * 0.05)
            for i, (seg_text, seg_voice) in enumerate(segments)
        ]
        audio_parts: List[bytes] = await asyncio.gather(*tasks)

        stitched_audio = b"".join(part for part in audio_parts if part)
        if not stitched_audio:
            raise ValueError("All synthesized bilingual segments returned empty audio")

        logger.info(f"Bilingual audio successfully stitched ({len(stitched_audio)} bytes)")

        # Отдаём стрим частями по 16 КБ
        chunk_size = 16384
        for i in range(0, len(stitched_audio), chunk_size):
            yield stitched_audio[i:i + chunk_size]

    except Exception as e:
        logger.warning(
            f"Bilingual audio stitching failed: {e}. Executing fallback to mono Dmitry voice.",
            exc_info=True,
        )
        # Fallback на моно-озвучку голосом Дмитрия
        async for chunk in generate_speech_stream(clean_text, voice=DEFAULT_VOICE):
            yield chunk
