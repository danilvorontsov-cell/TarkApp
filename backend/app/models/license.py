import re
from datetime import datetime
from typing import Optional, Any, List
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
    free_reviews_left = Column(Integer, default=20, nullable=False)
    max_free_reviews = Column(Integer, default=20, nullable=False)
    last_review_date = Column(String, nullable=True)  # YYYY-MM-DD for daily limit reset


class AccessKey(Base):
    __tablename__ = "access_keys"

    key_code = Column(String, primary_key=True, index=True)  # e.g. TARK-XXXX-XXXX
    duration_days = Column(Integer, default=30)              # Key validity in days
    is_used = Column(Boolean, default=False)
    used_by_device = Column(String, ForeignKey("devices.device_id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    used_at = Column(DateTime, nullable=True)


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_number = Column(String, unique=True, index=True, nullable=False)
    viitenumber = Column(String, index=True, nullable=False)
    device_id = Column(String, nullable=True, index=True)
    customer_email = Column(String, nullable=False)
    payer_name = Column(String, nullable=True)
    plan_id = Column(String, nullable=False)
    amount = Column(String, nullable=False)
    currency = Column(String, default="EUR", nullable=False)
    is_paid = Column(Boolean, default=False, nullable=False)
    pdf_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)


# ==========================================
# Pydantic Schemas for API
# ==========================================

class LicenseStatusResponse(BaseModel):
    is_active: bool
    has_key: bool = False
    free_reviews_left: int = 20
    max_free_reviews: int = 20
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
    free_reviews_left: int = 20
    max_free_reviews: int = 20
    days_left: int
    expires_at: str
    package_name: Optional[str] = None


class InvoiceRequest(BaseModel):
    email: Optional[str] = Field(default=None, description="Customer email for PDF invoice delivery")
    plan: Optional[str] = Field(default=None, description="Selected subscription plan: year, semester, month, full_year")
    plan_id: Optional[str] = Field(default=None, description="Selected subscription plan ID")
    device_id: Optional[str] = Field(default=None, description="Device ID of client")
    payer_name: Optional[str] = Field(default=None, description="Name of payer or company")


class InvoiceResponse(BaseModel):
    invoice_number: str
    viitenumber: str
    amount: str
    currency: str = "EUR"
    recipient: str = "Tark Systems OÜ"
    iban: str = "EE000000000000000000"
    swift_bic: str = "CPNKEE2X"
    explanation: str
    pdf_download_url: str
    success: bool = True
    email_sent: bool = False
    transport: str = "none"
    message: str = ""


class InvoiceConfirmRequest(BaseModel):
    invoice_number: Optional[str] = None
    viitenumber: Optional[str] = None


class InvoiceConfirmResponse(BaseModel):
    success: bool
    message: str
    invoice_number: str
    viitenumber: str
    is_active: bool
    days_left: int
    expires_at: str
    package_name: Optional[str] = None


class PlanItem(BaseModel):
    id: str
    title: str
    price: str
    price_per_month: str
    duration_months: int
    badge: Optional[str] = None
    is_popular: bool = False
    description: Optional[str] = None
    subtext: Optional[str] = None


class BankDetails(BaseModel):
    recipient_name: str
    iban: str
    swift_bic: str


class PlansCatalogResponse(BaseModel):
    plans: List[PlanItem]
    bank_details: BankDetails

