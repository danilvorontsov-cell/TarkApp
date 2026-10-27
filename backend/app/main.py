import asyncio
import logging
import time
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.logger import setup_logging, app_logger, error_logger
from app.routers.analyze import router as analyze_router
from app.routers.health import router as health_router
from app.routers.voice import router as voice_router
from app.routers.translate import router as translate_router
from app.services.telegram_alert import send_telegram_alert

# Setup file loggers with rotation (backend/logs/app.log and backend/logs/error.log)
setup_logging()
logger = app_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION} ({settings.APP_ENV})")
    yield
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

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests_middleware(request: Request, call_next):
    """
    Measures processing duration and logs all incoming requests (method, endpoint,
    status_code, response time in ms) into backend/logs/app.log.
    """
    start_time = time.perf_counter()
    try:
        response = await call_next(request)
        process_time_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            f"{request.method} {request.url.path} - {response.status_code} - {process_time_ms:.2f}ms"
        )
        return response
    except Exception as exc:
        process_time_ms = (time.perf_counter() - start_time) * 1000
        logger.error(
            f"{request.method} {request.url.path} - FAILED - {process_time_ms:.2f}ms - error: {exc}"
        )
        raise exc


# Register routers
app.include_router(health_router)
app.include_router(analyze_router)
app.include_router(voice_router)
app.include_router(translate_router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Preserves standard HTTP exceptions (400, 404, 413, etc.) without altering client contracts."""
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
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_ADMIN_CHAT_ID:
        try:
            asyncio.create_task(send_telegram_alert(path, exc, 500))
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
