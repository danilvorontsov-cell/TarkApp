"""
Сервис локального нейросетевого синтеза речи Silero TTS v5 (v5_ru).
Обеспечивает инференс на CPU для русского языка с поддержкой разметки ударений (+).
"""

import logging
import os
from pathlib import Path
import threading
import time
from typing import Optional

import numpy as np

try:
    import torch
    TORCH_AVAILABLE = True
except Exception as e:
    torch = None
    TORCH_AVAILABLE = False

from app.config import settings

logger = logging.getLogger(__name__)

SILERO_MODEL_URL = "https://models.silero.ai/models/tts/ru/v5_ru.pt"


class SileroTTSManager:
    _instance: Optional["SileroTTSManager"] = None
    _lock = threading.Lock()

    def __init__(self):
        self.model = None
        self.device = None
        self.is_loaded = False
        self._infer_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "SileroTTSManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _resolve_model_path(self) -> Path:
        candidates = [
            Path(settings.SILERO_MODEL_PATH),
            Path("/app/data/models/v5_ru.pt"),
            Path("data/models/v5_ru.pt"),
            Path("backend/data/models/v5_ru.pt"),
            Path(__file__).resolve().parent.parent.parent / "data" / "models" / "v5_ru.pt",
            Path(__file__).resolve().parent.parent.parent.parent / "tts_lab" / "v5_ru.pt",
        ]
        for p in candidates:
            if p.exists() and p.is_file() and p.stat().st_size > 10 * 1024 * 1024:
                return p

        # Default target path for download
        target = Path(settings.SILERO_MODEL_PATH)
        if not target.is_absolute():
            target = Path("/app/data/models/v5_ru.pt") if os.path.exists("/app") else Path("data/models/v5_ru.pt")
        return target

    def ensure_model_loaded(self) -> bool:
        if self.is_loaded and self.model is not None:
            return True

        if not TORCH_AVAILABLE or torch is None:
            logger.warning("[SileroTTS] PyTorch is not available in current environment.")
            return False

        with self._lock:
            if self.is_loaded and self.model is not None:
                return True

            model_path = self._resolve_model_path()
            if not model_path.exists() or model_path.stat().st_size < 10 * 1024 * 1024:
                logger.info(f"[SileroTTS] Model not found locally. Downloading from {SILERO_MODEL_URL} to {model_path}...")
                model_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    torch.hub.download_url_to_file(SILERO_MODEL_URL, str(model_path))
                    logger.info(f"[SileroTTS] Downloaded model ({model_path.stat().st_size} bytes).")
                except Exception as dl_err:
                    logger.error(f"[SileroTTS] Failed to download model: {dl_err}", exc_info=True)
                    return False

            try:
                t0 = time.perf_counter()
                self.device = torch.device("cpu")
                try:
                    torch.set_num_threads(2)
                except Exception:
                    pass

                self.model = torch.package.PackageImporter(str(model_path)).load_pickle("tts_models", "model")
                self.model.to(self.device)
                self.is_loaded = True
                load_time = (time.perf_counter() - t0) * 1000
                logger.info(f"[SileroTTS] Model v5_ru loaded in {load_time:.1f}ms from {model_path}. Speakers: {getattr(self.model, 'speakers', [])}")
                return True
            except Exception as load_err:
                logger.error(f"[SileroTTS] Error loading Silero v5 model: {load_err}", exc_info=True)
                self.is_loaded = False
                self.model = None
                return False

    def synthesize(
        self,
        text: str,
        speaker: Optional[str] = None,
        sample_rate: Optional[int] = None,
    ) -> Optional[np.ndarray]:
        """
        Синтезирует речь для русского текста с сохранением ударений (+).
        Возвращает 1D numpy array float32 с частотой sample_rate.
        """
        if not text or not text.strip():
            return None

        if not self.ensure_model_loaded():
            return None

        spk = speaker or getattr(settings, "SILERO_VOICE", "xenia")
        # Silero v5 supports 'xenia' / 'kseniya'
        if spk == "kseniya" and hasattr(self.model, "speakers") and "kseniya" not in self.model.speakers:
            spk = "xenia"

        sr = sample_rate or getattr(settings, "SILERO_SAMPLE_RATE", 24000)

        from app.services.tts_qa_validator import validate_and_fix_russian_tts
        validated_text = validate_and_fix_russian_tts(text.strip())

        with self._infer_lock:
            try:
                t0 = time.perf_counter()
                tensor_audio = self.model.apply_tts(
                    text=validated_text,
                    speaker=spk,
                    sample_rate=sr,
                )
                arr = tensor_audio.detach().cpu().numpy().astype(np.float32)
                dur_ms = (time.perf_counter() - t0) * 1000
                logger.debug(f"[SileroTTS] Synthesized {len(text)} chars in {dur_ms:.1f}ms (audio dur: {len(arr)/sr:.2f}s)")
                return arr
            except Exception as synth_err:
                logger.error(f"[SileroTTS] Synthesis error for text {repr(text[:60])}: {synth_err}", exc_info=True)
                return None


silero_tts = SileroTTSManager.get_instance()
