import math
import logging
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from fastapi import HTTPException, status as http_status
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.license import Device, AccessKey, Invoice

logger = logging.getLogger("tarkapp.license")

BETA_TRIAL_DURATION_DAYS: int = 14
BETA_DEFAULT_FREE_REVIEWS: int = 20
PROD_TRIAL_DURATION_DAYS: int = 5
PROD_DEFAULT_FREE_REVIEWS: int = 10
TRIAL_DURATION_DAYS: int = 14
DEFAULT_FREE_REVIEWS: int = 20
KEY_CHAR_SET: str = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

DEVICE_ID_REGEX = re.compile(r"^[a-zA-Z0-9._-]{16,64}$")

# 22 compromised access keys that were previously committed to repository history
REVOKED_COMPROMISED_KEYS = frozenset(
    {
        "TARK-3ZME-TA4W",
        "TARK-EP49-KRDZ",
        "TARK-THTA-DNKB",
        "TARK-EPUY-5S9Z",
        "TARK-SXE7-H99K",
        "TARK-A5F3-VVJF",
        "TARK-28ZJ-V62B",
        "TARK-PL9Q-C9J7",
        "TARK-X6SN-65V4",
        "TARK-HUYT-77W6",
        "TARK-9MTJ-U48J",
        "TARK-MVQY-GXKV",
        "TARK-GEH3-TSLH",
        "TARK-97E7-WYH6",
        "TARK-MFSC-8KB4",
        "TARK-CY6K-GQRV",
        "TARK-Z8TU-S7VK",
        "TARK-P3DL-7QVN",
        "TARK-D7AG-U9F2",
        "TARK-H2TD-X3Y6",
        "TARK-3RCF-UEYV",
        "TARK-BEXZ-ZZ7Y",
    }
)

PLAN_DURATIONS: Dict[str, int] = {
    "month_1": 30,
    "month": 30,
    "semester": 150,
    "school_year": 270,
    "year": 270,
    "full_year": 365,
}

PLAN_TITLES: Dict[str, str] = {
    "month_1": "1 месяц",
    "month": "1 месяц",
    "semester": "Семестр (5 месяцев)",
    "school_year": "Учебный год (9 месяцев)",
    "year": "Учебный год (9 месяцев)",
    "full_year": "Год с каникулами (12 месяцев)",
}


def validate_device_id(device_id: Optional[str]) -> str:
    """
    Validates X-Device-ID strictly against ^[a-zA-Z0-9._-]{16,64}$.
    Prevents arbitrary / malformed / SQLi / short / oversized device IDs from creating DB rows.
    """
    clean_id = (device_id or "").strip()
    if not DEVICE_ID_REGEX.match(clean_id):
        logger.warning(f"[LICENSE] Rejected invalid X-Device-ID format (len={len(clean_id)}).")
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "INVALID_DEVICE_ID",
                "message": "Некорректный идентификатор устройства X-Device-ID (ожидается 16–64 допустимых символа).",
            },
        )
    return clean_id


class TrialPolicy(tuple):
    def __new__(cls, duration_days: int, daily_reviews: int):
        return super().__new__(cls, (duration_days, daily_reviews))

    @property
    def duration_days(self) -> int:
        return self[0]

    @property
    def daily_reviews(self) -> int:
        return self[1]

    @property
    def days(self) -> int:
        return self[0]

    @property
    def daily_limit(self) -> int:
        return self[1]


