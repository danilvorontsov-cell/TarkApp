import base64
from datetime import datetime, timedelta
import io
import json
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import anyio.to_thread
import pytest
import starlette.concurrency
from PIL import Image

from app.auth import get_current_user, sign_auth_token, sign_invoice_download_token
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.license import AccessKey, Device, Invoice
from app.models.page_analysis import PageAnalysisResponse, UserProfile
from app.prompts.tutor_prompt import ESTONIAN_TUTOR_SYSTEM_PROMPT, build_tutor_user_prompt
from app.services import license_service
from app.services.gemini_service import gemini_tutor_service
from app.services.telegram_alert import send_telegram_message


# Ensure DB schema exists without requiring ASGI lifespan threadpool
Base.metadata.create_all(bind=engine)


def _drive_coro_no_sockets(coro):
    """
    Drives an async coroutine to completion synchronously without creating
    an OS event loop or Windows loopback socketpair (100% network-isolated).
    """
    try:
        while True:
            coro.send(None)
    except StopIteration as stop:
        return stop.value


class OfflineResponse:
    def __init__(self, status_code: int, headers: Dict[str, str], body: bytes):
        self.status_code = status_code
        self.headers = headers
        self.content = body

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8"))


class OfflineASGIClient:
    """
    Zero-socket synchronous ASGI test client for FastAPI/Starlette.
    Executes threadpool callables inline so tests run strictly offline in milliseconds.
    """

    def __init__(self, asgi_app, client_ip: str = "127.0.0.1"):
        self.app = asgi_app
        self.client_ip = client_ip

    def request(
        self,
        method: str,
        url: str,
        *,
        json_body: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> OfflineResponse:
        parsed = urllib.parse.urlsplit(url)
        path = parsed.path or "/"
        query_string = (parsed.query or "").encode("utf-8")

        raw_body = b""
        req_headers: List[tuple[bytes, bytes]] = [
            (b"host", b"testserver"),
            (b"user-agent", b"offline-asgi-testclient"),
        ]
        if json_body is not None:
            raw_body = json.dumps(json_body).encode("utf-8")
            req_headers.append((b"content-type", b"application/json"))
            if not headers or "content-length" not in [k.lower() for k in headers.keys()]:
                req_headers.append((b"content-length", str(len(raw_body)).encode("latin-1")))

        if headers:
            for k, v in headers.items():
                req_headers.append((k.lower().encode("latin-1"), str(v).encode("latin-1")))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method.upper(),
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("latin-1"),
            "query_string": query_string,
            "root_path": "",
            "headers": req_headers,
            "client": (self.client_ip, 50000),
            "server": ("testserver", 80),
            "state": {},
        }

        body_sent = False
        resp_status = 500
        resp_headers: Dict[str, str] = {}
        resp_chunks: List[bytes] = []

        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": raw_body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message: Dict[str, Any]):
            nonlocal resp_status, resp_headers
            msg_type = message.get("type")
            if msg_type == "http.response.start":
                resp_status = int(message.get("status", 200))
                resp_headers = {
                    k.decode("latin-1").lower(): v.decode("latin-1")
                    for k, v in message.get("headers", [])
                }
            elif msg_type == "http.response.body":
                chunk = message.get("body", b"")
                if chunk:
                    resp_chunks.append(chunk)

        async def _inline_run_sync(func, *args, **kwargs):
            return func(*args)

        async def _inline_threadpool(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch.object(anyio.to_thread, "run_sync", side_effect=_inline_run_sync), \
             patch.object(starlette.concurrency, "run_in_threadpool", side_effect=_inline_threadpool):
            _drive_coro_no_sockets(self.app(scope, receive, send))

        return OfflineResponse(resp_status, resp_headers, b"".join(resp_chunks))

    def get(self, url: str, *, headers: Optional[Dict[str, str]] = None) -> OfflineResponse:
        return self.request("GET", url, headers=headers)

    def post(
        self,
        url: str,
        *,
        json: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> OfflineResponse:
        return self.request("POST", url, json_body=json, headers=headers)

    def delete(self, url: str, *, headers: Optional[Dict[str, str]] = None) -> OfflineResponse:
        return self.request("DELETE", url, headers=headers)


@pytest.fixture
def client():
    if hasattr(app.state, "limiter"):
        app.state.limiter.reset()
    return OfflineASGIClient(app)


def test_gemini_prompt_anti_cheat_guardrails():
    """Verifies that the system prompt strictly prohibits direct homework answers."""
    assert "NO-LEAK" in ESTONIAN_TUTOR_SYSTEM_PROMPT
    assert "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО" in ESTONIAN_TUTOR_SYSTEM_PROMPT
    assert "ГДЗ" in ESTONIAN_TUTOR_SYSTEM_PROMPT
    assert "вымышленными числами" in ESTONIAN_TUTOR_SYSTEM_PROMPT.lower()

    profile = UserProfile(grade=4, nickname="Даниил")
    user_prompt = build_tutor_user_prompt(profile)
    assert "анти-чит" in user_prompt.lower() or "no-leak" in user_prompt.lower()


def test_gemini_emergency_fallback():
    """Verifies emergency fallback generates valid, friendly educational structure."""
    profile = UserProfile(grade=3, nickname="Маша")
    fallback = gemini_tutor_service._generate_emergency_fallback(profile)

    assert fallback is not None
    assert "Маша" in fallback.theme_explanation
    assert len(fallback.vocabulary) >= 2
    assert fallback.worked_example is not None
    assert "Попробовать снова" in fallback.worked_example.steps[2]


def test_telegram_message_length_truncation():
    """Verifies that exceptionally long error messages or texts are truncated to avoid Telegram 400."""
    giant_text = "E" * 5000
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value.status_code = 200

        with patch("app.config.settings.TELEGRAM_BOT_TOKEN", "mock_bot_token"), \
             patch("app.config.settings.TELEGRAM_CHAT_ID", "-10012345678"):
            _drive_coro_no_sockets(send_telegram_message(giant_text))
            assert mock_post.called
            kwargs = mock_post.call_args.kwargs
            if "json" in kwargs:
                sent_payload = kwargs["json"]
            elif "content" in kwargs:
                raw_c = kwargs["content"]
                sent_payload = json.loads(raw_c.decode("utf-8") if isinstance(raw_c, bytes) else raw_c)
            else:
                sent_payload = {}
            sent_text = sent_payload.get("text", "")
            assert len(sent_text) <= 4000
            assert "[truncated]" in sent_text


def test_rate_limiter_license_activate_blocks_excessive_attempts(client):
    """Verifies that brute-force attempts on /api/v1/license/activate are throttled at 5/minute."""
    headers = {"X-Device-ID": "test-ratelimit-device-activate"}

    for _ in range(5):
        resp = client.post(
            "/api/v1/license/activate",
            json={"key_code": "INVALID-KEY-CODE"},
            headers=headers,
        )
        assert resp.status_code in (400, 200), f"Expected 400, got {resp.status_code}"

    blocked_resp = client.post(
        "/api/v1/license/activate",
        json={"key_code": "INVALID-KEY-CODE"},
        headers=headers,
    )
    assert blocked_resp.status_code == 429
    data = blocked_resp.json()
    assert data.get("error") == "RATE_LIMIT_EXCEEDED"
    assert "Слишком много запросов" in data.get("message", "")


def test_dev_test_device_bypass_blocked_in_production(client):
    """Verifies that missing X-Device-ID is rejected and no DEV bypass exists in production."""
    dev_id = "default-dev-device-001"
    with patch("app.config.settings.APP_ENV", "production"):
        resp_missing = client.get("/api/v1/license/status")
        assert resp_missing.status_code == 400

        db = SessionLocal()
        try:
            db.query(Device).filter(Device.device_id == dev_id).delete()
            db.commit()
            status_prod = license_service.check_device_access(dev_id, db)
            assert status_prod["has_key"] is False
            assert status_prod["activated_key"] is None
            assert status_prod["days_left"] <= 14
        finally:
            db.query(Device).filter(Device.device_id == dev_id).delete()
            db.commit()
            db.close()


def test_telegram_webhook_secret_fail_closed_and_trusted_chat_routing(client):
    """
    [P0-B5] Verifies that /api/v1/telegram/webhook:
    1) Fails closed (HTTP 503) when TELEGRAM_WEBHOOK_SECRET is unset.
    2) Rejects wrong/missing header with HTTP 403 when secret is set.
    3) Routes /gen output ONLY to ADMIN_TELEGRAM_ID, ignoring forged chat.id in payload.
    4) Strips 'keys' and 'reply' from HTTP response body.
    """
    forged_payload = {
        "message": {
            "from": {"id": 777888999},
            "chat": {"id": 666666111},  # Attacker chat.id!
            "text": "/gen 1 30",
        }
    }

    # 1. Fail-closed when secret is empty in .env -> 503
    with patch("app.config.settings.TELEGRAM_WEBHOOK_SECRET", None):
        unconfigured_resp = client.post("/api/v1/telegram/webhook", json=forged_payload)
        assert unconfigured_resp.status_code == 503

    with patch("app.config.settings.ADMIN_TELEGRAM_ID", "777888999"), \
         patch("app.config.settings.TELEGRAM_WEBHOOK_SECRET", "super_secret_token_123"), \
         patch("app.services.telegram_alert.send_telegram_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True

        # 2. Missing secret header -> 403 Forbidden
        forbidden_resp = client.post("/api/v1/telegram/webhook", json=forged_payload)
        assert forbidden_resp.status_code == 403

        # 3. Valid secret header -> 200 OK, keys sent ONLY to trusted 777888999 (never 666666111)
        ok_resp = client.post(
            "/api/v1/telegram/webhook",
            json=forged_payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": "super_secret_token_123"},
        )
        assert ok_resp.status_code == 200
        body = ok_resp.json()
        assert body["ok"] is True
        assert body["result"]["command"] == "gen"
        assert "keys" not in body["result"]
        assert "reply" not in body["result"]

        assert mock_send.called
        target_chat = mock_send.call_args.kwargs.get("chat_id")
        assert str(target_chat) == "777888999"


def test_more_examples_allowed_when_zero_free_reviews_left(client):
    """Verifies that a trial user who spent their free reviews can still request 'More examples'."""
    device_id = "test-zero-reviews-more-examples"
    db = SessionLocal()
    try:
        client.get("/api/v1/license/status", headers={"X-Device-ID": device_id})
        dev = db.query(Device).filter(Device.device_id == device_id).first()
        dev.free_reviews_left = 0
        db.commit()

        with patch.object(
            gemini_tutor_service,
            "generate_more_examples",
            new=AsyncMock(return_value=["Summa on [12].", "Vastuseks on [15]."]),
        ):
            resp = client.post(
                "/api/v1/more-examples",
                json={
                    "task_title": "Liitmine",
                    "theme_explanation": "Сложение чисел",
                    "vocabulary": [{"est": "summa", "ru": "сумма", "example": "Summa on 10"}],
                    "current_template": "Summa on [10].",
                    "grade": 3,
                },
                headers={"X-Device-ID": device_id},
            )
        assert resp.status_code == 200
        assert len(resp.json().get("templates", [])) == 2
    finally:
        db.query(Device).filter(Device.device_id == device_id).delete()
        db.commit()
        db.close()


def test_invoice_confirm_admin_secret_and_idempotency(client):
    """
    [P0-B1] Verifies:
    1) POST /api/v1/license/invoice/confirm returns 503 if ADMIN_SECRET is unset,
       401 if X-Admin-Secret header is missing, and 403 if wrong.
    2) Repeated confirmation of the same invoice is strictly idempotent and NEVER adds days twice.
    """
    device_id = "test-invoice-confirm-dev-0001"
    inv_num = "INV-2026-990001"
    viite = "9900014"

    db = SessionLocal()
    try:
        db.query(Invoice).filter(Invoice.invoice_number == inv_num).delete()
        db.query(Device).filter(Device.device_id == device_id).delete()
        db.add(
            Invoice(
                invoice_number=inv_num,
                viitenumber=viite,
                customer_email="parent@test.ee",
                plan_id="month_1",
                amount="9.99",
                device_id=device_id,
                is_paid=False,
            )
        )
        db.commit()

        # 1. Empty ADMIN_SECRET in .env -> 503 Service Unavailable
        with patch("app.config.settings.ADMIN_SECRET", None):
            r_503 = client.post(
                "/api/v1/license/invoice/confirm",
                json={"invoice_number": inv_num},
                headers={"X-Admin-Secret": "anything"},
            )
            assert r_503.status_code == 503

        with patch("app.config.settings.ADMIN_SECRET", "top_secret_admin_key_2026"):
            # 2. Missing header -> 401 Unauthorized
            r_401 = client.post(
                "/api/v1/license/invoice/confirm",
                json={"invoice_number": inv_num},
            )
            assert r_401.status_code == 401

            # 3. Wrong secret -> 403 Forbidden
            r_403 = client.post(
                "/api/v1/license/invoice/confirm",
                json={"invoice_number": inv_num},
                headers={"X-Admin-Secret": "wrong_secret"},
            )
            assert r_403.status_code == 403

            # 4. Valid secret (1st call) -> 200 OK, activates 30 days
            r_ok_1 = client.post(
                "/api/v1/license/invoice/confirm",
                json={"invoice_number": inv_num},
                headers={"X-Admin-Secret": "top_secret_admin_key_2026"},
            )
            assert r_ok_1.status_code == 200
            body_1 = r_ok_1.json()
            assert body_1["is_active"] is True
            expires_1 = body_1["expires_at"]
            days_1 = body_1["days_left"]
            assert 29 <= days_1 <= 31

            # 5. Valid secret (2nd replay call) -> 200 OK, idempotent (days NOT added twice!)
            r_ok_2 = client.post(
                "/api/v1/license/invoice/confirm",
                json={"invoice_number": inv_num},
                headers={"X-Admin-Secret": "top_secret_admin_key_2026"},
            )
            assert r_ok_2.status_code == 200
            body_2 = r_ok_2.json()
            assert body_2["expires_at"] == expires_1
            assert body_2["days_left"] == days_1
    finally:
        db.query(Invoice).filter(Invoice.invoice_number == inv_num).delete()
        db.query(Device).filter(Device.device_id == device_id).delete()
        db.commit()
        db.close()


def test_invoice_pdf_idor_blocked_and_static_leak_closed(client):
    """
    [P0-B2] Verifies:
    1) /static/invoices/{invoice_number}.pdf is NOT publicly mounted (returns 404).
    2) Downloading another user's PDF invoice returns 403 Forbidden.
    3) Invalid invoice format is rejected with 400.
    4) Owner X-Device-ID or valid signed download token returns 200 with 'Cache-Control: private, no-store'.
    """
    owner_device = "device-owner-pdf-00001"
    attacker_device = "device-attacker-pdf-99"
    inv_num = "INV-2026-880001"
    private_dir = Path("data/private_invoices")
    private_dir.mkdir(parents=True, exist_ok=True)
    pdf_file = private_dir / f"{inv_num}.pdf"
    pdf_file.write_bytes(b"%PDF-1.4\n%Test Private Invoice\n%%EOF")

    db = SessionLocal()
    try:
        db.query(Invoice).filter(Invoice.invoice_number == inv_num).delete()
        db.add(
            Invoice(
                invoice_number=inv_num,
                viitenumber="8800018",
                customer_email="owner@test.ee",
                plan_id="school_year",
                amount="69.90",
                device_id=owner_device,
                pdf_path=str(pdf_file),
                is_paid=False,
            )
        )
        db.commit()

        # 1. Public /static/invoices/... must return 404
        static_resp = client.get(f"/static/invoices/{inv_num}.pdf")
        assert static_resp.status_code == 404

        # 2. Invalid invoice number regex -> 400
        bad_fmt = client.get(
            "/api/v1/license/invoice/BAD_INVOICE_NAME.pdf",
            headers={"X-Device-ID": owner_device},
        )
        assert bad_fmt.status_code == 400

        # 3. Attacker device trying to download owner's invoice -> 403 Forbidden
        idor_resp = client.get(
            f"/api/v1/license/invoice/{inv_num}.pdf",
            headers={"X-Device-ID": attacker_device},
        )
        assert idor_resp.status_code == 403

        # 4. Owner device -> 200 OK + Cache-Control: private, no-store
        owner_resp = client.get(
            f"/api/v1/license/invoice/{inv_num}.pdf",
            headers={"X-Device-ID": owner_device},
        )
        assert owner_resp.status_code == 200
        assert owner_resp.headers.get("cache-control") == "private, no-store"
        assert owner_resp.content.startswith(b"%PDF-1.4")

        # 5. Browser link with valid signed download token (no X-Device-ID header) -> 200 OK
        dl_token = sign_invoice_download_token(inv_num, owner_device)
        token_resp = client.get(f"/api/v1/license/invoice/{inv_num}.pdf?token={dl_token}")
        assert token_resp.status_code == 200
        assert token_resp.headers.get("cache-control") == "private, no-store"
    finally:
        db.query(Invoice).filter(Invoice.invoice_number == inv_num).delete()
        db.commit()
        db.close()
        if pdf_file.exists():
            pdf_file.unlink()


@pytest.mark.parametrize(
    "invalid_device_id",
    [
        "short-id-123",  # < 16 chars
        "x" * 65,  # > 64 chars
        "invalid spaces in device id",  # spaces
        "device_sql_inject';DROP--",  # forbidden punctuation
    ],
)
def test_invalid_x_device_id_rejected_without_creating_db_records(client, invalid_device_id):
    """[P0-B3] Verifies X-Device-ID regex ^[a-zA-Z0-9._-]{16,64}$ rejects bad IDs and writes zero DB rows."""
    resp = client.get("/api/v1/license/status", headers={"X-Device-ID": invalid_device_id})
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "INVALID_DEVICE_ID"

    db = SessionLocal()
    try:
        exists = db.query(Device).filter(Device.device_id == invalid_device_id).first()
        assert exists is None
    finally:
        db.close()


def test_revoked_compromised_keys_rejected_and_prod_sync_disabled(client):
    """[P0-B4] Verifies leaked repository keys cannot be activated and sync_keys_from_file is disabled in prod."""
    device_id = "test-compromised-key-dev-01"
    db = SessionLocal()
    try:
        license_service.revoke_compromised_keys(db)
        with patch("app.config.settings.APP_ENV", "production"):
            assert license_service.sync_keys_from_file(db) == 0

        resp = client.post(
            "/api/v1/license/activate",
            json={"key_code": "TARK-3ZME-TA4W"},
            headers={"X-Device-ID": device_id},
        )
        assert resp.status_code == 400
    finally:
        db.query(Device).filter(Device.device_id == device_id).delete()
        db.commit()
        db.close()


def test_trial_policy_closed_beta_vs_production():
    """
    Unit test for trial policy resolution and device registration:
    - TRIAL_MODE='production': 5 days, 10 daily reviews.
    - TRIAL_MODE='closed_beta': 14 days, 20 daily reviews.
    """
    with patch("app.config.settings.TRIAL_MODE", "production"), \
         patch("app.config.settings.PROD_TRIAL_DAYS", 5), \
         patch("app.config.settings.PROD_DAILY_REVIEWS", 10):
        days, quota = license_service._get_trial_policy()
        assert days == 5
        assert quota == 10

    with patch("app.config.settings.TRIAL_MODE", "closed_beta"), \
         patch("app.config.settings.BETA_TRIAL_DAYS", 14), \
         patch("app.config.settings.BETA_DAILY_REVIEWS", 20):
        days, quota = license_service._get_trial_policy()
        assert days == 14
        assert quota == 20


def test_trial_mode_switch_and_long_nickname_truncation(client):
    """
    Verifies:
    1) TRIAL_MODE='production' grants 5 days and 10 reviews/day with daily reset,
       while 'closed_beta' grants 14 days and 20 reviews/day.
    2) If trial expires, daily reset does not occur.
    3) Overlong nickname (>50 chars) on /api/v1/analyze-page/json is safely truncated instead of 500 error.
    """
    prod_device = "test-prod-trial-dev-01"
    beta_device = "test-beta-trial-dev-01"
    db = SessionLocal()
    try:
        db.query(Device).filter(Device.device_id.in_([prod_device, beta_device])).delete()
        db.commit()

        # 1. PRODUCTION MODE (5 days, 10 reviews/day)
        with patch("app.config.settings.TRIAL_MODE", "production"), \
             patch("app.config.settings.PROD_TRIAL_DAYS", 5), \
             patch("app.config.settings.PROD_DAILY_REVIEWS", 10):
            st = license_service.check_device_access(prod_device, db)
            assert st["allowed"] is True
            assert st["days_left"] == 5
            assert st["max_free_reviews"] == 10
            assert st["free_reviews_left"] == 10

            # Simulate consuming reviews down to 3 on previous day
            dev = db.query(Device).filter(Device.device_id == prod_device).first()
            dev.free_reviews_left = 3
            dev.last_review_date = "2020-01-01"
            db.commit()

            # Next day while trial is active: resets back to 10
            st_next_day = license_service.check_device_access(prod_device, db)
            assert st_next_day["free_reviews_left"] == 10
            assert st_next_day["max_free_reviews"] == 10

            # When trial has expired: daily reset must NOT occur
            dev.trial_expires_at = datetime.utcnow() - timedelta(hours=2)
            dev.free_reviews_left = 2
            dev.last_review_date = "2020-01-01"
            db.commit()

            st_expired = license_service.check_device_access(prod_device, db)
            assert st_expired["allowed"] is False
            assert st_expired["free_reviews_left"] == 2  # No reset when expired

        # 2. CLOSED_BETA MODE (14 days, 20 reviews/day)
        with patch("app.config.settings.TRIAL_MODE", "closed_beta"), \
             patch("app.config.settings.BETA_TRIAL_DAYS", 14), \
             patch("app.config.settings.BETA_DAILY_REVIEWS", 20):
            st_beta = license_service.check_device_access(beta_device, db)
            assert st_beta["allowed"] is True
            assert st_beta["days_left"] == 14
            assert st_beta["max_free_reviews"] == 20
            assert st_beta["free_reviews_left"] == 20

            # Simulate consuming reviews down to 5 on previous day
            dev_beta = db.query(Device).filter(Device.device_id == beta_device).first()
            dev_beta.free_reviews_left = 5
            dev_beta.last_review_date = "2020-01-01"
            db.commit()

            # Next day while trial is active: resets back to 20
            st_beta_next = license_service.check_device_access(beta_device, db)
            assert st_beta_next["free_reviews_left"] == 20
            assert st_beta_next["max_free_reviews"] == 20
    finally:
        db.query(Device).filter(Device.device_id.in_([prod_device, beta_device])).delete()
        db.commit()
        db.close()

    # Overlong nickname (120 chars) on analyze-page/json must succeed (200), not 500 ValidationError
    analyze_dev = "test-long-nickname-dev-001"
    img_buf = io.BytesIO()
    Image.new("RGB", (32, 32), color=(255, 255, 255)).save(img_buf, format="JPEG")
    b64_img = base64.b64encode(img_buf.getvalue()).decode("ascii")
    signed_tok = sign_auth_token(analyze_dev, "Ученик")

    mock_analysis = PageAnalysisResponse(
        task_title="Liitmine",
        theme_explanation="Проверка длинного имени",
        vocabulary=[{"est": "arv", "ru": "число", "example": "See on arv."}],
        how_to_answer="Сложи числа по шагам.",
        answer_template="Vastus on [5].",
        voice_prompt_script="Давай разберём задачу.",
    )

    db = SessionLocal()
    prev_override = app.dependency_overrides.pop(get_current_user, None)
    try:
        # Unsigned token must be rejected by real HMAC-SHA256 AuthGuard
        unauth_resp = client.post(
            "/api/v1/analyze-page/json",
            json={"images_base64": [b64_img], "grade": 3, "nickname": "Тест"},
            headers={
                "X-Device-ID": analyze_dev,
                "Authorization": f"Bearer {analyze_dev}:unsigned",
            },
        )
        assert unauth_resp.status_code == 401

        with patch.object(
            gemini_tutor_service,
            "analyze_page",
            new=AsyncMock(return_value=mock_analysis),
        ):
            resp = client.post(
                "/api/v1/analyze-page/json",
                json={
                    "images_base64": [b64_img],
                    "grade": 3,
                    "nickname": "Д" * 120,
                },
                headers={
                    "X-Device-ID": analyze_dev,
                    "Authorization": f"Bearer {signed_tok}",
                },
            )
        assert resp.status_code == 200
    finally:
        if prev_override is not None:
            app.dependency_overrides[get_current_user] = prev_override
        db.query(Device).filter(Device.device_id == analyze_dev).delete()
        db.commit()
        db.close()


def test_gdpr_delete_device_erases_private_invoices(client):
    """[P0-M5 / GDPR] Verifies DELETE /api/v1/license/device deletes associated invoices & PDFs."""
    gdpr_dev = "test-gdpr-delete-dev-0001"
    inv_num = "INV-2026-770001"
    private_dir = Path("data/private_invoices")
    private_dir.mkdir(parents=True, exist_ok=True)
    pdf_file = private_dir / f"{inv_num}.pdf"
    pdf_file.write_bytes(b"%PDF-1.4\n%GDPR Erasure Test\n%%EOF")

    db = SessionLocal()
    prev_override = app.dependency_overrides.pop(get_current_user, None)
    try:
        db.query(Invoice).filter(Invoice.invoice_number == inv_num).delete()
        db.add(
            Invoice(
                invoice_number=inv_num,
                viitenumber="7700012",
                customer_email="gdpr@test.ee",
                plan_id="month_1",
                amount="9.99",
                device_id=gdpr_dev,
                pdf_path=str(pdf_file),
                is_paid=False,
            )
        )
        db.commit()

        tok = sign_auth_token(gdpr_dev, "Ученик")
        del_resp = client.delete(
            "/api/v1/license/device",
            headers={
                "X-Device-ID": gdpr_dev,
                "Authorization": f"Bearer {tok}",
            },
        )
        assert del_resp.status_code == 200, del_resp.text
        assert del_resp.json().get("deleted_invoices") == 1
        assert not pdf_file.exists()
    finally:
        if prev_override is not None:
            app.dependency_overrides[get_current_user] = prev_override
        db.query(Invoice).filter(Invoice.invoice_number == inv_num).delete()
        db.query(Device).filter(Device.device_id == gdpr_dev).delete()
        db.commit()
        db.close()
        if pdf_file.exists():
            pdf_file.unlink()


def test_voice_post_endpoint_and_aliases(client, monkeypatch):
    """
    [P1-3] Проверка POST /api/v1/voice и POST /api/v1/voice/tts:
    1) Длинный текст (> 1300 символов, до 5000) успешно принимается без 414 URI Too Large и без 422.
    2) Передаются параметры grade и tier.
    3) GET /api/v1/voice и POST /api/v1/voice/tts алиасы работают корректно.
    """
    from app.services import tts_service
    from app.routers import voice as voice_router
    from app.routers.voice import VoiceRequest

    captured_kwargs = {}

    async def mock_get_or_synth(text, voice="ru-RU-SvetlanaNeural", bilingual=False, grade=None, tier=None):
        captured_kwargs["text"] = text
        captured_kwargs["voice"] = voice
        captured_kwargs["bilingual"] = bilingual
        captured_kwargs["grade"] = grade
        captured_kwargs["tier"] = tier
        return b"ID3" + b"\x00" * 1024

    monkeypatch.setattr(tts_service, "get_or_synthesize_audio", mock_get_or_synth)
    monkeypatch.setattr(voice_router, "get_or_synthesize_audio", mock_get_or_synth)

    # 1. POST /api/v1/voice с текстом > 2000 символов
    long_text = "Длинный текст для синтеза речи школьного урока математики. " * 45
    assert len(long_text) > 2000

    payload = {
        "text": long_text,
        "lang": "ru",
        "bilingual": True,
        "grade": 2,
        "tier": "primary",
    }
    resp_post = client.post(
        "/api/v1/voice",
        json=payload,
        headers={"X-Device-ID": "dev-test-device-0001"},
    )
    assert resp_post.status_code == 200, resp_post.text
    assert resp_post.headers["content-type"] == "audio/mpeg"
    assert captured_kwargs["grade"] == 2
    assert captured_kwargs["tier"] == "primary"
    assert captured_kwargs["bilingual"] is True

    # 2. POST /api/v1/voice/tts алиас
    resp_alias = client.post(
        "/api/v1/voice/tts",
        json=payload,
        headers={"X-Device-ID": "dev-test-device-0001"},
    )
    assert resp_alias.status_code == 200
    assert resp_alias.headers["content-type"] == "audio/mpeg"

    # 3. GET /api/v1/voice алиас
    resp_get = client.get(
        "/api/v1/voice?text=" + urllib.parse.quote("Привет") + "&lang=ru&device_id=dev-test-device-0001",
    )
    assert resp_get.status_code == 200
    assert resp_get.headers["content-type"] == "audio/mpeg"


def test_rate_limiter_proxy_headers_and_real_ip():
    """
    [P1-1] Проверка извлечения реального IP и двухуровневого лимита:
    1) get_remote_address извлекает IP из X-Real-IP.
    2) get_remote_address извлекает первый IP из X-Forwarded-For.
    3) Fallback к client.host при отсутствии прокси-заголовков.
    4) get_device_or_ip объединяет реальный IP и device_id.
    """
    from starlette.requests import Request
    from app.limiter import get_remote_address, get_device_or_ip

    # 1. X-Real-IP
    scope_real = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/analyze",
        "query_string": b"",
        "headers": [
            (b"x-real-ip", b"203.0.113.195"),
            (b"x-forwarded-for", b"198.51.100.1, 10.0.0.1"),
            (b"x-device-id", b"dev-client-123"),
        ],
        "client": ("127.0.0.1", 50000),
    }
    req_real = Request(scope_real)
    assert get_remote_address(req_real) == "203.0.113.195"
    assert get_device_or_ip(req_real) == "203.0.113.195:dev-client-123"

    # 2. X-Forwarded-For
    scope_xff = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/analyze",
        "query_string": b"",
        "headers": [
            (b"x-forwarded-for", b"198.51.100.42, 10.0.0.2"),
            (b"x-device-id", b"dev-client-456"),
        ],
        "client": ("127.0.0.1", 50000),
    }
    req_xff = Request(scope_xff)
    assert get_remote_address(req_xff) == "198.51.100.42"
    assert get_device_or_ip(req_xff) == "198.51.100.42:dev-client-456"

    # 3. Direct client without headers
    scope_direct = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/voice/tts",
        "query_string": b"",
        "headers": [],
        "client": ("192.168.1.55", 50000),
    }
    req_direct = Request(scope_direct)
    assert get_remote_address(req_direct) == "192.168.1.55"
    assert get_device_or_ip(req_direct) == "192.168.1.55:anon"


