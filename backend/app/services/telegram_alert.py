import logging
from datetime import datetime
from typing import Optional
import httpx

from app.config import settings

logger = logging.getLogger("tarkapp.telegram")


async def send_telegram_alert(endpoint: str, exc: Exception, status_code: int = 500) -> bool:
    """
    Sends an error notification message to Telegram admin chat.
    Silently skips if TELEGRAM_BOT_TOKEN or TELEGRAM_ADMIN_CHAT_ID are not set in .env.
    """
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_ADMIN_CHAT_ID

    if not token or not chat_id:
        # Telegram alerting is not configured; skip silently
        return False

    clean_token = str(token).strip()
    clean_chat_id = str(chat_id).strip()

    if not clean_token or not clean_chat_id:
        return False

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    exc_type = exc.__class__.__name__
    exc_message = str(exc) or "No error message"

    message_text = (
        f"🚨 Ошибка в TarkApp Backend!\n"
        f"Эндпоинт: {endpoint}\n"
        f"Ошибка: {exc_type}: {exc_message}\n"
        f"Время: {now_str}"
    )

    telegram_url = f"https://api.telegram.org/bot{clean_token}/sendMessage"

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(
                telegram_url,
                json={
                    "chat_id": clean_chat_id,
                    "text": message_text,
                },
            )
            if resp.status_code == 200:
                logger.info("Telegram alert sent successfully.")
                return True
            else:
                logger.warning(
                    f"Telegram alert responded with HTTP {resp.status_code}: {resp.text[:100]}"
                )
                return False
    except Exception as e:
        logger.warning(f"Failed to send Telegram alert: {e}")
        return False
