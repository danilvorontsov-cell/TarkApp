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
    Validates X-Telegram-Bot-Api-Secret-Token when TELEGRAM_WEBHOOK_SECRET is configured,
    and strips sensitive generated key material from the HTTP response body.
    """
    expected_secret = (settings.TELEGRAM_WEBHOOK_SECRET or "").strip()
    if expected_secret:
        provided_secret = (x_telegram_bot_api_secret_token or "").strip()
        if not provided_secret or not secrets.compare_digest(provided_secret, expected_secret):
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
