from datetime import datetime
from typing import Optional
from sqlalchemy import Column, String, DateTime, Boolean, Integer, ForeignKey
from pydantic import BaseModel, Field

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


class KeyActivateRequest(BaseModel):
    key_code: str = Field(..., min_length=4, max_length=64, description="Access key code, e.g. TARK-XXXX-XXXX")


class KeyActivateResponse(BaseModel):
    success: bool
    message: str
    is_active: bool
    has_key: bool = True
    free_reviews_left: int = 5
    max_free_reviews: int = 5
    days_left: int
    expires_at: str
