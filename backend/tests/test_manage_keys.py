from datetime import datetime, timedelta
from pathlib import Path
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.database import SessionLocal, init_db
from app.models.license import Device, AccessKey
from app.services.license_service import (
    generate_access_keys,
    get_keys_stats,
    list_access_keys,
)
from app.services.telegram_alert import (
    handle_admin_telegram_command,
    process_telegram_update,
    is_admin_user,
)
import scripts.manage_keys as cli_module


@pytest.fixture
def db_session():
    init_db()
    db = SessionLocal()
    # Clean up test keys and devices
    db.query(AccessKey).filter(AccessKey.key_code.like("MNG-%")).delete()
    db.query(AccessKey).filter(AccessKey.key_code.like("TARK-%")).delete()
    db.query(Device).filter(Device.device_id.like("test-mng-%")).delete()
    db.commit()
    try:
        yield db
    finally:
        db.query(AccessKey).filter(AccessKey.key_code.like("MNG-%")).delete()
        db.query(Device).filter(Device.device_id.like("test-mng-%")).delete()
        db.commit()
        db.close()


def test_generate_access_keys(db_session):
    """Verifies that generate_access_keys creates unique crypto-keys with is_used=False in DB."""
    keys = generate_access_keys(count=5, days=45, prefix="MNG", db=db_session)
    assert len(keys) == 5
    assert len(set(keys)) == 5

    for k in keys:
        assert k.startswith("MNG-")
        assert len(k.split("-")) == 3
        key_db = db_session.query(AccessKey).filter(AccessKey.key_code == k).first()
        assert key_db is not None
        assert key_db.is_used is False
        assert key_db.duration_days == 45
        assert key_db.used_by_device is None


def test_get_keys_stats_and_list_filtering(db_session):
    """Verifies accurate categorization of free, active, and expired keys and devices."""
    now = datetime.utcnow()

    # 1. Device that is active
    dev_active = Device(
        device_id="test-mng-active-dev",
        first_seen_at=now - timedelta(days=5),
        trial_expires_at=now + timedelta(days=25),
        has_active_access=True,
    )
    # 2. Device that has expired
    dev_expired = Device(
        device_id="test-mng-expired-dev",
        first_seen_at=now - timedelta(days=40),
        trial_expires_at=now - timedelta(days=10),
        has_active_access=False,
    )
    db_session.add_all([dev_active, dev_expired])
    db_session.commit()

    # 3. Create 1 free key, 1 active key, 1 expired key
    k_free = AccessKey(key_code="MNG-FREE-1111", duration_days=30, is_used=False)
    k_active = AccessKey(
        key_code="MNG-ACTV-2222",
        duration_days=30,
        is_used=True,
        used_by_device="test-mng-active-dev",
        used_at=now - timedelta(days=5),
    )
    k_expired = AccessKey(
        key_code="MNG-EXPR-3333",
        duration_days=30,
        is_used=True,
        used_by_device="test-mng-expired-dev",
        used_at=now - timedelta(days=40),
    )
    db_session.add_all([k_free, k_active, k_expired])
    db_session.commit()

    stats = get_keys_stats(db=db_session)
    assert stats["total_devices"] >= 2
    assert stats["free_keys"] >= 1
    assert stats["active_keys"] >= 1
    assert stats["expired_keys"] >= 1

    # Test list filtering
    free_list = list_access_keys(filter_status="free", db=db_session)
    assert any(item["key_code"] == "MNG-FREE-1111" for item in free_list)
    assert all(item["status"] == "free" for item in free_list)

    active_list = list_access_keys(filter_status="active", db=db_session)
    assert any(item["key_code"] == "MNG-ACTV-2222" for item in active_list)
    assert all(item["status"] == "active" for item in active_list)

    expired_list = list_access_keys(filter_status="expired", db=db_session)
    assert any(item["key_code"] == "MNG-EXPR-3333" for item in expired_list)
    assert all(item["status"] == "expired" for item in expired_list)


