import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models.license import Device, AccessKey, KeyActivateRequest
from app.services.license_service import normalize_key_code, activate_key, sync_keys_from_file

@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()

def test_normalize_key_code():
    assert normalize_key_code("  tark-1234-5678 \n") == "TARK-1234-5678"
    assert normalize_key_code("TARK–1234—5678") == "TARK-1234-5678"
    assert normalize_key_code("TARK - 1234 - 5678") == "TARK-1234-5678"
    assert normalize_key_code("TARK12345678") == "TARK-1234-5678"

def test_key_activate_request_validator():
    req = KeyActivateRequest(key_code="  tark-a5f3-vvjf \n")
    assert req.key_code == "TARK-A5F3-VVJF"

    req2 = KeyActivateRequest(key_code="TARK–A5F3—VVJF")
    assert req2.key_code == "TARK-A5F3-VVJF"

def test_activate_key_lifecycle(test_db):
    key = AccessKey(
        key_code="TARK-TEST-1234",
        duration_days=30,
        is_used=False,
    )
    test_db.add(key)
    test_db.commit()

    # 1. Activation with spaces and lowercase succeeds
    res = activate_key("device-alpha", "  tark-test-1234 \n", test_db)
    assert res["success"] is True
    assert res["is_active"] is True
    assert res["days_left"] >= 30

    # 2. Re-activating for the SAME device confirms active status without error
    res_repeat = activate_key("device-alpha", "TARK-TEST-1234", test_db)
    assert res_repeat["success"] is True
    assert res_repeat["is_active"] is True

    # 3. Activating the same key from a DIFFERENT device raises ValueError
    with pytest.raises(ValueError, match="уже был активирован ранее"):
        activate_key("device-beta", "TARK-TEST-1234", test_db)

    # 4. Unknown key raises ValueError
    with pytest.raises(ValueError, match="не найден"):
        activate_key("device-alpha", "TARK-NON-EXISTENT", test_db)
