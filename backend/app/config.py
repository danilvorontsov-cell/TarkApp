import os
from typing import List, Optional, Any
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "TarkApp Backend"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = "development"
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    
    # Gemini API settings
    GEMINI_API_KEY: str = ""
    # Model defaults to gemini-3.8-flash with environment override support
    GEMINI_MODEL: str = "gemini-3.8-flash"
    
    # Azure Speech Service settings
    AZURE_SPEECH_KEY: Optional[str] = None
    AZURE_SPEECH_REGION: str = "northeurope"
    
    # CORS
    CORS_ORIGINS: List[str] = ["*"]
    
    # Max image upload size in MB (e.g. 10MB)
    MAX_IMAGE_SIZE_MB: int = 10
    
    # Database settings (SQLite / SQLAlchemy)
    DATABASE_URL: str = "sqlite:///./tarkapp.db"

    # Rate Limiting settings (slowapi)
    RATE_LIMITING_ENABLED: bool = True

    # Telegram Alerting & Topic Routing (Optional)
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None
    TELEGRAM_ADMIN_CHAT_ID: Optional[str] = None
    TELEGRAM_TOPIC_BUGS: Optional[int] = None
    TELEGRAM_TOPIC_FEATURES: Optional[int] = None
    TELEGRAM_TOPIC_ALERTS: Optional[int] = None

    # Telegram Bot Admin (Optional - for /gen and /stats commands)
    ADMIN_TELEGRAM_ID: Optional[str] = None
    TELEGRAM_WEBHOOK_SECRET: Optional[str] = None

    # Email / Invoice Delivery Settings (SMTP or Resend API)
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM: str = "TarkApp Billing <billing@tarkapp.ee>"
    SMTP_USE_TLS: bool = True

    RESEND_API_KEY: Optional[str] = None
    RESEND_FROM: str = "TarkApp <onboarding@resend.dev>"

    @field_validator(
        "TELEGRAM_TOPIC_BUGS",
        "TELEGRAM_TOPIC_FEATURES",
        "TELEGRAM_TOPIC_ALERTS",
        mode="before",
    )
    @classmethod
    def parse_optional_topic_id(cls, v):
        if v is None or v == "" or (isinstance(v, str) and not v.strip()):
            return None
        return int(v)

    @property
    def telegram_chat_id(self) -> Optional[str]:
        """Resolves target Telegram chat/supergroup ID (prioritizing TELEGRAM_CHAT_ID)."""
        return (self.TELEGRAM_CHAT_ID or self.TELEGRAM_ADMIN_CHAT_ID or "").strip() or None
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
