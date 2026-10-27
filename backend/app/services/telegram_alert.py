import hashlib
import html
import logging
import time
import traceback
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import httpx

from app.config import settings
from app.logger import error_logger

logger = logging.getLogger("tarkapp.telegram")

# Cache of recent critical errors for debounce rate-limiting: error_hash -> timestamp (unix seconds)
_ALERT_HISTORY: Dict[str, float] = {}
# Debounce suppression window: 30 minutes
_ALERT_DEBOUNCE_SECONDS: float = 30 * 60


def clear_alert_history() -> None:
    """Clears error alert cache (used in tests and maintenance)."""
    _ALERT_HISTORY.clear()


def get_alert_history() -> Dict[str, float]:
    """Returns copy of the error alert cache."""
    return dict(_ALERT_HISTORY)


def compute_error_hash(endpoint: str, exc: Exception, tb: Optional[str] = None) -> str:
    """Computes a stable fingerprint hash for an error based on endpoint, type, and traceback/message."""
    exc_type = exc.__class__.__name__
    if tb and tb.strip() and tb.strip() != "NoneType: None":
        fingerprint = f"{endpoint}:{exc_type}:{tb.strip()}"
    else:
        fingerprint = f"{endpoint}:{exc_type}:{str(exc).strip()}"
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


async def send_telegram_message(
    text: str,
    parse_mode: Optional[str] = None,
    message_thread_id: Optional[int] = None,
) -> bool:
    """
    Sends a message to Telegram using Bot API sendMessage with optional topic routing (message_thread_id).
    Silently skips if TELEGRAM_BOT_TOKEN or chat ID are not configured.
    """
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.telegram_chat_id

    if not token or not chat_id:
        return False

    clean_token = str(token).strip()
    clean_chat_id = str(chat_id).strip()

    if not clean_token or not clean_chat_id:
        return False

    telegram_url = f"https://api.telegram.org/bot{clean_token}/sendMessage"

    payload: Dict[str, Any] = {
        "chat_id": clean_chat_id,
        "text": text,
    }

    if parse_mode:
        payload["parse_mode"] = parse_mode

    if message_thread_id is not None:
        try:
            payload["message_thread_id"] = int(message_thread_id)
        except (ValueError, TypeError):
            pass

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(telegram_url, json=payload)
            if resp.status_code == 200:
                logger.info(
                    f"Telegram message delivered successfully "
                    f"(chat_id={clean_chat_id}, thread_id={message_thread_id})."
                )
                return True
            else:
                logger.warning(
                    f"Telegram responded with HTTP {resp.status_code}: {resp.text[:120]}"
                )
                return False
    except Exception as e:
        logger.warning(f"Failed to deliver Telegram message: {e}")
        return False


async def send_telegram_alert(
    endpoint: str,
    exc: Exception,
    status_code: int = 500,
    tb: Optional[str] = None,
    message_thread_id: Optional[int] = None,
) -> bool:
    """
    Sends a critical system error alert to Telegram with topic routing and debounce rate limiting.
    - If status_code < 500, silently skips (4xx client warnings are never alerted to Telegram).
    - If the same error fingerprint occurred less than 30 minutes ago, suppresses Telegram delivery
      and records the duplicate only in backend/logs/error.log.
    """
    # 1. 4xx client errors are never sent to Telegram
    if status_code < 500:
        return False

    # 2. Extract traceback if not explicitly provided
    if tb is None and getattr(exc, "__traceback__", None) is not None:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    # 3. Debounce / Rate Limiting (30-minute window per error hash)
    error_hash = compute_error_hash(endpoint, exc, tb)
    now = time.time()
    last_sent = _ALERT_HISTORY.get(error_hash)

    if last_sent is not None and (now - last_sent) < _ALERT_DEBOUNCE_SECONDS:
        elapsed_mins = int((now - last_sent) / 60)
        error_logger.warning(
            f"[DEBOUNCE] Suppressed duplicate Telegram alert for {exc.__class__.__name__} on {endpoint}. "
            f"Last alert sent {elapsed_mins}m ago (window: 30m). Hash: {error_hash[:12]}"
        )
        return False

    # 4. Target topic: default to TELEGRAM_TOPIC_ALERTS if not specified
    target_thread = (
        message_thread_id
        if message_thread_id is not None
        else settings.TELEGRAM_TOPIC_ALERTS
    )

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    exc_type = exc.__class__.__name__
    exc_message = str(exc) or "No error message"

    message_text = (
        f"🚨 <b>[TarkApp Critical Alert]</b>\n\n"
        f"🌐 <b>Эндпоинт:</b> <code>{html.escape(endpoint)}</code>\n"
        f"❌ <b>Ошибка:</b> <code>{html.escape(exc_type)}: {html.escape(exc_message)}</code>\n"
        f"⏱ <b>Время:</b> {now_str}\n"
        f"🔑 <b>Hash:</b> <code>{error_hash[:12]}</code>"
    )

    # 5. Send message
    delivered = await send_telegram_message(
        text=message_text,
        parse_mode="HTML",
        message_thread_id=target_thread,
    )

    # Record in history if message was sent or if Telegram alerting is configured
    if delivered or (settings.TELEGRAM_BOT_TOKEN and settings.telegram_chat_id):
        _ALERT_HISTORY[error_hash] = now

    return delivered


async def send_telegram_feedback(
    data: Dict[str, Any],
    message_thread_id: Optional[int] = None,
) -> bool:
    """
    Formats and delivers user feedback (bug reports, feature requests) to Telegram.
    Routes to TELEGRAM_TOPIC_BUGS for bug reports and TELEGRAM_TOPIC_FEATURES for feature ideas.
    Includes rich device telemetry and linked Request ID for easy log correlation.
    """
    category = data.get("category", "bug")

    # Resolve target topic thread ID
    if message_thread_id is not None:
        target_thread = message_thread_id
    elif category == "bug":
        target_thread = settings.TELEGRAM_TOPIC_BUGS
    else:
        target_thread = settings.TELEGRAM_TOPIC_FEATURES

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

    return await send_telegram_message(
        text=telegram_msg,
        parse_mode="HTML",
        message_thread_id=target_thread,
    )
