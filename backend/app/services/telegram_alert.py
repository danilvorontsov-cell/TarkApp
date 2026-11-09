import asyncio
import hashlib
import html
import json
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

ADMIN_INLINE_KEYBOARD: Dict[str, Any] = {
    "inline_keyboard": [
        [
            {"text": "📊 Статистика системы", "callback_data": "admin:stats"}
        ],
        [
            {"text": "🔑 Сгенерировать ключ на 1 мес", "callback_data": "admin:gen:1:30"}
        ],
        [
            {"text": "🎓 Сгенерировать ключ на Учебный год", "callback_data": "admin:gen:1:270"}
        ],
    ]
}


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
    reply_markup: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Sends a message to Telegram using Bot API sendMessage with optional topic routing (message_thread_id),
    custom target chat_id, and optional interactive reply_markup (inline keyboard).
    Silently skips if TELEGRAM_BOT_TOKEN or target chat ID are not configured.
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

    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    headers = {"Content-Type": "application/json; charset=utf-8"}
    content_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(telegram_url, content=content_bytes, headers=headers)
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


async def answer_telegram_callback_query(
    callback_query_id: str,
    text: Optional[str] = None,
    show_alert: bool = False,
) -> bool:
    """
    Acknowledges incoming callback query to remove loading spinner on inline button.
    """
    token = settings.TELEGRAM_BOT_TOKEN
    if not token or not callback_query_id:
        return False

    clean_token = str(token).strip()
    url = f"https://api.telegram.org/bot{clean_token}/answerCallbackQuery"
    payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = show_alert

    headers = {"Content-Type": "application/json; charset=utf-8"}
    content_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(url, content=content_bytes, headers=headers)
            return resp.status_code == 200
    except Exception as e:
        logger.warning(f"Failed to answer callback query {callback_query_id}: {e}")
        return False


async def register_telegram_bot_commands() -> bool:
    """
    Registers command list in Telegram via Bot API setMyCommands:
    * /commands — показать все доступные команды и быстрые кнопки
    * /stats — статистика пользователей и активных лицензий
    * /gen — инструкция по генерации ключей доступа
    * /help — помощь по работе с ботом
    """
    token = settings.TELEGRAM_BOT_TOKEN
    if not token or any(p in str(token) for p in ("твой_токен", "your_token", "xxx", "None")):
        return False

    clean_token = str(token).strip()
    url = f"https://api.telegram.org/bot{clean_token}/setMyCommands"
    payload = {
        "commands": [
            {"command": "commands", "description": "Показать все доступные команды и быстрые кнопки"},
            {"command": "stats", "description": "Статистика пользователей и активных лицензий"},
            {"command": "gen", "description": "Инструкция по генерации ключей доступа"},
            {"command": "tts_last", "description": "Последний запрос и SSML озвучки"},
            {"command": "tts_errors", "description": "Последняя ошибка синтеза речи"},
            {"command": "help", "description": "Помощь по работе с ботом"},
        ]
    }
    headers = {"Content-Type": "application/json; charset=utf-8"}
    content_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, content=content_bytes, headers=headers)
            if resp.status_code == 200 and resp.json().get("ok"):
                logger.info("[TELEGRAM] Bot command menu successfully registered via setMyCommands.")
                return True
            else:
                logger.warning(f"[TELEGRAM] setMyCommands returned {resp.status_code}: {resp.text}")
                return False
    except Exception as e:
        logger.warning(f"[TELEGRAM] Failed to call setMyCommands: {e}")
        return False


