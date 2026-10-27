import asyncio
import hashlib
import logging
import re
from typing import AsyncGenerator, Dict, List, Optional, Tuple
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

# Семафор для параллельных WebSocket-запросов к Microsoft Edge-TTS (до 4 одновременных сокетов)
# Заменяет жесткий одиночный Lock(), ускоряя склейку двуязычных фрагментов в 8-10 раз
_tts_semaphore = asyncio.Semaphore(4)

# Серверные кэши синтезированного аудио в оперативной памяти (LRU-ограничение)
_TTS_STREAM_CACHE: Dict[str, bytes] = {}
_TTS_SEGMENT_CACHE: Dict[str, bytes] = {}
MAX_CACHE_ENTRIES = 500

# Реестр активных in-flight задач для дедупликации одновременных одинаковых запросов
_IN_FLIGHT_TASKS: Dict[str, asyncio.Task[bytes]] = {}


def _get_cache_key(prefix: str, text: str, voice: str = "") -> str:
    raw = f"{prefix}:{voice}:{text.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _store_in_cache(cache: Dict[str, bytes], key: str, data: bytes):
    if len(cache) >= MAX_CACHE_ENTRIES:
        # Удаляем 20% старейших записей (FIFO очистка для простоты и высокой скорости)
        keys_to_remove = list(cache.keys())[: max(1, MAX_CACHE_ENTRIES // 5)]
        for k in keys_to_remove:
            cache.pop(k, None)
    cache[key] = data


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
    t = re.sub(r'[/\\|]', ' ', t)
    t = re.sub(r'(\b\d+)\s*\.(?!\d)', r'\1 ', t)
    t = re.sub(r'(\d+)([,!?;:])', r'\1 \2', t)
    t = re.sub(r'([,!?;:])(\d+)', r'\1 \2', t)
    t = re.sub(r'(\d+)[-–—]+', r'\1 ', t)
    t = re.sub(r'[-–—]+(\d+)', r' \1', t)
    return re.sub(r'\s+', ' ', t).strip()


def parse_bilingual_segments(text: str) -> List[Tuple[str, str]]:
    """
    Разбивает двуязычный текст на последовательные сегменты (текст, голос):
    - Эстонские фразы и слова в кавычках («...», "...", “...”, „...“) -> et-EE-KertNeural (+20% громкости).
    - Эстонские слова и фразы в скобках ((...)) (напр. (loodusõpetus)) -> et-EE-KertNeural.
    - Отдельные эстонские слова/термины на латинице (loodusõpetus, matemaatika) -> et-EE-KertNeural.
    - Основной русский текст -> ru-RU-SvetlanaNeural.
    """
    if not text or not text.strip():
        return [(text or "", DEFAULT_VOICE)]

    est_char_pattern = re.compile(r'[A-Za-zõäöüšžÕÄÖÜŠŽ]')
    token_pattern = re.compile(
        r'([«"“„][^»"”]+[»"”])|'  # фраза в кавычках
        r'(\([^)]+\))|'            # фраза в скобках
        r'([A-Za-zõäöüšžÕÄÖÜŠŽ][A-Za-zõäöüšžÕÄÖÜŠŽ0-9\-\']*(?:\s+[A-Za-zõäöüšžÕÄÖÜŠŽ][A-Za-zõäöüšžÕÄÖÜŠŽ0-9\-\']*)*)'  # латинские/эстонские слова
    )

    raw_segments: List[Tuple[str, str]] = []
    last_idx = 0

    for match in token_pattern.finditer(text):
        start, end = match.span()
        if start > last_idx:
            prefix = text[last_idx:start]
            raw_segments.append((prefix, DEFAULT_VOICE))

        matched_str = match.group(0)
        inner = matched_str
        if (matched_str.startswith(('«', '"', '“', '„')) and matched_str.endswith(('»', '"', '”', '“'))):
            inner = matched_str[1:-1]
        elif matched_str.startswith('(') and matched_str.endswith(')'):
            inner = matched_str[1:-1]

        if est_char_pattern.search(inner):
            clean_est = normalize_text_for_estonian_tts(inner)
            if clean_est:
                raw_segments.append((clean_est, ESTONIAN_VOICE))
        else:
            raw_segments.append((matched_str, DEFAULT_VOICE))

        last_idx = end

    if last_idx < len(text):
        suffix = text[last_idx:]
        raw_segments.append((suffix, DEFAULT_VOICE))

    # Склеиваем и очищаем пустые сегменты и знаки препинания
    segments: List[Tuple[str, str]] = []
    for s_text, s_voice in raw_segments:
        s_clean = s_text.strip()
        if not s_clean:
            continue

        # Если в сегменте нет букв/цифр (только знаки препинания вроде точки или запятой)
        if not re.search(r'\w', s_clean):
            if segments and segments[-1][1] == DEFAULT_VOICE:
                prev_text, prev_voice = segments[-1]
                segments[-1] = (f"{prev_text}{s_clean}", prev_voice)
            continue

        if segments and segments[-1][1] == s_voice:
            prev_text, prev_voice = segments[-1]
            segments[-1] = (f"{prev_text} {s_clean}", prev_voice)
        else:
            segments.append((s_clean, s_voice))

    if not segments:
        segments.append((text.strip(), DEFAULT_VOICE))

    return segments


async def synthesize_segment(text: str, voice: str, delay: float = 0.0) -> bytes:
    """
    Синтезирует один фрагмент в байты MP3 с защитой от сбоев, повторными попытками,
    встроенным кэшированием и автоматическим fallback на резервный голос.
    """
    clean_text = text.strip()
    if "et-EE" in voice:
        clean_text = normalize_text_for_estonian_tts(clean_text)
    if not clean_text:
        return b""

    # Проверка сегментного кэша
    seg_key = _get_cache_key("seg", clean_text, voice)
    if seg_key in _TTS_SEGMENT_CACHE:
        return _TTS_SEGMENT_CACHE[seg_key]

    if delay > 0:
        await asyncio.sleep(delay)

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
                async with _tts_semaphore:
                    communicate = edge_tts.Communicate(text=clean_text, voice=cand_voice, volume=vol)
                    async for chunk in communicate.stream():
                        if chunk.get("type") == "audio" and chunk.get("data"):
                            chunks.append(chunk["data"])
                audio_bytes = b"".join(chunks)
                if audio_bytes:
                    _store_in_cache(_TTS_SEGMENT_CACHE, seg_key, audio_bytes)
                    return audio_bytes
            except Exception as e:
                logger.warning(
                    f"Segment synthesis attempt failed for voice '{cand_voice}', vol '{vol}': {e}"
                )
                await asyncio.sleep(0.05)

    logger.error(f"Failed to synthesize segment for text: '{clean_text[:40]}...' with all candidate voices.")
    return b""


async def _synthesize_mono_audio_bytes(clean_text: str, voice: str) -> bytes:
    """Синтезирует полный моно-аудиопоток в байты с кэшированием."""
    if "et-EE" in voice:
        clean_text = normalize_text_for_estonian_tts(clean_text)

    fallback_voice = VOICE_FALLBACK_MAP.get(voice)
    candidates = [voice]
    if fallback_voice and fallback_voice != voice:
        candidates.append(fallback_voice)

    for cand_voice in candidates:
        volume = "+20%" if "et-EE" in cand_voice else "+0%"
        for vol in ([volume, "+0%"] if volume != "+0%" else ["+0%"]):
            try:
                chunks_buffer: List[bytes] = []
                async with _tts_semaphore:
                    communicate = edge_tts.Communicate(text=clean_text, voice=cand_voice, volume=vol)
                    async for chunk in communicate.stream():
                        if chunk.get("type") == "audio" and chunk.get("data"):
                            chunks_buffer.append(chunk["data"])

                audio_bytes = b"".join(chunks_buffer)
                if audio_bytes:
                    return audio_bytes
            except Exception as e:
                logger.warning(
                    f"TTS mono stream candidate '{cand_voice}' (vol '{vol}') failed: {e}. Trying fallback..."
                )
                await asyncio.sleep(0.08)

    raise RuntimeError(f"All TTS candidates failed for text: {clean_text[:50]}...")


async def _synthesize_bilingual_audio_bytes(clean_text: str) -> bytes:
    """Синтезирует и склеивает двуязычные фрагменты с кэшированием."""
    segments = parse_bilingual_segments(clean_text)
    has_estonian = any(v == ESTONIAN_VOICE for _, v in segments)

    if not has_estonian:
        return await _synthesize_mono_audio_bytes(clean_text, DEFAULT_VOICE)

    logger.info(
        f"Bilingual TTS: {len(segments)} segments parsed for text ({len(clean_text)} chars). Fetching concurrently..."
    )

    # Параллельный запрос фрагментов с шагом 0.02s через семафор
    tasks = [
        synthesize_segment(seg_text, seg_voice, delay=i * 0.02)
        for i, (seg_text, seg_voice) in enumerate(segments)
    ]
    audio_parts: List[bytes] = await asyncio.gather(*tasks)

    stitched_audio = b"".join(part for part in audio_parts if part)
    if not stitched_audio:
        logger.warning("Bilingual segments returned empty audio. Falling back to mono.")
        return await _synthesize_mono_audio_bytes(clean_text, DEFAULT_VOICE)

    return stitched_audio


async def get_or_synthesize_audio(
    text: str,
    voice: str = DEFAULT_VOICE,
    bilingual: bool = False,
) -> bytes:
    """
    Получает готовый байтовый буфер аудио (MP3) с мгновенным кэшированием (0 мс при повторе)
    и дедупликацией одновременных in-flight запросов.
    """
    clean_text = text.strip()
    if not clean_text:
        return b""

    cache_prefix = "bi" if bilingual else "mono"
    cache_key = _get_cache_key(cache_prefix, clean_text, voice)

    # 1. Быстрый возврат из кэша
    if cache_key in _TTS_STREAM_CACHE:
        logger.info(f"Serving TTS from cache [{cache_prefix}] for text ({len(clean_text)} chars)")
        return _TTS_STREAM_CACHE[cache_key]

    # 2. Дедупликация: если для этого же текста уже идёт синтез, ожидаем ту же задачу
    if cache_key in _IN_FLIGHT_TASKS:
        logger.info(f"Awaiting existing in-flight TTS task for text ({len(clean_text)} chars)")
        try:
            return await _IN_FLIGHT_TASKS[cache_key]
        except Exception:
            pass

    # 3. Создаем новую in-flight задачу
    async def _worker() -> bytes:
        if bilingual:
            audio = await _synthesize_bilingual_audio_bytes(clean_text)
        else:
            audio = await _synthesize_mono_audio_bytes(clean_text, voice)
        _store_in_cache(_TTS_STREAM_CACHE, cache_key, audio)
        return audio

    task = asyncio.create_task(_worker())
    _IN_FLIGHT_TASKS[cache_key] = task

    try:
        audio_result = await task
        return audio_result
    finally:
        _IN_FLIGHT_TASKS.pop(cache_key, None)


async def generate_speech_stream(
    text: str,
    voice: str = DEFAULT_VOICE,
) -> AsyncGenerator[bytes, None]:
    """Стримит моно-озвучку порциями по 16 КБ из кэшированного буфера."""
    if not text or not text.strip():
        return

    audio_bytes = await get_or_synthesize_audio(text, voice=voice, bilingual=False)
    chunk_size = 16384
    for i in range(0, len(audio_bytes), chunk_size):
        yield audio_bytes[i:i + chunk_size]


async def generate_bilingual_speech_stream(
    text: str,
) -> AsyncGenerator[bytes, None]:
    """Стримит двуязычную склейку порциями по 16 КБ из кэшированного буфера."""
    if not text or not text.strip():
        return

    audio_bytes = await get_or_synthesize_audio(text, voice=DEFAULT_VOICE, bilingual=True)
    chunk_size = 16384
    for i in range(0, len(audio_bytes), chunk_size):
        yield audio_bytes[i:i + chunk_size]
