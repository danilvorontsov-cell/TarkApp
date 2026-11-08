import asyncio
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import anyio.to_thread
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import (
    CurrentUser,
    get_current_user,
    sign_auth_token,
    sign_invoice_download_token,
    verify_invoice_download_token,
)
from app.config import settings
from app.database import get_db
from app.limiter import safe_limit
from app.models.license import (
    AuthTokenRequest,
    AuthTokenResponse,
    BankDetails,
    Invoice,
    InvoiceConfirmRequest,
    InvoiceConfirmResponse,
    InvoiceRequest,
    InvoiceResponse,
    KeyActivateRequest,
    KeyActivateResponse,
    LicenseStatusResponse,
    PlanItem,
    PlansCatalogResponse,
)
from app.services import license_service
from app.services.email_service import (
    PLAN_ALIASES,
    PLAN_CATALOG,
    build_invoice_pdf,
    get_bank_requisites,
    send_invoice_to_customer,
)
from app.services.telegram_alert import send_telegram_invoice_notification
from app.utils.viitenumber import generate_estonian_reference_number

logger = logging.getLogger("tarkapp.license")

router = APIRouter(prefix="/api/v1/license", tags=["License"])

PRIVATE_INVOICES_DIR = Path("data") / "private_invoices"
INVOICE_NUMBER_RE = re.compile(r"^INV-\d{4}-\d{4,8}$")
DEV_FALLBACK_DEVICE_ID = "dev-test-device-0001"


