from datetime import datetime, timedelta
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal, init_db
from app.models.license import Device, AccessKey
from app.services import license_service

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    db = SessionLocal()
    # Clean up test records
    db.query(Device).filter(Device.device_id.like("test-%")).delete()
    db.query(AccessKey).filter(AccessKey.key_code.like("TEST-%")).delete()
    db.commit()
    yield db
    db.query(Device).filter(Device.device_id.like("test-%")).delete()
    db.query(AccessKey).filter(AccessKey.key_code.like("TEST-%")).delete()
    db.commit()
    db.close()


def test_first_seen_device_gets_14_day_trial(setup_db):
    db = setup_db
    device_id = "test-device-fresh-1"

    res = license_service.check_device_access(device_id, db)
    assert res["allowed"] is True
    assert res["is_active"] is True
    assert res["has_key"] is False
    assert res["free_reviews_left"] == 5
    assert res["max_free_reviews"] == 5
    assert res["days_left"] == 14

    dev_in_db = db.query(Device).filter(Device.device_id == device_id).first()
    assert dev_in_db is not None
    assert dev_in_db.has_active_access is True
    assert dev_in_db.free_reviews_left == 5
    assert dev_in_db.trial_expires_at > datetime.utcnow()


def test_expired_trial_blocked(setup_db):
    db = setup_db
    device_id = "test-device-expired-1"

    # Pre-create expired device
    past_date = datetime.utcnow() - timedelta(days=2)
    dev = Device(
        device_id=device_id,
        first_seen_at=datetime.utcnow() - timedelta(days=16),
        trial_expires_at=past_date,
        has_active_access=False,
    )
    db.add(dev)
    db.commit()

    res = license_service.check_device_access(device_id, db)
    assert res["allowed"] is False
    assert res["is_active"] is False
    assert res["days_left"] == 0


def test_endpoint_status_returns_trial_info(setup_db):
    device_id = "test-device-endpoint-status"
    response = client.get("/api/v1/license/status", headers={"X-Device-ID": device_id})
    assert response.status_code == 200
    data = response.json()
    assert data["is_active"] is True
    assert data["days_left"] == 14
    assert "expires_at" in data


def test_activate_key_success(setup_db):
    db = setup_db
    device_id = "test-device-activate-1"
    key_code = "TEST-KEY-30DAYS"

    # Pre-create key
    key_obj = AccessKey(
        key_code=key_code,
        duration_days=30,
        is_used=False,
    )
    db.add(key_obj)
    db.commit()

    response = client.post(
        "/api/v1/license/activate",
        headers={"X-Device-ID": device_id},
        json={"key_code": key_code},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["is_active"] is True
    assert data["days_left"] >= 40  # 14 trial + 30 key

    # Verify key in DB is marked used
    db_key = db.query(AccessKey).filter(AccessKey.key_code == key_code).first()
    assert db_key.is_used is True
    assert db_key.used_by_device == device_id


def test_activate_already_used_key_rejected(setup_db):
    db = setup_db
    device_id = "test-device-activate-2"
    key_code = "TEST-USED-KEY"

    key_obj = AccessKey(
        key_code=key_code,
        duration_days=30,
        is_used=True,
        used_by_device="another-device",
    )
    db.add(key_obj)
    db.commit()

    response = client.post(
        "/api/v1/license/activate",
        headers={"X-Device-ID": device_id},
        json={"key_code": key_code},
    )
    assert response.status_code == 400
    data = response.json()
    assert "KEY_ACTIVATION_FAILED" in str(data)


def test_activate_nonexistent_key_rejected(setup_db):
    device_id = "test-device-activate-3"
    response = client.post(
        "/api/v1/license/activate",
        headers={"X-Device-ID": device_id},
        json={"key_code": "TEST-NONEXISTENT"},
    )
    assert response.status_code == 400
    data = response.json()
    assert "KEY_ACTIVATION_FAILED" in str(data)


def test_expired_device_blocked_on_protected_endpoint(setup_db):
    db = setup_db
    expired_device_id = "test-device-blocked-endpoint"

    # Pre-create expired device in DB
    past_date = datetime.utcnow() - timedelta(days=5)
    dev = Device(
        device_id=expired_device_id,
        first_seen_at=datetime.utcnow() - timedelta(days=20),
        trial_expires_at=past_date,
        has_active_access=False,
    )
    db.add(dev)
    db.commit()

    # Attempt to use quick translate
    response = client.post(
        "/api/v1/translate/quick",
        headers={"X-Device-ID": expired_device_id},
        json={"text": "Tere tulemast kooli!"},
    )
    assert response.status_code == 403
    data = response.json()
    assert data["detail"]["error"] == "TRIAL_EXPIRED"


def test_status_endpoint_returns_review_counters(setup_db):
    device_id = "test-device-review-counters"
    response = client.get("/api/v1/license/status", headers={"X-Device-ID": device_id})
    assert response.status_code == 200
    data = response.json()
    assert data["has_key"] is False
    assert data["free_reviews_left"] == 5
    assert data["max_free_reviews"] == 5
    assert data["is_active"] is True


def test_deduct_review_attempt_decreases_counter(setup_db):
    db = setup_db
    device_id = "test-device-deduct"

    # Register device
    license_service.check_device_access(device_id, db)

    # Deduct 1 review
    left1 = license_service.deduct_review_attempt(device_id, db)
    assert left1 == 4

    left2 = license_service.deduct_review_attempt(device_id, db)
    assert left2 == 3


def test_reviews_limit_reached_blocks_analysis(setup_db):
    db = setup_db
    device_id = "test-device-limit-reached"

    # Pre-create device with 0 reviews left
    dev = Device(
        device_id=device_id,
        first_seen_at=datetime.utcnow() - timedelta(days=1),
        trial_expires_at=datetime.utcnow() + timedelta(days=13),
        has_active_access=True,
        free_reviews_left=0,
    )
    db.add(dev)
    db.commit()

    # Attempt to analyze page via JSON
    payload = {
        "images_base64": ["aGVsbG8="],
        "mime_type": "image/jpeg",
        "grade": 3,
    }
    response = client.post(
        "/api/v1/analyze-page/json",
        headers={"X-Device-ID": device_id},
        json=payload,
    )
    assert response.status_code == 403
    data = response.json()
    assert data["detail"]["error"] == "REVIEWS_LIMIT_REACHED"
    assert "Бесплатные разборы закончились" in data["detail"]["message"]


def test_activated_key_grants_unlimited_reviews(setup_db):
    db = setup_db
    device_id = "test-device-unlimited"
    key_code = "TEST-UNLIMITED-KEY"

    # Create key and activate
    key_obj = AccessKey(
        key_code=key_code,
        duration_days=30,
        is_used=False,
    )
    db.add(key_obj)
    db.commit()

    # Pre-create device with 0 reviews left
    dev = Device(
        device_id=device_id,
        first_seen_at=datetime.utcnow() - timedelta(days=1),
        trial_expires_at=datetime.utcnow() + timedelta(days=13),
        has_active_access=True,
        free_reviews_left=0,
    )
    db.add(dev)
    db.commit()

    # Activate key
    act_res = license_service.activate_key(device_id, key_code, db)
    assert act_res["success"] is True
    assert act_res["has_key"] is True

    # Now verify_review_allowance should pass without error!
    allowance = license_service.verify_review_allowance(device_id, db)
    assert allowance["has_key"] is True
    assert allowance["allowed"] is True

    # And deducting should NOT decrement reviews for key holders
    left = license_service.deduct_review_attempt(device_id, db)
    assert left == 0  # unchanged

