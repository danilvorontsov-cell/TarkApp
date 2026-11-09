import json
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Integer, String, Text, Boolean, Float, DateTime

from app.database import Base


class TTSAuditLog(Base):
    __tablename__ = "tts_audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    endpoint = Column(String, nullable=False, default="/api/v1/voice/tts")
    device_id = Column(String, nullable=True, index=True)
    is_speech_text = Column(Boolean, default=False, nullable=False)
    incoming_text = Column(Text, nullable=False)
    final_ssml = Column(Text, nullable=True)
    has_accents = Column(Boolean, default=False, nullable=False)
    has_estonian = Column(Boolean, default=False, nullable=False)
    status = Column(String, nullable=False, default="SUCCESS")
    error_message = Column(Text, nullable=True)
    cache_status = Column(String, nullable=True)
    duration_ms = Column(Float, nullable=True)


class TTSAuditLogItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    endpoint: str
    device_id: Optional[str] = None
    is_speech_text: bool
    incoming_text: str
    final_ssml: Optional[str] = None
    has_accents: bool
    has_estonian: bool
    status: str
    error_message: Optional[str] = None
    cache_status: Optional[str] = None
    duration_ms: Optional[float] = None


class TTSAuditLogResponse(BaseModel):
    items: List[TTSAuditLogItem]
    total: int
