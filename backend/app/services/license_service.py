import math
import logging
import secrets
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.license import Device, AccessKey

logger = logging.getLogger("tarkapp.license")

TRIAL_DURATION_DAYS: int = 14
DEFAULT_FREE_REVIEWS: int = 5
KEY_CHAR_SET: str = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def check_device_access(device_id: str, db: Session) -> Dict[str, Any]:
    """
    Checks or registers a device by device_id.
    - If device is not in database, automatically grants a 14-day trial period and 5 free reviews.
    - Compares trial_expires_at against server UTC time (cannot be spoofed by phone time changes).
    - Returns status dictionary: { allowed, is_active, has_key, free_reviews_left, max_free_reviews, days_left, expires_at, device_id, activated_key }.
    """
    clean_id = (device_id or "").strip()
    if not clean_id:
        clean_id = "unknown-device"

    now = datetime.utcnow()
    device = db.query(Device).filter(Device.device_id == clean_id).first()
    is_dev = (
        settings.APP_ENV in ("development", "test")
        and clean_id in ("dev-test-device", "default-dev-device")
    )

    if not device:
        # First seen: create new device with 14-day trial and 5 free reviews
        expires_at = now + timedelta(days=365 if is_dev else TRIAL_DURATION_DAYS)
        device = Device(
            device_id=clean_id,
            first_seen_at=now,
            trial_expires_at=expires_at,
            has_active_access=True,
            activated_key="DEV-KEY-TEST" if is_dev else None,
            free_reviews_left=DEFAULT_FREE_REVIEWS,
        )
        db.add(device)
        db.commit()
        db.refresh(device)
        logger.info(
            f"[LICENSE] Registered new device {clean_id} with 14-day trial until {expires_at.isoformat()}Z "
            f"and {DEFAULT_FREE_REVIEWS} free reviews."
        )

    # For dev-test-device, always keep active
    if is_dev and not device.activated_key:
        device.activated_key = "DEV-KEY-TEST"
        device.has_active_access = True
        device.trial_expires_at = now + timedelta(days=365)
        db.commit()

    is_allowed = is_dev or (device.trial_expires_at > now)
    has_key = is_dev or bool(device.activated_key and device.activated_key.strip() and is_allowed)

    # Keep has_active_access in sync
    if device.has_active_access != is_allowed:
        device.has_active_access = is_allowed
        db.commit()

    delta = device.trial_expires_at - now
    if delta.total_seconds() > 0:
        days_left = max(1, math.ceil(delta.total_seconds() / 86400))
    else:
        days_left = 0

    package_name = None
    if has_key:
        if device.activated_key:
            key_code = device.activated_key.strip().upper()
            if key_code == "DEV-KEY-TEST":
                package_name = "PRO"
            else:
                key_obj = db.query(AccessKey).filter(AccessKey.key_code == device.activated_key).first()
                if key_obj:
                    dur = key_obj.duration_days or 30
                    if dur >= 360:
                        package_name = "12 месяцев"
                    elif dur >= 240:
                        package_name = "Учебный год"
                    elif dur >= 120:
                        package_name = "Семестр"
                    elif dur >= 25:
                        package_name = "1 месяц"
                    else:
                        package_name = f"{dur} дн."
                elif "YEAR" in key_code or "9M" in key_code:
                    package_name = "Учебный год"
                elif "SEM" in key_code or "5M" in key_code:
                    package_name = "Семестр"
                elif "MONTH" in key_code or "1M" in key_code:
                    package_name = "1 месяц"
                elif "FULL" in key_code or "12M" in key_code:
                    package_name = "12 месяцев"
                else:
                    package_name = "PRO"
        else:
            package_name = "PRO"

    return {
        "allowed": is_allowed,
        "is_active": is_allowed,
        "has_key": has_key,
        "free_reviews_left": device.free_reviews_left,
        "max_free_reviews": DEFAULT_FREE_REVIEWS,
        "days_left": days_left,
        "expires_at": device.trial_expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "device_id": device.device_id,
        "activated_key": device.activated_key,
        "package_name": package_name,
    }