def test_lesson_session_lru_and_ram_protection():
    """
    [P1-6 & P1-2] Проверка емкости кэша сессий в RAM, LRU вытеснения и освобождения памяти:
    1) MAX_ACTIVE_SESSIONS = 50 жестко соблюдается.
    2) При создании 51-й сессии самая старая сессия вытесняется (LRU/FIFO).
    3) У вытесненной сессии буферы изображений (images) освобождаются (images.clear()).
    4) TTL сессии жестко ограничен 15 минутами (900 сек).
    5) Окно добавления разворота (can_append) ограничено 10 минутами (600 сек).
    """
    import time
    from app.services.lesson_session_service import (
        LessonSessionService,
        MAX_ACTIVE_SESSIONS,
        SESSION_TTL_SECONDS,
        APPEND_WINDOW_SECONDS,
    )
    from app.models.page_analysis import UserProfile

    svc = LessonSessionService(max_active_sessions=50, session_ttl=900)
    profile = UserProfile(grade=3)

    # 1. Заполняем кэш ровно до 50 сессий с фиктивными данными изображений
    fake_img = (b"\xff\xd8\xff\xe0" + b"\x00" * 1024, "image/jpeg")
    created_sessions = []
    for i in range(50):
        s = svc.create_session(
            lesson_id=f"ls_test_{i:03d}",
            device_id=f"dev-device-{i:03d}",
            profile=profile,
            images=[fake_img],
        )
        created_sessions.append(s)

    assert len(svc._sessions) == 50
    first_session = created_sessions[0]
    assert len(first_session.images) == 1

    # 2. Создаем 51-ю сессию: должна вытесниться ls_test_000
    s_new = svc.create_session(
        lesson_id="ls_test_050",
        device_id="dev-device-050",
        profile=profile,
        images=[fake_img],
    )
    assert len(svc._sessions) == 50
    assert svc.get_session("ls_test_000") is None
    # Буфер вытесненной сессии очищен
    assert len(first_session.images) == 0

    # 3. Проверка окна добавления (10 минут) и TTL (15 минут)
    now = time.time()
    s_test = svc.create_session(
        lesson_id="ls_ttl_test",
        device_id="dev-device-ttl",
        profile=profile,
        images=[fake_img],
    )
    assert s_test.can_append is True
    assert s_test.is_expired is False

    # Эмулируем прошло 650 секунд (> 10 мин, но < 15 мин)
    s_test.created_at = now - 650
    assert s_test.can_append is False  # Окно добавления закрыто
    assert s_test.is_expired is False   # Но сессия еще жива в памяти
    assert svc.get_session("ls_ttl_test") is not None

    # Эмулируем прошло 950 секунд (> 15 минут TTL)
    s_test.created_at = now - 950
    s_test.expires_at = now - 50
    assert s_test.is_expired is True
    # При запросе get_session просроченная сессия удаляется и очищаются буферы
    assert svc.get_session("ls_ttl_test") is None
    assert len(s_test.images) == 0


