from typing import Optional
from pydantic import BaseModel, Field


class QuickTranslateRequest(BaseModel):
    text: Optional[str] = Field(
        default=None,
        description="Текст, слово или абзац для быстрого перевода",
    )
    image_base64: Optional[str] = Field(
        default=None,
        description="Изображение фрагмента учебника/тетради в формате base64",
    )
    mime_type: Optional[str] = Field(
        default="image/jpeg",
        description="MIME-тип изображения (image/jpeg, image/png)",
    )
    source_lang: Optional[str] = Field(
        default="auto",
        description="Исходный язык (auto, et, ru)",
    )
    target_lang: Optional[str] = Field(
        default="ru",
        description="Целевой язык (ru, et)",
    )


class QuickTranslateResponse(BaseModel):
    original_text: str = Field(
        ...,
        description="Исходный текст или распознанный текст с изображения",
    )
    translated_text: str = Field(
        ...,
        description="Переведенный текст с адаптацией под школьную терминологию Эстонии",
    )
    base_forms: Optional[str] = Field(
        default=None,
        description="3 основные словарные формы (algvormid), если переведено отдельное слово",
    )
    context_note: Optional[str] = Field(
        default=None,
        description="Школьный предмет, область знаний или пояснение контекста термина",
    )
    source_lang: str = Field(
        default="et",
        description="Фактический исходный язык (et или ru)",
    )
    target_lang: str = Field(
        default="ru",
        description="Фактический целевой язык (ru или et)",
    )
