import pytest
from app.main import app


@pytest.fixture(autouse=True)
def reset_rate_limit_storage():
    """Ensures each pytest unit test runs with fresh rate limit quotas."""
    if hasattr(app.state, "limiter"):
        app.state.limiter.reset()
    yield
    if hasattr(app.state, "limiter"):
        app.state.limiter.reset()