def verify_review_allowance(device_id: str, db: Session) -> Dict[str, Any]:
    """
    Verifies if device is permitted to request a textbook page analysis.
    - If device has an active paid/promo key -> unlimited access allowed.
    - If device is on trial: checks free_reviews_left > 0.
      Raises HTTP 403 REVIEWS_LIMIT_REACHED if free reviews ran out.
    - Raises HTTP 403 TRIAL_EXPIRED if 14-day trial expired.
    """
    clean_id = (device_id or "").strip()
    status_data = check_device_access(clean_id, db)

    # 1. Check general expiration
    if not status_data["allowed"]:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={"error": "TRIAL_EXPIRED", "message": "Срок действия пробного периода завершен"},
        )

    # 2. If device has activated key, unlimited reviews are granted
    if status_data["has_key"]:
        return status_data

    # 3. Trial mode: check remaining free reviews
    if status_data["free_reviews_left"] <= 0:
        logger.warning(f"[LICENSE] Device {clean_id} reached 0 free reviews limit.")
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": "REVIEWS_LIMIT_REACHED",
                "message": "Бесплатные разборы закончились. Введите ключ доступа.",
            },
        )

    return status_data


def deduct_review_attempt(device_id: str, db: Session) -> int:
    """
    Deducts 1 free review attempt upon SUCCESSFUL lesson analysis generation.
    Does NOT deduct if an active key is present or if an error occurred.
    """
    clean_id = (device_id or "").strip()
    if not clean_id:
        return 0

    device = db.query(Device).filter(Device.device_id == clean_id).first()
    if not device:
        return 0

    now = datetime.utcnow()
    has_key = bool(device.activated_key and device.activated_key.strip() and device.trial_expires_at > now)

    # Paid / Promo key users enjoy unlimited reviews without deduction
    if has_key:
        return device.free_reviews_left

    # Deduct 1 review for trial users
    if device.free_reviews_left > 0:
        device.free_reviews_left -= 1
        db.commit()
        db.refresh(device)
        logger.info(
            f"[LICENSE] Deducted 1 review attempt for device {clean_id}. "
            f"Remaining: {device.free_reviews_left}/{DEFAULT_FREE_REVIEWS}"
        )

    return device.free_reviews_left


