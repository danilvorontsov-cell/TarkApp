import functools
import inspect
import ipaddress
import logging
from typing import Any, Callable, Optional
from fastapi import Request
from slowapi import Limiter
from app.config import settings

logger = logging.getLogger("tarkapp.limiter")


def _is_trusted_proxy(host: str) -> bool:
    """
    Checks if a host address belongs to a trusted proxy (loopback 127.0.0.1, ::1 or private RFC1918 subnet).
    """
    if not host or not isinstance(host, str):
        return False
    h = host.strip()
    if h in ("127.0.0.1", "::1", "localhost"):
        return True
    try:
        ip = ipaddress.ip_address(h)
        return ip.is_loopback or ip.is_private
    except ValueError:
        return False


def get_remote_address(request: Request) -> str:
    """
    Извлекает реальный IP-адрес пользователя с защитой от спуфинга заголовков:
    Доверяет заголовкам X-Real-IP и X-Forwarded-For ТОЛЬКО если прямой request.client.host
    является loopback (127.0.0.1, ::1) или приватной подсетью (ipaddress.ip_address(host).is_private).
    Иначе возвращает request.client.host (или '127.0.0.1', если client отсутствует).
    """
    client_host = request.client.host if request.client else None
    if not client_host:
        return "127.0.0.1"

    if _is_trusted_proxy(client_host):
        x_real_ip = request.headers.get("x-real-ip")
        if x_real_ip and x_real_ip.strip():
            return x_real_ip.strip().split(",")[0].strip()

        x_forwarded_for = request.headers.get("x-forwarded-for")
        if x_forwarded_for and x_forwarded_for.strip():
            return x_forwarded_for.split(",")[0].strip()

    return client_host


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

