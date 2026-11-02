import pytest
from fastapi import HTTPException, status
from app.auth import get_current_user, CurrentUser


def test_get_current_user_missing_token_raises_401():
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization=None, x_auth_token=None)
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == {
        "error": "UNAUTHORIZED",
        "message": "Войдите в профиль, чтобы использовать разборы",
    }
    assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}


@pytest.mark.parametrize("bad_token", [
    "",
    "   ",
    "null",
    "undefined",
    "guest",
    "anonymous",
    "none",
])
def test_get_current_user_disallowed_tokens_raise_401(bad_token):
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization=f"Bearer {bad_token}")
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail["error"] == "UNAUTHORIZED"

    with pytest.raises(HTTPException) as exc_info2:
        get_current_user(x_auth_token=bad_token)
    assert exc_info2.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info2.value.detail["error"] == "UNAUTHORIZED"


def test_get_current_user_valid_bearer_token():
    user = get_current_user(authorization="Bearer dev-device-123:Данил")
    assert isinstance(user, CurrentUser)
    assert user.user_id == "dev-device-123"
    assert user.nickname == "Данил"
    assert user.token == "dev-device-123:Данил"


def test_get_current_user_valid_x_auth_token():
    user = get_current_user(x_auth_token="device-999:Марк")
    assert isinstance(user, CurrentUser)
    assert user.user_id == "device-999"
    assert user.nickname == "Марк"
    assert user.token == "device-999:Марк"


def test_get_current_user_token_without_nickname():
    user = get_current_user(authorization="Bearer valid-token-uuid")
    assert isinstance(user, CurrentUser)
    assert user.user_id == "valid-token-uuid"
    assert user.nickname == "Ученик"
    assert user.token == "valid-token-uuid"