def test_spread_append_page_free_and_security(client, monkeypatch):
    """
    [P1-2] Проверка добавления второй страницы разворота учебника:
    1) Добавление страницы 2 в активную сессию (POST /api/v1/lessons/{lesson_id}/append-page) успешно
       работает без списания квоты разборов.
    2) Попытка добавить третью страницу отклоняется с кодом 400 PAGE_LIMIT_REACHED.
    3) Попытка обратиться с чужого X-Device-ID отклоняется с кодом 403 DEVICE_MISMATCH.
    4) Попытка отправить более 2 страниц в /api/v1/analyze-page/json отклоняется с кодом 400.
    """
    from app.services.lesson_session_service import lesson_session_service
    from app.models.page_analysis import PageAnalysisResponse, UserProfile, VocabularyItem

    lesson_session_service.clear()

    owner_dev = "dev-test-device-0001"
    other_dev = "dev-intruder-device-9999"

    # Создаем фиктивный результат анализа первой страницы
    mock_analysis_1 = PageAnalysisResponse(
        task_title="Умножение и деление",
        theme_explanation="Учимся умножать числа",
        how_to_answer="По шагам умножаем числа",
        answer_template="Vastus on [arv].",
        voice_prompt_script="Давай решим вместе!",
        vocabulary=[VocabularyItem(est="korrutamine", ru="умножение", example="See on korrutamine.")],
        lesson_id="ls_spread_123",
        page_count=1,
        can_append_page=True,
    )

    fake_img_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 500
    session = lesson_session_service.create_session(
        lesson_id="ls_spread_123",
        device_id=owner_dev,
        profile=UserProfile(grade=3),
        images=[(fake_img_bytes, "image/jpeg")],
        analysis=mock_analysis_1,
    )

    # Мокируем вызов Gemini для анализа второй страницы
    async def mock_gemini_analyze(profile, images):
        assert len(images) == 2
        return PageAnalysisResponse(
            task_title="Умножение и деление (Разворот)",
            theme_explanation="Полный разбор разворота",
            how_to_answer="Алгоритм для обеих страниц",
            answer_template="Vastus on [lahendus].",
            voice_prompt_script="Отлично, обе страницы проанализированы!",
            vocabulary=[VocabularyItem(est="jagamine", ru="деление", example="See on jagamine.")],
            lesson_id=session.lesson_id,
            page_count=2,
            can_append_page=False,
        )

    monkeypatch.setattr(gemini_tutor_service, "analyze_page", mock_gemini_analyze)

    # 1. Попытка добавить страницу с ЧУЖОГО устройства -> 403 DEVICE_MISMATCH
    payload_page2 = {
        "image_base64": base64.b64encode(fake_img_bytes).decode("ascii"),
        "mime_type": "image/jpeg",
    }
    resp_mismatch = client.post(
        f"/api/v1/lessons/{session.lesson_id}/append-page",
        json=payload_page2,
        headers={"X-Device-ID": other_dev},
    )
    assert resp_mismatch.status_code == 403
    assert "DEVICE_MISMATCH" in resp_mismatch.text

    # 2. Успешное добавление страницы 2 законным владельцем сессии -> 200 OK
    resp_append = client.post(
        f"/api/v1/lessons/{session.lesson_id}/append-page",
        json=payload_page2,
        headers={"X-Device-ID": owner_dev},
    )
    assert resp_append.status_code == 200, resp_append.text
    data_append = resp_append.json()
    assert data_append["page_count"] == 2
    assert data_append["can_append_page"] is False
    assert len(session.images) == 2

    # 3. Попытка добавить третью страницу в ту же сессию -> 400 PAGE_LIMIT_REACHED
    resp_third = client.post(
        f"/api/v1/lessons/{session.lesson_id}/append-page",
        json=payload_page2,
        headers={"X-Device-ID": owner_dev},
    )
    assert resp_third.status_code == 400
    assert "PAGE_LIMIT_REACHED" in resp_third.text


