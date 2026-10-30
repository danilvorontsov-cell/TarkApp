from enum import Enum
from typing import Annotated, List, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator


class AgeTier(str, Enum):
    PRIMARY = "primary"        # 1–3 классы (Младшая школа / Algkool)
    MIDDLE = "middle"          # 4–6 классы (Среднее звено I / Põhikool I)
    HIGH = "high"              # 7–9 классы (Старшее звено / Põhikool II)
    GYMNASIUM = "gymnasium"    # 10–12 классы (Гимназия / Gümnaasium)

    @classmethod
    def from_grade(cls, grade: int) -> "AgeTier":
        if 1 <= grade <= 3:
            return cls.PRIMARY
        elif 4 <= grade <= 6:
            return cls.MIDDLE
        elif 7 <= grade <= 9:
            return cls.HIGH
        elif 10 <= grade <= 12:
            return cls.GYMNASIUM
        raise ValueError(f"Grade must be between 1 and 12, got: {grade}")


def is_full_audio_enabled(grade_or_tier: Union[int, AgeTier]) -> bool:
    """Returns True if long audio narration (prompt, explanation, example, steps) is permitted."""
    if isinstance(grade_or_tier, int):
        return grade_or_tier < 7
    return grade_or_tier in (AgeTier.PRIMARY, AgeTier.MIDDLE)


def is_sentence_frame_enabled(grade_or_tier: Union[int, AgeTier]) -> bool:
    """Returns True if the gamified interactive sentence frame with drag-and-drop slots is shown."""
    if isinstance(grade_or_tier, int):
        return grade_or_tier < 10
    return grade_or_tier != AgeTier.GYMNASIUM


def is_visual_template_enabled(grade_or_tier: Union[int, AgeTier]) -> bool:
    """Returns True if interactive visual templates (grades 1–6) are permitted."""
    if isinstance(grade_or_tier, int):
        return 1 <= grade_or_tier <= 6
    return grade_or_tier in (AgeTier.PRIMARY, AgeTier.MIDDLE)


# Обратная совместимость для старых клиентов
class ThemeInterest(str, Enum):
    MINECRAFT = "minecraft"
    ROBLOX = "roblox"
    SPORTS = "sports"
    ART = "art"
    TECH = "tech"
    NEUTRAL = "neutral"


