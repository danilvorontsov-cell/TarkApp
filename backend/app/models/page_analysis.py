import re
from enum import Enum
from typing import Any, List, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator


def strip_combining_accents(v: Any) -> Any:
    """Removes Combining Acute Accent (\u0301) and technical stress plus (+) from display text."""
    if v is None:
        return None
    if isinstance(v, str):
        return re.sub(r'[\u0301\u0341]|\+(?=[а-яА-ЯёЁa-zA-Z])', '', v)
    if isinstance(v, list):
        return [strip_combining_accents(item) for item in v]
    if isinstance(v, dict):
        return {k: strip_combining_accents(val) for k, val in v.items()}
    return v


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
    def populate_tier_and_sanitize_interests(self) -> "UserProfile":
        if self.tier is None:
            self.tier = AgeTier.from_grade(self.grade)

        # Defense-in-depth: If grade >= 4 (middle, high, gymnasium) received the legacy primary default trio
        # ['Minecraft', 'LEGO', 'Roblox'] due to an un-synced client, replace with age-appropriate tier defaults.
        if self.tier != AgeTier.PRIMARY and self.interests:
            norm_set = {i.strip().lower() for i in self.interests}
            if norm_set == {"minecraft", "lego", "roblox"}:
                self.interests = AGE_TIER_DEFAULT_INTERESTS.get(self.tier, [])[:3]
            elif self.tier in (AgeTier.HIGH, AgeTier.GYMNASIUM):
                # High school and gymnasium should never receive pure childish toy interests
                cleaned = [i for i in self.interests if i.strip().lower() not in {"lego", "roblox"}]
                self.interests = cleaned if cleaned else AGE_TIER_DEFAULT_INTERESTS.get(self.tier, [])[:3]

        return self


class StepItem(BaseModel):
    """
    Модель отдельного шага решения с разделением визуального слоя и речевого слоя.
    text: для компактного отображения на экране (с формулами и сокращениями).
    speech_text: для синтезатора Azure TTS полными словами без сокращений и формул.
    """
    text: str = Field(..., description="Визуальный текст шага для отображения на экране")
    speech_text: Optional[str] = Field(default=None, description="Транскрибированный речевой слой для TTS")
    step_number: Optional[int] = Field(default=None, description="Номер шага")
    is_formula: Optional[bool] = Field(default=False, description="Флаг математической формулы")

    @field_validator("text", mode="before")
    @classmethod
    def validate_non_empty_text(cls, v: Any) -> str:
        s = str(v or "").strip()
        if not s:
            raise ValueError("Поле 'text' шага не может быть пустым")
        return strip_combining_accents(s)

    @model_validator(mode="after")
    def fallback_speech_text(self) -> "StepItem":
        if not self.speech_text or not self.speech_text.strip():
            self.speech_text = self.text
        return self


class SelfSolveStep(BaseModel):
    """Модель шага для блока самостоятельного решения задания."""
    text: str = Field(..., description="Визуальный текст шага")
    speech_text: Optional[str] = Field(default=None, description="Речевой слой для TTS")
    hint: Optional[str] = Field(default=None, description="Подсказка к шагу")

    @field_validator("text", mode="before")
    @classmethod
    def validate_non_empty_text(cls, v: Any) -> str:
        s = str(v or "").strip()
        if not s:
            raise ValueError("Поле 'text' шага не может быть пустым")
        return strip_combining_accents(s)

    @field_validator("hint", mode="before")
    @classmethod
    def sanitize_hint(cls, v: Any) -> Optional[str]:
        return strip_combining_accents(v)

    @model_validator(mode="after")
    def fallback_speech_text(self) -> "SelfSolveStep":
        if not self.speech_text or not self.speech_text.strip():
            self.speech_text = self.text
        return self


class LessonCard(BaseModel):
    """Модель карточки учебного материала с разделением text и speech_text."""
    id: Optional[str] = Field(default=None, description="ID карточки")
    title: Optional[str] = Field(default=None, description="Заголовок карточки")
    text: str = Field(..., description="Визуальный текст карточки")
    speech_text: Optional[str] = Field(default=None, description="Речевой слой для TTS")

    @field_validator("text", mode="before")
    @classmethod
    def validate_non_empty_text(cls, v: Any) -> str:
        s = str(v or "").strip()
        if not s:
            raise ValueError("Поле 'text' карточки не может быть пустым")
        return strip_combining_accents(s)

    @field_validator("title", mode="before")
    @classmethod
    def sanitize_title(cls, v: Any) -> Optional[str]:
        return strip_combining_accents(v)

    @model_validator(mode="after")
    def fallback_speech_text(self) -> "LessonCard":
        if not self.speech_text or not self.speech_text.strip():
            self.speech_text = self.text
        return self


