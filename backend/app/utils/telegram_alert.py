"""
Telegram alert utilities and re-exports.
Allows clean importing from app.utils.telegram_alert as well as app.services.telegram_alert.
"""
from app.services.telegram_alert import (
    send_telegram_invoice_notification,
    build_telegram_invoice_message,
    send_telegram_alert,
    send_telegram_feedback,
    send_telegram_message,
    mask_email,
)

__all__ = [
    "send_telegram_invoice_notification",
    "build_telegram_invoice_message",
    "send_telegram_alert",
    "send_telegram_feedback",
    "send_telegram_message",
    "mask_email",
]
