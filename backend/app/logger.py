import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Base directory for TarkApp backend logs
BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"

APP_LOG_PATH = LOGS_DIR / "app.log"
ERROR_LOG_PATH = LOGS_DIR / "error.log"
TTS_AUDIT_LOG_PATH = LOGS_DIR / "tts_audit.log"

MAX_BYTES = 10 * 1024 * 1024  # 10 MB per log file
BACKUP_COUNT = 5               # Keep up to 5 rotated backup files


def setup_logging() -> None:
    """Configures application-wide logging with file rotation (app.log and error.log)."""
    # Ensure logs directory exists
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    formatter = logging.Formatter(log_format)

    # Root Logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    from app.middleware.security import SensitiveDataLoggingFilter
    sensitive_filter = SensitiveDataLoggingFilter()
    root_logger.addFilter(sensitive_filter)

    # Avoid duplicate handlers if setup_logging is called multiple times
    if not any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
        # 1. Rotating File Handler for general app logs (INFO and higher)
        app_file_handler = RotatingFileHandler(
            APP_LOG_PATH,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        app_file_handler.setLevel(logging.INFO)
        app_file_handler.setFormatter(formatter)
        app_file_handler.addFilter(sensitive_filter)
        root_logger.addHandler(app_file_handler)

        # 2. Rotating File Handler exclusively for errors & tracebacks (ERROR and higher)
        error_file_handler = RotatingFileHandler(
            ERROR_LOG_PATH,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        error_file_handler.setLevel(logging.ERROR)
        error_file_handler.setFormatter(formatter)
        error_file_handler.addFilter(sensitive_filter)
        root_logger.addHandler(error_file_handler)

        # 3. Console Stream Handler (if not already attached)
        if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(formatter)
            console_handler.addFilter(sensitive_filter)
            root_logger.addHandler(console_handler)

        # 4. Dedicated Rotating File Handler for TTS Audit
        tts_audit_handler = RotatingFileHandler(
            TTS_AUDIT_LOG_PATH,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        tts_audit_handler.setLevel(logging.INFO)
        tts_audit_handler.setFormatter(logging.Formatter("%(message)s"))
        tts_audit_handler.addFilter(sensitive_filter)
        tts_audit_inst = logging.getLogger("tarkapp.tts_audit")
        tts_audit_inst.setLevel(logging.INFO)
        tts_audit_inst.addHandler(tts_audit_handler)

    # Dedicated error logger
    error_logger = logging.getLogger("tarkapp.error")
    error_logger.setLevel(logging.ERROR)


# Initialize loggers for modules to import
app_logger = logging.getLogger("tarkapp")
error_logger = logging.getLogger("tarkapp.error")
tts_audit_logger = logging.getLogger("tarkapp.tts_audit")