async def send_telegram_invoice_notification(
    invoice_number: str,
    viitenumber: str,
    plan_title: str,
    amount_eur: str,
    customer_email: str,
    device_id: str,
    message_thread_id: Optional[int] = None,
) -> bool:
    """
    Sends transparent notification to Telegram when a customer requests a bank transfer invoice:
    🧾 Новый запрос счёта (Arve)
    • Номер инвойса: INV-2026-XXXX
    • Тариф: Учебный год (71.90 €)
    • Viitenumber для сверки: XXXXXXX
    • Email плательщика: user@example.com
    • ID устройства: xxxxxxxx
    """
    target_thread = (
        message_thread_id
        if message_thread_id is not None
        else (settings.TELEGRAM_TOPIC_INVOICES or settings.TELEGRAM_TOPIC_FEATURES)
    )

    clean_inv = html.escape(str(invoice_number or "").strip())
    clean_viite = html.escape(str(viitenumber or "").strip())
    clean_plan = html.escape(str(plan_title or "").strip())
    clean_amount = html.escape(str(amount_eur or "").strip())
    clean_email = html.escape(str(customer_email or "").strip()) or "Не указан"
    clean_dev = html.escape(str(device_id or "").strip()) or "Unknown"

    text = (
        f"🧾 <b>Новый запрос счёта (Arve)</b>\n\n"
        f"• <b>Номер инвойса:</b> <code>{clean_inv}</code>\n"
        f"• <b>Тариф:</b> {clean_plan} ({clean_amount} €)\n"
        f"• <b>Viitenumber для сверки:</b> <code>{clean_viite}</code>\n"
        f"• <b>Email плательщика:</b> {clean_email}\n"
        f"• <b>ID устройства:</b> <code>{clean_dev}</code>"
    )

    return await send_telegram_message(
        text=text,
        parse_mode="HTML",
        message_thread_id=target_thread,
    )


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

    action_hint = ""
    if "402" in raw_exc_msg or "RESOURCE_EXHAUSTED" in raw_exc_msg or "prepayment credits" in raw_exc_msg.lower() or "баланс" in raw_exc_msg.lower():
        action_hint = (
            "\n\n💡 <b>ДЕЙСТВИЕ:</b> Исчерпаны предоплаченные кредиты Google AI Studio (402)!\n"
            "Пополните баланс на <a href='https://ai.studio/projects'>ai.studio/projects</a> или обновите <code>GEMINI_API_KEY</code> в <code>backend/.env</code>."
        )

    message_text = (
        f"🚨 <b>[TarkApp Critical Alert]</b>\n\n"
        f"🌐 <b>Эндпоинт:</b> <code>{html.escape(endpoint)}</code>\n"
        f"❌ <b>Ошибка:</b> <code>{html.escape(exc_type)}: {html.escape(exc_message)}</code>\n"
        f"⏱ <b>Время:</b> {now_str}\n"
        f"🔑 <b>Hash:</b> <code>{error_hash[:12]}</code>"
        f"{action_hint}"
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


def _resolve_trusted_admin_chat_id(incoming_chat_id: Optional[Union[str, int]]) -> Optional[str]:
    """
    Strictly resolves the destination chat_id for sensitive admin command outputs (/gen, /stats).
    Ignores arbitrary untrusted chat.id values from incoming webhook JSON payloads.
    """
    admin_id = str(settings.ADMIN_TELEGRAM_ID or "").strip()
    configured_chat = str(settings.telegram_chat_id or "").strip()
    trusted_ids = {cid for cid in (admin_id, configured_chat) if cid}
    if not trusted_ids:
        return None
    if incoming_chat_id is not None and str(incoming_chat_id).strip() in trusted_ids:
        return str(incoming_chat_id).strip()
    return admin_id or configured_chat


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
    Sends admin command outputs strictly to trusted ADMIN_TELEGRAM_ID / TELEGRAM_CHAT_ID.
    """
    clean_text = (text or "").strip()
    if not clean_text.startswith("/"):
        return {"handled": False}

    # 1. Authorization check
    if not is_admin_user(user_id):
        raw_uid = str(user_id or "Неизвестный")
        logger.warning(f"[TELEGRAM] Unauthorized command attempt '{clean_text}' from user_id={raw_uid}")
        reply_msg = (
            f"⛔ <b>Доступ запрещен</b>\n\n"
            f"Ваш Telegram ID: <code>{html.escape(raw_uid)}</code>\n\n"
            f"Для авторизации укажите этот ID в переменной <code>ADMIN_TELEGRAM_ID</code> в файле <code>backend/.env</code>."
        )
        if chat_id:
            await send_telegram_message(
                text=reply_msg,
                chat_id=chat_id,
                parse_mode="HTML",
                message_thread_id=message_thread_id,
            )
        return {
            "handled": True,
            "authorized": False,
            "error": "UNAUTHORIZED",
            "reply": reply_msg,
        }

    # Strictly pin destination chat to trusted ADMIN_TELEGRAM_ID / TELEGRAM_CHAT_ID (ignore forged chat_id)
    target_chat = _resolve_trusted_admin_chat_id(chat_id)
    if incoming_mismatch := (
        chat_id is not None
        and target_chat is not None
        and str(chat_id).strip() != target_chat
    ):
        logger.warning(
            f"[TELEGRAM] Ignored untrusted chat_id={chat_id} for admin command '{clean_text}'; routing strictly to trusted {target_chat}."
        )
        message_thread_id = None

    # 2. Parse command name and arguments (support /gen@bot_name syntax)
    tokens = clean_text.split()
    command = tokens[0].split("@")[0].lower()
    args = tokens[1:]

    # 3. Handle /gen <count> <days> or /gen without args
    if command == "/gen":
        if not args:
            reply_msg = (
                f"🔑 <b>Инструкция по генерации ключей доступа</b>\n\n"
                f"Формат команды: <code>/gen &lt;кол-во&gt; &lt;дни&gt;</code>\n\n"
                f"💡 <b>Примеры:</b>\n"
                f"• <code>/gen 1 30</code> — 1 ключ на 1 месяц (30 дней)\n"
                f"• <code>/gen 3 150</code> — 3 ключа на семестр (150 дней)\n"
                f"• <code>/gen 5 270</code> — 5 ключей на учебный год (270 дней)\n"
                f"• <code>/gen 1 365</code> — 1 ключ на полный год (365 дней)\n\n"
                f"<i>Либо воспользуйтесь быстрыми кнопками ниже:</i>"
            )
            if target_chat:
                await send_telegram_message(
                    text=reply_msg,
                    parse_mode="HTML",
                    message_thread_id=message_thread_id,
                    chat_id=target_chat,
                    reply_markup=ADMIN_INLINE_KEYBOARD,
                )
            return {
                "handled": True,
                "authorized": True,
                "command": "gen_help",
                "reply": reply_msg,
            }

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
                reply_markup=ADMIN_INLINE_KEYBOARD,
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
                reply_markup=ADMIN_INLINE_KEYBOARD,
            )

        return {
            "handled": True,
            "authorized": True,
            "command": "stats",
            "stats": stats,
            "reply": reply_msg,
        }

    # 5. Handle /tts_last and /tts_errors
    elif command in ("/tts_last", "/tts_errors"):
        from app.models.tts_audit import TTSAuditLog
        sess = db or SessionLocal()
        try:
            query = sess.query(TTSAuditLog)
            if command == "/tts_errors":
                query = query.filter((TTSAuditLog.status != "SUCCESS") | (TTSAuditLog.error_message.isnot(None)))
            log_record = query.order_by(TTSAuditLog.id.desc()).first()

            if not log_record:
                reply_msg = f"🎙 <b>{'Ошибок' if command == '/tts_errors' else 'Записей'} синтеза речи пока не зафиксировано.</b>"
            else:
                acc_label = "✅ Да" if log_record.has_accents else "❌ Нет"
                est_label = "✅ Да" if log_record.has_estonian else "❌ Нет"
                speech_label = "✅ Да (is_speech_text)" if log_record.is_speech_text else "ℹ️ Обычный"
                status_icon = "🟢" if log_record.status == "SUCCESS" else "🔴"
                time_str = log_record.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')
                raw_ssml = (log_record.final_ssml or "").strip()
                safe_ssml = html.escape(raw_ssml[:1800])
                if len(raw_ssml) > 1800:
                    safe_ssml += "\n... [truncated]"

                reply_msg = (
                    f"🎙 <b>Аудит TTS #{log_record.id} {status_icon} ({log_record.status})</b>\n\n"
                    f"📅 <b>Время:</b> <code>{time_str}</code>\n"
                    f"🔗 <b>Эндпоинт:</b> <code>{html.escape(log_record.endpoint or '')}</code>\n"
                    f"🏷 <b>Слой:</b> {speech_label} | <b>Кэш:</b> <code>{log_record.cache_status or 'N/A'}</code>\n"
                    f"⏱ <b>Длительность:</b> {log_record.duration_ms or 0:.1f} мс\n"
                    f"🔤 <b>Ударения:</b> {acc_label} | <b>Эстонские теги:</b> {est_label}\n\n"
                    f"📝 <b>Входящий текст:</b>\n<code>{html.escape(log_record.incoming_text[:600])}</code>\n\n"
                    f"📄 <b>Результирующий SSML:</b>\n<code>{safe_ssml}</code>"
                )
                if log_record.error_message:
                    reply_msg += f"\n\n⚠️ <b>Ошибка:</b>\n<code>{html.escape(log_record.error_message)}</code>"
        finally:
            if not db:
                sess.close()

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
            "command": command.replace("/", ""),
            "reply": reply_msg,
        }

    # 6. Handle /commands, /help or /start
    elif command in ("/commands", "/help", "/start"):
        reply_msg = (
            f"🛠 <b>Административная панель TarkApp</b>\n\n"
            f"📋 <b>Доступные команды:</b>\n"
            f"• <code>/commands</code> — показать все доступные команды и быстрые кнопки\n"
            f"• <code>/stats</code> — статистика пользователей и активных лицензий\n"
            f"• <code>/gen &lt;кол-во&gt; &lt;дни&gt;</code> — генерация ключей доступа\n"
            f"• <code>/tts_last</code> — последний запрос и SSML озвучки\n"
            f"• <code>/tts_errors</code> — последняя ошибка синтеза речи\n"
            f"• <code>/help</code> — помощь по работе с ботом\n\n"
            f"💡 <b>Примеры генерации ключей:</b>\n"
            f"• <code>/gen 1 30</code> — 1 ключ на 1 месяц (30 дней)\n"
            f"• <code>/gen 3 150</code> — 3 ключа на семестр (150 дней)\n"
            f"• <code>/gen 5 270</code> — 5 ключей на учебный год (270 дней)\n"
            f"• <code>/gen 1 365</code> — 1 ключ на полный год с каникулами (365 дней)\n\n"
            f"<i>💡 Нажмите кнопку ниже для быстрого действия:</i>"
        )

        if target_chat:
            await send_telegram_message(
                text=reply_msg,
                parse_mode="HTML",
                message_thread_id=message_thread_id,
                chat_id=target_chat,
                reply_markup=ADMIN_INLINE_KEYBOARD,
            )

        return {
            "handled": True,
            "authorized": True,
            "command": "commands" if command == "/commands" else "help",
            "reply": reply_msg,
        }

    # 6. Unknown command
    else:
        reply_msg = (
            f"❓ Команда <code>{html.escape(command)}</code> не распознана.\n"
            f"Используйте <code>/commands</code> или <code>/help</code> для списка доступных команд."
        )
        if target_chat:
            await send_telegram_message(
                text=reply_msg,
                parse_mode="HTML",
                message_thread_id=message_thread_id,
                chat_id=target_chat,
                reply_markup=ADMIN_INLINE_KEYBOARD,
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
    Inspects an incoming Telegram update payload and dispatches commands or callback queries.
    Used by webhook endpoints and background polling loops.
    """
    # 1. Handle Inline Keyboard Callback Queries
    callback_query = update.get("callback_query")
    if callback_query:
        cb_id = callback_query.get("id")
        if cb_id:
            try:
                await answer_telegram_callback_query(cb_id)
            except Exception as cb_err:
                logger.warning(f"[TELEGRAM] Failed answering callback query: {cb_err}")

        user = callback_query.get("from") or {}
        user_id = user.get("id")
        msg = callback_query.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        thread_id = msg.get("message_thread_id")
        cb_data = str(callback_query.get("data") or "").strip()

        if cb_data == "admin:stats":
            return await handle_admin_telegram_command(
                text="/stats",
                user_id=user_id,
                chat_id=chat_id,
                message_thread_id=thread_id,
                db=db,
            )
        elif cb_data.startswith("admin:gen:"):
            parts = cb_data.split(":")
            cnt = parts[2] if len(parts) > 2 else "1"
            days = parts[3] if len(parts) > 3 else "30"
            return await handle_admin_telegram_command(
                text=f"/gen {cnt} {days}",
                user_id=user_id,
                chat_id=chat_id,
                message_thread_id=thread_id,
                db=db,
            )
        elif cb_data in ("admin:commands", "admin:help"):
            return await handle_admin_telegram_command(
                text="/commands",
                user_id=user_id,
                chat_id=chat_id,
                message_thread_id=thread_id,
                db=db,
            )
        return {"handled": False, "callback_data": cb_data}

    # 2. Handle Text Commands
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
    await register_telegram_bot_commands()
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