def test_oom_dos_payload_size_limit_pre_read(client):
    """
    [P1-6] Проверка защиты от OOM DoS:
    1) Запрос с Content-Length > 20 МБ отклоняется кодом 413 до чтения потока.
    2) Base64 строка изображения > 14 МБ отклоняется кодом 413 до b64decode.
    3) QuickTranslateRequest с текстом > 1000 символов отклоняется валидатором (422).
    4) MoreExamplesRequest с заголовком > 1000 символов отклоняется валидатором (422).
    """
    # 1. Pre-read Content-Length > 20 MB на /api/v1/analyze-page/json
    resp_cl = client.post(
        "/api/v1/analyze-page/json",
        json={"grade": 3},
        headers={
            "X-Device-ID": "dev-test-device-0001",
            "Content-Length": "25000000",  # 25 MB
        },
    )
    assert resp_cl.status_code == 413, resp_cl.text
    assert "превышает допустимый лимит 20 МБ" in resp_cl.text

    # 2. Слишком большая Base64 строка (15 MB)
    oversized_b64 = "A" * (15 * 1024 * 1024)
    resp_b64 = client.post(
        "/api/v1/translate/quick",
        json={"image_base64": oversized_b64},
        headers={"X-Device-ID": "dev-test-device-0001"},
    )
    assert resp_b64.status_code == 413, resp_b64.text
    assert "превышает лимит 10 МБ" in resp_b64.text

    # 3. QuickTranslateRequest max_length=1000 валидация
    too_long_text = "слово " * 250  # 1500 chars > 1000
    resp_translate = client.post(
        "/api/v1/translate/quick",
        json={"text": too_long_text},
        headers={"X-Device-ID": "dev-test-device-0001"},
    )
    assert resp_translate.status_code == 422

    # 4. MoreExamplesRequest max_length=1000 валидация
    resp_examples = client.post(
        "/api/v1/more-examples",
        json={"task_title": "А" * 1200},
        headers={"X-Device-ID": "dev-test-device-0001"},
    )
    assert resp_examples.status_code == 422