def activate_key(device_id: str, key_code: str, db: Session) -> Dict[str, Any]:
    """
    Activates an access promo key for a given device.
    - Validates key existence and unused status.
    - Extends device access: adds duration_days to existing expiry if active, or to now if expired.
    - Marks key as used and binds to device.
    - Unlocks unlimited reviews.
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
            free_reviews_left=DEFAULT_FREE_REVIEWS,
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

    if duration >= 360:
        package_name = "12 месяцев"
    elif duration >= 240:
        package_name = "Учебный год"
    elif duration >= 120:
        package_name = "Семестр"
    elif duration >= 25:
        package_name = "1 месяц"
    else:
        package_name = f"{duration} дн."

    return {
        "success": True,
        "message": f"Ключ успешно активирован! Доступ продлен на {duration} дней.",
        "is_active": True,
        "has_key": True,
        "free_reviews_left": device.free_reviews_left,
        "max_free_reviews": DEFAULT_FREE_REVIEWS,
        "days_left": days_left,
        "expires_at": expires_str,
        "package_name": package_name,
    }


# ==========================================
# Administrative Key Management & Analytics
# ==========================================

def generate_key_code(prefix: str = "TARK") -> str:
    """Generates an unambiguous, cryptographically secure readable key code (e.g. TARK-A7B2-C9D4)."""
    clean_prefix = (prefix or "TARK").strip().upper()
    part1 = "".join(secrets.choice(KEY_CHAR_SET) for _ in range(4))
    part2 = "".join(secrets.choice(KEY_CHAR_SET) for _ in range(4))
    return f"{clean_prefix}-{part1}-{part2}"


def generate_access_keys(
    count: int = 20,
    days: int = 30,
    prefix: str = "TARK",
    db: Optional[Session] = None,
) -> List[str]:
    """
    Generates a batch of unique cryptographic access keys, saves them in the database with is_used=False,
    and returns the list of generated key codes.
    """
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True

    try:
        created_keys: List[str] = []
        now = datetime.utcnow()
        attempts = 0
        max_attempts = max(count * 10, 100)

        while len(created_keys) < count and attempts < max_attempts:
            attempts += 1
            code = generate_key_code(prefix)

            # Ensure global uniqueness
            existing = db.query(AccessKey).filter(AccessKey.key_code == code).first()
            if existing or code in created_keys:
                continue

            key_obj = AccessKey(
                key_code=code,
                duration_days=days,
                is_used=False,
                used_by_device=None,
                created_at=now,
                used_at=None,
            )
            db.add(key_obj)
            created_keys.append(code)

        db.commit()
        logger.info(f"[LICENSE] Generated {len(created_keys)} new access keys with duration {days} days.")
        return created_keys
    finally:
        if should_close:
            db.close()


def get_keys_stats(db: Optional[Session] = None) -> Dict[str, Any]:
    """
    Returns administrative statistics:
    - total registered devices
    - total keys
    - free (unused) keys
    - active keys (used and access hasn't expired yet)
    - expired keys (used and access has expired)
    """
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True

    try:
        now = datetime.utcnow()
        total_devices = db.query(Device).count()
        total_keys = db.query(AccessKey).count()
        free_keys = db.query(AccessKey).filter(AccessKey.is_used == False).count()

        used_rows = (
            db.query(AccessKey, Device)
            .outerjoin(Device, AccessKey.used_by_device == Device.device_id)
            .filter(AccessKey.is_used == True)
            .all()
        )

        active_keys = 0
        expired_keys = 0

        for key_obj, device_obj in used_rows:
            if device_obj and device_obj.trial_expires_at:
                if device_obj.trial_expires_at > now:
                    active_keys += 1
                else:
                    expired_keys += 1
            elif key_obj.used_at:
                exp = key_obj.used_at + timedelta(days=key_obj.duration_days or 30)
                if exp > now:
                    active_keys += 1
                else:
                    expired_keys += 1
            else:
                active_keys += 1

        return {
            "total_devices": total_devices,
            "total_keys": total_keys,
            "free_keys": free_keys,
            "active_keys": active_keys,
            "expired_keys": expired_keys,
        }
    finally:
        if should_close:
            db.close()


def list_access_keys(
    filter_status: Optional[str] = None,
    db: Optional[Session] = None,
) -> List[Dict[str, Any]]:
    """
    Returns a structured list of access keys with calculated status (free | active | expired),
    bound device_id, activation date, and expiration date.
    Optional filter_status can be 'active', 'free', or 'expired'.
    """
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True

    try:
        now = datetime.utcnow()
        rows = (
            db.query(AccessKey, Device)
            .outerjoin(Device, AccessKey.used_by_device == Device.device_id)
            .order_by(AccessKey.created_at.desc())
            .all()
        )

        results: List[Dict[str, Any]] = []
        normalized_filter = (filter_status or "all").strip().lower()

        for key_obj, device_obj in rows:
            if not key_obj.is_used:
                status_code = "free"
                status_label = "Свободен"
                device_str = "-"
                used_str = "-"
                expires_str = "-"
            else:
                if device_obj and device_obj.trial_expires_at:
                    expiry_dt = device_obj.trial_expires_at
                elif key_obj.used_at:
                    expiry_dt = key_obj.used_at + timedelta(days=key_obj.duration_days or 30)
                else:
                    expiry_dt = None

                is_active = (expiry_dt > now) if expiry_dt else True
                status_code = "active" if is_active else "expired"
                status_label = "Активен" if is_active else "Истёк"
                device_str = key_obj.used_by_device or (device_obj.device_id if device_obj else "-")
                used_str = key_obj.used_at.strftime("%Y-%m-%d %H:%M") if key_obj.used_at else "-"
                expires_str = expiry_dt.strftime("%Y-%m-%d %H:%M") if expiry_dt else "-"

            if normalized_filter != "all" and normalized_filter != status_code:
                continue

            results.append({
                "key_code": key_obj.key_code,
                "duration_days": key_obj.duration_days,
                "status": status_code,
                "status_label": status_label,
                "device_id": device_str,
                "used_at": used_str,
                "expires_at": expires_str,
            })

        return results
    finally:
        if should_close:
            db.close()
