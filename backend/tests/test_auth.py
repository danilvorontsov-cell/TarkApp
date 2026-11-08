import urllib.parse
import pytest
from fastapi import HTTPException, status
from app.auth import (
    CurrentUser,
    get_current_user,
    sign_auth_token,
    sign_invoice_download_token,
    verify_invoice_download_token,
)


def test_get_current_user_missing_token_raises_401():
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization=None, x_auth_token=None)
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == {
        "error": "UNAUTHORIZED",
        "message": "Войдите в профиль, чтобы использовать разборы",
    }
    assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}


@pytest.mark.parametrize(
    "bad_token",
    [
        "",
        "   ",
        "null",
        "undefined",
        "guest",
        "anonymous",
        "none",
        "dev-device-12345678:Данил",  # Unsigned legacy token must be rejected!
        "dev-device-12345678:Данил.0000000000000000000000000000000000000000000000000000000000000000",  # Forged HMAC
    ],
)
def test_get_current_user_invalid_or_unsigned_tokens_raise_401(bad_token):
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization=f"Bearer {bad_token}")
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail["error"] == "UNAUTHORIZED"

    with pytest.raises(HTTPException) as exc_info2:
        get_current_user(x_auth_token=bad_token)
    assert exc_info2.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info2.value.detail["error"] == "UNAUTHORIZED"


def test_get_current_user_valid_signed_bearer_token():
    signed = sign_auth_token("dev-device-12345678", "Данил")
    user = get_current_user(authorization=f"Bearer {signed}")
    assert isinstance(user, CurrentUser)
    assert user.user_id == "dev-device-12345678"
    assert user.nickname == "Данил"
    assert user.token == signed


def test_get_current_user_valid_signed_x_auth_token():
    signed = sign_auth_token("device-999999999999", "Марк")
    user = get_current_user(x_auth_token=signed)
    assert isinstance(user, CurrentUser)
    assert user.user_id == "device-999999999999"
    assert user.nickname == "Марк"
    assert user.token == signed


def test_tampered_payload_with_valid_signature_format_raises_401():
    signed = sign_auth_token("device-111111111111", "Алиса")
    _, sig = signed.rsplit(".", 1)
    forged = f"device-222222222222:{urllib.parse.quote('Алиса')}.{sig}"
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization=f"Bearer {forged}")
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


def test_sign_auth_token_truncates_long_nickname_to_50_chars():
    long_nick = "А" * 120
    signed = sign_auth_token("device-123456789012", long_nick)
    user = get_current_user(authorization=f"Bearer {signed}")
    assert len(user.nickname) == 50
    assert user.nickname == "А" * 50


def test_invoice_download_token_signing_and_verification():
    tok = sign_invoice_download_token("INV-2026-1001", "device-owner-123456")
    assert verify_invoice_download_token("INV-2026-1001", "device-owner-123456", tok) is True
    assert verify_invoice_download_token("INV-2026-1002", "device-owner-123456", tok) is False
    assert verify_invoice_download_token("INV-2026-1001", "device-attacker-999", tok) is False
    assert verify_invoice_download_token("INV-2026-1001", "device-owner-123456", "") is False
