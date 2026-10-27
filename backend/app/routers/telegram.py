import logging
from typing import Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.telegram_alert import process_telegram_update

logger = logging.getLogger("tarkapp.telegram")

router = APIRouter(prefix="/api/v1/telegram", tags=["Telegram"])


@router.post("/webhook")
async def telegram_webhook(
    update: Dict[str, Any],
    db: Session = Depends(get_db),
):
    """
    Receives incoming webhook updates from Telegram Bot API
    and dispatches administrative commands (/gen, /stats, /help).
    """
    try:
        result = await process_telegram_update(update, db=db)
        return {"ok": True, "result": result}
    except Exception as e:
        logger.error(f"[TELEGRAM] Webhook processing exception: {e}")
        return {"ok": False, "error": str(e)}
