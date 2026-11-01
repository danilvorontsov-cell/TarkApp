import re
from datetime import datetime
from typing import Optional, Any
from sqlalchemy import Column, String, DateTime, Boolean, Integer, ForeignKey
from pydantic import BaseModel, Field, field_validator

from app.database import Base


# ==========================================
# SQLAlchemy ORM Models
# ==========================================

class Device(Base):
    __tablename__ = "devices"

    device_id = Column(String, primary_key=True, index=True)  # Android/Expo ID
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    trial_expires_at = Column(DateTime, nullable=False)
    has_active_access = Column(Boolean, default=True)
    activated_key = Column(String, nullable=True)
    free_reviews_left = Column(Integer, default=5, nullable=False)


class AccessKey(Base):
    __tablename__ = "access_keys"

    key_code = Column(String, primary_key=True, index=True)  # e.g. TARK-XXXX-XXXX
    duration_days = Column(Integer, default=30)              # Key validity in days
    is_used = Column(Boolean, default=False)
    used_by_device = Column(String, ForeignKey("devices.device_id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    used_at = Column(DateTime, nullable=True)


# ==========================================
# Pydantic Schemas for API
# ==========================================

class LicenseStatusResponse(BaseModel):
    is_active: bool
    has_key: bool = False
    free_reviews_left: int = 5
    max_free_reviews: int = 5
    days_left: int
    expires_at: str
    device_id: Optional[str] = None
    activated_key: Optional[str] = None
    package_name: Optional[str] = None


class KeyActivateRequest(BaseModel):
    key_code: str = Field(..., min_length=4, max_length=64, description="Access key code, e.g. TARK-XXXX-XXXX")

    @field_validator("key_code", mode="before")
    @classmethod
    def clean_key_code(cls, v: Any) -> str:
        if isinstance(v, str):
            cleaned = v.strip().upper()
            cleaned = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]", "-", cleaned)
            cleaned = re.sub(r"\s*-\s*", "-", cleaned)
            cleaned = "".join(cleaned.split())
            if len(cleaned) == 12 and "-" not in cleaned and cleaned.startswith("TARK"):
                cleaned = f"{cleaned[:4]}-{cleaned[4:8]}-{cleaned[8:12]}"
            return cleaned
        return v


class KeyActivateResponse(BaseModel):
    success: bool
    message: str
    is_active: bool
    has_key: bool = True
    free_reviews_left: int = 5
    max_free_reviews: int = 5
    days_left: int
    expires_at: str
    package_name: Optional[str] = None


class InvoiceRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254, description="Customer email for PDF invoice delivery")
    plan: str = Field(default="year", description="Selected subscription plan: year, semester, month, full_year")


class InvoiceResponse(BaseModel):
    success: bool
    email_sent: bool
    invoice_number: str
    transport: str = "none"
    message: str

