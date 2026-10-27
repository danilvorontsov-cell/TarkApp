import functools
import inspect
import logging
from typing import Any, Callable, Optional
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.config import settings

logger = logging.getLogger("tarkapp.limiter")


def get_device_or_ip(request: Request) -> str:
    """
    Key function for slowapi:
    Prefers 'X-Device-ID' header for device-level quotas,
    falling back to client IP address if the header is absent.
    """
    device_id = request.headers.get("x-device-id")
    if device_id and device_id.strip():
        return f"dev:{device_id.strip()}"
    return f"ip:{get_remote_address(request)}"


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