def test_more_examples_lightweight_system_prompt():
    """
    [P1-6] Проверка использования специализированного легковесного промпта:
    1) MORE_EXAMPLES_SYSTEM_PROMPT определен и компактен (< 1 КБ).
    2) Не содержит тяжеловесных инструкций Режима A / Режима B из базового 23 КБ промпта.
    """
    from app.prompts.tutor_prompt import MORE_EXAMPLES_SYSTEM_PROMPT, ESTONIAN_TUTOR_SYSTEM_PROMPT

    assert len(MORE_EXAMPLES_SYSTEM_PROMPT) < 1000
    assert "Õppetöö" not in MORE_EXAMPLES_SYSTEM_PROMPT
    assert "Maailma Avastaja" not in MORE_EXAMPLES_SYSTEM_PROMPT
    assert len(ESTONIAN_TUTOR_SYSTEM_PROMPT) > 6000


def test_atomic_review_deduction_toctou_prevented():
    """
    [P1-5] Атомарное списание квоты и устранение TOCTOU:
    1) При наличии квоты (free_reviews_left > 0) списывает ровно 1 разбор атомарно.
    2) При нулевой квоте (free_reviews_left == 0) UPDATE затрагивает 0 строк и
       возбуждает HTTPException(403, detail={"error": "REVIEWS_LIMIT_REACHED", ...}).
    3) Баланс не уходит в минус, total_reviews_used отражает фактическое число списаний.
    """
    from fastapi import HTTPException
    device_id = "test-atomic-toctou-device-01"
    db = SessionLocal()
    try:
        db.query(Device).filter(Device.device_id == device_id).delete()
        dev = Device(
            device_id=device_id,
            free_reviews_left=1,
            max_free_reviews=20,
            total_reviews_used=0,
            trial_expires_at=datetime.utcnow() + timedelta(days=14),
            activated_key=None,
        )
        db.add(dev)
        db.commit()

        # Первое списание: 1 -> 0, total: 0 -> 1
        rem = license_service.deduct_review_attempt(device_id, db)
        assert rem == 0

        db.refresh(dev)
        assert dev.free_reviews_left == 0
        assert dev.total_reviews_used == 1

        # Второе списание: баланс 0 -> rowcount == 0 -> 403 REVIEWS_LIMIT_REACHED
        with pytest.raises(HTTPException) as exc_info:
            license_service.deduct_review_attempt(device_id, db)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail.get("error") == "REVIEWS_LIMIT_REACHED"

        # Проверка неизменности состояния в базе (нет отрицательного баланса)
        db.refresh(dev)
        assert dev.free_reviews_left == 0
        assert dev.total_reviews_used == 1
    finally:
        db.query(Device).filter(Device.device_id == device_id).delete()
        db.commit()
        db.close()


