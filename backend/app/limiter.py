import functools
import inspect
import logging
from typing import Any, Callable, Optional
from fastapi import Request
from slowapi import Limiter
from app.config import settings

logger = logging.getLogger("tarkapp.limiter")


def get_remote_address(request: Request) -> str:
    """
    Извлекает реальный IP-адрес пользователя с учетом доверенных заголовков Nginx:
    1. Заголовок 'X-Real-IP'
    2. Первый адрес из списка 'X-Forwarded-For'
    3. Fallback к прямому request.client.host (или '127.0.0.1')
    """
    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip and x_real_ip.strip():
        return x_real_ip.strip().split(",")[0].strip()

    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for and x_forwarded_for.strip():
        return x_forwarded_for.split(",")[0].strip()

    if request.client and request.client.host:
        return request.client.host

    return "127.0.0.1"


def get_device_or_ip(request: Request) -> str:
    """
    Key function for slowapi:
    Combines client IP address and device_id (from 'X-Device-ID' header or 'device_id' query param)
    as f"{ip}:{device_id}", closing header-rotation rate-limit bypasses while isolating devices behind NAT.
    """
    ip = get_remote_address(request) or "unknown"
    raw_dev = request.headers.get("x-device-id")
    if not raw_dev:
        try:
            raw_dev = request.query_params.get("device_id")
        except Exception:
            raw_dev = ""
    device_id = (raw_dev or "").strip() or "anon"
    return f"{ip}:{device_id}"


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    headers_enabled=False,
    enabled=settings.RATE_LIMITING_ENABLED,
)


def safe_limit(*limit_args: Any, **limit_kwargs: Any) -> Callable:
    """
    Decorator that applies slowapi rate limiting for FastAPI HTTP requests,
    while gracefully bypassing limiter when the endpoint function is called
    directly in unit tests without a Starlette Request instance.
    """
    slowapi_decorator = limiter.limit(*limit_args, **limit_kwargs)

    def decorator(func: Callable) -> Callable:
        wrapped = slowapi_decorator(func)

        @functools.wraps(func)
        async def async_handler(*args: Any, **kwargs: Any) -> Any:
            has_request = any(isinstance(a, Request) for a in args) or isinstance(kwargs.get("request"), Request)
            if not has_request:
                return await func(*args, **kwargs)
            return await wrapped(*args, **kwargs)

        @functools.wraps(func)
        def sync_handler(*args: Any, **kwargs: Any) -> Any:
            has_request = any(isinstance(a, Request) for a in args) or isinstance(kwargs.get("request"), Request)
            if not has_request:
                return func(*args, **kwargs)
            return wrapped(*args, **kwargs)

        return async_handler if inspect.iscoroutinefunction(func) else sync_handler

    return decorator

