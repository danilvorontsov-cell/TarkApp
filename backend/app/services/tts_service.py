import asyncio
import logging
import re
from typing import AsyncGenerator, List, Tuple
import edge_tts

logger = logging.getLogger(__name__)

# Supported voice mappings
# ru-RU-SvetlanaNeural: максимально стабильный, чистый и надежный русский голос (Edge-TTS не сбрасывает соединение)
# et-EE-KertNeural: четкий мужской эстонский голос (+20% громкости)
VOICE_MAP = {
    "ru": "ru-RU-SvetlanaNeural",
    "et": "et-EE-KertNeural",
}

DEFAULT_VOICE = "ru-RU-SvetlanaNeural"
ESTONIAN_VOICE = "et-EE-KertNeural"

# Карта резервных голосов для отказоустойчивости при сетевых сбоях Edge-TTS
VOICE_FALLBACK_MAP = {
    "ru-RU-SvetlanaNeural": "ru-RU-DmitryNeural",
    "ru-RU-DmitryNeural": "ru-RU-SvetlanaNeural",
    "et-EE-KertNeural": "et-EE-AnuNeural",
    "et-EE-AnuNeural": "et-EE-KertNeural",
}

# Глобальный асинхронный мьютекс для сериализации WebSocket-запросов к Microsoft Edge-TTS
# Защищает от ошибки NoAudioReceived при одновременных параллельных запросах
_tts_lock = asyncio.Lock()


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
    Синтезирует один фрагмент в байты MP3 с защитой от сбоев, повторными попытками
    и автоматическим fallback на резервный голос.
    """
    if delay > 0:
        await asyncio.sleep(delay)

    clean_text = text.strip()
    if "et-EE" in voice:
        clean_text = normalize_text_for_estonian_tts(clean_text)
    if not clean_text:
        return b""

    # Список кандидатов: [основной голос, резервный голос]
    fallback_voice = VOICE_FALLBACK_MAP.get(voice)
    candidates = [voice]
    if fallback_voice and fallback_voice != voice:
        candidates.append(fallback_voice)

    for cand_voice in candidates:
        volume = "+20%" if "et-EE" in cand_voice else "+0%"
        for vol in ([volume, "+0%"] if volume != "+0%" else ["+0%"]):
            try:
                chunks: List[bytes] = []
                async with _tts_lock:
                    communicate = edge_tts.Communicate(text=clean_text, voice=cand_voice, volume=vol)
                    async for chunk in communicate.stream():
                        if chunk.get("type") == "audio" and chunk.get("data"):
                            chunks.append(chunk["data"])
                audio_bytes = b"".join(chunks)
                if audio_bytes:
                    return audio_bytes
            except Exception as e:
                logger.warning(
                    f"Segment synthesis attempt failed for voice '{cand_voice}', vol '{vol}': {e}"
                )
                await asyncio.sleep(0.08)

    logger.error(f"Failed to synthesize segment for text: '{clean_text[:40]}...' with all candidate voices.")
    return b""


async def generate_speech_stream(
    text: str,
    voice: str = DEFAULT_VOICE,
) -> AsyncGenerator[bytes, None]:
    """
    Streams synthesized speech chunks directly from memory without saving temporary files to disk.
    Zero-Disk In-Memory Streaming via Edge-TTS с автоматическим fallback на резервный голос.
    """
    if not text or not text.strip():
        logger.warning("generate_speech_stream called with empty text")
        return

    clean_text = text.strip()
    if "et-EE" in voice:
        clean_text = normalize_text_for_estonian_tts(clean_text)

    # Список кандидатов для озвучки (только в рамках того же языка!)
    fallback_voice = VOICE_FALLBACK_MAP.get(voice)
    candidates = [voice]
    if fallback_voice and fallback_voice != voice:
        candidates.append(fallback_voice)

    for cand_voice in candidates:
        volume = "+20%" if "et-EE" in cand_voice else "+0%"
        logger.info(
            f"Generating TTS stream with voice '{cand_voice}', volume '{volume}' for text ({len(clean_text)} chars)"
        )
        for vol in ([volume, "+0%"] if volume != "+0%" else ["+0%"]):
            try:
                chunks_buffer: List[bytes] = []
                async with _tts_lock:
                    communicate = edge_tts.Communicate(text=clean_text, voice=cand_voice, volume=vol)
                    async for chunk in communicate.stream():
                        if chunk.get("type") == "audio" and chunk.get("data"):
                            chunks_buffer.append(chunk["data"])

                if chunks_buffer:
                    for chunk_data in chunks_buffer:
                        yield chunk_data
                    return

            except Exception as e:
                logger.warning(
                    f"TTS stream candidate '{cand_voice}' (vol '{vol}') failed: {e}. Trying next option..."
                )
                await asyncio.sleep(0.1)

    logger.error(f"All TTS candidates failed for text: {clean_text[:50]}...")


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