# Дефолтные наборы трендовых интересов по четырем возрастным звеньям (Fallback & Diversity Pool)
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
        "Футбол и спорт",
        "Видеоигры и Brawl Stars",
        "Музыка и треки",
        "Скейт и трюки",
        "Покупка гаджетов",
        "Мемы и тренды",
        "Настолки с друзьями",
    ],
    AgeTier.HIGH: [
        "Подростковый спорт и футбол",
        "CS:GO / Valorant",
        "Музыка и треки",
        "Скейт и самокаты",
        "Гаджеты и технологии",
        "Мемы и TikTok",
        "Аниме и манга",
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
            # Разделяем по запятым, точке с запятой или переносам строк и ограничиваем длину
            items = [item.strip()[:60] for item in v.replace(";", ",").replace("\n", ",").split(",") if item.strip()]
            return items[:15]
        if isinstance(v, list):
            cleaned = []
            for item in v:
                if isinstance(item, str) and item.strip():
                    cleaned.append(item.strip()[:60])
            return cleaned[:15]
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


class WorkedExample(BaseModel):
    title: str = Field(
        default="Пример решения (Näidis)",
        description="Заголовок примера (напр. 'Пример решения (Näidis)')"
    )
    given: str = Field(
        ...,
        description="Дано / исходная ситуация с конкретными вымышленными цифрами или мини-предложением (напр. 'Если у нас есть: 12 яблок на 3 тарелки')"
    )
    steps: List[str] = Field(
        ...,
        description="Пошаговые действия 'было -> сделали -> получили' (напр. ['1. Делим: 12 : 3 = 4', '2. Вывод: на каждой тарелке по 4 яблока'])"
    )
    note: Optional[str] = Field(
        default="По этому же образцу сделай примеры из своего учебника!",
        description="Поясняющий вывод или подсказка для самостоятельного решения"
    )


# --- Интерактивные визуальные шаблоны (1–6 классы) ---

class MathBlockGroup(BaseModel):
    label: str = Field(..., description="Название группы (напр. 'Красные кубики' или 'Liidetav 1')")
    count: int = Field(..., ge=1, le=50, description="Количество элементов в группе")
    color: Optional[str] = Field(default=None, description="Цвет плашки (HEX, напр. '#3B82F6')")
    item_label: Optional[str] = Field(default=None, description="Подпись единичного предмета (яблоко, кубик)")
    symbol: Optional[str] = Field(default=None, description="Эмодзи или символ (🍎, 🟦, ⭐️)")


class MathBlocksVisual(BaseModel):
    type: Literal["math_blocks"] = "math_blocks"
    title: Optional[str] = Field(default=None, description="Заголовок визуализации (напр. 'Счёт группами')")
    instruction: Optional[str] = Field(default=None, description="Инструкция ученику (напр. 'Нажимай на кубики, чтобы посчитать их')")
    groups: List[MathBlockGroup] = Field(..., description="Группы счётных предметов")
    operation: Optional[str] = Field(default="+", description="Математическая операция (+, -, *, /, =)")
    target_count: Optional[int] = Field(default=None, description="Ожидаемая сумма/результат")


class MatchPairItem(BaseModel):
    id: str = Field(..., description="Уникальный идентификатор пары")
    left: str = Field(..., description="Левый элемент (термин на эстонском или понятие)")
    right: str = Field(..., description="Правый элемент (русский перевод или соответствие)")
    hint: Optional[str] = Field(default=None, description="Краткая подсказка при затруднении")


class MatchPairsVisual(BaseModel):
    type: Literal["match_pairs"] = "match_pairs"
    title: Optional[str] = Field(default=None, description="Заголовок (напр. 'Соедини пары терминов')")
    instruction: Optional[str] = Field(default=None, description="Инструкция для ученика")
    pairs: List[MatchPairItem] = Field(..., min_length=2, max_length=8, description="Список пар для сопоставления")


class StepSequenceItem(BaseModel):
    step_number: int = Field(..., description="Порядковый номер шага (1, 2, 3...)")
    title: str = Field(..., description="Краткое название шага")
    description: Optional[str] = Field(default=None, description="Подробное описание или действие")
    icon_or_badge: Optional[str] = Field(default=None, description="Эмодзи или иконка шага")
    is_highlighted: Optional[bool] = Field(default=False, description="Выделен ли шаг как ключевой")


class StepSequenceVisual(BaseModel):
    type: Literal["step_sequence"] = "step_sequence"
    title: Optional[str] = Field(default=None, description="Заголовок цепочки (напр. 'Этапы решения' или 'Жизненный цикл')")
    instruction: Optional[str] = Field(default=None, description="Инструкция ученику")
    steps: List[StepSequenceItem] = Field(..., min_length=2, max_length=10, description="Последовательные шаги алгоритма или процесса")


class BalanceScaleItem(BaseModel):
    label: str = Field(..., description="Подпись предмета")
    count: int = Field(default=1, ge=1, description="Количество предметов")
    color: Optional[str] = Field(default=None, description="Цвет плашки")


class BalanceScaleSide(BaseModel):
    label: str = Field(..., description="Подпись чаши (напр. 'Левая чаша: 5 + 3' или 'Kast A')")
    value: Union[int, float, str] = Field(..., description="Числовое значение или выражение для сравнения")
    items: Optional[List[BalanceScaleItem]] = Field(default=None, description="Визуальные предметы на чаше")


class BalanceScaleVisual(BaseModel):
    type: Literal["balance_scale"] = "balance_scale"
    title: Optional[str] = Field(default=None, description="Заголовок (напр. 'Сравнение величин на весах')")
    instruction: Optional[str] = Field(default=None, description="Инструкция ученику")
    left_side: BalanceScaleSide = Field(..., description="Левая чаша весов")
    right_side: BalanceScaleSide = Field(..., description="Правая чаша весов")
    comparison: Literal["<", ">", "=", "?"] = Field(default="?", description="Соотношение весов (<, >, = или ? для интерактива)")
    hint: Optional[str] = Field(default=None, description="Подсказка к сравнению")


class UniversalCardVisual(BaseModel):
    type: Literal["universal_card"] = "universal_card"
    title: str = Field(..., description="Заголовок фокусной карточки")
    icon: str = Field(default="💡", description="Крупная иконка или эмодзи")
    badge: Optional[str] = Field(default=None, description="Бейдж-категория (напр. 'Правило', 'Лайфхак', 'Важно')")
    highlight_text: str = Field(..., description="Ключевое правило, формула или формула-акцент")
    explanation: Optional[str] = Field(default=None, description="Краткое пояснение правила")
    accent_color: Optional[str] = Field(default=None, description="Цветовой акцент карточки")


VisualData = Annotated[
    Union[MathBlocksVisual, MatchPairsVisual, StepSequenceVisual, BalanceScaleVisual, UniversalCardVisual],
    Field(discriminator="type"),
]


class PageAnalysisResponse(BaseModel):
    task_title: str = Field(
        ...,
        description="Название темы или задания на русском языке"
    )
    theme_explanation: str = Field(
        ...,
        description="Суть темы простыми словами через динамически подобранную метафору увлечения"
    )
    alternative_explanation: Optional[str] = Field(
        default=None,
        description="Запасное объяснение через другую бытовую аналогию (на случай клика 'Объяснить по-другому')"
    )
    vocabulary: List[VocabularyItem] = Field(
        ...,
        description="Словарь ключевых академических терминов урока (эстонский + русский + пример)"
    )
    worked_example: Optional[WorkedExample] = Field(
        default=None,
        description="Наглядный пример решения (Näidis)"
    )
    visual: Optional[VisualData] = Field(
        default=None,
        description="Интерактивный визуальный шаблон (UI-primitive) для 1–6 классов (строго null для 7–12 классов)"
    )
    how_to_answer: str = Field(
        ...,
        description="Пошаговая инструкция, как ребенку решить задание или ответить на вопрос самому"
    )
    answer_template: str = Field(
        ...,
        description="Грамматический каркас эстонского предложения с пропусками в квадратных скобках [слово] (напр. 'Summa on [16]')"
    )
    voice_prompt_script: str = Field(
        ...,
        description="Короткий поддерживающий текст (2-3 предложения) для мгновенной озвучки ребенку"
    )
    is_acceptable: Optional[bool] = Field(
        default=True,
        description="Флаг пригодности снимка: False, если фото не читаемое/размытое и выдан обучающий fallback"
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

