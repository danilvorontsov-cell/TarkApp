import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.limiter import safe_limit
from app.models.license import (
    Device,
    Invoice,
    LicenseStatusResponse,
    KeyActivateRequest,
    KeyActivateResponse,
    InvoiceRequest,
    InvoiceResponse,
    InvoiceConfirmRequest,
    InvoiceConfirmResponse,
    PlanItem,
    BankDetails,
    PlansCatalogResponse,
)
from app.services import license_service
from app.services.email_service import (
    build_invoice_pdf,
    send_invoice_to_customer,
    PLAN_CATALOG,
    PLAN_ALIASES,
    COMPANY_NAME,
    BANK_IBAN,
    BANK_SWIFT,
)
from app.services.telegram_alert import send_telegram_feedback
from app.utils.viitenumber import generate_estonian_reference_number

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
@safe_limit("30/minute")
def get_license_status(
    request: Request,
    x_device_id: Optional[str] = Header(None, alias="X-Device-ID"),
    db: Session = Depends(get_db),
) -> LicenseStatusResponse:
    device_id = (x_device_id or "").strip()
    if not device_id:
        if settings.APP_ENV in ("development", "test"):
            device_id = "dev-test-device"
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "DEVICE_ID_REQUIRED", "message": "Заголовок X-Device-ID обязателен"},
            )
    status_data = license_service.check_device_access(device_id, db)
    has_key = bool(status_data.get("has_key", False))
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
    )


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
    bank_details = BankDetails(
        recipient_name=COMPANY_NAME,
        iban=BANK_IBAN,
        swift_bic=BANK_SWIFT,
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
            device_id = "dev-test-device"
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "DEVICE_ID_REQUIRED", "message": "Заголовок X-Device-ID обязателен"},
            )
    try:
        res = license_service.activate_key(device_id, payload.key_code, db)
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
            f"[LICENSE] Key activation rejected for device='{device_id}', key='{payload.key_code}': {val_err}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "KEY_ACTIVATION_FAILED", "message": str(val_err)},
        )
    except Exception as exc:
        logger.error(
            f"[LICENSE] Unexpected activation error for device='{device_id}', key='{payload.key_code}': {exc}",
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
    description="Формирует счёт (PDF + HTML) с реквизитами LHV Pank и отправляет на указанный email через SMTP или Resend API.",
)
@safe_limit("5/minute")
async def request_invoice_email(
    request: Request,
    payload: InvoiceRequest,
    x_device_id: Optional[str] = Header(None, alias="X-Device-ID"),
    db: Session = Depends(get_db),
) -> InvoiceResponse:
    clean_email = (payload.email or "").strip()
    if clean_email:
        if "@" not in clean_email or "." not in clean_email.split("@")[-1]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "INVALID_EMAIL", "message": "Пожалуйста, укажите корректный адрес электронной почты."},
            )

    device_id = (payload.device_id or x_device_id or "").strip() or "unknown-device"
    if not clean_email:
        clean_email = f"app-{device_id[:8]}@tarkapp.ee"

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
    explanation = f"TarkApp litsents: {title_ru} ({invoice_number})"

    # Also notify admin in Telegram asynchronously
    try:
        asyncio.create_task(
            send_telegram_feedback(
                {
                    "category": "feature",
                    "message": (
                        f"📄 ЗАПРОС СЧЁТА НА ПОДПИСКУ PRO\n"
                        f"Счёт: {invoice_number} | Viitenumber: {viitenumber}\n"
                        f"Тариф: {title_ru} — {amount} €\n"
                        f"Email: {clean_email}\n"
                        f"Device ID: {device_id}"
                    ),
                    "contact": clean_email,
                },
                message_thread_id=settings.TELEGRAM_TOPIC_FEATURES,
            )
        )
    except Exception as tel_err:
        logger.warning(f"Could not schedule Telegram invoice notification: {tel_err}")

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
            "message": f"Счёт {invoice_number} сформирован.",
        }

    invoices_dir = Path("static/invoices")
    invoices_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = invoices_dir / f"{invoice_number}.pdf"
    pdf_bytes = result.get("pdf_bytes")
    if pdf_bytes:
        try:
            pdf_path.write_bytes(pdf_bytes)
        except Exception as err:
            logger.error(f"Error saving PDF to disk: {err}")

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

    pdf_download_url = f"/api/v1/license/invoice/{invoice_number}.pdf"

    return InvoiceResponse(
        invoice_number=invoice_number,
        viitenumber=viitenumber,
        amount=amount,
        currency="EUR",
        recipient=COMPANY_NAME,
        iban=BANK_IBAN,
        swift_bic=BANK_SWIFT,
        explanation=explanation,
        pdf_download_url=pdf_download_url,
        success=result.get("success", True),
        email_sent=result.get("email_sent", False),
        transport=result.get("transport", "none"),
        message=result.get("message", f"Счёт {invoice_number} сформирован."),
    )


@router.get(
    "/invoice/{invoice_number}.pdf",
    summary="Скачивание официального PDF-счёта",
    description="Возвращает бинарный PDF-файл сформированного инвойса.",
)
def download_invoice_pdf(
    invoice_number: str,
    db: Session = Depends(get_db),
):
    clean_number = invoice_number.strip()
    if clean_number.endswith(".pdf"):
        clean_number = clean_number[:-4]

    inv = db.query(Invoice).filter(Invoice.invoice_number == clean_number).first()
    file_path = Path("static/invoices") / f"{clean_number}.pdf"

    if file_path.exists():
        pdf_bytes = file_path.read_bytes()
    elif inv:
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
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(pdf_bytes)
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "INVOICE_NOT_FOUND", "message": f"Счёт {clean_number} не найден"},
        )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{clean_number}.pdf"',
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.post(
    "/invoice/confirm",
    response_model=InvoiceConfirmResponse,
    summary="Подтверждение оплаты инвойса",
    description="Отмечает счёт как оплаченный по номеру счёта или viitenumber и активирует подписку для устройства.",
)
def confirm_invoice(
    payload: InvoiceConfirmRequest,
    db: Session = Depends(get_db),
) -> InvoiceConfirmResponse:
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

