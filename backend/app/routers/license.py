import logging
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.limiter import safe_limit
from app.models.license import (
    LicenseStatusResponse,
    KeyActivateRequest,
    KeyActivateResponse,
)
from app.services import license_service

logger = logging.getLogger("tarkapp.license")

router = APIRouter(prefix="/api/v1/license", tags=["License"])


async def verify_device_access(
    x_device_id: Optional[str] = Header(None, alias="X-Device-ID"),
    db: Session = Depends(get_db),
):
    """
    FastAPI Dependency: verifies 14-day trial or active key for incoming device.
    Raises HTTP 403 Forbidden with {"error": "TRIAL_EXPIRED", "message": "..."} when trial expires.
    """
    device_id = (x_device_id or "").strip()
    if not device_id:
        if settings.APP_ENV in ("development", "test"):
            device_id = "dev-test-device"
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "TRIAL_EXPIRED", "message": "Заголовок X-Device-ID обязателен для проверки лицензии"},
            )

    check_res = license_service.check_device_access(device_id, db)
    if not check_res["allowed"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "TRIAL_EXPIRED", "message": "Срок действия пробного периода завершен"},
        )
    return check_res


async def verify_review_access(
    x_device_id: Optional[str] = Header(None, alias="X-Device-ID"),
    db: Session = Depends(get_db),
):
    """
    FastAPI Dependency for textbook review endpoints (/api/v1/analyze-page*).
    Verifies trial expiration and the 5 free reviews allowance.
    """
    device_id = (x_device_id or "").strip()
    if not device_id:
        if settings.APP_ENV in ("development", "test"):
            device_id = "dev-test-device"
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "TRIAL_EXPIRED", "message": "Заголовок X-Device-ID обязателен для проверки лицензии"},
            )

    return license_service.verify_review_allowance(device_id, db)


@router.get(
    "/status",
    response_model=LicenseStatusResponse,
    summary="Проверка статуса лицензии и триал-периода по Device ID",
    description="Возвращает активность доступа, количество оставшихся дней и дату окончания триала.",
)
def get_license_status(
    x_device_id: Optional[str] = Header(None, alias="X-Device-ID"),
    db: Session = Depends(get_db),
) -> LicenseStatusResponse:
    device_id = (x_device_id or "").strip() or "dev-test-device"
    status_data = license_service.check_device_access(device_id, db)
    return LicenseStatusResponse(
        is_active=status_data["allowed"],
        has_key=status_data.get("has_key", False),
        free_reviews_left=status_data.get("free_reviews_left", 5),
        max_free_reviews=status_data.get("max_free_reviews", 5),
        days_left=status_data["days_left"],
        expires_at=status_data["expires_at"],
        device_id=status_data["device_id"],
        activated_key=status_data["activated_key"],
        package_name=status_data.get("package_name"),
    )


@router.post(
    "/activate",
    response_model=KeyActivateResponse,
    summary="Активация ключа доступа для устройства",
    description="Продлевает срок доступа устройства на указанное в ключе количество дней (например, 30 дней).",
)
@safe_limit("5/minute")
def activate_access_key(
    request: Request,
    payload: KeyActivateRequest,
    x_device_id: Optional[str] = Header(None, alias="X-Device-ID"),
    db: Session = Depends(get_db),
) -> KeyActivateResponse:
    device_id = (x_device_id or "").strip() or "dev-test-device"
    try:
        res = license_service.activate_key(device_id, payload.key_code, db)
        return KeyActivateResponse(
            success=True,
            message=res["message"],
            is_active=res["is_active"],
            has_key=res.get("has_key", True),
            free_reviews_left=res.get("free_reviews_left", 5),
            max_free_reviews=res.get("max_free_reviews", 5),
            days_left=res["days_left"],
            expires_at=res["expires_at"],
            package_name=res.get("package_name"),
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "KEY_ACTIVATION_FAILED", "message": str(val_err)},
        )
