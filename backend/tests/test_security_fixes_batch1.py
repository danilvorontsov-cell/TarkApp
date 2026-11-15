import pytest
from fastapi import HTTPException
from app.auth import get_current_user, require_valid_bearer_token, sign_auth_token, CurrentUser
from app.routers.license import mask_activated_key
from app.utils.security import sanitize_log_message, mask_device_id
from app.config import Settings


def test_mask_activated_key():
    assert mask_activated_key("TARK-ABCD-1234-EF56") == "TARK-****-EF56"
    assert mask_activated_key("XYZ9876") == "TARK-****-9876"
    assert mask_activated_key("") is None
    assert mask_activated_key(None) is None


def test_sanitize_log_message_with_dots():
    raw_header = "Incoming header X-Device-ID: my.device.id.12345678 processing"
    sanitized = sanitize_log_message(raw_header)
    assert "my.device.id.12345678" not in sanitized
    assert "my.d...5678" in sanitized

    raw_json = '{"device_id": "com.company.app.device.77889900"}'
    sanitized_json = sanitize_log_message(raw_json)
    assert "com.company.app.device.77889900" not in sanitized_json
    assert "com....9900" in sanitized_json


def test_config_production_secret_key_validator():
    # Production with default dev key MUST raise RuntimeError
    with pytest.raises(RuntimeError) as exc_info:
        Settings(
            APP_ENV="production",
            SECRET_KEY="tarkapp-dev-hmac-secret-change-in-production",
        )
    assert "CRITICAL SECURITY CONFIGURATION ERROR" in str(exc_info.value)

    # Production with customized secret key MUST pass
    prod_custom = Settings(
        APP_ENV="production",
        SECRET_KEY="a-very-secure-custom-production-secret-key-12345",
    )
    assert prod_custom.APP_ENV == "production"

    # Development with default dev key MUST pass
    dev_default = Settings(
        APP_ENV="development",
        SECRET_KEY="tarkapp-dev-hmac-secret-change-in-production",
    )
    assert dev_default.APP_ENV == "development"


def test_auth_invalid_authorization_header_no_fallback_to_device_id():
    # 1. Invalid HMAC token in Authorization header MUST raise 401, even if valid X-Device-ID is provided
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(
            authorization="Bearer invalid.forged.token.payload.0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            x_device_id="valid-device-12345",
        )
    assert exc_info.value.status_code == 401

    # 2. Malformed Authorization header MUST raise 401, even with X-Device-ID
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(
            authorization="Bearer badtoken",
            x_device_id="valid-device-12345",
        )
    assert exc_info.value.status_code == 401

    # 3. Valid Authorization Bearer token passes
    valid_token = sign_auth_token("user-valid-123", "Alice")
    user = get_current_user(
        authorization=f"Bearer {valid_token}",
        x_device_id="different-device-456",
    )
    assert user.user_id == "user-valid-123"
    assert user.nickname == "Alice"

    # 4. Fallback to X-Device-ID works ONLY when Authorization is omitted
    fallback_user = get_current_user(
        authorization=None,
        x_device_id="native-device-9999",
    )
    assert fallback_user.user_id == "native-device-9999"


def test_require_valid_bearer_token():
    valid_token = sign_auth_token("user-test-777", "Bob")
    valid_user = CurrentUser(user_id="user-test-777", nickname="Bob", token=valid_token)

    # Valid Bearer header passes
    user = require_valid_bearer_token(
        authorization=f"Bearer {valid_token}",
        current_user=valid_user,
    )
    assert user.user_id == "user-test-777"

    # Missing Authorization header raises 401
    with pytest.raises(HTTPException) as exc_info:
        require_valid_bearer_token(
            authorization=None,
            current_user=valid_user,
        )
    assert exc_info.value.status_code == 401

    # Non-Bearer Authorization header raises 401
    with pytest.raises(HTTPException) as exc_info:
        require_valid_bearer_token(
            authorization="Basic dXNlcjpwYXNz",
            current_user=valid_user,
        )
    assert exc_info.value.status_code == 401
