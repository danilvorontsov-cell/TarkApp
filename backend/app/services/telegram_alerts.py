"""
Re-export module for telegram alerting services.
Provides seamless import compatibility for both telegram_alert and telegram_alerts.
"""
from app.services.telegram_alert import (
    send_telegram_message,
    send_telegram_alert,
    send_telegram_feedback,
    send_telegram_invoice_notification,
    compute_error_hash,
    clear_alert_history,
    get_alert_history,
    _ALERT_HISTORY,
    _ALERT_DEBOUNCE_SECONDS,
    ADMIN_INLINE_KEYBOARD,
    is_admin_user,
    handle_admin_telegram_command,
    process_telegram_update,
    start_telegram_polling,
    register_telegram_bot_commands,
    answer_telegram_callback_query,
)

__all__ = [
    "send_telegram_message",
    "send_telegram_alert",
    "send_telegram_feedback",
    "send_telegram_invoice_notification",
    "compute_error_hash",
    "clear_alert_history",
    "get_alert_history",
    "_ALERT_HISTORY",
    "_ALERT_DEBOUNCE_SECONDS",
    "ADMIN_INLINE_KEYBOARD",
    "is_admin_user",
    "handle_admin_telegram_command",
    "process_telegram_update",
    "start_telegram_polling",
    "register_telegram_bot_commands",
    "answer_telegram_callback_query",
]
