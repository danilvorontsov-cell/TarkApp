from typing import Optional, Literal
from pydantic import BaseModel, Field


class FeedbackCreate(BaseModel):
    category: Literal["bug", "feature"] = Field(
        ...,
        description="Категория сообщения: 'bug' (ошибка) или 'feature' (пожелание/идея)",
    )
    message: str = Field(
        ...,
        min_length=3,
        max_length=5000,
        description="Текст сообщения или описание проблемы",
    )
    contact: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Email или Telegram для связи",
    )
    device_model: Optional[str] = Field(
        default="Unknown",
        max_length=100,
        description="Модель устройства (например, Xiaomi 2201116SG)",
    )
    os_version: Optional[str] = Field(
        default="Unknown",
        max_length=100,
        description="Версия операционной системы",
    )
    app_version: Optional[str] = Field(
        default="Unknown",
        max_length=50,
        description="Версия сборки приложения",
    )
    current_grade: Optional[int] = Field(
        default=None,
        ge=1,
        le=12,
        description="Текущий выбранный класс ученика",
    )
    last_request_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="ID последнего сетевого запроса для привязки к логам",
    )
    client_time: Optional[str] = Field(
        default=None,
        max_length=60,
        description="Локальное время на устройстве пользователя в формате ISO",
    )


class FeedbackResponse(BaseModel):
    success: bool = True
    message: str = "Спасибо! Сообщение передано разработчику."
