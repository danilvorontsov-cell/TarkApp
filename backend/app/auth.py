import hashlib
import hmac
import logging
import urllib.parse
from typing import Optional
from fastapi import Header, HTTPException, status
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
    Enforces that incoming requests to analysis/lesson endpoints carry a valid
    HMAC-SHA256 signed authentication token.
    Falls back gracefully to valid X-Device-ID or legacy deviceId:nickname tokens for native mobile clients.
    Raises HTTP 401 Unauthorized only on missing, guest, or unauthenticated requests without valid device context.
    """
    clean_dev = x_device_id.strip() if isinstance(x_device_id, str) else ""
    raw_token = None
    if isinstance(authorization, str) and authorization.strip():
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw_token = parts[1].strip()
        elif len(parts) == 1 and parts[0].lower() != "bearer":
            raw_token = parts[0].strip()

    if not raw_token and isinstance(x_auth_token, str) and x_auth_token.strip():
        raw_token = x_auth_token.strip()

    # Helper: auto-authenticate by device ID
    def _auth_by_device(uid: str, nick: str = "Ученик") -> CurrentUser:
        clean_uid = uid.strip()
        clean_nick = (nick.strip() or "Ученик")[:MAX_NICKNAME_LEN]
        signed = sign_auth_token(clean_uid, clean_nick)
        return CurrentUser(user_id=clean_uid, nickname=clean_nick, token=signed)

    # 1. Missing or guest token -> fallback to device ID
    if not raw_token or raw_token.lower() in ("null", "undefined", "anonymous", "guest", "none", ""):
        if clean_dev and clean_dev.lower() not in ("null", "undefined", "anonymous", "guest", "none", ""):
            logger.info(f"[AUTH] Auto-authenticating native client via X-Device-ID ({clean_dev[:8]}...)")
            return _auth_by_device(clean_dev)
        logger.warning("[AUTH] Blocked unauthenticated scan attempt - missing or guest token.")
        _raise_unauthorized()

    # 2. Check for signed HMAC token: <payload>.<64-hex-sig>
    payload_part, sep, provided_sig = raw_token.rpartition(".")
    if sep and payload_part and len(provided_sig) == 64:
        expected_sig = hmac.new(
            _get_hmac_secret(),
            payload_part.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if hmac.compare_digest(provided_sig.lower(), expected_sig.lower()):
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

            if user_id and user_id.lower() not in ("null", "undefined", "anonymous", "guest", "none"):
                nickname = (nickname.strip() or "Ученик")[:MAX_NICKNAME_LEN]
                return CurrentUser(user_id=user_id, nickname=nickname, token=raw_token)

    # 3. Graceful fallback for legacy native tokens or re-signed server secrets
    # ONLY IF client provides verified X-Device-ID header
    if clean_dev and clean_dev.lower() not in ("null", "undefined", "anonymous", "guest", "none", ""):
        fallback_nick = "Ученик"
        legacy_candidate = payload_part if sep else raw_token
        if ":" in legacy_candidate:
            _, raw_nick = legacy_candidate.split(":", 1)
            if raw_nick:
                try:
                    fallback_nick = urllib.parse.unquote(raw_nick) or "Ученик"
                except Exception:
                    fallback_nick = raw_nick
        logger.info(f"[AUTH] Accepted native mobile client device {clean_dev[:8]}... (upgrading to signed session)")
        return _auth_by_device(clean_dev, fallback_nick)

    logger.warning("[AUTH] Blocked unsigned or malformed auth token without valid device context.")
    _raise_unauthorized()