def test_atomic_review_deduction_pro_unlimited():
    """
    [P1-5] Для платных / PRO подписок (is_unlimited):
    free_reviews_left не декрементируется (сохраняется для пользователя),
    а total_reviews_used инкрементируется при каждом обращении.
    """
    device_id = "test-pro-unlimited-device-02"
    db = SessionLocal()
    try:
        db.query(Device).filter(Device.device_id == device_id).delete()
        dev = Device(
            device_id=device_id,
            free_reviews_left=15,
            max_free_reviews=20,
            total_reviews_used=3,
            trial_expires_at=datetime.utcnow() + timedelta(days=30),
            activated_key="TARK-PRO-TEST-KEY",
        )
        db.add(dev)
        db.commit()

        # Первое обращение PRO пользователя
        rem1 = license_service.deduct_review_attempt(device_id, db)
        assert rem1 == 15
        db.refresh(dev)
        assert dev.free_reviews_left == 15
        assert dev.total_reviews_used == 4

        # Второе обращение PRO пользователя
        rem2 = license_service.deduct_review_attempt(device_id, db)
        assert rem2 == 15
        db.refresh(dev)
        assert dev.free_reviews_left == 15
        assert dev.total_reviews_used == 5
    finally:
        db.query(Device).filter(Device.device_id == device_id).delete()
        db.commit()
        db.close()


