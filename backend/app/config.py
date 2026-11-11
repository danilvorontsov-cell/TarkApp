import os
from typing import List, Optional, Any
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "TarkApp Backend"
    APP_VERSION: str = "1.3.2"
    APP_ENV: str = "development"
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # Security & Auth settings
    SECRET_KEY: str = "tarkapp-dev-hmac-secret-change-in-production"
    ADMIN_SECRET: Optional[str] = None

    # Monetization & Trial Mode ("closed_beta" vs "production")
    TRIAL_MODE: str = "closed_beta"
    BETA_TRIAL_DAYS: int = 14
    BETA_DAILY_REVIEWS: int = 20
    PROD_TRIAL_DAYS: int = 5
    PROD_DAILY_REVIEWS: int = 10

    # Company & Bank Requisites (must be configured in .env for live SEPA invoicing)
    COMPANY_NAME: str = "Tark Systems OÜ"
    COMPANY_REG: str = "16987456"
    BANK_NAME: str = "Coop Pank"
    BANK_IBAN: str = ""
    BANK_SWIFT: str = "CPNKEE2X"
    
    # Gemini API settings
    GEMINI_API_KEY: str = ""
    # Model defaults to gemini-3.8-flash with environment override support
    GEMINI_MODEL: str = "gemini-3.8-flash"
    GEMINI_MODEL_NAME: Optional[str] = None
    GEMINI_BASE_URL: Optional[str] = None
    
    # TTS Pipeline settings (Silero v5 for Russian + Microsoft Neural for Estonian)
    TTS_PROVIDER: str = "silero"  # "silero" (default), "microsoft", "openai" (deprecated)
    SILERO_MODEL_PATH: str = "data/models/v5_ru.pt"
    SILERO_VOICE: str = "xenia"  # "xenia" or "kseniya"
    SILERO_SAMPLE_RATE: int = 24000

    # Azure Speech Service settings
    AZURE_SPEECH_KEY: Optional[str] = None
    AZURE_SPEECH_REGION: str = "northeurope"
    
    # CORS: Explicit trusted domains (replaces open allow_origins=["*"])
    CORS_ORIGINS: List[str] = [
        "https://tarkapp.ee",
        "https://www.tarkapp.ee",
        "https://app.tarkapp.ee",
        "http://localhost:8081",
        "http://localhost:19006",
        "http://localhost:3000",
    ]
    
    # Max image upload size in MB (e.g. 10MB)
    MAX_IMAGE_SIZE_MB: int = 10
    
    # Database settings (SQLite / SQLAlchemy)
    # Automatically prefers ./data/tarkapp.db when volume-mounted data dir exists
    DATABASE_URL: str = (
        "sqlite:///./data/tarkapp.db"
        if os.path.isdir("data") or os.path.isdir("/app/data")
        else "sqlite:///./tarkapp.db"
    )

    # Rate Limiting settings (slowapi)
    RATE_LIMITING_ENABLED: bool = True

    # Telegram Alerting & Topic Routing (Optional)
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None
    TELEGRAM_ADMIN_CHAT_ID: Optional[str] = None
    TELEGRAM_TOPIC_BUGS: Optional[int] = None
    TELEGRAM_TOPIC_FEATURES: Optional[int] = None
    TELEGRAM_TOPIC_ALERTS: Optional[int] = None
    TELEGRAM_TOPIC_INVOICES: Optional[int] = None

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

    @model_validator(mode="after")
    def sync_gemini_model_names(self) -> "Settings":
        if self.GEMINI_MODEL_NAME:
            self.GEMINI_MODEL = self.GEMINI_MODEL_NAME
        else:
            self.GEMINI_MODEL_NAME = self.GEMINI_MODEL
        return self

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            clean_v = v.strip()
            if clean_v.startswith("[") and clean_v.endswith("]"):
                import json
                try:
                    return json.loads(clean_v)
                except Exception:
                    pass
            return [origin.strip() for origin in clean_v.split(",") if origin.strip()]
        if isinstance(v, (list, tuple)):
            return [str(origin).strip() for origin in v if str(origin).strip()]
        return v

    @field_validator(
        "TELEGRAM_TOPIC_BUGS",
        "TELEGRAM_TOPIC_FEATURES",
        "TELEGRAM_TOPIC_ALERTS",
        "TELEGRAM_TOPIC_INVOICES",
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
