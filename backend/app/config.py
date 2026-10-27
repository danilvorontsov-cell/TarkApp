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
    
    # CORS
    CORS_ORIGINS: List[str] = ["*"]
    
    # Max image upload size in MB (e.g. 10MB)
    MAX_IMAGE_SIZE_MB: int = 10
    
    # Telegram Alerting & Topic Routing (Optional)
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None
    TELEGRAM_ADMIN_CHAT_ID: Optional[str] = None
    TELEGRAM_TOPIC_BUGS: Optional[int] = None
    TELEGRAM_TOPIC_FEATURES: Optional[int] = None
    TELEGRAM_TOPIC_ALERTS: Optional[int] = None

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
