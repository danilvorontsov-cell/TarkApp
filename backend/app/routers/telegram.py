import logging
import secrets
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.services.telegram_alert import process_telegram_update

logger = logging.getLogger("tarkapp.telegram")

router = APIRouter(prefix="/api/v1/telegram", tags=["Telegram"])


@router.post("/webhook")
async def telegram_webhook(
    update: Dict[str, Any],
    x_telegram_bot_api_secret_token: Optional[str] = Header(
        None, alias="X-Telegram-Bot-Api-Secret-Token"
    ),
    db: Session = Depends(get_db),
):
    """
    Receives incoming webhook updates from Telegram Bot API
    and dispatches administrative commands (/gen, /stats, /help).
    Strictly fail-closed: returns HTTP 503 if TELEGRAM_WEBHOOK_SECRET is not configured,
    and HTTP 403 if X-Telegram-Bot-Api-Secret-Token does not match via constant-time compare.
    """
    expected_secret = (settings.TELEGRAM_WEBHOOK_SECRET or "").strip()
    if not expected_secret:
        logger.error("[TELEGRAM] Webhook rejected: TELEGRAM_WEBHOOK_SECRET is not configured in .env (fail-closed).")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram webhook secret is not configured.",
        )

    provided_secret = (x_telegram_bot_api_secret_token or "").strip()
    if not provided_secret or not secrets.compare_digest(
        provided_secret.encode("utf-8"), expected_secret.encode("utf-8")
    ):
        logger.warning("[TELEGRAM] Rejected webhook call due to invalid or missing secret token.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Telegram webhook secret token.",
        )

    try:
        result = await process_telegram_update(update, db=db)
        safe_result = (
            {k: v for k, v in result.items() if k not in ("keys", "reply")}
            if isinstance(result, dict)
            else result
        )
        return {"ok": True, "result": safe_result}
    except Exception as e:
        logger.error(f"[TELEGRAM] Webhook processing exception: {e}")
        return {"ok": False, "error": "Webhook processing error"}


legacy_telegram_router = APIRouter(prefix="/api/telegram", tags=["Telegram"])


@legacy_telegram_router.post("/webhook")
async def telegram_webhook_legacy_alias(
    update: Dict[str, Any],
    x_telegram_bot_api_secret_token: Optional[str] = Header(
        None, alias="X-Telegram-Bot-Api-Secret-Token"
    ),
    db: Session = Depends(get_db),
):
    return await telegram_webhook(
        update=update,
        x_telegram_bot_api_secret_token=x_telegram_bot_api_secret_token,
        db=db,
    )