def _get_trial_policy() -> Tuple[int, int]:
    """
    Returns (duration_days, daily_reviews) based on settings.TRIAL_MODE:
    - "production": PROD_TRIAL_DAYS (5 days), PROD_DAILY_REVIEWS (10 reviews/day)
    - "closed_beta" (default): BETA_TRIAL_DAYS (14 days), BETA_DAILY_REVIEWS (20 reviews/day)
    """
    mode = (getattr(settings, "TRIAL_MODE", "closed_beta") or "closed_beta").strip().lower()
    if mode == "production":
        duration_days = getattr(settings, "PROD_TRIAL_DAYS", PROD_TRIAL_DURATION_DAYS)
        daily_reviews = getattr(settings, "PROD_DAILY_REVIEWS", PROD_DEFAULT_FREE_REVIEWS)
        return TrialPolicy(duration_days, daily_reviews)
    duration_days = getattr(settings, "BETA_TRIAL_DAYS", BETA_TRIAL_DURATION_DAYS)
    daily_reviews = getattr(settings, "BETA_DAILY_REVIEWS", BETA_DEFAULT_FREE_REVIEWS)
    return TrialPolicy(duration_days, daily_reviews)


def check_device_access(device_id: str, db: Session) -> Dict[str, Any]:
    """
    Checks or registers a device by validated device_id.
    - Enforces ^[a-zA-Z0-9._-]{16,64}$ before reading/creating Device rows.
    - Supports both "closed_beta" (14d, 20/day) and "production" (5d, 10/day) via settings.TRIAL_MODE.
    """
    clean_id = validate_device_id(device_id)
    duration_days, daily_limit = _get_trial_policy()

    now = datetime.utcnow()
    today_str = now.strftime("%Y-%m-%d")
    device = db.query(Device).filter(Device.device_id == clean_id).first()

    if not device:
        expires_at = now + timedelta(days=duration_days)
        device = Device(
            device_id=clean_id,
            first_seen_at=now,
            trial_expires_at=expires_at,
            has_active_access=True,
            activated_key=None,
            free_reviews_left=daily_limit,
            max_free_reviews=daily_limit,
            last_review_date=today_str,
        )
        db.add(device)
        db.commit()
        db.refresh(device)
        mode = getattr(settings, "TRIAL_MODE", "closed_beta")
        logger.info(
            f"[LICENSE] Registered new device {clean_id} in mode={mode} until {expires_at.isoformat()}Z "
            f"with {daily_limit} free reviews (trial_days={duration_days})."
        )

    is_allowed = bool(device.trial_expires_at and device.trial_expires_at > now)
    has_key = bool(device.activated_key and device.activated_key.strip() and is_allowed)

    if device.has_active_access != is_allowed:
        device.has_active_access = is_allowed
        db.commit()

    device_last_date = getattr(device, "last_review_date", None)
    device_max_reviews = getattr(device, "max_free_reviews", None)
    is_trial_active = bool(device.trial_expires_at and device.trial_expires_at >= now)

    if not has_key:
        if is_trial_active:
            # При смене даты (last_review_date < today) и условии, что срок действия триала не истек (trial_expires_at >= now):
            # сбрасывать free_reviews_left до значения суточного лимита текущего режима (10 для prod, 20 для beta).
            date_changed = (device_last_date is None) or (device_last_date < today_str) or (device_last_date != today_str)
            needs_max_sync = device_max_reviews is None or device_max_reviews != daily_limit
            if date_changed:
                device.free_reviews_left = daily_limit
                device.max_free_reviews = daily_limit
                device.last_review_date = today_str
                db.commit()
                db.refresh(device)
                logger.info(
                    f"[LICENSE] Reset daily free reviews quota for device {clean_id} to {daily_limit}/{daily_limit} (date={today_str})"
                )
            elif needs_max_sync:
                device.max_free_reviews = daily_limit
                if device.free_reviews_left is not None and device.free_reviews_left > daily_limit:
                    device.free_reviews_left = daily_limit
                db.commit()
                db.refresh(device)
        else:
            # Если срок триала истек (trial_expires_at < now): сброс не производить.
            if device_max_reviews is None or device_max_reviews != daily_limit:
                device.max_free_reviews = daily_limit
                db.commit()
                db.refresh(device)

    delta = device.trial_expires_at - now if device.trial_expires_at else timedelta(0)
    if delta.total_seconds() > 0:
        days_left = max(1, math.ceil(delta.total_seconds() / 86400))
    else:
        days_left = 0

    package_name = None
    if has_key and device.activated_key:
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

    return {
        "allowed": is_allowed,
        "is_active": is_allowed,
        "has_key": has_key,
        "free_reviews_left": device.free_reviews_left,
        "max_free_reviews": getattr(device, "max_free_reviews", daily_limit) or daily_limit,
        "days_left": days_left,
        "expires_at": device.trial_expires_at.strftime("%Y-%m-%dT%H:%M:%SZ") if device.trial_expires_at else "",
        "device_id": device.device_id,
        "activated_key": device.activated_key if has_key else None,
        "package_name": package_name if has_key else None,
    }


