import asyncio
import hashlib
import html
import logging
import time
import traceback
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Union
import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.logger import error_logger
from app.services.license_service import generate_access_keys, get_keys_stats

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
    chat_id: Optional[Union[str, int]] = None,
) -> bool:
    """
    Sends a message to Telegram using Bot API sendMessage with optional topic routing (message_thread_id)
    and optional custom target chat_id. Silently skips if TELEGRAM_BOT_TOKEN or target chat ID are not configured.
    """
    token = settings.TELEGRAM_BOT_TOKEN
    target_chat = str(chat_id).strip() if chat_id is not None else (settings.telegram_chat_id or "").strip()

    if not token or not target_chat:
        return False

    clean_token = str(token).strip()
    clean_chat_id = target_chat

    if not clean_token or not clean_chat_id:
        return False

    telegram_url = f"https://api.telegram.org/bot{clean_token}/sendMessage"

    # Ensure message does not exceed Telegram 4096 character limit
    safe_text = text if len(text) <= 4000 else text[:3950] + "\n... [truncated]"

    payload: Dict[str, Any] = {
        "chat_id": clean_chat_id,
        "text": safe_text,
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
    raw_exc_msg = str(exc) or "No error message"
    # Truncate exception message to 1200 chars before HTML escaping to prevent Telegram 400
    exc_message = (
        raw_exc_msg if len(raw_exc_msg) <= 1200 else raw_exc_msg[:1200] + "... [truncated]"
    )

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
    if len(raw_message) > 2000:
        raw_message = raw_message[:2000] + "... [truncated]"
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


# ==========================================
# Telegram Admin Bot Commands & Updates
# ==========================================

def is_admin_user(user_id: Optional[Union[str, int]]) -> bool:
    """Verifies whether the given Telegram user ID matches ADMIN_TELEGRAM_ID."""
    if user_id is None or not settings.ADMIN_TELEGRAM_ID:
        return False
    return str(user_id).strip() == str(settings.ADMIN_TELEGRAM_ID).strip()


async def handle_admin_telegram_command(
    text: str,
    user_id: Optional[Union[str, int]] = None,
    chat_id: Optional[Union[str, int]] = None,
    message_thread_id: Optional[int] = None,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Processes administrative commands from Telegram:
    - /gen <count> <days>: Generates access keys in DB and returns them formatted with <code>KEY</code>.
    - /stats: Returns count of free, active, expired keys and total registered device_id count.
    - /help or /start: Returns usage instructions.
    Rejects unauthorized users by showing their Telegram ID for easy configuration.
    """
    clean_text = (text or "").strip()
    if not clean_text.startswith("/"):
        return {"handled": False}

    target_chat = chat_id or user_id or settings.telegram_chat_id

    # 1. Authorization check
    if not is_admin_user(user_id):
        raw_uid = str(user_id or "Неизвестный")
        logger.warning(f"[TELEGRAM] Unauthorized command attempt '{clean_text}' from user_id={raw_uid}")
        reply_msg = (
            f"⛔ <b>Доступ запрещен</b>\n\n"
            f"Ваш Telegram ID: <code>{html.escape(raw_uid)}</code>\n\n"
            f"Для авторизации укажите этот ID в переменной <code>ADMIN_TELEGRAM_ID</code> в файле <code>backend/.env</code>."
        )
        if target_chat:
            await send_telegram_message(
                text=reply_msg,
                parse_mode="HTML",
                message_thread_id=message_thread_id,
                chat_id=target_chat,
            )
        return {
            "handled": True,
            "authorized": False,
            "error": "UNAUTHORIZED",
            "reply": reply_msg,
        }

    # 2. Parse command name and arguments (support /gen@bot_name syntax)
    tokens = clean_text.split()
    command = tokens[0].split("@")[0].lower()
    args = tokens[1:]

    # 3. Handle /gen <count> <days>
    if command == "/gen":
        count = 10
        days = 30

        if len(args) >= 1:
            try:
                count = int(args[0])
            except ValueError:
                count = 10
        if len(args) >= 2:
            try:
                days = int(args[1])
            except ValueError:
                days = 30

        # Safety clamps
        count = max(1, min(count, 50))
        days = max(1, min(days, 365))

        keys = generate_access_keys(count=count, days=days, prefix="TARK", db=db)
        keys_html = "\n".join(f"<code>{k}</code>" for k in keys)

        reply_msg = (
            f"🔑 <b>Сгенерировано ключей: {len(keys)} (срок: {days} дн.)</b>\n\n"
            f"{keys_html}\n\n"
            f"<i>💡 Нажмите на любой ключ, чтобы скопировать его в буфер обмена.</i>"
        )

        if target_chat:
            await send_telegram_message(
                text=reply_msg,
                parse_mode="HTML",
                message_thread_id=message_thread_id,
                chat_id=target_chat,
            )

        return {
            "handled": True,
            "authorized": True,
            "command": "gen",
            "count": len(keys),
            "days": days,
            "keys": keys,
            "reply": reply_msg,
        }

    # 4. Handle /stats
    elif command == "/stats":
        stats = get_keys_stats(db=db)

        reply_msg = (
            f"📊 <b>Статистика лицензий TarkApp</b>\n\n"
            f"👥 <b>Всего устройств:</b> {stats['total_devices']}\n"
            f"🔑 <b>Всего ключей:</b> {stats['total_keys']}\n"
            f"🟢 <b>Свободных (ждут выдачи):</b> {stats['free_keys']}\n"
            f"🔵 <b>Активных (действуют):</b> {stats['active_keys']}\n"
            f"🔴 <b>Просроченных (истекли):</b> {stats['expired_keys']}"
        )

        if target_chat:
            await send_telegram_message(
                text=reply_msg,
                parse_mode="HTML",
                message_thread_id=message_thread_id,
                chat_id=target_chat,
            )

        return {
            "handled": True,
            "authorized": True,
            "command": "stats",
            "stats": stats,
            "reply": reply_msg,
        }

    # 5. Handle /help or /start
    elif command in ("/start", "/help"):
        reply_msg = (
            f"🛠 <b>Административная панель TarkApp</b>\n\n"
            f"Доступные команды:\n"
            f"• <code>/gen &lt;кол-во&gt; &lt;дни&gt;</code> — сгенерировать новые ключи доступа (напр. <code>/gen 10 30</code>)\n"
            f"• <code>/stats</code> — статистика зарегистрированных устройств и статусов ключей\n"
            f"• <code>/help</code> — показать эту справку"
        )

        if target_chat:
            await send_telegram_message(
                text=reply_msg,
                parse_mode="HTML",
                message_thread_id=message_thread_id,
                chat_id=target_chat,
            )

        return {
            "handled": True,
            "authorized": True,
            "command": "help",
            "reply": reply_msg,
        }

    # 6. Unknown command
    else:
        reply_msg = (
            f"❓ Команда <code>{html.escape(command)}</code> не распознана.\n"
            f"Используйте <code>/help</code> для списка доступных команд."
        )
        if target_chat:
            await send_telegram_message(
                text=reply_msg,
                parse_mode="HTML",
                message_thread_id=message_thread_id,
                chat_id=target_chat,
            )
        return {
            "handled": True,
            "authorized": True,
            "command": command,
            "reply": reply_msg,
        }


async def process_telegram_update(
    update: Dict[str, Any],
    db: Optional[Session] = None,
) -> Optional[Dict[str, Any]]:
    """
    Inspects an incoming Telegram update payload and dispatches commands.
    Used by webhook endpoints and background polling loops.
    """
    message = update.get("message") or update.get("edited_message")
    if not message:
        return None

    text = message.get("text", "")
    if not text or not text.strip().startswith("/"):
        return None

    user = message.get("from") or {}
    user_id = user.get("id")

    chat = message.get("chat") or {}
    chat_id = chat.get("id")

    thread_id = message.get("message_thread_id")

    return await handle_admin_telegram_command(
        text=text,
        user_id=user_id,
        chat_id=chat_id,
        message_thread_id=thread_id,
        db=db,
    )


async def start_telegram_polling() -> None:
    """
    Background polling worker that listens for Telegram updates via Bot API getUpdates.
    Automatically sleeps or gracefully terminates if token is not configured.
    """
    token = settings.TELEGRAM_BOT_TOKEN
    if not token or any(p in str(token) for p in ("твой_токен", "your_token", "xxx", "None")):
        logger.info("[TELEGRAM] Polling skipped (no valid TELEGRAM_BOT_TOKEN configured).")
        return

    logger.info("[TELEGRAM] Starting Telegram admin command polling worker...")
    offset = 0
    clean_token = str(token).strip()
    url = f"https://api.telegram.org/bot{clean_token}/getUpdates"

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            try:
                resp = await client.get(url, params={"offset": offset, "timeout": 20})
                if resp.status_code == 200:
                    payload = resp.json()
                    for item in payload.get("result", []):
                        offset = max(offset, item["update_id"] + 1)
                        try:
                            await process_telegram_update(item)
                        except Exception as proc_e:
                            logger.error(f"[TELEGRAM] Error handling update {item.get('update_id')}: {proc_e}")
                elif resp.status_code in (401, 404):
                    logger.warning(
                        f"[TELEGRAM] Telegram Bot API returned {resp.status_code}. "
                        f"Check TELEGRAM_BOT_TOKEN. Polling stopped."
                    )
                    break
                elif resp.status_code == 409:
                    # Conflict: another instance or webhook is active
                    logger.warning("[TELEGRAM] getUpdates conflict (HTTP 409). Retrying in 15s...")
                    await asyncio.sleep(15.0)
                else:
                    await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                logger.info("[TELEGRAM] Polling worker received cancellation. Shutting down.")
                break
            except Exception as e:
                logger.warning(f"[TELEGRAM] Polling error: {e}. Retrying in 5s...")
                await asyncio.sleep(5.0)