def test_telegram_webhook_secret_token_authentication(client):
    """
    [P2-2] Безопасность Telegram Bot Webhook:
    1) Отклонение запроса с 503 если TELEGRAM_WEBHOOK_SECRET не настроен в .env (fail-closed).
    2) Отклонение запроса с 403 при отсутствии заголовка X-Telegram-Bot-Api-Secret-Token.
    3) Отклонение запроса с 403 при неверном значении токена.
    4) Успешная обработка (200 OK) при совпадении токена как на /api/v1/telegram/webhook,
       так и на legacy алиасе /api/telegram/webhook.
    """
    sample_update = {
        "update_id": 999888,
        "message": {
            "from": {"id": 12345678},
            "chat": {"id": 12345678},
            "text": "/help",
        },
    }

    # 1. Fail-closed если секрет не сконфигурирован
    with patch("app.config.settings.TELEGRAM_WEBHOOK_SECRET", ""):
        resp_no_secret = client.post("/api/v1/telegram/webhook", json=sample_update)
        assert resp_no_secret.status_code == 503
        assert "not configured" in resp_no_secret.text.lower()

    configured_secret = "secure_webhook_secret_abc123"
    with patch("app.config.settings.TELEGRAM_WEBHOOK_SECRET", configured_secret), \
         patch("app.services.telegram_alert.process_telegram_update", new_callable=AsyncMock) as mock_process:
        mock_process.return_value = {"command": "help", "status": "ok"}

        # 2. Отсутствие заголовка -> 403
        resp_missing = client.post("/api/v1/telegram/webhook", json=sample_update)
        assert resp_missing.status_code == 403
        assert "invalid telegram webhook secret" in resp_missing.text.lower()

        # 3. Неверный заголовок -> 403
        resp_wrong = client.post(
            "/api/v1/telegram/webhook",
            json=sample_update,
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong_secret_xyz"},
        )
        assert resp_wrong.status_code == 403

        # 4. Валидный заголовок на /api/v1/telegram/webhook -> 200 OK
        resp_v1_ok = client.post(
            "/api/v1/telegram/webhook",
            json=sample_update,
            headers={"X-Telegram-Bot-Api-Secret-Token": configured_secret},
        )
        assert resp_v1_ok.status_code == 200
        assert resp_v1_ok.json().get("ok") is True

        # 5. Валидный заголовок на legacy алиасе /api/telegram/webhook -> 200 OK
        resp_legacy_ok = client.post(
            "/api/telegram/webhook",
            json=sample_update,
            headers={"X-Telegram-Bot-Api-Secret-Token": configured_secret},
        )
        assert resp_legacy_ok.status_code == 200
        assert resp_legacy_ok.json().get("ok") is True