def verify_review_allowance(device_id: str, db: Session) -> Dict[str, Any]:
    """
    Verifies if device is permitted to request a textbook page analysis.
    """
    clean_id = validate_device_id(device_id)
    status_data = check_device_access(clean_id, db)
    _, max_reviews = _get_trial_policy()

    if not status_data["allowed"]:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={"error": "TRIAL_EXPIRED", "message": "Срок действия пробного периода завершен"},
        )

    if status_data["has_key"]:
        return status_data

    if status_data["free_reviews_left"] <= 0:
        mode = getattr(settings, "TRIAL_MODE", "closed_beta")
        logger.warning(f"[LICENSE] Device {clean_id} reached 0 free reviews limit (mode={mode}).")
        limit_msg = f"Бесплатные разборы на сегодня закончились ({max_reviews}/{max_reviews}). Введите ключ доступа или возвращайтесь завтра."
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": "REVIEWS_LIMIT_REACHED",
                "message": limit_msg,
            },
        )

    return status_data


def deduct_review_attempt(device_id: str, db: Session) -> int:
    """
    Atomically deducts 1 review attempt with a single SQL UPDATE.
    Eliminates Check-Then-Act TOCTOU race conditions.

    If device has an active paid / PRO license (is_unlimited), reviews are not decremented,
    only total_reviews_used is incremented.

    If device is on free/trial allowance, decrements free_reviews_left only if > 0.
    If rowcount == 0, raises 403 REVIEWS_LIMIT_REACHED.
    """
    clean_id = (device_id or "").strip()
    if not clean_id:
        return 0

    now = datetime.utcnow()

    with db.transaction():
        device = db.query(Device).filter(Device.device_id == clean_id).first()
        if not device:
            return 0

        # Check if device has an active paid/unlimited license
        is_allowed = bool(device.trial_expires_at and device.trial_expires_at > now)
        has_key = bool(device.activated_key and device.activated_key.strip() and is_allowed)
        is_unlimited = has_key

        if is_unlimited:
            # For paid subscriptions and unlimited licenses, preserve free reviews balance without decrement
            db.execute(
                text(
                    "UPDATE devices "
                    "SET total_reviews_used = coalesce(total_reviews_used, 0) + 1 "
                    "WHERE device_id = :device_id"
                ),
                {"device_id": clean_id},
            )
            return device.free_reviews_left

        # Free / trial tier: atomic decrement with strict condition free_reviews_left > 0
        result = db.execute(
            text(
                "UPDATE devices "
                "SET free_reviews_left = free_reviews_left - 1, "
                "    total_reviews_used = coalesce(total_reviews_used, 0) + 1 "
                "WHERE device_id = :device_id AND free_reviews_left > 0"
            ),
            {"device_id": clean_id},
        )

        if result.rowcount == 0:
            logger.warning(
                f"[LICENSE] Atomic deduction rejected for device '{clean_id}': free_reviews_left <= 0 (TOCTOU blocked)."
            )
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "REVIEWS_LIMIT_REACHED",
                    "message": "Бесплатные разборы на сегодня закончились. Введите ключ доступа или возвращайтесь завтра.",
                },
            )

        # Read remaining count
        remaining = db.execute(
            text("SELECT free_reviews_left FROM devices WHERE device_id = :device_id"),
            {"device_id": clean_id},
        ).scalar()
        logger.info(f"[LICENSE] Atomically deducted 1 review for {clean_id}. Remaining: {remaining}")
        return remaining if remaining is not None else 0


