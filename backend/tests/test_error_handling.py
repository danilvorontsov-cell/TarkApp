import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import asyncio
import json
import pytest
from fastapi import Request

from app.main import global_exception_handler, app
from app.logger import APP_LOG_PATH, ERROR_LOG_PATH
from app.services.telegram_alert import send_telegram_alert


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
async def test_global_exception_handler_and_error_logging():
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/analyze-page",
        "headers": [],
        "server": ("testserver", 80),
    }
    req = Request(scope)
    try:
        raise RuntimeError("Simulated critical failure during analysis")
    except Exception as e:
        exc = e

    # Call global exception handler directly with await
    response = await global_exception_handler(req, exc)

    # 1. Verify HTTP 500 status code
    assert response.status_code == 500

    # 2. Verify structured user-friendly JSON contract
    body = json.loads(response.body.decode("utf-8"))
    assert body.get("error") is True
    assert body.get("code") == "INTERNAL_SERVER_ERROR"
    assert "Временный сбой при обработке задания" in body.get("message", "")

    # 3. Verify traceback is written to backend/logs/error.log
    assert Path(ERROR_LOG_PATH).exists()
    error_content = Path(ERROR_LOG_PATH).read_text(encoding="utf-8")
    assert "Simulated critical failure during analysis" in error_content
    assert "Traceback" in error_content


@pytest.mark.anyio
async def test_telegram_alert_silent_when_not_configured():
    # Should safely return False without throwing when tokens are missing
    result = await send_telegram_alert("/api/v1/test", RuntimeError("Test error"), 500)
    assert result is False


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_global_exception_handler_and_error_logging())
    asyncio.run(test_telegram_alert_silent_when_not_configured())
    print("ALL TESTS PASSED SUCCESSFULLY!")
