import hashlib
import hmac
import logging
import urllib.parse
from typing import Optional
from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger("tarkapp.auth")

MAX_NICKNAME_LEN = 50


class CurrentUser(BaseModel):
    user_id: str
    nickname: Optional[str] = "Ученик"
    token: str


def _get_hmac_secret() -> bytes:
    secret = (settings.SECRET_KEY or "tarkapp-dev-hmac-secret-change-in-production").strip()
    return secret.encode("utf-8")


def sign_auth_token(user_id: str, nickname: Optional[str] = "Ученик") -> str:
    """
    Generates an HMAC-SHA256 signed authentication token:
    <user_id>:<url_encoded_nickname>.<hmac_sha256_hex>
    """
    clean_uid = (user_id or "").strip()
    if not clean_uid:
        raise ValueError("user_id cannot be empty")
    clean_nick = ((nickname or "").strip() or "Ученик")[:MAX_NICKNAME_LEN]
    encoded_nick = urllib.parse.quote(clean_nick, safe="")
    payload = f"{clean_uid}:{encoded_nick}"
    signature = hmac.new(_get_hmac_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def sign_invoice_download_token(invoice_number: str, device_id: str) -> str:
    """Generates an HMAC-SHA256 token granting read access to a specific invoice PDF."""
    clean_inv = (invoice_number or "").strip().upper()
    clean_dev = (device_id or "").strip()
    payload = f"invoice_pdf:{clean_inv}:{clean_dev}"
    return hmac.new(_get_hmac_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_invoice_download_token(invoice_number: str, device_id: str, token: Optional[str]) -> bool:
    """Constant-time verification of an invoice download token."""
    if not token or not token.strip():
        return False
    expected = sign_invoice_download_token(invoice_number, device_id)
    return hmac.compare_digest(token.strip().lower(), expected.lower())


def _raise_unauthorized() -> None:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error": "UNAUTHORIZED",
            "message": "Войдите в профиль, чтобы использовать разборы",
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_auth_token: Optional[str] = Header(None, alias="X-Auth-Token"),
    x_device_id: Optional[str] = Header(None, alias="X-Device-ID"),
) -> CurrentUser:
    """
    FastAPI AuthGuard Dependency.
    Enforces that incoming requests carry a valid HMAC-SHA256 signed authentication token.
    If the client explicitly provided an Authorization header, its HMAC signature must be valid;
    an invalid or expired signature immediately raises HTTP 401 Unauthorized without falling back to X-Device-ID.
    Gracefully falls back to valid X-Device-ID ONLY when Authorization is completely omitted.
    """
    clean_dev = x_device_id.strip() if isinstance(x_device_id, str) else ""

    # Helper: auto-authenticate by device ID
    def _auth_by_device(uid: str, nick: str = "Ученик") -> CurrentUser:
        clean_uid = uid.strip()
        clean_nick = (nick.strip() or "Ученик")[:MAX_NICKNAME_LEN]
        signed = sign_auth_token(clean_uid, clean_nick)
        return CurrentUser(user_id=clean_uid, nickname=clean_nick, token=signed)

    # Helper: validate signed HMAC token: <payload>.<64-hex-sig>
    def _validate_hmac_token(token: str) -> Optional[CurrentUser]:
        payload_part, sep, provided_sig = token.rpartition(".")
        if not (sep and payload_part and len(provided_sig) == 64):
            return None
        expected_sig = hmac.new(
            _get_hmac_secret(),
            payload_part.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(provided_sig.lower(), expected_sig.lower()):
            return None
        user_id = payload_part
        nickname = "Ученик"
        if ":" in payload_part:
            uid_part, raw_nick = payload_part.split(":", 1)
            user_id = uid_part.strip()
            if raw_nick:
                try:
                    nickname = urllib.parse.unquote(raw_nick) or "Ученик"
                except Exception:
                    nickname = raw_nick
        if not user_id or user_id.lower() in ("null", "undefined", "anonymous", "guest", "none"):
            return None
        nickname = (nickname.strip() or "Ученик")[:MAX_NICKNAME_LEN]
        return CurrentUser(user_id=user_id, nickname=nickname, token=token)

    # 1. If client sent an Authorization header, it MUST be valid HMAC signed token.
    # NO fallback to X-Device-ID is allowed if Authorization was provided.
    has_auth_header = isinstance(authorization, str) and bool(authorization.strip())
    if has_auth_header:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw_token = parts[1].strip()
        elif len(parts) == 1 and parts[0].lower() != "bearer":
            raw_token = parts[0].strip()
        else:
            logger.warning("[AUTH] Malformed Authorization header format.")
            _raise_unauthorized()

        if not raw_token or raw_token.lower() in ("null", "undefined", "anonymous", "guest", "none", ""):
            logger.warning("[AUTH] Blocked unauthenticated attempt - empty/guest token in Authorization header.")
            _raise_unauthorized()

        user = _validate_hmac_token(raw_token)
        if user is None:
            logger.warning("[AUTH] Blocked invalid/expired HMAC signature in Authorization header (no device ID fallback).")
            _raise_unauthorized()
        return user

    # 2. Check X-Auth-Token if provided
    if isinstance(x_auth_token, str) and x_auth_token.strip():
        raw_token = x_auth_token.strip()
        user = _validate_hmac_token(raw_token)
        if user is not None:
            return user
        logger.warning("[AUTH] Invalid X-Auth-Token provided.")
        _raise_unauthorized()

    # 3. Graceful fallback for native mobile clients sending only X-Device-ID (without Authorization header)
    if clean_dev and clean_dev.lower() not in ("null", "undefined", "anonymous", "guest", "none", ""):
        logger.info(f"[AUTH] Auto-authenticating native client via X-Device-ID ({clean_dev[:8]}...)")
        return _auth_by_device(clean_dev)

    logger.warning("[AUTH] Blocked unauthenticated request - missing both auth token and device context.")
    _raise_unauthorized()


def require_valid_bearer_token(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """
    Strict AuthGuard for sensitive endpoints (e.g. DELETE /api/v1/license/device).
    Requires a valid Bearer token in the Authorization header.
    Rejects requests without Bearer token even if X-Device-ID is present.
    """
    if not authorization or not authorization.strip():
        logger.warning("[AUTH] Missing Authorization Bearer header for protected endpoint.")
        _raise_unauthorized()
    parts = authorization.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        logger.warning("[AUTH] Authorization header is not a Bearer token.")
        _raise_unauthorized()
    return current_user