def normalize_key_code(code: str) -> str:
    """Normalizes key code to canonical uppercase TARK-XXXX-XXXX format."""
    if not code:
        return ""
    s = str(code).strip().upper()
    s = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]", "-", s)
    s = re.sub(r"\s*-\s*", "-", s)
    s = "".join(s.split())
    if len(s) == 12 and "-" not in s and s.startswith("TARK"):
        s = f"{s[:4]}-{s[4:8]}-{s[8:12]}"
    return s


def revoke_compromised_keys(db: Session) -> int:
    """
    Marks the 22 compromised repository keys as is_used = True (is_used = 1)
    so they can never be redeemed on any device.
    """
    now = datetime.utcnow()
    revoked_count = 0
    try:
        for code in REVOKED_COMPROMISED_KEYS:
            existing = db.query(AccessKey).filter(func.upper(AccessKey.key_code) == code).first()
            if existing:
                if not existing.is_used:
                    existing.is_used = True
                    existing.used_by_device = existing.used_by_device or "REVOKED_REPO_KEY"
                    existing.used_at = existing.used_at or now
                    revoked_count += 1
            else:
                db.add(
                    AccessKey(
                        key_code=code,
                        duration_days=30,
                        is_used=True,
                        used_by_device="REVOKED_REPO_KEY",
                        created_at=now,
                        used_at=now,
                    )
                )
                revoked_count += 1
        if revoked_count > 0:
            db.commit()
            logger.info(f"[LICENSE] Marked {revoked_count} compromised repository keys as used/revoked.")
    except Exception as exc:
        logger.warning(f"[LICENSE] Could not revoke compromised keys: {exc}")
        db.rollback()
    return revoked_count


def sync_keys_from_file(db: Session, file_path: Optional[str] = None) -> int:
    """
    Syncs access keys from generated_keys.txt into the database ONLY in non-production environments,
    excluding any revoked repository keys.
    """
    if settings.APP_ENV == "production":
        logger.info("[LICENSE] Skipping sync_keys_from_file in production environment.")
        return 0

    candidates = [
        Path(file_path) if file_path else None,
        Path("generated_keys.txt"),
        Path(__file__).resolve().parent.parent.parent / "generated_keys.txt",
        Path("/app/generated_keys.txt"),
    ]
    target_file = next((p for p in candidates if p and p.exists() and p.is_file()), None)
    if not target_file:
        return 0

    added = 0
    try:
        content = target_file.read_text(encoding="utf-8")
        for line in content.splitlines():
            cleaned = normalize_key_code(line)
            if not cleaned or cleaned.startswith("#") or len(cleaned) < 4:
                continue
            if cleaned in REVOKED_COMPROMISED_KEYS:
                continue
            existing = db.query(AccessKey).filter(func.upper(AccessKey.key_code) == cleaned).first()
            if not existing:
                key_obj = AccessKey(
                    key_code=cleaned,
                    duration_days=30,
                    is_used=False,
                    used_by_device=None,
                    created_at=datetime.utcnow(),
                    used_at=None,
                )
                db.add(key_obj)
                added += 1
        if added > 0:
            db.commit()
            logger.info(f"[LICENSE] Seeded/synced {added} new keys from {target_file.name} into database.")
    except Exception as e:
        logger.warning(f"[LICENSE] Error syncing keys from {target_file}: {e}")
        db.rollback()
    return added


