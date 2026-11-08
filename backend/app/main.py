import asyncio
import logging
import os
import sys
import time
import traceback
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.limiter import limiter
from app.logger import setup_logging, app_logger, error_logger
from app.database import init_db, SessionLocal
from app.routers.analyze import router as analyze_router, legacy_lessons_router
from app.routers.health import router as health_router
from app.routers.voice import router as voice_router
from app.routers.translate import router as translate_router
from app.routers.feedback import router as feedback_router
from app.routers.license import router as license_router
from app.routers.telegram import router as telegram_router, legacy_telegram_router
from app.services.telegram_alert import send_telegram_alert, start_telegram_polling
from app.middleware.security import (
    SecurityHeadersMiddleware,
    mask_device_id,
    sanitize_log_message,
)

# Setup file loggers with rotation (backend/logs/app.log and backend/logs/error.log)
setup_logging()
logger = app_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION} ({settings.APP_ENV})")
    try:
        init_db()
        logger.info("Database initialized successfully.")
        if settings.APP_ENV != "production":
            try:
                with SessionLocal() as db_session:
                    from app.services.license_service import sync_keys_from_file
                    synced_count = sync_keys_from_file(db_session)
                    if synced_count > 0:
                        logger.info(f"Auto-synced {synced_count} keys from generated_keys.txt.")
            except Exception as seed_err:
                logger.warning(f"Could not auto-sync keys from file: {seed_err}")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

    polling_task = None
    if (
        settings.TELEGRAM_BOT_TOKEN
        and settings.ADMIN_TELEGRAM_ID
        and "pytest" not in sys.modules
        and not os.environ.get("PYTEST_CURRENT_TEST")
        and settings.APP_ENV != "test"
    ):
        try:
            from app.services.telegram_alert import register_telegram_bot_commands
            asyncio.create_task(register_telegram_bot_commands())
            polling_task = asyncio.create_task(start_telegram_polling())
        except Exception as e:
            logger.warning(f"Could not start Telegram polling: {e}")

    yield

    if polling_task and not polling_task.done():
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass

    logger.info(f"Shutting down {settings.APP_NAME}")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "TarkApp Backend — карманный адаптационный мостик для русскоязычных школьников в Эстонии. "
        "Помогает преодолеть языковой барьер при переходе на 100% эстоноязычное обучение "
        "через персонализированный мультимодальный разбор учебников (Opiq, Koolibri, Avita)."
    ),
    lifespan=lifespan,
)

app.state.limiter = limiter

# Pure ASGI Security Headers & CORS Configuration
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RequestLoggingMiddleware:
    """
    Pure ASGI request logging & X-Request-ID tracing middleware.
    Avoids Starlette BaseHTTPMiddleware TaskGroup overhead and preserves streaming responses.
    Sanitizes logs by masking X-Device-ID, tokens, license keys, and Base64 images.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.perf_counter()
        raw_headers = scope.get("headers") or []
        req_id = None
        device_id_raw = None

        for k, v in raw_headers:
            k_lower = k.lower()
            if k_lower == b"x-request-id" and not req_id:
                req_id = v.decode("latin-1", errors="ignore").strip()
            elif k_lower == b"x-device-id" and not device_id_raw:
                device_id_raw = v.decode("latin-1", errors="ignore").strip()

        request_id = req_id or f"req_{uuid.uuid4().hex[:8]}"
        scope.setdefault("state", {})["request_id"] = request_id

        method = scope.get("method", "HTTP")
        raw_path = scope.get("path", "")
        clean_path = sanitize_log_message(raw_path)
        dev_tag = f" [dev:{mask_device_id(device_id_raw)}]" if device_id_raw else ""
        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = message.get("status", 200)
                headers = list(message.get("headers") or [])
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
            process_time_ms = (time.perf_counter() - start_time) * 1000
            logger.info(
                f"[{request_id}] {method} {clean_path}{dev_tag} - {status_code} - {process_time_ms:.2f}ms"
            )
        except Exception as exc:
            process_time_ms = (time.perf_counter() - start_time) * 1000
            clean_error = sanitize_log_message(str(exc))
            logger.error(
                f"[{request_id}] {method} {clean_path}{dev_tag} - FAILED - {process_time_ms:.2f}ms - error: {clean_error}"
            )
            raise


app.add_middleware(RequestLoggingMiddleware)


# Register routers
app.include_router(health_router)
app.include_router(analyze_router)
app.include_router(legacy_lessons_router)
app.include_router(voice_router)
app.include_router(translate_router)
app.include_router(feedback_router)
app.include_router(license_router)
app.include_router(telegram_router)
app.include_router(legacy_telegram_router)

# Mount ONLY isolated static audio subdirectory (never expose root static/ or private invoices)
static_audio_dir = Path("static") / "audio"
static_audio_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/audio", StaticFiles(directory=str(static_audio_dir)), name="static_audio")


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """
    Handles 429 Too Many Requests:
    Returns structured JSON with user-friendly Russian message and Retry-After header.
    """
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error": "RATE_LIMIT_EXCEEDED",
            "message": "Слишком много запросов. Пожалуйста, подождите минуту перед повторной попыткой.",
            "detail": str(exc.detail),
        },
        headers={"Retry-After": "60"},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Preserves standard HTTP exceptions (400, 404, 413, etc.) and alerts on 5xx errors."""
    if exc.status_code >= 500 and settings.TELEGRAM_BOT_TOKEN and settings.telegram_chat_id:
        path = request.scope.get("path", str(request.url.path) if hasattr(request, "url") else "")
        try:
            asyncio.create_task(
                send_telegram_alert(
                    endpoint=path,
                    exc=exc,
                    status_code=exc.status_code,
                    message_thread_id=settings.TELEGRAM_TOPIC_ALERTS,
                )
            )
        except Exception as tel_err:
            logger.warning(f"Could not schedule Telegram alert for HTTP {exc.status_code}: {tel_err}")

    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Global 500 unhandled exception handler:
    - Writes full stacktrace to backend/logs/error.log
    - Fires asynchronous Telegram alert to admin chat
    - Returns structured user-friendly JSON without leaking internal server paths
    """
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if not tb.strip() or tb.strip() == "NoneType: None":
        tb = "".join(traceback.format_exception(exc))
    path = request.scope.get("path", str(request.url.path) if hasattr(request, "url") else "")
    method = request.method if hasattr(request, "method") else request.scope.get("method", "HTTP")

    error_logger.error(
        f"Unhandled exception on {method} {path}: {exc.__class__.__name__}: {exc}\n{tb}"
    )

    # Trigger Telegram alert in background task only if configured
    if settings.TELEGRAM_BOT_TOKEN and settings.telegram_chat_id:
        try:
            asyncio.create_task(
                send_telegram_alert(
                    endpoint=path,
                    exc=exc,
                    status_code=500,
                    tb=tb,
                    message_thread_id=settings.TELEGRAM_TOPIC_ALERTS,
                )
            )
        except Exception as tel_err:
            logger.warning(f"Could not schedule Telegram alert: {tel_err}")

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": True,
            "message": "Временный сбой при обработке задания. Попробуйте еще раз через несколько секунд.",
            "code": "INTERNAL_SERVER_ERROR",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
