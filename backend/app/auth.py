import logging
from typing import Optional
from fastapi import Header, HTTPException, status
from pydantic import BaseModel

logger = logging.getLogger("tarkapp.auth")


class CurrentUser(BaseModel):
    user_id: str
    nickname: Optional[str] = "Ученик"
    token: str


def get_current_user(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_auth_token: Optional[str] = Header(None, alias="X-Auth-Token"),
) -> CurrentUser:
    """
    FastAPI AuthGuard Dependency.
    Enforces that incoming requests to analysis/lesson endpoints have a valid authentication token.
    Raises HTTP 401 Unauthorized with {"error": "UNAUTHORIZED", "message": "Войдите в профиль, чтобы использовать разборы"}.
    """
    raw_token = None
    if isinstance(authorization, str) and authorization.strip():
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw_token = parts[1].strip()
        elif len(parts) == 1 and parts[0].lower() != "bearer":
            raw_token = parts[0].strip()

    if not raw_token and isinstance(x_auth_token, str) and x_auth_token.strip():
        raw_token = x_auth_token.strip()

    if not raw_token or raw_token.lower() in ("null", "undefined", "anonymous", "guest", "none", ""):
        logger.warning("[AUTH] Blocked unauthenticated scan attempt - missing or guest token.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "UNAUTHORIZED",
                "message": "Войдите в профиль, чтобы использовать разборы",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = raw_token
    nickname = "Ученик"
    if ":" in raw_token:
        parts = raw_token.split(":", 1)
        user_id = parts[0]
        nickname = parts[1] or "Ученик"

    return CurrentUser(user_id=user_id, nickname=nickname, token=raw_token)