def activate_key(device_id: str, key_code: str, db: Session) -> Dict[str, Any]:
    """
    Activates an access promo key for a given device.
    """
    clean_dev_id = (device_id or "").strip()
    if not clean_dev_id:
        raise ValueError("Device ID не может быть пустым")

    clean_key = normalize_key_code(key_code)
    if not clean_key:
        raise ValueError("Код ключа не может быть пустым")

    if clean_key in REVOKED_COMPROMISED_KEYS:
        logger.warning(f"[LICENSE] Blocked activation of revoked key {clean_key} by device '{clean_dev_id}'")
        raise ValueError("Этот ключ доступа уже был активирован ранее или отозван.")

    now = datetime.utcnow()
    duration_days, max_reviews = _get_trial_policy()

    device = db.query(Device).filter(Device.device_id == clean_dev_id).first()
    if not device:
        device = Device(
            device_id=clean_dev_id,
            first_seen_at=now,
            trial_expires_at=now + timedelta(days=duration_days),
            has_active_access=True,
            activated_key=None,
            free_reviews_left=max_reviews,
            max_free_reviews=max_reviews,
            last_review_date=now.strftime("%Y-%m-%d"),
        )
        db.add(device)
        db.commit()
        db.refresh(device)

    key_obj = db.query(AccessKey).filter(func.upper(AccessKey.key_code) == clean_key).first()
    if not key_obj:
        clean_raw = clean_key.replace("-", "")
        for candidate in db.query(AccessKey).all():
            if candidate.key_code.replace("-", "").upper() == clean_raw:
                key_obj = candidate
                break

    if not key_obj and settings.APP_ENV != "production":
        sync_keys_from_file(db)
        key_obj = db.query(AccessKey).filter(func.upper(AccessKey.key_code) == clean_key).first()
        if not key_obj:
            clean_raw = clean_key.replace("-", "")
            for candidate in db.query(AccessKey).all():
                if candidate.key_code.replace("-", "").upper() == clean_raw:
                    key_obj = candidate
                    break

    if not key_obj:
        logger.warning(f"[LICENSE] Activation failed: key '{clean_key}' not found in database for device '{clean_dev_id}'.")
        raise ValueError("Ключ доступа не найден. Проверьте правильность ввода.")

    duration = key_obj.duration_days or 30
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

    if key_obj.is_used and key_obj.used_by_device == device.device_id:
        logger.info(f"[LICENSE] Key {clean_key} is already active for device {clean_dev_id}.")
        device.has_active_access = True
        device.activated_key = key_obj.key_code
        db.commit()
        db.refresh(device)

        delta = device.trial_expires_at - now
        days_left = max(1, math.ceil(delta.total_seconds() / 86400))
        expires_str = device.trial_expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")

        return {
            "success": True,
            "message": f"Ключ уже привязан к этому устройству! Доступ активен ({days_left} дн.).",
            "is_active": True,
            "has_key": True,
            "free_reviews_left": device.free_reviews_left,
            "max_free_reviews": max_reviews,
            "days_left": days_left,
            "expires_at": expires_str,
            "package_name": package_name,
        }

    with db.transaction():
        if key_obj.is_used:
            logger.warning(
                f"[LICENSE] Key {clean_key} already used by device '{key_obj.used_by_device}' (attempted by '{clean_dev_id}')"
            )
            raise ValueError("Этот ключ доступа уже был активирован ранее.")

        if device.trial_expires_at > now:
            device.trial_expires_at = device.trial_expires_at + timedelta(days=duration)
        else:
            device.trial_expires_at = now + timedelta(days=duration)

        device.has_active_access = True
        device.activated_key = key_obj.key_code

        key_obj.is_used = True
        key_obj.used_by_device = device.device_id
        key_obj.used_at = now

    delta = device.trial_expires_at - now
    days_left = max(1, math.ceil(delta.total_seconds() / 86400))
    expires_str = device.trial_expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    logger.info(
        f"[LICENSE] Successfully activated key {clean_key} (+{duration}d) for device {clean_dev_id}. "
        f"New expiry: {expires_str}"
    )

    return {
        "success": True,
        "message": f"Ключ успешно активирован! Доступ продлен на {duration} дней.",
        "is_active": True,
        "has_key": True,
        "free_reviews_left": device.free_reviews_left,
        "max_free_reviews": getattr(device, "max_free_reviews", max_reviews) or max_reviews,
        "days_left": days_left,
        "expires_at": expires_str,
        "package_name": package_name,
    }


