import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_submit_feedback_bug_success():
    payload = {
        "category": "bug",
        "message": "Кнопка озвучки не сработала на 3 странице учебника.",
        "contact": "@student_danil",
        "device_model": "Google Pixel 7",
        "os_version": "Android 14",
        "app_version": "1.0.0",
        "current_grade": 8,
        "last_request_id": "req_abc12345",
        "client_time": "2026-10-27T18:30:00.000Z",
    }
    with patch("app.routers.feedback.send_telegram_feedback", new_callable=AsyncMock) as mock_tg:
        mock_tg.return_value = True
        response = client.post("/api/v1/feedback", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Спасибо" in data["message"]


def test_submit_feedback_feature_success():
    payload = {
        "category": "feature",
        "message": "Добавьте, пожалуйста, темную тему для вечерних занятий!",
        "contact": "danil@example.com",
        "device_model": "iPhone 15 Pro",
        "os_version": "iOS 17.5",
        "app_version": "1.0.0",
        "current_grade": 11,
    }
    with patch("app.routers.feedback.send_telegram_feedback", new_callable=AsyncMock) as mock_tg:
        mock_tg.return_value = True
        response = client.post("/api/v1/feedback", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


def test_submit_feedback_invalid_category():
    payload = {
        "category": "complaint",  # Invalid, must be bug or feature
        "message": "Что-то не работает",
    }
    response = client.post("/api/v1/feedback", json=payload)
    assert response.status_code == 422


def test_submit_feedback_short_message():
    payload = {
        "category": "bug",
        "message": "1",  # Too short (min_length=3)
    }
    response = client.post("/api/v1/feedback", json=payload)
    assert response.status_code == 422


def test_x_request_id_in_response_headers():
    response = client.get("/health", headers={"x-request-id": "trace-test-123"})
    assert response.status_code == 200
    assert response.headers.get("x-request-id") == "trace-test-123"