async def verify_device_access(
    x_device_id: Optional[str] = Header(None, alias="X-Device-ID"),
    db: Session = Depends(get_db),
):
    """
    FastAPI Dependency: verifies trial or active key for incoming device.
    Raises HTTP 403 Forbidden with {"error": "TRIAL_EXPIRED", "message": "..."} when trial expires.
    """
    device_id = (x_device_id or "").strip()
    if not device_id:
        if settings.APP_ENV in ("development", "test"):
            device_id = DEV_FALLBACK_DEVICE_ID
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "TRIAL_EXPIRED", "message": "Заголовок X-Device-ID обязателен для проверки лицензии"},
            )

    check_res = await anyio.to_thread.run_sync(license_service.check_device_access, device_id, db)
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
    Verifies trial expiration and free reviews allowance.
    """
    device_id = (x_device_id or "").strip()
    if not device_id:
        if settings.APP_ENV in ("development", "test"):
            device_id = DEV_FALLBACK_DEVICE_ID
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "TRIAL_EXPIRED", "message": "Заголовок X-Device-ID обязателен для проверки лицензии"},
            )

    return await anyio.to_thread.run_sync(license_service.verify_review_allowance, device_id, db)


@router.get(
    "/status",
    response_model=LicenseStatusResponse,
    summary="Проверка статуса лицензии и триал-периода по Device ID",
    description="Возвращает активность доступа, количество оставшихся дней, дату окончания триала и подписанный токен.",
)
@safe_limit("30/minute")
def get_license_status(
    request: Request,
    nickname: Optional[str] = Query(default=None, max_length=50),
    x_device_id: Optional[str] = Header(None, alias="X-Device-ID"),
    db: Session = Depends(get_db),
) -> LicenseStatusResponse:
    device_id = (x_device_id or "").strip()
    if not device_id:
        if settings.APP_ENV in ("development", "test"):
            device_id = DEV_FALLBACK_DEVICE_ID
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "DEVICE_ID_REQUIRED", "message": "Заголовок X-Device-ID обязателен"},
            )
    status_data = license_service.check_device_access(device_id, db)
    has_key = bool(status_data.get("has_key", False))
    signed_token = sign_auth_token(status_data["device_id"], (nickname or "Ученик")[:50])
    return LicenseStatusResponse(
        is_active=status_data["allowed"],
        has_key=has_key,
        free_reviews_left=status_data.get("free_reviews_left", 20),
        max_free_reviews=status_data.get("max_free_reviews", 20),
        days_left=status_data["days_left"],
        expires_at=status_data["expires_at"],
        device_id=status_data["device_id"],
        activated_key=status_data["activated_key"] if has_key else None,
        package_name=status_data.get("package_name") if has_key else None,
        auth_token=signed_token,
    )


@router.post(
    "/auth-token",
    response_model=AuthTokenResponse,
    summary="Выпуск подписанного HMAC-SHA256 токена сессии профиля",
)
@safe_limit("30/minute")
def issue_auth_token(
    request: Request,
    payload: AuthTokenRequest,
    x_device_id: Optional[str] = Header(None, alias="X-Device-ID"),
    db: Session = Depends(get_db),
) -> AuthTokenResponse:
    device_id = (x_device_id or "").strip()
    if not device_id:
        if settings.APP_ENV in ("development", "test"):
            device_id = DEV_FALLBACK_DEVICE_ID
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "DEVICE_ID_REQUIRED", "message": "Заголовок X-Device-ID обязателен"},
            )
    valid_device_id = license_service.validate_device_id(device_id)
    license_service.check_device_access(valid_device_id, db)
    clean_nick = ((payload.nickname or "").strip() or "Ученик")[:50]
    token = sign_auth_token(valid_device_id, clean_nick)
    return AuthTokenResponse(auth_token=token, user_id=valid_device_id, nickname=clean_nick)


@router.delete(
    "/device",
    summary="Удаление связанных с устройством персональных данных (GDPR Right to be Forgotten)",
)
@safe_limit("5/minute")
def delete_device_account_data(
    request: Request,
    x_device_id: Optional[str] = Header(None, alias="X-Device-ID"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device_id = license_service.validate_device_id(x_device_id)
    if current_user.user_id != device_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "DEVICE_MISMATCH", "message": "Токен авторизации не соответствует X-Device-ID."},
        )
    return license_service.delete_device_and_data(device_id, db)


@router.get(
    "/plans",
    response_model=PlansCatalogResponse,
    summary="Каталог тарифов и банковские реквизиты",
    description="Возвращает актуальный список тарифов подписки и банковские реквизиты (Server-Driven UI).",
)
@safe_limit("60/minute")
def get_plans_catalog(request: Request) -> PlansCatalogResponse:
    plans = [
        PlanItem(
            id="month_1",
            title="Попробовать 1 месяц",
            price="9.99",
            price_per_month="9.99",
            duration_months=1,
            badge=None,
            is_popular=False,
            description="Для разовой помощи или подготовки к четверти",
            subtext="Продление каждый месяц, отмена в любой момент",
        ),
        PlanItem(
            id="semester",
            title="Оформить семестр",
            price="44.90",
            price_per_month="8.99",
            duration_months=5,
            badge="-10%",
            is_popular=False,
            description="Уверенная учёба на один семестр (5 месяцев)",
            subtext="~8.99 € / мес (разовая оплата)",
        ),
        PlanItem(
            id="school_year",
            title="Учебный год",
            price="71.90",
            price_per_month="7.99",
            duration_months=9,
            badge="Хит",
            is_popular=True,
            description="Сентябрь — Май (все 9 учебных месяцев)",
            subtext="~7.99 € / мес (разовый платёж на все 9 месяцев учёбы)",
        ),
        PlanItem(
            id="full_year",
            title="Год с каникулами",
            price="89.90",
            price_per_month="7.49",
            duration_months=12,
            badge="Выгодно",
            is_popular=False,
            description="Учебный год + 3 месяца лета для закрепления языка",
            subtext="~7.49 € / мес (9 мес учёбы + 3 мес лета)",
        ),
    ]
    req = get_bank_requisites()
    bank_details = BankDetails(
        recipient_name=req["company_name"],
        iban=req["iban"],
        swift_bic=req["swift"],
    )
    return PlansCatalogResponse(plans=plans, bank_details=bank_details)


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
    device_id = (x_device_id or "").strip()
    if not device_id:
        if settings.APP_ENV in ("development", "test"):
            device_id = DEV_FALLBACK_DEVICE_ID
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "DEVICE_ID_REQUIRED", "message": "Заголовок X-Device-ID обязателен"},
            )
    valid_device_id = license_service.validate_device_id(device_id)
    try:
        res = license_service.activate_key(valid_device_id, payload.key_code, db)
        return KeyActivateResponse(
            success=True,
            message=res["message"],
            is_active=res["is_active"],
            has_key=res.get("has_key", True),
            free_reviews_left=res.get("free_reviews_left", 20),
            max_free_reviews=res.get("max_free_reviews", 20),
            days_left=res["days_left"],
            expires_at=res["expires_at"],
            package_name=res.get("package_name"),
        )
    except ValueError as val_err:
        logger.warning(
            f"[LICENSE] Key activation rejected for device='{valid_device_id}', key='{payload.key_code}': {val_err}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "KEY_ACTIVATION_FAILED", "message": str(val_err)},
        )
    except Exception as exc:
        logger.error(
            f"[LICENSE] Unexpected activation error for device='{valid_device_id}', key='{payload.key_code}': {exc}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "INTERNAL_ERROR", "message": "Внутренняя ошибка сервера при активации ключа."},
        )


@router.post(
    "/invoice",
    response_model=InvoiceResponse,
    summary="Генерация и отправка официального PDF e-счёта на email",
    description="Формирует счёт (PDF + HTML) с банковскими реквизитами из .env и сохраняет PDF в закрытую директорию.",
)
@safe_limit("5/minute")
async def request_invoice_email(
    request: Request,
    payload: InvoiceRequest,
    x_device_id: Optional[str] = Header(None, alias="X-Device-ID"),
    db: Session = Depends(get_db),
) -> InvoiceResponse:
    clean_email = (payload.email or "").strip()
    if not clean_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "EMAIL_REQUIRED", "message": "Пожалуйста, укажите адрес электронной почты для отправки счёта и ключа доступа."},
        )
    if "@" not in clean_email or "." not in clean_email.split("@")[-1]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "INVALID_EMAIL", "message": "Пожалуйста, укажите корректный адрес электронной почты."},
        )

    raw_dev = (x_device_id or payload.device_id or "").strip()
    if not raw_dev and settings.APP_ENV in ("development", "test"):
        raw_dev = DEV_FALLBACK_DEVICE_ID
    device_id = license_service.validate_device_id(raw_dev)

    raw_plan = (payload.plan_id or payload.plan or "school_year").strip()
    resolved_plan = PLAN_ALIASES.get(raw_plan, raw_plan)
    plan_info = PLAN_CATALOG.get(resolved_plan, PLAN_CATALOG["year"])

    now = datetime.now(timezone.utc)
    year_str = now.strftime("%Y")
    inv_count = db.query(func.count(Invoice.id)).scalar() or 0
    inv_seq = 1001 + inv_count
    invoice_number = f"INV-{year_str}-{inv_seq:04d}"
    base_ref = f"{year_str}{inv_seq:04d}"
    viitenumber = generate_estonian_reference_number(base_ref)

    while db.query(Invoice).filter(Invoice.invoice_number == invoice_number).first():
        inv_seq += 1
        invoice_number = f"INV-{year_str}-{inv_seq:04d}"
        base_ref = f"{year_str}{inv_seq:04d}"
        viitenumber = generate_estonian_reference_number(base_ref)

    amount = plan_info.get("amount", "71.90")
    title_ru = plan_info.get("title_ru", "PRO")
    explanation = f"Tarkapp, {invoice_number}"
    req = get_bank_requisites()

    if payload.email and payload.email.strip():
        result = await send_invoice_to_customer(
            email=clean_email,
            plan_id=resolved_plan,
            device_id=device_id,
            invoice_number=invoice_number,
            viitenumber=viitenumber,
        )
    else:
        issue_date = now.strftime("%d.%m.%Y")
        due_date = (now + timedelta(days=7)).strftime("%d.%m.%Y")
        pdf_bytes = build_invoice_pdf(
            invoice_number=invoice_number,
            customer_email=clean_email,
            plan_title_en=plan_info.get("title_en", "TarkApp PRO"),
            amount_eur=amount,
            selgitus=plan_info.get("selgitus", "TarkApp PRO"),
            issue_date=issue_date,
            due_date=due_date,
            viitenumber=viitenumber,
        )
        result = {
            "success": True,
            "email_sent": False,
            "invoice_number": invoice_number,
            "viitenumber": viitenumber,
            "transport": "none",
            "pdf_bytes": pdf_bytes,
            "message": f"Счёт № {invoice_number} готов к оплате. Используйте реквизиты IBAN и Viitenumber ниже.",
        }

    PRIVATE_INVOICES_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = PRIVATE_INVOICES_DIR / f"{invoice_number}.pdf"
    pdf_bytes = result.get("pdf_bytes")
    if pdf_bytes:
        try:
            pdf_path.write_bytes(pdf_bytes)
        except Exception as err:
            logger.error(f"Error saving private PDF to disk: {err}")

    inv_record = Invoice(
        invoice_number=invoice_number,
        viitenumber=viitenumber,
        device_id=device_id,
        customer_email=clean_email,
        payer_name=payload.payer_name,
        plan_id=resolved_plan,
        amount=amount,
        currency="EUR",
        is_paid=False,
        pdf_path=str(pdf_path),
        created_at=datetime.utcnow(),
    )
    db.add(inv_record)
    db.commit()
    db.refresh(inv_record)

    try:
        asyncio.create_task(
            send_telegram_invoice_notification(
                invoice_number=invoice_number,
                viitenumber=viitenumber,
                plan_title=title_ru,
                amount_eur=amount,
                customer_email=clean_email,
                device_id=device_id,
                message_thread_id=settings.TELEGRAM_TOPIC_INVOICES,
            )
        )
    except Exception as tel_err:
        logger.warning(f"Could not schedule Telegram invoice notification: {tel_err}")

    dl_token = sign_invoice_download_token(invoice_number, device_id)
    pdf_download_url = f"/api/v1/license/invoice/{invoice_number}.pdf?token={dl_token}"

    return InvoiceResponse(
        invoice_number=invoice_number,
        viitenumber=viitenumber,
        amount=amount,
        currency="EUR",
        recipient=req["company_name"],
        iban=req["iban"],
        swift_bic=req["swift"],
        explanation=explanation,
        pdf_download_url=pdf_download_url,
        success=result.get("success", True),
        email_sent=result.get("email_sent", False),
        transport=result.get("transport", "none"),
        message=result.get(
            "message",
            f"Номер счёта: {invoice_number}\nРеквизиты и Viitenumber отображены на экране. После подтверждения банковского перевода ключ активации будет автоматически отправлен на указанный email.",
        ),
    )


@router.get(
    "/invoice/{invoice_number}.pdf",
    summary="Защищённое скачивание официального PDF-счёта",
    description="Проверяет формат счёта и принадлежность устройству (X-Device-ID или подписанный download-токен).",
)
def download_invoice_pdf(
    invoice_number: str,
    token: Optional[str] = Query(default=None, description="Подписанный токен скачивания счёта"),
    x_device_id: Optional[str] = Header(None, alias="X-Device-ID"),
    db: Session = Depends(get_db),
):
    clean_number = invoice_number.strip().upper()
    if clean_number.endswith(".PDF"):
        clean_number = clean_number[:-4]

    if not INVOICE_NUMBER_RE.match(clean_number):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "INVALID_INVOICE_NUMBER", "message": "Некорректный формат номера счёта."},
        )

    inv = db.query(Invoice).filter(Invoice.invoice_number == clean_number).first()
    if not inv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "INVOICE_NOT_FOUND", "message": f"Счёт {clean_number} не найден"},
        )

    owner_device_id = (inv.device_id or "").strip()
    caller_device_id = (x_device_id or "").strip()

    is_device_match = bool(
        owner_device_id
        and owner_device_id != "unknown-device"
        and caller_device_id
        and secrets.compare_digest(caller_device_id, owner_device_id)
    )
    is_token_valid = bool(
        owner_device_id and verify_invoice_download_token(clean_number, owner_device_id, token)
    )

    if not (is_device_match or is_token_valid):
        logger.warning(
            f"[GDPR] Blocked unauthorized PDF download attempt for {clean_number} "
            f"(caller_device='{caller_device_id}')."
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "FORBIDDEN", "message": "Доступ к чужому счёту запрещён."},
        )

    PRIVATE_INVOICES_DIR.mkdir(parents=True, exist_ok=True)
    private_root = PRIVATE_INVOICES_DIR.resolve()
    file_path = (PRIVATE_INVOICES_DIR / f"{clean_number}.pdf").resolve()
    if file_path.parent != private_root:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid invoice path.")

    if file_path.exists():
        pdf_bytes = file_path.read_bytes()
    else:
        resolved_plan = PLAN_ALIASES.get(inv.plan_id, inv.plan_id)
        plan_info = PLAN_CATALOG.get(resolved_plan, PLAN_CATALOG["year"])
        issue_date = inv.created_at.strftime("%d.%m.%Y") if inv.created_at else datetime.utcnow().strftime("%d.%m.%Y")
        due_date = ((inv.created_at or datetime.utcnow()) + timedelta(days=7)).strftime("%d.%m.%Y")
        pdf_bytes = build_invoice_pdf(
            invoice_number=inv.invoice_number,
            customer_email=inv.customer_email,
            plan_title_en=plan_info["title_en"],
            amount_eur=inv.amount,
            selgitus=plan_info["selgitus"],
            issue_date=issue_date,
            due_date=due_date,
            viitenumber=inv.viitenumber,
        )
        file_path.write_bytes(pdf_bytes)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{clean_number}.pdf"',
            "Cache-Control": "private, no-store",
        },
    )


@router.post(
    "/invoice/confirm",
    response_model=InvoiceConfirmResponse,
    summary="Административное подтверждение оплаты инвойса",
    description="Требует валидный заголовок X-Admin-Secret. Отмечает счёт как оплаченный идемпотентно.",
)
@safe_limit("20/minute")
def confirm_invoice(
    request: Request,
    payload: InvoiceConfirmRequest,
    x_admin_secret: Optional[str] = Header(None, alias="X-Admin-Secret"),
    db: Session = Depends(get_db),
) -> InvoiceConfirmResponse:
    expected_secret = (settings.ADMIN_SECRET or "").strip()
    if not expected_secret:
        logger.error("[LICENSE] /invoice/confirm rejected: ADMIN_SECRET is not configured in .env")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "ADMIN_SECRET_NOT_CONFIGURED",
                "message": "Административный секрет не настроен на сервере.",
            },
        )

    provided_secret = (x_admin_secret or "").strip()
    if not provided_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "ADMIN_AUTH_REQUIRED", "message": "Требуется заголовок X-Admin-Secret."},
        )

    if not secrets.compare_digest(provided_secret.encode("utf-8"), expected_secret.encode("utf-8")):
        logger.warning("[LICENSE] Blocked /invoice/confirm call with invalid X-Admin-Secret.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "INVALID_ADMIN_SECRET", "message": "Недействительный административный ключ."},
        )

    target = (payload.invoice_number or payload.viitenumber or "").strip()
    if not target:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "TARGET_REQUIRED", "message": "Необходимо указать invoice_number или viitenumber"},
        )
    try:
        res = license_service.confirm_invoice_payment(target, db)
        return InvoiceConfirmResponse(
            success=True,
            message=res["message"],
            invoice_number=res["invoice_number"],
            viitenumber=res["viitenumber"],
            is_active=res["is_active"],
            days_left=res["days_left"],
            expires_at=res["expires_at"],
            package_name=res.get("package_name"),
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "INVOICE_NOT_FOUND", "message": str(val_err)},
        )
    except Exception as exc:
        logger.error(f"[LICENSE] Error confirming invoice payment '{target}': {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "INTERNAL_ERROR", "message": "Ошибка подтверждения оплаты инвойса"},
        )