def grant_plan_access(
    device_id: str,
    plan_id: str,
    db: Session,
    reference_info: Optional[str] = None,
) -> Dict[str, Any]:
    """Grants or extends device subscription based on PLAN_DURATIONS matrix."""
    clean_dev_id = (device_id or "").strip()
    if not clean_dev_id:
        raise ValueError("Device ID не может быть пустым")

    resolved_plan_id = (plan_id or "school_year").strip().lower()
    duration = PLAN_DURATIONS.get(resolved_plan_id, 30)
    package_name = PLAN_TITLES.get(resolved_plan_id, "PRO")
    duration_days, max_reviews = _get_trial_policy()

    now = datetime.utcnow()
    device = db.query(Device).filter(Device.device_id == clean_dev_id).first()
    if not device:
        expires_at = now + timedelta(days=duration)
        device = Device(
            device_id=clean_dev_id,
            first_seen_at=now,
            trial_expires_at=expires_at,
            has_active_access=True,
            activated_key=reference_info or f"PLAN-{resolved_plan_id.upper()}",
            free_reviews_left=max_reviews,
            max_free_reviews=max_reviews,
            last_review_date=now.strftime("%Y-%m-%d"),
        )
        db.add(device)
    else:
        if device.trial_expires_at > now:
            device.trial_expires_at = device.trial_expires_at + timedelta(days=duration)
        else:
            device.trial_expires_at = now + timedelta(days=duration)
        device.has_active_access = True
        device.activated_key = reference_info or device.activated_key or f"PLAN-{resolved_plan_id.upper()}"

    db.commit()
    db.refresh(device)

    delta = device.trial_expires_at - now
    days_left = max(1, math.ceil(delta.total_seconds() / 86400))
    expires_str = device.trial_expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    logger.info(
        f"[LICENSE] Granted {package_name} (+{duration}d) for device {clean_dev_id}. "
        f"New expiry: {expires_str}"
    )

    return {
        "success": True,
        "is_active": True,
        "has_key": True,
        "days_left": days_left,
        "expires_at": expires_str,
        "package_name": package_name,
        "duration_days": duration,
    }