class BilingualCard(BaseModel):
    """Модель двуязычной карточки с эстонским и русским слоями."""
    est: str = Field(..., description="Эстонский термин")
    ru: Optional[str] = Field(default=None, description="Русский перевод")
    text: Optional[str] = Field(default=None, description="Визуальный текст")
    speech_text: Optional[str] = Field(default=None, description="Речевой слой для TTS")

    @model_validator(mode="after")
    def fallback_speech_text(self) -> "BilingualCard":
        if not self.text or not self.text.strip():
            self.text = self.est
        if not self.speech_text or not self.speech_text.strip():
            self.speech_text = self.text
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
        description="Сократический наводящий вывод или совет для самостоятельного решения без прямых подсказок правильного ответа"
    )
    speech_text: Optional[str] = Field(
        default=None,
        description="Речевой слой для TTS примера решения"
    )

    @field_validator("title", "given", "note", mode="before")
    @classmethod
    def sanitize_worked_example_text(cls, v: Any) -> Any:
        return strip_combining_accents(v)

    @field_validator("steps", mode="before")
    @classmethod
    def clean_steps(cls, v) -> List[str]:
        if not v:
            return []
        if isinstance(v, list):
            return [strip_combining_accents(str(s).strip()) for s in v if s and str(s).strip()]
        if isinstance(v, str):
            cleaned = strip_combining_accents(str(v).strip())
            return [cleaned] if cleaned else []
        return []

    @model_validator(mode="after")
    def fallback_speech_text(self) -> "WorkedExample":
        if not self.speech_text or not self.speech_text.strip():
            parts = []
            if self.given and self.given.strip():
                parts.append(self.given.strip())
            if self.steps:
                parts.extend([s.strip() for s in self.steps if s and s.strip()])
            if self.note and self.note.strip():
                parts.append(self.note.strip())
            self.speech_text = " ".join(parts) if parts else (self.given or "")
        return self


class SelfSolveGuide(BaseModel):
    """
    Модель руководства для самостоятельного решения задания (SelfSolveGuide).
    Автоматически фильтрует пустые и состоящие только из пробелов элементы.
    """
    steps: List[str] = Field(
        default_factory=list,
        description="Пошаговые действия для самостоятельного решения"
    )
    guided_steps: Optional[List[str]] = Field(
        default=None,
        description="Направляющие шаги с подсказками"
    )
    actions: Optional[List[str]] = Field(
        default=None,
        description="Действия или инструкции"
    )
    speech_text: Optional[str] = Field(
        default=None,
        description="Речевой слой для TTS"
    )

    @field_validator("steps", "guided_steps", "actions", mode="before")
    @classmethod
    def clean_step_arrays(cls, v) -> Optional[List[str]]:
        if v is None:
            return None
        if isinstance(v, list):
            return [strip_combining_accents(str(s).strip()) for s in v if s and str(s).strip()]
        if isinstance(v, str):
            cleaned = strip_combining_accents(str(v).strip())
            return [cleaned] if cleaned else []
        return []

    @model_validator(mode="after")
    def fallback_speech_text(self) -> "SelfSolveGuide":
        if not self.speech_text or not self.speech_text.strip():
            items = []
            if self.steps:
                items.extend([s for s in self.steps if s and s.strip()])
            elif self.guided_steps:
                items.extend([s for s in self.guided_steps if s and s.strip()])
            elif self.actions:
                items.extend([s for s in self.actions if s and s.strip()])
            self.speech_text = " ".join(items) if items else ""
        return self


class LessonSpeechLayer(BaseModel):
    voice_prompt_script: str = Field(..., description="Фонетически подготовленный текст голосового приветствия для Azure TTS")
    theme_explanation: str = Field(..., description="Фонетически подготовленный текст объяснения темы")
    alternative_explanation: Optional[str] = Field(default=None, description="Фонетически подготовленный текст альтернативного объяснения")
    how_to_answer: str = Field(..., description="Фонетически подготовленный текст шагов решения")
    worked_example: Optional[str] = Field(default=None, description="Фонетически подготовленный текст примера решения")


