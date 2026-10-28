import asyncio
import base64
import html
import logging
import smtplib
import ssl
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Dict, Any, Tuple
import httpx

from app.config import settings

logger = logging.getLogger("tarkapp.email")

PLAN_CATALOG: Dict[str, Dict[str, str]] = {
    "year": {
        "title_ru": "Учебный год (9 месяцев)",
        "title_en": "TarkApp PRO - School Year (9 months)",
        "amount": "71.90",
        "selgitus": "TarkApp PRO Aasta 9k",
    },
    "semester": {
        "title_ru": "Семестр (5 месяцев)",
        "title_en": "TarkApp PRO - Semester (5 months)",
        "amount": "44.90",
        "selgitus": "TarkApp PRO Semester 5k",
    },
    "month": {
        "title_ru": "1 месяц (Гибкий)",
        "title_en": "TarkApp PRO - 1 Month Flexible",
        "amount": "9.99",
        "selgitus": "TarkApp PRO Kuu 1k",
    },
    "full_year": {
        "title_ru": "Полный год с каникулами (12 месяцев)",
        "title_en": "TarkApp PRO - Full Year (12 months)",
        "amount": "89.90",
        "selgitus": "TarkApp PRO Aasta 12k",
    },
}

COMPANY_NAME = "TarkApp OÜ"
COMPANY_REG = "16987456"
BANK_NAME = "AS LHV Pank"
BANK_IBAN = "EE129900001234567890"
BANK_SWIFT = "LHVBEE22"


def _escape_pdf_text(text: str) -> str:
    """Escapes ASCII text for PDF content streams."""
    ascii_safe = text.encode("latin-1", errors="replace").decode("latin-1")
    return ascii_safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_invoice_pdf(
    invoice_number: str,
    customer_email: str,
    plan_title_en: str,
    amount_eur: str,
    selgitus: str,
    issue_date: str,
    due_date: str,
) -> bytes:
    """
    Generates a clean, valid single-page PDF 1.4 invoice in pure Python without external C libraries.
    """
    lines = [
        ("F2", 20, 50, 770, "TarkApp OU - INVOICE / ARVE"),
        ("F1", 11, 50, 742, f"Invoice No / Arve nr: {invoice_number}"),
        ("F1", 11, 50, 725, f"Issue Date / Kuupaev: {issue_date}"),
        ("F1", 11, 50, 708, f"Due Date / Maksetahtaeg: {due_date}"),
        ("F1", 11, 50, 685, "------------------------------------------------------------------------"),
        ("F2", 12, 50, 665, "Seller / Muuja:"),
        ("F1", 11, 50, 648, "TarkApp OU (Reg. code: 16987456)"),
        ("F1", 11, 50, 632, "Tallinn, Estonia | support@tarkapp.ee"),
        ("F2", 12, 50, 602, "Customer / Ostja:"),
        ("F1", 11, 50, 585, f"Email: {customer_email}"),
        ("F1", 11, 50, 562, "------------------------------------------------------------------------"),
        ("F2", 12, 50, 540, "Description / Kirjeldus"),
        ("F1", 11, 50, 520, f"1x {plan_title_en}"),
        ("F2", 14, 50, 490, f"TOTAL TO PAY / KUULUB TASUMISELE: {amount_eur} EUR"),
        ("F1", 11, 50, 465, "------------------------------------------------------------------------"),
        ("F2", 12, 50, 442, "Payment Details / Makse rekvisiidid (SEPA / Estonia):"),
        ("F1", 11, 50, 422, f"Recipient / Saaja: TarkApp OU"),
        ("F1", 11, 50, 405, f"Bank / Pank: {BANK_NAME}"),
        ("F2", 11, 50, 388, f"IBAN: {BANK_IBAN}"),
        ("F1", 11, 50, 371, f"SWIFT / BIC: {BANK_SWIFT}"),
        ("F2", 11, 50, 354, f"Payment Reference / Selgitus: {selgitus} ({invoice_number})"),
        ("F1", 10, 50, 315, "Thank you for choosing TarkApp! / Taname, et valisite TarkAppi!"),
    ]

    stream_cmds = ["BT"]
    for font_key, size, x, y, text in lines:
        escaped = _escape_pdf_text(text)
        stream_cmds.append(f"/{font_key} {size} Tf 1 0 0 1 {x} {y} Tm ({escaped}) Tj")
    stream_cmds.append("ET")
    stream_bytes = "\n".join(stream_cmds).encode("latin-1")

    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>\nendobj\n"
        ),
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>\nendobj\n",
        f"6 0 obj\n<< /Length {len(stream_bytes)} >>\nstream\n".encode("latin-1")
        + stream_bytes
        + b"\nendstream\nendobj\n",
    ]

    pdf_out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for obj in objects:
        offsets.append(len(pdf_out))
        pdf_out.extend(obj)

    xref_pos = len(pdf_out)
    pdf_out.extend(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    pdf_out.extend(b"0000000000 65535 f \n")
    for off in offsets:
        pdf_out.extend(f"{off:010d} 00000 n \n".encode("latin-1"))

    pdf_out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "latin-1"
        )
    )
    return bytes(pdf_out)