def test_async_threadpool_offloading():
    """
    [P2-1] Проверка выноса блокирующих SQLite вызовов из Event Loop:
    1) analyze_page & analyze_page_json используют anyio.to_thread.run_sync для deduct_review_attempt.
    2) verify_device_access & verify_review_access используют anyio.to_thread.run_sync.
    """
    import inspect
    from app.routers import analyze as analyze_mod, license as license_mod

    # Проверка исходного кода analyze.py на вызов deduct_review_attempt через to_thread.run_sync
    analyze_src = inspect.getsource(analyze_mod)
    assert "await anyio.to_thread.run_sync(license_service.deduct_review_attempt" in analyze_src

    # Проверка исходного кода license.py на вызовы через to_thread.run_sync
    license_src = inspect.getsource(license_mod)
    assert "await anyio.to_thread.run_sync(license_service.check_device_access" in license_src
    assert "await anyio.to_thread.run_sync(license_service.verify_review_allowance" in license_src


def test_security_headers_middleware(client):
    """
    [P3-3] Проверка глобального Security Headers Middleware:
    Все исходящие ответы содержат защитные заголовки:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - Referrer-Policy: strict-origin-when-cross-origin
    - Permissions-Policy: geolocation=(), camera=(), microphone=()
    """
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200

    headers = resp.headers
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("x-frame-options") == "DENY"
    assert headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert "geolocation=()" in headers.get("permissions-policy", "")
    assert "camera=()" in headers.get("permissions-policy", "")
    assert "microphone=()" in headers.get("permissions-policy", "")


def test_cors_origins_configuration():
    """
    [P3-3] Проверка строгой конфигурации CORS:
    1) Отсутствие открытого allow_origins=["*"] в конфигурации по умолчанию.
    2) Наличие доверенных доменов tarkapp.ee и портов локальной разработки.
    3) Корректная десериализация списка источников из строки или JSON.
    """
    from app.config import settings, Settings

    assert "*" not in settings.CORS_ORIGINS
    assert any("tarkapp.ee" in origin for origin in settings.CORS_ORIGINS)

    # Проверка парсинга из переменной окружения через валидатор
    parsed_comma = Settings.parse_cors_origins("https://tarkapp.ee, https://admin.tarkapp.ee")
    assert parsed_comma == ["https://tarkapp.ee", "https://admin.tarkapp.ee"]

    parsed_json = Settings.parse_cors_origins('["https://app.tarkapp.ee"]')
    assert parsed_json == ["https://app.tarkapp.ee"]


def test_sensitive_data_logging_sanitizer():
    """
    [P3-2] Санитайзинг логов и защита персональных данных:
    1) Маскирование X-Device-ID (первые 4 и последние 4 символа: abcd...1234).
    2) Полное маскирование лицензионных ключей (TARK-****-****, [KEY_MASKED]).
    3) Полное маскирование Bearer токенов, X-Auth-Token, вебхук и админ секретов.
    4) Замена бинарных Base64-строк изображений на компактный размер [image: X KB].
    """
    from app.middleware.security import mask_device_id, sanitize_log_message

    # 1. Device ID
    assert mask_device_id("dev-test-device-0001") == "dev-...0001"
    assert mask_device_id("abcdef123456") == "abcd...3456"
    assert mask_device_id("short") == "****"
    assert mask_device_id("") == ""

    # 2. X-Device-ID в тексте лога
    log_dev = sanitize_log_message("Request X-Device-ID: dev-test-device-0001 dispatched")
    assert "dev-test-device-0001" not in log_dev
    assert "dev-...0001" in log_dev

    # 3. Лицензионные ключи
    log_key = sanitize_log_message("User activated key TARK-A1B2-C3D4 successfully")
    assert "TARK-A1B2-C3D4" not in log_key
    assert "TARK-****-****" in log_key

    log_json_key = sanitize_log_message('Payload: {"key_code": "TARK-9999-8888"}')
    assert "TARK-9999-8888" not in log_json_key
    assert "[KEY_MASKED]" in log_json_key

    # 4. Токены и секреты
    log_token = sanitize_log_message("Header Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz")
    assert "eyJhbGci" not in log_token
    assert "Bearer [TOKEN_MASKED]" in log_token

    log_secret = sanitize_log_message("Header X-Telegram-Bot-Api-Secret-Token: my_secret_token_abc")
    assert "my_secret_token_abc" not in log_secret
    assert "X-Telegram-Bot-Api-Secret-Token: [SECRET_MASKED]" in log_secret

    log_admin = sanitize_log_message("Header X-Admin-Secret: ultra_secret_admin_pw")
    assert "ultra_secret_admin_pw" not in log_admin
    assert "X-Admin-Secret: [SECRET_MASKED]" in log_admin

    # 5. Base64 изображения (не выводить мегабайты в лог)
    fake_b64 = "A" * 800  # ~600 байт
    log_b64_data = sanitize_log_message(f"Image uploaded: data:image/jpeg;base64,{fake_b64}")
    assert fake_b64 not in log_b64_data
    assert "[image: 1 KB]" in log_b64_data

    log_b64_json = sanitize_log_message(f'{{"images_base64": ["{fake_b64}"]}}')
    assert fake_b64 not in log_b64_json
    assert "[image: 1 KB]" in log_b64_json


def test_request_logging_middleware_masks_device_id(client, caplog):
    """
    [P3-2] Проверка RequestLoggingMiddleware на маскирование X-Device-ID при логировании входящих HTTP запросов.
    """
    import logging
    with caplog.at_level(logging.INFO):
        resp = client.get("/api/v1/health", headers={"X-Device-ID": "dev-test-device-0001"})
        assert resp.status_code == 200

        # В логах запроса должен фигурировать маскированный ID dev-...0001, а не сырой полный ID
        found_masked = any("dev-...0001" in record.message for record in caplog.records)
        found_raw = any("dev-test-device-0001" in record.message for record in caplog.records)

        assert found_masked is True
        assert found_raw is False