class GeminiPageAnalysisSchema(BaseModel):
    """
    Выходная JSON-схема для Gemini Structured Outputs (Display-слой и Speech-слой).
    Генерирует чистые отображаемые тексты и напрямую подготовленный речевой слой без цифр и формул.
    """
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
    how_to_solve: List[str] = Field(
        default_factory=list,
        description="Пошаговый массив строк с алгоритмом рассуждения (каждый шаг без префиксов 'Шаг 1' или '1.')"
    )
    how_to_answer: str = Field(
        default="",
        description="Пошаговая инструкция и сократический алгоритм рассуждения, как ребенку решить задание или ответить на вопрос самому без прямых подсказок вариантов"
    )
    answer_template: str = Field(
        ...,
        description="Грамматический каркас эстонского предложения с пропусками в квадратных скобках [слово] (напр. 'Summa on [16]')"
    )
    voice_prompt_script: str = Field(
        ...,
        description="Короткий поддерживающий текст (2-3 предложения) для мгновенной озвучки ребенку"
    )
    theme_explanation_speech: str = Field(
        ...,
        description="Текст объяснения темы полными словами для озвучки без цифр и формул"
    )
    how_to_answer_speech: str = Field(
        ...,
        description="Полный алгоритм рассуждения словами для озвучки, передающий наводящую мысль полностью и связно без сокращения до телеграфного стиля"
    )
    worked_example_speech: Optional[str] = Field(
        default=None,
        description="Разбор примера полными словами"
    )
    voice_prompt_script_speech: Optional[str] = Field(
        default=None,
        description="Приветствие диктора полными словами"
    )
    alternative_explanation_speech: Optional[str] = Field(
        default=None,
        description="Speech-слой для alternative_explanation"
    )
    is_acceptable: Optional[bool] = Field(
        default=True,
        description="Флаг пригодности снимка: False, если фото не читаемое/размытое и выдан обучающий fallback"
    )

    @field_validator("task_title", "theme_explanation", "how_to_answer", "voice_prompt_script", mode="before")
    @classmethod
    def sanitize_schema_visual_strings(cls, v: Any) -> str:
        return strip_combining_accents(str(v or ""))

    @field_validator("alternative_explanation", mode="before")
    @classmethod
    def sanitize_schema_alt_visual(cls, v: Any) -> Optional[str]:
        return strip_combining_accents(v)