def build_invoice_html(
    invoice_number: str,
    customer_email: str,
    plan_title_ru: str,
    amount_eur: str,
    selgitus: str,
    issue_date: str,
    due_date: str,
) -> str:
    """Builds a styled HTML email for the invoice."""
    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 560px; margin: 0 auto; background-color: #12161A; color: #F8FAFC; border-radius: 16px; overflow: hidden; border: 1px solid #2C363F;">
      <div style="background: linear-gradient(180deg, #66F6CF 0%, #42DCA3 100%); padding: 24px 28px; color: #064E3B;">
        <h1 style="margin: 0; font-size: 24px; font-weight: 900;">TarkApp</h1>
        <p style="margin: 4px 0 0 0; font-size: 14px; font-weight: 700;">Официальный счёт на оплату (Arve № {html.escape(invoice_number)})</p>
      </div>
      <div style="padding: 24px 28px;">
        <p style="font-size: 15px; line-height: 1.5; color: #E2E8F0; margin-top: 0;">
          Здравствуйте! Спасибо за выбор <b>TarkApp PRO</b>. Ниже приведены реквизиты для оплаты по банковскому переводу (SEPA / Эстония), а также прикреплён PDF-счёт.
        </p>

        <div style="background-color: #1E252B; border: 1px solid #5FEDC5; border-radius: 12px; padding: 16px; margin: 20px 0;">
          <p style="margin: 0 0 8px 0; font-size: 13px; color: #94A3B8;">Выбранный тариф:</p>
          <p style="margin: 0 0 12px 0; font-size: 17px; font-weight: 800; color: #5FEDC5;">{html.escape(plan_title_ru)}</p>
          <p style="margin: 0; font-size: 22px; font-weight: 900; color: #FFFFFF;">Сумма к оплате: {html.escape(amount_eur)} €</p>
        </div>

        <h3 style="font-size: 15px; color: #F8FAFC; margin-bottom: 10px;">Реквизиты для перевода (LHV Pank):</h3>
        <table style="width: 100%; border-collapse: collapse; font-size: 14px; color: #E2E8F0; background-color: #1E252B; border-radius: 12px; padding: 12px;">
          <tr>
            <td style="padding: 8px 12px; color: #94A3B8;">Получатель (Saaja):</td>
            <td style="padding: 8px 12px; font-weight: 700;">{COMPANY_NAME} (Reg: {COMPANY_REG})</td>
          </tr>
          <tr>
            <td style="padding: 8px 12px; color: #94A3B8;">IBAN:</td>
            <td style="padding: 8px 12px; font-weight: 800; color: #5FEDC5;">{BANK_IBAN}</td>
          </tr>
          <tr>
            <td style="padding: 8px 12px; color: #94A3B8;">SWIFT / BIC:</td>
            <td style="padding: 8px 12px; font-weight: 600;">{BANK_SWIFT}</td>
          </tr>
          <tr>
            <td style="padding: 8px 12px; color: #94A3B8;">Пояснение (Selgitus):</td>
            <td style="padding: 8px 12px; font-weight: 700;">{html.escape(selgitus)} ({html.escape(invoice_number)})</td>
          </tr>
          <tr>
            <td style="padding: 8px 12px; color: #94A3B8;">Срок оплаты:</td>
            <td style="padding: 8px 12px;">{html.escape(due_date)}</td>
          </tr>
        </table>

        <p style="font-size: 13px; color: #94A3B8; line-height: 1.5; margin-top: 20px;">
          После поступления платежа мы отправим ваш персональный ключ активации <b>TARK-XXXX-XXXX</b> на этот адрес ({html.escape(customer_email)}).
        </p>
      </div>
    </div>
    """


def _is_configured_value(val: Any, placeholders: Tuple[str, ...] = ("your_", "твой_", "xxxx", "example")) -> bool:
    if not val:
        return False
    s = str(val).strip()
    if not s:
        return False
    lower = s.lower()
    return not any(p in lower for p in placeholders)


def _send_via_smtp_sync(
    to_email: str,
    subject: str,
    html_body: str,
    plain_body: str,
    pdf_bytes: bytes,
    pdf_filename: str,
) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
    msg["To"] = to_email
    msg.set_content(plain_body)
    msg.add_alternative(html_body, subtype="html")
    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=pdf_filename,
    )

    host = str(settings.SMTP_HOST).strip()
    port = int(settings.SMTP_PORT or 587)
    user = str(settings.SMTP_USER).strip()
    password = str(settings.SMTP_PASSWORD).strip()

    if port == 465:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=context, timeout=15) as server:
            server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.ehlo()
            if settings.SMTP_USE_TLS:
                context = ssl.create_default_context()
                server.starttls(context=context)
                server.ehlo()
            server.login(user, password)
            server.send_message(msg)


async def _send_via_resend(
    to_email: str,
    subject: str,
    html_body: str,
    pdf_bytes: bytes,
    pdf_filename: str,
) -> None:
    api_key = str(settings.RESEND_API_KEY).strip()
    payload = {
        "from": settings.RESEND_FROM or "TarkApp <onboarding@resend.dev>",
        "to": [to_email],
        "subject": subject,
        "html": html_body,
        "attachments": [
            {
                "filename": pdf_filename,
                "content": base64.b64encode(pdf_bytes).decode("ascii"),
            }
        ],
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Resend API HTTP {resp.status_code}: {resp.text[:200]}")


async def send_invoice_to_customer(
    email: str,
    plan_id: str,
    device_id: str = "",
) -> Dict[str, Any]:
    """
    Generates an official PDF + HTML invoice and dispatches it via configured email transport
    (Resend API or SMTP). Never raises an unhandled 500 error.
    """
    clean_email = email.strip()
    plan = PLAN_CATALOG.get(plan_id, PLAN_CATALOG["year"])

    now = datetime.now(timezone.utc)
    issue_date = now.strftime("%d.%m.%Y")
    due_date = (now + timedelta(days=7)).strftime("%d.%m.%Y")
    invoice_number = f"TARK-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
    pdf_filename = f"Invoice_{invoice_number}.pdf"

    pdf_bytes = build_invoice_pdf(
        invoice_number=invoice_number,
        customer_email=clean_email,
        plan_title_en=plan["title_en"],
        amount_eur=plan["amount"],
        selgitus=plan["selgitus"],
        issue_date=issue_date,
        due_date=due_date,
    )

    html_body = build_invoice_html(
        invoice_number=invoice_number,
        customer_email=clean_email,
        plan_title_ru=plan["title_ru"],
        amount_eur=plan["amount"],
        selgitus=plan["selgitus"],
        issue_date=issue_date,
        due_date=due_date,
    )

    plain_body = (
        f"TarkApp OÜ — Счёт на оплату № {invoice_number}\n"
        f"Тариф: {plan['title_ru']}\n"
        f"Сумма: {plan['amount']} EUR\n"
        f"Получатель: {COMPANY_NAME} (Reg: {COMPANY_REG})\n"
        f"IBAN (LHV Pank): {BANK_IBAN}\n"
        f"SWIFT/BIC: {BANK_SWIFT}\n"
        f"Пояснение к платежу (Selgitus): {plan['selgitus']} ({invoice_number})\n"
    )

    subject = f"Счёт на оплату TarkApp PRO № {invoice_number} ({plan['amount']} €)"

    logger.info(
        f"[INVOICE] Generated invoice {invoice_number} for email={clean_email}, "
        f"plan={plan_id} ({plan['amount']} EUR), device_id={device_id}"
    )

    # Check Resend API first
    if _is_configured_value(settings.RESEND_API_KEY):
        try:
            await _send_via_resend(
                to_email=clean_email,
                subject=subject,
                html_body=html_body,
                pdf_bytes=pdf_bytes,
                pdf_filename=pdf_filename,
            )
            logger.info(f"[INVOICE] Sent invoice {invoice_number} to {clean_email} via Resend API.")
            return {
                "success": True,
                "email_sent": True,
                "invoice_number": invoice_number,
                "transport": "resend",
                "message": f"Счёт № {invoice_number} (PDF) успешно отправлен на {clean_email}. Проверьте папку «Входящие» или «Спам».",
            }
        except Exception as e:
            logger.error(f"[INVOICE] Resend delivery failed for {clean_email}: {e}")
            return {
                "success": False,
                "email_sent": False,
                "invoice_number": invoice_number,
                "transport": "resend",
                "message": f"Не удалось отправить письмо через Resend API ({e}). Проверьте ключ RESEND_API_KEY в backend/.env.",
            }

    # Check SMTP second
    if (
        _is_configured_value(settings.SMTP_HOST)
        and _is_configured_value(settings.SMTP_USER)
        and _is_configured_value(settings.SMTP_PASSWORD)
    ):
        try:
            await asyncio.to_thread(
                _send_via_smtp_sync,
                clean_email,
                subject,
                html_body,
                plain_body,
                pdf_bytes,
                pdf_filename,
            )
            logger.info(f"[INVOICE] Sent invoice {invoice_number} to {clean_email} via SMTP ({settings.SMTP_HOST}).")
            return {
                "success": True,
                "email_sent": True,
                "invoice_number": invoice_number,
                "transport": "smtp",
                "message": f"Счёт № {invoice_number} (PDF) успешно отправлен на {clean_email}. Проверьте папку «Входящие» или «Спам».",
            }
        except Exception as e:
            logger.error(f"[INVOICE] SMTP delivery failed for {clean_email}: {e}")
            return {
                "success": False,
                "email_sent": False,
                "invoice_number": invoice_number,
                "transport": "smtp",
                "message": f"Ошибка почтового сервера SMTP ({e}). Проверьте настройки SMTP_USER / SMTP_PASSWORD в backend/.env.",
            }

    # Neither Resend nor SMTP is configured in backend/.env
    logger.warning(
        f"[INVOICE] Email transport not configured in backend/.env (neither RESEND_API_KEY nor SMTP_HOST/SMTP_USER/SMTP_PASSWORD set). "
        f"Invoice {invoice_number} for {clean_email} saved to server log only."
    )
    return {
        "success": False,
        "email_sent": False,
        "invoice_number": invoice_number,
        "transport": "none",
        "message": (
            f"Счёт № {invoice_number} сформирован, но почтовый сервер (SMTP / Resend) ещё не настроен в backend/.env "
            f"(укажите SMTP_HOST, SMTP_USER, SMTP_PASSWORD или RESEND_API_KEY). "
            f"Вы можете оплатить перевод прямо сейчас по реквизитам IBAN выше."
        ),
    }
