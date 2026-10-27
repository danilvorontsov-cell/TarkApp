import html
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
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


async def send_telegram_feedback(data: Dict[str, Any]) -> bool:
    """
    Formats and delivers user feedback (bug reports, feature requests) to Telegram admin chat.
    Includes rich device telemetry and linked Request ID for easy log correlation.
    """
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_ADMIN_CHAT_ID

    if not token or not chat_id:
        logger.info("Telegram bot credentials not configured; skipping Telegram delivery.")
        return False

    clean_token = str(token).strip()
    clean_chat_id = str(chat_id).strip()
    if not clean_token or not clean_chat_id:
        return False

    category = data.get("category", "bug")
    category_label = "🐞 ОШИБКА" if category == "bug" else "💡 ПОЖЕЛАНИЕ"

    raw_message = data.get("message", "").strip()
    safe_message = html.escape(raw_message)

    contact = html.escape(str(data.get("contact") or "").strip()) or "Не указан"
    grade = data.get("current_grade")
    grade_str = f"{grade} класс" if grade else "Не выбран"

    device_model = html.escape(str(data.get("device_model") or "Unknown"))
    os_version = html.escape(str(data.get("os_version") or "Unknown"))
    app_version = html.escape(str(data.get("app_version") or "Unknown"))
    client_time = html.escape(str(data.get("client_time") or "Не указано"))
    last_req_id = html.escape(str(data.get("last_request_id") or "Нет"))

    server_utc_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    telegram_msg = (
        f"🔔 <b>[TarkApp Feedback] {category_label}</b>\n\n"
        f"📝 <b>Сообщение:</b>\n{safe_message}\n\n"
        f"👤 <b>Контакт:</b> {contact}\n"
        f"🎓 <b>Класс:</b> {grade_str}\n\n"
        f"📱 <b>Телеметрия для логов:</b>\n"
        f"• Устройство: {device_model} (OS: {os_version})\n"
        f"• Версия приложения: {app_version}\n"
        f"• Время клиента: {client_time}\n"
        f"• Время сервера: {server_utc_time}\n"
        f"• Связанный Request ID: <code>{last_req_id}</code>"
    )

    telegram_url = f"https://api.telegram.org/bot{clean_token}/sendMessage"

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(
                telegram_url,
                json={
                    "chat_id": clean_chat_id,
                    "text": telegram_msg,
                    "parse_mode": "HTML",
                },
            )
            if resp.status_code == 200:
                logger.info("Telegram feedback delivered successfully.")
                return True
            else:
                logger.warning(
                    f"Telegram feedback responded with HTTP {resp.status_code}: {resp.text[:120]}"
                )
                return False
    except Exception as e:
        logger.warning(f"Failed to deliver Telegram feedback: {e}")
        return False
