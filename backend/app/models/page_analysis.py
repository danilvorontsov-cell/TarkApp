from enum import Enum
from typing import List, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator


class AgeTier(str, Enum):
    PRIMARY = "primary"        # 1–4 классы (Младшее звено)
    MIDDLE = "middle"          # 5–9 классы (Среднее звено)
    GYMNASIUM = "gymnasium"    # 10–12 классы (Старшее звено / Гимназия)

    @classmethod
    def from_grade(cls, grade: int) -> "AgeTier":
        if 1 <= grade <= 4:
            return cls.PRIMARY
        elif 5 <= grade <= 9:
            return cls.MIDDLE
        elif 10 <= grade <= 12:
            return cls.GYMNASIUM
        raise ValueError(f"Grade must be between 1 and 12, got: {grade}")


# Обратная совместимость для старых клиентов
class ThemeInterest(str, Enum):
    MINECRAFT = "minecraft"
    ROBLOX = "roblox"
    SPORTS = "sports"
    ART = "art"
    TECH = "tech"
    NEUTRAL = "neutral"


# Дефолтные наборы трендовых интересов по трем возрастным звеньям (Fallback & Diversity Pool)
AGE_TIER_DEFAULT_INTERESTS = {
    AgeTier.PRIMARY: [
        "Roblox",
        "Brawl Stars",
        "LEGO",
        "Minecraft",
        "Мультфильмы и анимация",
        "Животные и питомцы",
        "Сладости и выпечка",
    ],
    AgeTier.MIDDLE: [
        "Подростковый спорт и футбол",
        "Современные видеоигры",
        "Музыка и треки",
        "Скейт и самокаты",
        "Покупка гаджетов и распаковки",
        "Мемы и тренды",
        "Кибертурниры",
    ],
    AgeTier.GYMNASIUM: [
        "Реальные жизненные ситуации",
        "Современные технологии и IT",
        "Кино, сериалы и режиссура",
        "Карьера, стартапы и личные финансы",
        "Фитнес и спорт",
        "Путешествия и урбанистика",
    ],
}


class UserProfile(BaseModel):
    grade: int = Field(default=3, ge=1, le=12, description="Класс обучения (от 1 до 12)")
    tier: Optional[AgeTier] = Field(
        default=None,
        description="Возрастное звено (вычисляется автоматически из grade, если не указано)"
    )
    interests: List[str] = Field(
        default_factory=list,
        description="Свободный список любимых тем и увлечений ребенка (Minecraft, Roblox, футбол, котики и т.д.)"
    )
    nickname: Optional[str] = Field(
        default="Друг",
        max_length=50,
        description="Имя или никнейм для дружелюбного обращения"
    )

    @field_validator("interests", mode="before")
    @classmethod
    def normalize_interests(cls, v) -> List[str]:
        if v is None:
            return []
        if isinstance(v, str):
            # Разделяем по запятым, точке с запятой или переносам строк
            items = [item.strip() for item in v.replace(";", ",").replace("\n", ",").split(",") if item.strip()]
            return items
        if isinstance(v, list):
            cleaned = []
            for item in v:
                if isinstance(item, str) and item.strip():
                    cleaned.append(item.strip())
            return cleaned
        return []

    @model_validator(mode="before")
    @classmethod
    def handle_legacy_theme_interest(cls, data):
        if isinstance(data, dict):
            # Обратная совместимость, если передан старый theme_interest
            legacy_theme = data.get("theme_interest")
            current_interests = data.get("interests")
            if legacy_theme and not current_interests:
                data["interests"] = [str(legacy_theme)]
        return data

    @model_validator(mode="after")
    def populate_tier_if_missing(self) -> "UserProfile":
        if self.tier is None:
            self.tier = AgeTier.from_grade(self.grade)
        return self


class VocabularyItem(BaseModel):
    est: str = Field(..., description="Эстонский термин в словарной форме или в контексте урока")
    ru: str = Field(..., description="Понятный перевод и краткое пояснение на русском языке")
    example: str = Field(..., description="Пример употребления в предложении на эстонском языке из контекста учебника")


class PageAnalysisResponse(BaseModel):
    task_title: str = Field(
        ...,
        description="Название темы или задания на русском языке"
    )
    theme_explanation: str = Field(
        ...,
        description="Суть темы простыми словами через динамически подобранную метафору увлечения"
    )
    vocabulary: List[VocabularyItem] = Field(
        ...,
        description="Словарь ключевых академических терминов урока (эстонский + русский + пример)"
    )
    how_to_answer: str = Field(
        ...,
        description="Пошаговая инструкция, как ребенку решить задание или ответить на вопрос самому"
    )
    answer_template: str = Field(
        ...,
        description="Грамматический каркас эстонского предложения с пропусками (напр. 'Summa on ___')"
    )
    voice_prompt_script: str = Field(
        ...,
        description="Короткий поддерживающий текст (2-3 предложения) для мгновенной озвучки ребенку"
    )


class AnalyzePageJsonRequest(BaseModel):
    image_base64: Optional[str] = Field(default=None, description="Изображение страницы учебника в формате base64 (одиночное)")
    images_base64: Optional[List[str]] = Field(default=None, description="Список изображений нескольких страниц учебника/тетради в формате base64")
    mime_type: str = Field(default="image/jpeg", description="MIME тип изображения (image/jpeg, image/png)")
    mime_types: Optional[List[str]] = Field(default=None, description="Список MIME типов изображений")
    grade: int = Field(default=3, ge=1, le=12)
    tier: Optional[AgeTier] = None
    interests: Optional[Union[List[str], str]] = Field(
        default_factory=list,
        description="Список увлечений ребенка (строка через запятую или массив)"
    )
    theme_interest: Optional[str] = None  # Для обратной совместимости
    nickname: Optional[str] = "Друг"


class MoreExamplesRequest(BaseModel):
    task_title: str = Field(..., description="Тема урока")
    theme_explanation: Optional[str] = Field(default="", description="Суть темы")
    vocabulary: List[VocabularyItem] = Field(default_factory=list, description="Словарь урока")
    current_template: str = Field(default="", description="Текущий речевой каркас")
    grade: int = Field(default=3, ge=1, le=12)
    tier: Optional[AgeTier] = None


class MoreExamplesResponse(BaseModel):
    templates: List[str] = Field(default_factory=list, description="Новые примеры с пропусками [слово]")