class PageAnalysisResponse(GeminiPageAnalysisSchema):
    lesson_id: Optional[str] = Field(
        default=None,
        description="Уникальный идентификатор активной сессии урока для бесплатного добавления разворота"
    )
    page_count: Optional[int] = Field(
        default=1,
        description="Количество страниц в текущем разборе урока (1 или 2)"
    )
    can_append_page: Optional[bool] = Field(
        default=True,
        description="Доступна ли бесплатная досылка второй страницы разворота в текущей сессии"
    )
    session_expires_at: Optional[float] = Field(
        default=None,
        description="Unix-время окончания 5-минутного окна для бесплатного дополнения разворота"
    )
    session_seconds_remaining: Optional[int] = Field(
        default=None,
        description="Осталось секунд для бесплатного дополнения разворота (до 300)"
    )

    speech_layer: Optional[LessonSpeechLayer] = Field(
        default=None,
        description="Слой фонетически подготовленных текстов для Azure TTS (детерминированно рассчитывается на бэкенде)"
    )
    voice_prompt_script_speech: Optional[str] = Field(default=None, description="Speech-слой для voice_prompt_script")
    theme_explanation_speech: Optional[str] = Field(default=None, description="Speech-слой для theme_explanation")
    alternative_explanation_speech: Optional[str] = Field(default=None, description="Speech-слой для alternative_explanation")
    how_to_answer_speech: Optional[str] = Field(default=None, description="Speech-слой для how_to_answer")
    worked_example_speech: Optional[str] = Field(default=None, description="Speech-слой для worked_example")
    speech_text: Optional[str] = Field(default=None, description="Общий транскрибированный речевой слой для TTS")

    @model_validator(mode="before")
    @classmethod
    def clean_page_analysis_steps(cls, data):
        if isinstance(data, dict):
            for key in ("steps", "guided_steps", "actions"):
                if key in data and isinstance(data[key], list):
                    data[key] = [strip_combining_accents(str(s).strip()) for s in data[key] if s and str(s).strip()]
            for display_key in ("task_title", "theme_explanation", "alternative_explanation", "voice_prompt_script"):
                if display_key in data and data[display_key]:
                    data[display_key] = strip_combining_accents(data[display_key])

            # Синхронизация и очистка how_to_solve и how_to_answer
            how_solve = data.get("how_to_solve")
            how_ans = data.get("how_to_answer")
            if isinstance(how_solve, list) and how_solve:
                clean_solve = [strip_combining_accents(str(s).strip()) for s in how_solve if s and str(s).strip()]
                clean_solve = [re.sub(r'^(?:\(?\d+[\.\)]|\bШаг\s+\d+[:.]?)\s*', '', s).strip() for s in clean_solve if s]
                data["how_to_solve"] = clean_solve
                if not how_ans or not str(how_ans).strip():
                    data["how_to_answer"] = "\n".join(f"{i+1}. {s}" for i, s in enumerate(clean_solve))
                else:
                    data["how_to_answer"] = strip_combining_accents(how_ans)
            elif how_ans and isinstance(how_ans, str) and str(how_ans).strip():
                clean_ans = strip_combining_accents(how_ans)
                data["how_to_answer"] = clean_ans
                raw_parts = re.split(r'(?:^|\n+|\s+)(?=(?:\(?\d+[\.\)]|\bШаг\s+\d+[:.]?)\s+)', clean_ans.strip())
                cand = [p.strip() for p in raw_parts if p.strip()]
                if len(cand) <= 1:
                    cand = [p.strip() for p in clean_ans.strip().split('\n') if p.strip()]
                parsed = [re.sub(r'^(?:\(?\d+[\.\)]|\bШаг\s+\d+[:.]?)\s*', '', s).strip() for s in cand if s.strip()]
                data["how_to_solve"] = parsed if len(parsed) > 1 else [clean_ans.strip()]
            else:
                data["how_to_solve"] = []
                data["how_to_answer"] = str(how_ans or "")

            if "worked_example" in data and isinstance(data["worked_example"], dict):
                we = data["worked_example"]
                if "steps" in we and isinstance(we["steps"], list):
                    we["steps"] = [strip_combining_accents(str(s).strip()) for s in we["steps"] if s and str(s).strip()]
                if "given" in we and we["given"]:
                    we["given"] = strip_combining_accents(we["given"])
                if "note" in we and we["note"]:
                    we["note"] = strip_combining_accents(we["note"])
                if "title" in we and we["title"]:
                    we["title"] = strip_combining_accents(we["title"])
        return data

    @model_validator(mode="after")
    def populate_speech_layer(self) -> "PageAnalysisResponse":
        try:
            if self.worked_example:
                if getattr(self.worked_example, "steps", None):
                    self.worked_example.steps = [strip_combining_accents(str(s).strip()) for s in self.worked_example.steps if s and str(s).strip()]
                if getattr(self.worked_example, "given", None):
                    self.worked_example.given = strip_combining_accents(self.worked_example.given)
                if getattr(self.worked_example, "note", None):
                    self.worked_example.note = strip_combining_accents(self.worked_example.note)
                if getattr(self.worked_example, "title", None):
                    self.worked_example.title = strip_combining_accents(self.worked_example.title)

            from app.services.tts_normalizer import (
                prepare_speech_text,
                prepare_worked_example_speech,
                normalize_text_for_estonian_tts,
            )

            v_speech = (self.voice_prompt_script_speech or "").strip() or prepare_speech_text(self.voice_prompt_script or "")
            th_speech = (self.theme_explanation_speech or "").strip() or prepare_speech_text(self.theme_explanation or "")
            alt_speech = (self.alternative_explanation_speech or "").strip() or (prepare_speech_text(self.alternative_explanation) if self.alternative_explanation else None)

            how_speech = (self.how_to_answer_speech or "").strip()
            if not how_speech:
                if self.how_to_solve and len(self.how_to_solve) > 1:
                    ordinals_map = {
                        1: "первый", 2: "втор+ой", 3: "тр+етий", 4: "четв+ёртый", 5: "п+ятый",
                        6: "шест+ой", 7: "седьм+ой", 8: "восьм+ой", 9: "дев+ятый", 10: "дес+ятый"
                    }
                    speech_steps = [prepare_speech_text(s) for s in self.how_to_solve if s and s.strip()]
                    how_speech = "\n".join(
                        f"Шаг {ordinals_map.get(i+1, str(i+1))}: {step}"
                        for i, step in enumerate(speech_steps)
                    )
                else:
                    how_speech = prepare_speech_text(self.how_to_answer or "")
            else:
                # Гарантируем перенос строк между шагами для паузы 500 мс при склейке
                step_boundary = re.compile(
                    r'(?<=[.!?…])\s+(?=(?:Шаг\s+[\w\+]+[:.]?|(?:\(?\d+[\.\)]))\s*)',
                    re.IGNORECASE
                )
                how_speech = step_boundary.sub("\n", how_speech)

            ex_speech = (self.worked_example_speech or "").strip()
            if not ex_speech and self.worked_example:
                ex_speech = prepare_worked_example_speech(self.worked_example)

            def _normalize_speech_est_tags(s: Optional[str]) -> Optional[str]:
                if not s or "<est" not in s.lower():
                    return s
                def _repl_tag(m: re.Match) -> str:
                    inner = m.group(1).strip()
                    if re.search(r'[\d+\-*\/=·×]', inner):
                        norm = normalize_text_for_estonian_tts(
                            inner, verbalize_math_signs=True, verbalize_numbers=True
                        )
                        return f"<est>{norm}</est>"
                    return m.group(0)
                return re.sub(r'<\s*est(?:\s+[^>]*)?>(.*?)<\s*/\s*est\s*>', _repl_tag, s, flags=re.IGNORECASE | re.DOTALL)

            v_speech = _normalize_speech_est_tags(v_speech)
            th_speech = _normalize_speech_est_tags(th_speech)
            alt_speech = _normalize_speech_est_tags(alt_speech)
            how_speech = _normalize_speech_est_tags(how_speech)
            ex_speech = _normalize_speech_est_tags(ex_speech)

            self.voice_prompt_script_speech = v_speech
            self.theme_explanation_speech = th_speech
            self.alternative_explanation_speech = alt_speech
            self.how_to_answer_speech = how_speech
            self.worked_example_speech = ex_speech

            if not self.speech_text or not self.speech_text.strip():
                self.speech_text = self.how_to_answer_speech or self.theme_explanation_speech or self.voice_prompt_script_speech or ""

            if self.speech_layer is None:
                self.speech_layer = LessonSpeechLayer(
                    voice_prompt_script=v_speech,
                    theme_explanation=th_speech,
                    alternative_explanation=alt_speech,
                    how_to_answer=how_speech,
                    worked_example=ex_speech,
                )
        except Exception:
            pass
        return self


