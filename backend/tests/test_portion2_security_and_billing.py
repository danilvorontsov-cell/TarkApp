import os
import tempfile
from pathlib import Path
from unittest.mock import patch, AsyncMock
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import Base, transaction
from app.limiter import get_remote_address
from app.models.license import Device, AccessKey, Invoice
from app.services import license_service
from app.services.license_service import (
    check_device_access,
    delete_device_and_data,
    confirm_invoice_payment,
    clear_ip_registration_history,
)
from app.services.telegram_alert import (
    mask_email,
    build_telegram_invoice_message,
    send_telegram_invoice_notification,
)


@pytest.fixture
def test_db_session():
    """Provides an isolated in-memory SQLite database session with all tables."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


def test_sqlite_transaction_begin_immediate(test_db_session):
    """Verifies that Session.transaction executes BEGIN IMMEDIATE on root SQLite transaction."""
    db = test_db_session
    with db.transaction():
        db.execute(text("CREATE TABLE test_tx (id INTEGER PRIMARY KEY, val TEXT)"))
        db.execute(text("INSERT INTO test_tx (id, val) VALUES (1, 'hello')"))
        # Test nested transaction
        with db.transaction():
            db.execute(text("INSERT INTO test_tx (id, val) VALUES (2, 'world')"))

    rows = db.execute(text("SELECT id, val FROM test_tx ORDER BY id")).fetchall()
    assert len(rows) == 2
    assert rows[0][1] == "hello"
    assert rows[1][1] == "world"


def test_limiter_get_remote_address_trusted_proxy_logic():
    """
    Verifies that X-Real-IP and X-Forwarded-For are trusted ONLY when request.client.host
    is loopback or private subnet.
    """
    class MockClient:
        def __init__(self, host):
            self.host = host

    class MockRequest:
        def __init__(self, host, headers=None):
            self.client = MockClient(host) if host else None
            self.headers = headers or {}

    # 1. Untrusted public client spoofing X-Forwarded-For -> returns direct host
    req1 = MockRequest("93.184.216.34", {"x-forwarded-for": "1.1.1.1", "x-real-ip": "8.8.8.8"})
    assert get_remote_address(req1) == "93.184.216.34"

    # 2. Trusted localhost proxy (127.0.0.1) -> trusts X-Real-IP
    req2 = MockRequest("127.0.0.1", {"x-real-ip": "194.126.100.5"})
    assert get_remote_address(req2) == "194.126.100.5"

    # 3. Trusted localhost IPv6 (::1) -> trusts X-Forwarded-For
    req3 = MockRequest("::1", {"x-forwarded-for": "194.126.100.10, 10.0.0.1"})
    assert get_remote_address(req3) == "194.126.100.10"

    # 4. Trusted private subnet (10.0.0.2) -> trusts X-Real-IP
    req4 = MockRequest("10.0.0.2", {"x-real-ip": "194.126.100.20"})
    assert get_remote_address(req4) == "194.126.100.20"

    # 5. Trusted private subnet (192.168.1.5) -> trusts X-Forwarded-For
    req5 = MockRequest("192.168.1.5", {"x-forwarded-for": "194.126.100.30"})
    assert get_remote_address(req5) == "194.126.100.30"

    # 6. No client -> returns 127.0.0.1
    req6 = MockRequest(None)
    assert get_remote_address(req6) == "127.0.0.1"


def test_license_service_in_memory_ip_rate_limiting(test_db_session):
    """
    Verifies that soft in-memory rate limiting allows up to 35 devices per IP per 24 hours.
    The 36th device gets created with free_reviews_left = 0.
    """
    clear_ip_registration_history()
    db = test_db_session
    school_ip = "195.250.180.10"

    # Register 35 devices from the same school IP
    for i in range(1, 36):
        dev_id = f"school-device-{i:04d}-uuid1234"
        res = check_device_access(dev_id, db, client_ip=school_ip)
        assert res["allowed"] is True
        assert res["free_reviews_left"] > 0

    # 36th device from the same IP MUST be throttled: free_reviews_left = 0
    dev_36 = "school-device-0036-uuid1234"
    res_36 = check_device_access(dev_36, db, client_ip=school_ip)
    assert res_36["allowed"] is True
    assert res_36["free_reviews_left"] == 0

    # Device from a different IP is NOT throttled
    home_ip = "195.250.180.20"
    dev_home = "home-device-0001-uuid1234"
    res_home = check_device_access(dev_home, db, client_ip=home_ip)
    assert res_home["allowed"] is True
    assert res_home["free_reviews_left"] > 0


def test_delete_device_and_data_gdpr_and_estonian_accounting(test_db_session, tmp_path):
    """
    Verifies Raamatupidamise seadus § 12 and GDPR compliance:
    - Paid invoice and its PDF are NOT deleted; device_id is anonymized to 'GDPR_ANONYMIZED'.
    - Unpaid draft invoice: PDF is unlinked from disk, customer_email/payer_name cleared,
      status set to 'cancelled', invoice DB record preserved.
    """
    db = test_db_session
    dev_id = "test-gdpr-device-12345678"

    # Create dummy PDF files
    paid_pdf = tmp_path / "paid_inv.pdf"
    paid_pdf.write_text("PAID PDF CONTENT")

    draft_pdf = tmp_path / "draft_inv.pdf"
    draft_pdf.write_text("DRAFT PDF CONTENT")

    # 1. Paid invoice
    inv_paid = Invoice(
        invoice_number="INV-2026-9001",
        viitenumber="202690011",
        device_id=dev_id,
        customer_email="parent.paid@example.com",
        payer_name="John Doe",
        plan_id="year",
        amount="71.90",
        currency="EUR",
        is_paid=True,
        status="paid",
        pdf_path=str(paid_pdf),
    )
    # 2. Unpaid draft invoice
    inv_draft = Invoice(
        invoice_number="INV-2026-9002",
        viitenumber="202690022",
        device_id=dev_id,
        customer_email="parent.draft@example.com",
        payer_name="Jane Doe",
        plan_id="month",
        amount="9.99",
        currency="EUR",
        is_paid=False,
        status="pending",
        pdf_path=str(draft_pdf),
    )
    db.add(inv_paid)
    db.add(inv_draft)
    db.commit()

    # Perform deletion
    res = delete_device_and_data(dev_id, db)
    assert res["success"] is True

    # 1. Verify paid invoice: PDF exists, record exists, device_id anonymized
    assert paid_pdf.exists()
    db.refresh(inv_paid)
    assert inv_paid.device_id == "GDPR_ANONYMIZED"
    assert inv_paid.customer_email == "parent.paid@example.com"
    assert inv_paid.is_paid is True

    # 2. Verify draft invoice: PDF deleted, record exists, PII cleared, status cancelled
    assert not draft_pdf.exists()
    db.refresh(inv_draft)
    assert inv_draft.device_id == "GDPR_ANONYMIZED"
    assert inv_draft.customer_email == ""
    assert inv_draft.payer_name == ""
    assert inv_draft.status == "cancelled"
    assert inv_draft.pdf_path is None


def test_confirm_invoice_payment_backup_key_and_email(test_db_session):
    """
    Verifies that confirm_invoice_payment:
    1. Sets is_paid=1, status='paid'
    2. Automatically generates backup key TARK-XXXX-XXXX in access_keys table with is_used=False
    3. Triggers email notification dispatch to customer_email
    4. Returns backup_key in response dict
    """
    db = test_db_session
    inv = Invoice(
        invoice_number="INV-2026-8888",
        viitenumber="202688880",
        device_id="test-buyer-device-uuid1234",
        customer_email="buyer.parent@example.com",
        payer_name="Buyer Parent",
        plan_id="year",
        amount="71.90",
        currency="EUR",
        is_paid=False,
        status="pending",
    )
    db.add(inv)
    db.commit()

    with patch("app.services.email_service.send_payment_confirmation_email_sync") as mock_email:
        mock_email.return_value = True

        res = confirm_invoice_payment("INV-2026-8888", db)
        assert res["success"] is True
        assert res["already_paid"] is False
        backup_key = res["backup_key"]
        assert backup_key.startswith("TARK-")

        # Verify backup key stored in access_keys table
        key_record = db.query(AccessKey).filter(AccessKey.key_code == backup_key).first()
        assert key_record is not None
        assert key_record.is_used is False
        assert key_record.duration_days == 270  # year plan

        # Verify email dispatch was called
        assert mock_email.called
        call_kwargs = mock_email.call_args.kwargs
        assert call_kwargs["customer_email"] == "buyer.parent@example.com"
        assert call_kwargs["backup_key"] == backup_key
        assert call_kwargs["invoice_number"] == "INV-2026-8888"


def test_telegram_alert_mask_email_and_device():
    """Verifies that mask_email and send_telegram_invoice_notification mask PII."""
    assert mask_email("ivan.petrov@gmail.com") == "iv***@gmail.com"
    assert mask_email("danil.zuravov@gmail.com") == "da***@gmail.com"
    assert mask_email("a@b.com") == "a***@b.com"
    assert mask_email("") == "Не указан"
    assert mask_email(None) == "Не указан"


def test_send_telegram_invoice_notification_pii_masked():
    """Verifies that customer_email and device_id are masked in the Telegram message."""
    msg = build_telegram_invoice_message(
        invoice_number="INV-2026-7777",
        viitenumber="202677771",
        plan_title="Учебный год",
        amount_eur="71.90",
        customer_email="secret.parent@gmail.com",
        device_id="secret-device-id-998877",
    )

    # Ensure raw PII is NOT present
    assert "secret.parent@gmail.com" not in msg
    assert "secret-device-id-998877" not in msg

    # Ensure masked PII IS present
    assert "se***@gmail.com" in msg
    assert "secr...8877" in msg
    assert "INV-2026-7777" in msg
    assert "202677771" in msg
