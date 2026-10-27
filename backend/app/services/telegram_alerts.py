"""
Re-export module for telegram alerting services.
Provides seamless import compatibility for both telegram_alert and telegram_alerts.
"""
from app.services.telegram_alert import (
    send_telegram_message,
    send_telegram_alert,
    send_telegram_feedback,
    compute_error_hash,
    clear_alert_history,
    get_alert_history,
    _ALERT_HISTORY,
    _ALERT_DEBOUNCE_SECONDS,
)

__all__ = [
    "send_telegram_message",
    "send_telegram_alert",
    "send_telegram_feedback",
    "compute_error_hash",
    "clear_alert_history",
    "get_alert_history",
    "_ALERT_HISTORY",
    "_ALERT_DEBOUNCE_SECONDS",
]