class AppendPageJsonRequest(BaseModel):
    image_base64: str = Field(
        ...,
        description="Изображение второй страницы (разворота или тетради) в формате Base64"
    )
    mime_type: Optional[str] = Field(
        default="image/jpeg",
        description="MIME тип изображения (image/jpeg, image/png)"
    )


class AnalyzePageJsonRequest(BaseModel):
    lesson_id: Optional[str] = Field(default=None, description="ID активной сессии урока для добавления разворота без списания баллов")
    image_base64: Optional[str] = Field(default=None, description="Изображение страницы учебника в формате base64 (одиночное)")
    images_base64: Optional[List[str]] = Field(default=None, max_length=2, description="Список изображений нескольких страниц учебника/тетради в формате base64 (максимум 2 страницы)")
    mime_type: str = Field(default="image/jpeg", description="MIME тип изображения (image/jpeg, image/png)")
    mime_types: Optional[List[str]] = Field(default=None, max_length=2, description="Список MIME типов изображений")
    grade: int = Field(default=3, ge=1, le=12)
    tier: Optional[AgeTier] = None
    interests: Optional[Union[List[str], str]] = Field(
        default_factory=list,
        description="Список увлечений ребенка (строка через запятую или массив)"
    )
    theme_interest: Optional[str] = None  # Для обратной совместимости
    nickname: Optional[str] = "Друг"


class MoreExamplesRequest(BaseModel):
    task_title: str = Field(..., max_length=1000, description="Тема урока")
    theme_explanation: Optional[str] = Field(default="", max_length=1000, description="Суть темы")
    vocabulary: List[VocabularyItem] = Field(default_factory=list, description="Словарь урока")
    current_template: str = Field(default="", max_length=1000, description="Текущий речевой каркас")
    grade: int = Field(default=3, ge=1, le=12)
    tier: Optional[AgeTier] = None


class MoreExamplesResponse(BaseModel):
    templates: List[str] = Field(default_factory=list, description="Новые примеры с пропусками [слово]")
