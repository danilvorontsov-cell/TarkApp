import asyncio
import io
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models.license import Device
from app.services import license_service
from app.services.gemini_service import gemini_tutor_service


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def sample_jpeg_bytes():
    img = Image.new("RGB", (100, 100), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class TestNetworkDropAndDisconnection:
    """
    Chaos testing: simulates client disconnection and network drop mid-flight.
    Verifies that free review quota (free_reviews_left) is NEVER decremented
    if the response was not successfully generated and delivered to the user.
    """

    def test_client_disconnect_cancellation_does_not_deduct_attempts(
        self, db_session, sample_jpeg_bytes, monkeypatch
    ):
        dev_id = "test-drop-client-cancel-dev"

        # Register device with 5 free reviews
        device = db_session.query(Device).filter(Device.device_id == dev_id).first()
        if device:
            device.free_reviews_left = 5
            device.activated_key = None
            db_session.commit()
        else:
            license_service.check_device_access(dev_id, db_session)
            device = db_session.query(Device).filter(Device.device_id == dev_id).first()
            device.free_reviews_left = 5
            device.activated_key = None
            db_session.commit()

        initial_reviews = device.free_reviews_left
        assert initial_reviews == 5

        # Simulate client abruptly disconnecting mid-flight (asyncio task cancellation)
        async def mock_disconnected_mid_flight(*args, **kwargs):
            # Client aborted connection -> asyncio.CancelledError is raised by ASGI
            raise asyncio.CancelledError("Client connection dropped / aborted by mobile network")

        monkeypatch.setattr(gemini_tutor_service, "analyze_page", mock_disconnected_mid_flight)

        client = TestClient(app)
        files = {"files": ("page.jpg", sample_jpeg_bytes, "image/jpeg")}

        # When client connection drops / cancels, request terminates with error
        try:
            response = client.post(
                "/api/v1/analyze-page",
                files=files,
                data={"grade": 3, "nickname": "Петя"},
                headers={"X-Device-ID": dev_id},
            )
            # Should not be 200 OK since connection was interrupted
            assert response.status_code != 200
        except Exception:
            pass

        # Check database: attempts must remain UNCHANGED (5 attempts remaining)
        db_session.expire_all()
        refreshed_device = db_session.query(Device).filter(Device.device_id == dev_id).first()
        assert refreshed_device.free_reviews_left == 5, (
            f"Expected free_reviews_left to remain 5 after network drop, got: {refreshed_device.free_reviews_left}"
        )

    def test_server_error_500_does_not_deduct_attempts(
        self, db_session, sample_jpeg_bytes, monkeypatch
    ):
        dev_id = "test-drop-server-err-dev"

        # Register device with 5 free reviews
        device = db_session.query(Device).filter(Device.device_id == dev_id).first()
        if device:
            device.free_reviews_left = 5
            device.activated_key = None
            db_session.commit()
        else:
            license_service.check_device_access(dev_id, db_session)
            device = db_session.query(Device).filter(Device.device_id == dev_id).first()
            device.free_reviews_left = 5
            device.activated_key = None
            db_session.commit()

        # Simulate unexpected network socket timeout / connection drop to LLM
        async def mock_network_socket_drop(*args, **kwargs):
            raise ConnectionResetError("Connection reset by peer (Network drop to upstream)")

        monkeypatch.setattr(gemini_tutor_service, "analyze_page", mock_network_socket_drop)

        client = TestClient(app)
        files = {"files": ("page.jpg", sample_jpeg_bytes, "image/jpeg")}

        response = client.post(
            "/api/v1/analyze-page",
            files=files,
            data={"grade": 3, "nickname": "Петя"},
            headers={"X-Device-ID": dev_id},
        )

        assert response.status_code == 500

        # Verify free_reviews_left is still 5
        db_session.expire_all()
        refreshed_device = db_session.query(Device).filter(Device.device_id == dev_id).first()
        assert refreshed_device.free_reviews_left == 5

    def test_successful_delivery_deducts_exactly_one_attempt(
        self, db_session, sample_jpeg_bytes
    ):
        dev_id = "test-drop-success-dev"

        device = db_session.query(Device).filter(Device.device_id == dev_id).first()
        if device:
            device.free_reviews_left = 5
            device.activated_key = None
            db_session.commit()
        else:
            license_service.check_device_access(dev_id, db_session)
            device = db_session.query(Device).filter(Device.device_id == dev_id).first()
            device.free_reviews_left = 5
            device.activated_key = None
            db_session.commit()

        client = TestClient(app)
        files = {"files": ("page.jpg", sample_jpeg_bytes, "image/jpeg")}

        response = client.post(
            "/api/v1/analyze-page",
            files=files,
            data={"grade": 3, "nickname": "Петя"},
            headers={"X-Device-ID": dev_id},
        )

        assert response.status_code == 200

        # Verify free_reviews_left is now 4
        db_session.expire_all()
        refreshed_device = db_session.query(Device).filter(Device.device_id == dev_id).first()
        assert refreshed_device.free_reviews_left == 4
