import base64
import time
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.lesson_session_service import lesson_session_service, SESSION_TIMEOUT_SECONDS
from app.services import license_service
from app.database import SessionLocal

TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


@pytest.fixture(autouse=True)
def reset_sessions():
    lesson_session_service.clear()
    yield
    lesson_session_service.clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_initial_scan_creates_session_and_deducts_one_point(client):
    """
    Scenario 1: Initial scan creates active lesson session, returns lesson_id,
    and deducts exactly 1 review point from the device quota.
    """
    device_id = "test-session-dev-1"
    headers = {
        "X-Device-ID": device_id,
        "Authorization": f"Bearer {device_id}:Student",
    }

    # Verify initial quota
    with SessionLocal() as db:
        status_data = license_service.check_device_access(device_id, db)
        initial_left = status_data["free_reviews_left"]

    payload = {
        "image_base64": TINY_PNG_B64,
        "mime_type": "image/png",
        "grade": 3,
        "interests": ["LEGO", "Roblox"],
        "nickname": "Ученик",
    }

    response = client.post("/api/v1/analyze-page/json", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()

    assert data.get("lesson_id") is not None
    assert data.get("lesson_id").startswith("ls_")
    assert data.get("page_count") == 1
    assert data.get("can_append_page") is True
    assert data.get("session_seconds_remaining") is not None
    assert data.get("session_seconds_remaining") > 0

    # Verify exactly 1 point was deducted
    with SessionLocal() as db:
        status_after = license_service.check_device_access(device_id, db)
        assert status_after["free_reviews_left"] == initial_left - 1


def test_append_page_reactive_and_zero_cost(client):
    """
    Scenario 2: Appending a 2nd page within 5 minutes regenerates analysis
    with 2 pages and DOES NOT deduct any balance points.
    """
    device_id = "test-session-dev-2"
    headers = {
        "X-Device-ID": device_id,
        "Authorization": f"Bearer {device_id}:Student",
    }

    # 1. Initial scan
    payload_1 = {
        "image_base64": TINY_PNG_B64,
        "mime_type": "image/png",
        "grade": 3,
        "interests": ["LEGO"],
    }
    res_1 = client.post("/api/v1/analyze-page/json", json=payload_1, headers=headers)
    assert res_1.status_code == 200
    lesson_id = res_1.json()["lesson_id"]

    # Record remaining reviews before append
    with SessionLocal() as db:
        before_append = license_service.check_device_access(device_id, db)["free_reviews_left"]

    # 2. Append page 2 via JSON
    append_payload = {
        "image_base64": TINY_PNG_B64,
        "mime_type": "image/png",
    }
    res_append = client.post(
        f"/api/v1/lessons/{lesson_id}/append-page",
        json=append_payload,
        headers=headers,
    )
    assert res_append.status_code == 200, res_append.text
    append_data = res_append.json()

    assert append_data["lesson_id"] == lesson_id
    assert append_data["page_count"] == 2
    assert append_data["can_append_page"] is False

    # Verify quota did NOT decrease! (1 point for entire session)
    with SessionLocal() as db:
        after_append = license_service.check_device_access(device_id, db)["free_reviews_left"]
        assert after_append == before_append


def test_append_page_legacy_alias_url(client):
    """
    Scenario 3: Supports /api/lessons/{lesson_id}/append-page route alias.
    """
    device_id = "test-session-dev-alias"
    headers = {
        "X-Device-ID": device_id,
        "Authorization": f"Bearer {device_id}:Student",
    }

    res_1 = client.post(
        "/api/v1/analyze-page/json",
        json={"image_base64": TINY_PNG_B64, "mime_type": "image/png", "grade": 4},
        headers=headers,
    )
    assert res_1.status_code == 200
    lesson_id = res_1.json()["lesson_id"]

    res_alias = client.post(
        f"/api/lessons/{lesson_id}/append-page",
        json={"image_base64": TINY_PNG_B64, "mime_type": "image/png"},
        headers=headers,
    )
    assert res_alias.status_code == 200
    assert res_alias.json()["page_count"] == 2


def test_page_limit_enforcement_max_two_pages(client):
    """
    Scenario 4: Rejects 3rd page append with HTTP 400 PAGE_LIMIT_REACHED.
    """
    device_id = "test-session-dev-limit"
    headers = {
        "X-Device-ID": device_id,
        "Authorization": f"Bearer {device_id}:Student",
    }

    res_1 = client.post(
        "/api/v1/analyze-page/json",
        json={"image_base64": TINY_PNG_B64, "mime_type": "image/png", "grade": 3},
        headers=headers,
    )
    lesson_id = res_1.json()["lesson_id"]

    # Append 2nd page -> OK
    res_2 = client.post(
        f"/api/v1/lessons/{lesson_id}/append-page",
        json={"image_base64": TINY_PNG_B64, "mime_type": "image/png"},
        headers=headers,
    )
    assert res_2.status_code == 200

    # Attempt to append 3rd page -> Rejection
    res_3 = client.post(
        f"/api/v1/lessons/{lesson_id}/append-page",
        json={"image_base64": TINY_PNG_B64, "mime_type": "image/png"},
        headers=headers,
    )
    assert res_3.status_code == 400
    err = res_3.json()
    assert err["detail"]["error"] == "PAGE_LIMIT_REACHED"


def test_session_timeout_five_minutes(client):
    """
    Scenario 5: Rejects append after 5 minutes with HTTP 410 SESSION_EXPIRED.
    """
    device_id = "test-session-dev-timeout"
    headers = {
        "X-Device-ID": device_id,
        "Authorization": f"Bearer {device_id}:Student",
    }

    res_1 = client.post(
        "/api/v1/analyze-page/json",
        json={"image_base64": TINY_PNG_B64, "mime_type": "image/png", "grade": 3},
        headers=headers,
    )
    lesson_id = res_1.json()["lesson_id"]

    # Artificially expire the session
    session = lesson_session_service.get_session(lesson_id)
    session.expires_at = time.time() - 10

    res_append = client.post(
        f"/api/v1/lessons/{lesson_id}/append-page",
        json={"image_base64": TINY_PNG_B64, "mime_type": "image/png"},
        headers=headers,
    )
    assert res_append.status_code == 410
    err = res_append.json()
    assert err["detail"]["error"] == "SESSION_EXPIRED"


def test_device_mismatch_protection(client):
    """
    Scenario 6: Cross-device append attempt is rejected with HTTP 403.
    """
    dev_1 = "test-session-dev-owner"
    dev_2 = "test-session-dev-attacker"

    res_1 = client.post(
        "/api/v1/analyze-page/json",
        json={"image_base64": TINY_PNG_B64, "mime_type": "image/png", "grade": 3},
        headers={"X-Device-ID": dev_1, "Authorization": f"Bearer {dev_1}:Owner"},
    )
    lesson_id = res_1.json()["lesson_id"]

    res_hack = client.post(
        f"/api/v1/lessons/{lesson_id}/append-page",
        json={"image_base64": TINY_PNG_B64, "mime_type": "image/png"},
        headers={"X-Device-ID": dev_2, "Authorization": f"Bearer {dev_2}:Attacker"},
    )
    assert res_hack.status_code == 403
    err = res_hack.json()
    assert err["detail"]["error"] == "DEVICE_MISMATCH"


def test_session_not_found(client):
    """
    Scenario 7: Appending to non-existent lesson_id returns HTTP 404.
    """
    res = client.post(
        "/api/v1/lessons/ls_non_existent_12345/append-page",
        json={"image_base64": TINY_PNG_B64, "mime_type": "image/png"},
        headers={"X-Device-ID": "dev-1", "Authorization": "Bearer dev-1:User"},
    )
    assert res.status_code == 404
    err = res.json()
    assert err["detail"]["error"] == "SESSION_NOT_FOUND"
