import os
from typing import List, Optional
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
    
    # Telegram Alerting (Optional)
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_ADMIN_CHAT_ID: Optional[str] = None
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