def test_cli_manage_keys_gen_and_list(tmp_path, db_session):
    """Verifies CLI gen and list commands using argparse Namespace."""
    out_file = tmp_path / "test_generated_keys.txt"

    # Test gen command
    gen_args = cli_module.argparse.Namespace(
        count=3,
        days=15,
        prefix="MNG",
        output=str(out_file),
    )
    ret_gen = cli_module.cmd_gen(gen_args)
    assert ret_gen == 0
    assert out_file.exists()
    lines = [line.strip() for line in out_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 3
    for line in lines:
        assert line.startswith("MNG-")

    # Test list command
    list_args = cli_module.argparse.Namespace(filter="free")
    ret_list = cli_module.cmd_list(list_args)
    assert ret_list == 0


@pytest.mark.anyio
async def test_telegram_admin_authorization(db_session):
    """Verifies that unauthorized Telegram users are rejected with their ID shown."""
    orig_admin = settings.ADMIN_TELEGRAM_ID
    settings.ADMIN_TELEGRAM_ID = "555666777"
    try:
        assert is_admin_user("555666777") is True
        assert is_admin_user("12345") is False

        with patch("app.services.telegram_alert.send_telegram_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            result = await handle_admin_telegram_command(
                text="/gen 5 30",
                user_id="999000111",  # Not admin
                chat_id="chat-123",
                db=db_session,
            )
            assert result["handled"] is True
            assert result["authorized"] is False
            assert "999000111" in result["reply"]
            assert "Доступ запрещен" in result["reply"]
            mock_send.assert_awaited_once()
    finally:
        settings.ADMIN_TELEGRAM_ID = orig_admin


@pytest.mark.anyio
async def test_telegram_admin_gen_command(db_session):
    """Verifies that /gen generates keys and formats them with <code>KEY</code> for 1-click copy."""
    orig_admin = settings.ADMIN_TELEGRAM_ID
    settings.ADMIN_TELEGRAM_ID = "777888999"
    try:
        with patch("app.services.telegram_alert.send_telegram_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            result = await handle_admin_telegram_command(
                text="/gen 4 45",
                user_id="777888999",
                chat_id="admin-chat-1",
                db=db_session,
            )
            assert result["handled"] is True
            assert result["authorized"] is True
            assert result["command"] == "gen"
            assert result["count"] == 4
            assert result["days"] == 45
            assert len(result["keys"]) == 4

            # Verify <code>...</code> formatting in the message
            for k in result["keys"]:
                assert f"<code>{k}</code>" in result["reply"]
            assert "45 дн." in result["reply"]

            mock_send.assert_awaited_once()
            call_kwargs = mock_send.call_args.kwargs
            assert call_kwargs["chat_id"] == "admin-chat-1"
            assert call_kwargs["parse_mode"] == "HTML"
    finally:
        settings.ADMIN_TELEGRAM_ID = orig_admin


@pytest.mark.anyio
async def test_telegram_admin_stats_command(db_session):
    """Verifies that /stats returns accurate summary metrics."""
    orig_admin = settings.ADMIN_TELEGRAM_ID
    settings.ADMIN_TELEGRAM_ID = "777888999"
    try:
        with patch("app.services.telegram_alert.send_telegram_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            result = await handle_admin_telegram_command(
                text="/stats",
                user_id="777888999",
                chat_id="admin-chat-1",
                db=db_session,
            )
            assert result["handled"] is True
            assert result["authorized"] is True
            assert result["command"] == "stats"
            assert "Статистика лицензий TarkApp" in result["reply"]
            assert "Всего устройств:" in result["reply"]
            assert "Свободных" in result["reply"]
            mock_send.assert_awaited_once()
    finally:
        settings.ADMIN_TELEGRAM_ID = orig_admin


@pytest.mark.anyio
async def test_telegram_admin_help_command(db_session):
    """Verifies that /help returns available commands."""
    orig_admin = settings.ADMIN_TELEGRAM_ID
    settings.ADMIN_TELEGRAM_ID = "777888999"
    try:
        with patch("app.services.telegram_alert.send_telegram_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            result = await handle_admin_telegram_command(
                text="/help",
                user_id="777888999",
                chat_id="admin-chat-1",
                db=db_session,
            )
            assert result["handled"] is True
            assert result["authorized"] is True
            assert result["command"] == "help"
            assert "/gen" in result["reply"]
            assert "/stats" in result["reply"]
    finally:
        settings.ADMIN_TELEGRAM_ID = orig_admin


@pytest.mark.anyio
async def test_process_telegram_update_wrapper(db_session):
    """Verifies that update payloads with messages are parsed and dispatched."""
    orig_admin = settings.ADMIN_TELEGRAM_ID
    settings.ADMIN_TELEGRAM_ID = "111222333"
    try:
        with patch("app.services.telegram_alert.send_telegram_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            update_payload = {
                "update_id": 1001,
                "message": {
                    "message_id": 42,
                    "from": {"id": 111222333, "is_bot": False, "first_name": "Admin"},
                    "chat": {"id": 111222333, "type": "private"},
                    "text": "/gen 2 30",
                },
            }

            res = await process_telegram_update(update_payload, db=db_session)
            assert res is not None
            assert res["command"] == "gen"
            assert res["count"] == 2
    finally:
        settings.ADMIN_TELEGRAM_ID = orig_admin


def test_telegram_webhook_route():
    """Verifies that POST /api/v1/telegram/webhook accepts updates."""
    client = TestClient(app)
    payload = {
        "update_id": 9999,
        "message": {
            "message_id": 1,
            "from": {"id": 999, "is_bot": False},
            "chat": {"id": 999},
            "text": "regular non-command message",
        },
    }
    response = client.post("/api/v1/telegram/webhook", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