def confirm_invoice_payment(
    invoice_number_or_viitenumber: str,
    db: Session,
) -> Dict[str, Any]:
    """
    Confirms an invoice payment idempotently:
    Executes atomic UPDATE ... WHERE invoice_number = :num AND is_paid = 0 and checks rowcount == 1.
    If the invoice was already paid, returns current subscription status WITHOUT stacking extra days.
    """
    query_str = (invoice_number_or_viitenumber or "").strip()
    if not query_str:
        raise ValueError("Номер счёта или viitenumber обязателен")

    inv = (
        db.query(Invoice)
        .filter(
            (Invoice.invoice_number == query_str)
            | (Invoice.viitenumber == query_str)
            | (func.upper(Invoice.invoice_number) == query_str.upper())
        )
        .first()
    )

    if not inv:
        raise ValueError(f"Инвойс с номером/viitenumber '{query_str}' не найден")

    now = datetime.utcnow()
    update_result = db.execute(
        text(
            "UPDATE invoices SET is_paid = 1, paid_at = :now "
            "WHERE invoice_number = :num AND (is_paid = 0 OR is_paid IS NULL)"
        ),
        {"now": now, "num": inv.invoice_number},
    )

    if update_result.rowcount != 1:
        db.commit()
        db.refresh(inv)
        device_id = (inv.device_id or "paid-device-000001").strip()
        dev = db.query(Device).filter(Device.device_id == device_id).first()
        resolved_plan_id = (inv.plan_id or "school_year").strip().lower()
        package_name = PLAN_TITLES.get(resolved_plan_id, "PRO")
        if dev and dev.trial_expires_at:
            delta = dev.trial_expires_at - now
            days_left = max(0, math.ceil(delta.total_seconds() / 86400)) if delta.total_seconds() > 0 else 0
            expires_str = dev.trial_expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")
            is_active = bool(dev.trial_expires_at > now)
        else:
            days_left = PLAN_DURATIONS.get(resolved_plan_id, 30)
            expires_str = (now + timedelta(days=days_left)).strftime("%Y-%m-%dT%H:%M:%SZ")
            is_active = True

        logger.info(f"[LICENSE] Idempotent confirm_invoice_payment skipped duplicate grant for {inv.invoice_number}.")
        return {
            "success": True,
            "already_paid": True,
            "message": f"Инвойс {inv.invoice_number} уже был оплачен ранее. Повторное начисление дней не требуется.",
            "invoice_number": inv.invoice_number,
            "viitenumber": inv.viitenumber,
            "is_active": is_active,
            "days_left": days_left,
            "expires_at": expires_str,
            "package_name": package_name,
        }

    db.commit()
    db.refresh(inv)

    device_id = (inv.device_id or "paid-device-000001").strip()
    grant_res = grant_plan_access(
        device_id=device_id,
        plan_id=inv.plan_id,
        db=db,
        reference_info=f"INVOICE:{inv.invoice_number}",
    )

    return {
        "success": True,
        "already_paid": False,
        "message": f"Оплата инвойса {inv.invoice_number} (Viitenumber: {inv.viitenumber}) подтверждена. Доступ активирован на {grant_res['duration_days']} дн.",
        "invoice_number": inv.invoice_number,
        "viitenumber": inv.viitenumber,
        "is_active": grant_res["is_active"],
        "days_left": grant_res["days_left"],
        "expires_at": grant_res["expires_at"],
        "package_name": grant_res["package_name"],
    }


def delete_device_and_data(device_id: str, db: Session) -> Dict[str, Any]:
    """
    GDPR Right-to-be-Forgotten erasure for a specific device_id:
    - Deletes any private invoice PDF files associated with this device_id
    - Anonymizes/removes Invoice PII records for this device_id
    - Detaches AccessKey bindings (preserving is_used=True so consumed keys cannot be reused)
    """
    clean_id = validate_device_id(device_id)
    invoices = db.query(Invoice).filter(Invoice.device_id == clean_id).all()
    deleted_pdfs = 0
    for inv in invoices:
        if inv.pdf_path:
            try:
                p = Path(inv.pdf_path)
                if p.exists() and p.is_file():
                    p.unlink()
                    deleted_pdfs += 1
            except Exception as err:
                logger.warning(f"[GDPR] Failed removing PDF {inv.pdf_path}: {err}")
        db.delete(inv)

    db.query(AccessKey).filter(AccessKey.used_by_device == clean_id).update(
        {"used_by_device": "DELETED_GDPR"},
        synchronize_session=False,
    )

    # Clear activated key PII binding on Device while keeping anti-abuse quota state intact
    dev = db.query(Device).filter(Device.device_id == clean_id).first()
    if dev:
        dev.activated_key = None

    db.commit()
    logger.info(f"[GDPR] Deleted PII & {len(invoices)} invoices ({deleted_pdfs} PDFs) for device {clean_id}.")
    return {"success": True, "deleted_invoices": len(invoices), "deleted_pdfs": deleted_pdfs}


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

            existing = db.query(AccessKey).filter(AccessKey.key_code == code).first()
            if existing or code in created_keys or code in REVOKED_COMPROMISED_KEYS:
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
    """Returns administrative statistics."""
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
    """Returns a structured list of access keys with calculated status (free | active | expired)."""
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
