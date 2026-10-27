import math
import logging
from datetime import datetime, timedelta
from typing import Dict, Any
from sqlalchemy.orm import Session

from app.models.license import Device, AccessKey

logger = logging.getLogger("tarkapp.license")

TRIAL_DURATION_DAYS: int = 14


def check_device_access(device_id: str, db: Session) -> Dict[str, Any]:
    """
    Checks or registers a device by device_id.
    - If device is not in database, automatically grants a 14-day trial period.
    - Compares trial_expires_at against server UTC time (cannot be spoofed by phone time changes).
    - Returns status dictionary: { allowed, days_left, expires_at, device_id, activated_key }.
    """
    clean_id = (device_id or "").strip()
    if not clean_id:
        clean_id = "unknown-device"

    now = datetime.utcnow()
    device = db.query(Device).filter(Device.device_id == clean_id).first()

    if not device:
        # First seen: create new device with 14-day trial
        expires_at = now + timedelta(days=TRIAL_DURATION_DAYS)
        device = Device(
            device_id=clean_id,
            first_seen_at=now,
            trial_expires_at=expires_at,
            has_active_access=True,
            activated_key=None,
        )
        db.add(device)
        db.commit()
        db.refresh(device)
        logger.info(f"[LICENSE] Registered new device {clean_id} with 14-day trial until {expires_at.isoformat()}Z")

    is_allowed = device.trial_expires_at > now

    # Keep has_active_access in sync
    if device.has_active_access != is_allowed:
        device.has_active_access = is_allowed
        db.commit()

    delta = device.trial_expires_at - now
    if delta.total_seconds() > 0:
        days_left = max(1, math.ceil(delta.total_seconds() / 86400))
    else:
        days_left = 0

    return {
        "allowed": is_allowed,
        "is_active": is_allowed,
        "days_left": days_left,
        "expires_at": device.trial_expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "device_id": device.device_id,
        "activated_key": device.activated_key,
    }


def activate_key(device_id: str, key_code: str, db: Session) -> Dict[str, Any]:
    """
    Activates an access promo key for a given device.
    - Validates key existence and unused status.
    - Extends device access: adds duration_days to existing expiry if active, or to now if expired.
    - Marks key as used and binds to device.
    """
    clean_dev_id = (device_id or "").strip()
    if not clean_dev_id:
        raise ValueError("Device ID не может быть пустым")

    clean_key = (key_code or "").strip().upper()
    if not clean_key:
        raise ValueError("Код ключа не может быть пустым")

    now = datetime.utcnow()

    # Ensure device exists (or registers it)
    device = db.query(Device).filter(Device.device_id == clean_dev_id).first()
    if not device:
        device = Device(
            device_id=clean_dev_id,
            first_seen_at=now,
            trial_expires_at=now + timedelta(days=TRIAL_DURATION_DAYS),
            has_active_access=True,
            activated_key=None,
        )
        db.add(device)
        db.commit()
        db.refresh(device)

    # Check access key
    key_obj = db.query(AccessKey).filter(AccessKey.key_code == clean_key).first()
    if not key_obj:
        raise ValueError("Ключ доступа не найден. Проверьте правильность ввода.")

    if key_obj.is_used:
        raise ValueError("Этот ключ доступа уже был активирован ранее.")

    # Extend trial/access
    duration = key_obj.duration_days or 30
    if device.trial_expires_at > now:
        device.trial_expires_at = device.trial_expires_at + timedelta(days=duration)
    else:
        device.trial_expires_at = now + timedelta(days=duration)

    device.has_active_access = True
    device.activated_key = key_obj.key_code

    # Mark key as used
    key_obj.is_used = True
    key_obj.used_by_device = device.device_id
    key_obj.used_at = now

    db.commit()
    db.refresh(device)

    delta = device.trial_expires_at - now
    days_left = max(1, math.ceil(delta.total_seconds() / 86400))
    expires_str = device.trial_expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    logger.info(
        f"[LICENSE] Activated key {clean_key} (+{duration}d) for device {clean_dev_id}. "
        f"New expiry: {expires_str}"
    )

    return {
        "success": True,
        "message": f"Ключ успешно активирован! Доступ продлен на {duration} дней.",
        "is_active": True,
        "days_left": days_left,
        "expires_at": expires_str,
    }
