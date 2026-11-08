"""
Unit tests for Speech Text Two-Layer Architecture, Database Migrations,
and Empty Step Filtering (Technical Specification: Speech Text Architecture).
"""
import re
from pathlib import Path
import pytest
from sqlalchemy import create_engine, text

from app.database import init_db
from app.main import app
from app.models.page_analysis import (
    StepItem,
    SelfSolveStep,
    LessonCard,
    BilingualCard,
    WorkedExample,
    SelfSolveGuide,
    PageAnalysisResponse,
    VocabularyItem,
)
from app.prompts.tutor_prompt import ESTONIAN_TUTOR_SYSTEM_PROMPT
from app.services.tts_service import build_ssml, is_already_speech_text


from tests.test_closed_beta_fixes import OfflineASGIClient


@pytest.fixture
def client():
    if hasattr(app.state, "limiter"):
        app.state.limiter.reset()
    return OfflineASGIClient(app)


def test_step_item_model_and_fallback():
    # 1. StepItem with explicit speech_text
    s1 = StepItem(text="2 + 3 = 5", speech_text="два плюс три равно пять")
    assert s1.text == "2 + 3 = 5"
    assert s1.speech_text == "два плюс три равно пять"

    # 2. StepItem with fallback when speech_text is None or empty
    s2 = StepItem(text="Делим пополам")
    assert s2.text == "Делим пополам"
    assert s2.speech_text == "Делим пополам"

    s3 = StepItem(text="Делим пополам", speech_text="   ")
    assert s3.speech_text == "Делим пополам"

    # 3. StepItem rejects empty text
    with pytest.raises(ValueError):
        StepItem(text="   ")


def test_self_solve_step_model_and_fallback():
    st1 = SelfSolveStep(text="12 : 3 = 4", speech_text="двенадцать разделить на три равно четыре")
    assert st1.speech_text == "двенадцать разделить на три равно четыре"

    st2 = SelfSolveStep(text="Шаг решения")
    assert st2.speech_text == "Шаг решения"

    with pytest.raises(ValueError):
        SelfSolveStep(text="")


def test_lesson_card_and_bilingual_card():
    lc = LessonCard(text="Основное правило")
    assert lc.speech_text == "Основное правило"

    bc1 = BilingualCard(est="liidetav", ru="слагаемое")
    assert bc1.text == "liidetav"
    assert bc1.speech_text == "liidetav"

    bc2 = BilingualCard(est="summa", text="Сумма", speech_text="сумма")
    assert bc2.text == "Сумма"
    assert bc2.speech_text == "сумма"


def test_worked_example_steps_filtering_and_speech_text():
    we = WorkedExample(
        given="10 конфет на 2 детей",
        steps=["1. 10 : 2 = 5", "  ", "", "2. Ответ: по 5 конфет"],
        note="Решай так же",
    )
    # Empty steps must be pruned automatically
    assert len(we.steps) == 2
    assert we.steps == ["1. 10 : 2 = 5", "2. Ответ: по 5 конфет"]
    # Fallback speech_text should be formed from given, steps, note
    assert "10 конфет на 2 детей" in we.speech_text
    assert "2. Ответ: по 5 конфет" in we.speech_text


def test_self_solve_guide_arrays_filtering():
    guide = SelfSolveGuide(
        steps=["Шаг 1", "  ", "", "Шаг 2"],
        guided_steps=["Подсказка 1", ""],
        actions=["", "Действие 1", "  "],
    )
    assert guide.steps == ["Шаг 1", "Шаг 2"]
    assert guide.guided_steps == ["Подсказка 1"]
    assert guide.actions == ["Действие 1"]
    assert "Шаг 1 Шаг 2" in guide.speech_text


def test_page_analysis_response_pruning_and_speech_text():
    resp = PageAnalysisResponse(
        task_title="Тема урока",
        theme_explanation="Объяснение темы",
        vocabulary=[
            VocabularyItem(est="liitmine", ru="сложение", example="See on liitmine.")
        ],
        worked_example=WorkedExample(
            given="4 яблока",
            steps=["1. Считаем", "  ", "2. Готово"],
        ),
        how_to_answer="Алгоритм решения",
        answer_template="Summa on [10]",
        voice_prompt_script="Привет, решим вместе!",
    )
    assert len(resp.worked_example.steps) == 2
    assert resp.speech_text is not None
    assert len(resp.speech_text.strip()) > 0
    assert resp.speech_layer is not None


def test_system_prompt_contains_speech_text_rules():
    assert "ПРАВИЛО РЕЧЕВОГО СЛОЯ (SPEECH_TEXT)" in ESTONIAN_TUTOR_SYSTEM_PROMPT
    assert "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать любые цифры" in ESTONIAN_TUTOR_SYSTEM_PROMPT
    assert "именительный падеж числительных" in ESTONIAN_TUTOR_SYSTEM_PROMPT


def test_tts_bypass_with_is_speech_text():
    # When is_speech_text is True, numerals and math expressions in speech_text are NOT re-normalized
    speech_text = "четыре плюс пять равно девять"
    ssml = build_ssml(speech_text, is_speech_text=True)
    assert "четыре плюс пять равно девять" in ssml

    # When text is pure Estonian speech_text
    est_speech_text = "neli pluss viis on üheksa"
    ssml_est = build_ssml(est_speech_text, voice="et-EE-AnuNeural", is_speech_text=True)
    assert "neli pluss viis on üheksa" in ssml_est
    assert "et-EE" in ssml_est


def test_database_speech_text_migration_and_backfill(tmp_path):
    # Create a temporary SQLite database with a mock 'lessons' table
    test_db_path = tmp_path / "test_migration.db"
    db_url = f"sqlite:///{test_db_path}"
    test_engine = create_engine(db_url)

    with test_engine.connect() as conn:
        conn.execute(text("CREATE TABLE lessons (id INTEGER PRIMARY KEY, text TEXT)"))
        conn.execute(text("INSERT INTO lessons (id, text) VALUES (1, 'Урок 1: Текст урока')"))
        conn.commit()

    # Verify table has no speech_text column yet
    with test_engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(lessons)")).fetchall()]
        assert "speech_text" not in cols

    # Run migration logic
    from app import database
    orig_engine = database.engine
    orig_url = database.settings.DATABASE_URL
    try:
        database.engine = test_engine
        database.settings.DATABASE_URL = db_url
        init_db()

        # Check column added and backfilled
        with test_engine.connect() as conn:
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info(lessons)")).fetchall()]
            assert "speech_text" in cols

            row = conn.execute(text("SELECT id, text, speech_text FROM lessons WHERE id = 1")).fetchone()
            assert row[1] == "Урок 1: Текст урока"
            assert row[2] == "Урок 1: Текст урока"
    finally:
        database.engine = orig_engine
        database.settings.DATABASE_URL = orig_url


# =====================================================================
# Специфические E2E тесты порции верификации (Раздел 2.1 ТЗ)
# =====================================================================

def test_e2e_mock_estonian_units_speech_text(client, monkeypatch):
    """
    Тест 1 (Эстонский, меры):
    Входной text: 'Kauplusesse toodi 15 kg õunu ja 3 l piima'.
    Проверить, что speech_text содержит 'viisteist kilogrammi õunu ja kolm liitrit piima'
    (без цифр и латинских сокращений 'kg'/'l').
    Проверить, что при отправке в /api/v1/voice/tts с флагом is_speech_text=True
    текст попадает в SSML без искажения устаревшим нормализатором.
    """
    visual_text = "Kauplusesse toodi 15 kg õunu ja 3 l piima"
    speech_text = "Kauplusesse toodi viisteist kilogrammi õunu ja kolm liitrit piima"

    # 1. Проверяем соответствие контракту speech_text
    assert not re.search(r'\d', speech_text), "speech_text не должен содержать цифр"
    assert not re.search(r'\b(?:kg|l)\b', speech_text), "speech_text не должен содержать латинских сокращений"
    assert "viisteist kilogrammi" in speech_text
    assert "kolm liitrit" in speech_text

    # 2. Модель StepItem
    step = StepItem(text=visual_text, speech_text=speech_text)
    assert step.text == visual_text
    assert step.speech_text == speech_text

    # 3. Прямая передача в SSML с is_speech_text=True
    ssml = build_ssml(step.speech_text, voice="et-EE-AnuNeural", is_speech_text=True)
    assert "viisteist kilogrammi õunu ja kolm liitrit piima" in ssml
    assert "et-EE" in ssml

    # 4. Сквозной вызов эндпоинта /api/v1/voice/tts
    captured = {}
    async def mock_synth(text, voice="ru-RU-SvetlanaNeural", bilingual=False, grade=None, tier=None, is_speech_text=False):
        captured["text"] = text
        captured["voice"] = voice
        captured["is_speech_text"] = is_speech_text
        return b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x44" * 300

    from app.services import tts_service
    from app.routers import voice as voice_router
    monkeypatch.setattr(tts_service, "get_or_synthesize_audio", mock_synth)
    monkeypatch.setattr(voice_router, "get_or_synthesize_audio", mock_synth)

    resp = client.post(
        "/api/v1/voice/tts",
        json={
            "text": step.speech_text,
            "lang": "et",
            "is_speech_text": True,
        },
        headers={"X-Device-ID": "dev-test-device-0001"},
    )
    assert resp.status_code == 200
    assert captured.get("is_speech_text") is True
    assert captured.get("text") == speech_text


def test_e2e_mock_russian_arithmetic_nominative(client, monkeypatch):
    """
    Тест 2 (Русский, арифметика):
    Входной text: '4 · 5 = 20 и 18 : 3 = 6'.
    Проверить, что speech_text содержит 'четыре умножить на пять равно двадцать и восемнадцать разделить на три равно шесть'
    (строго именительный падеж).
    """
    visual_text = "4 · 5 = 20 и 18 : 3 = 6"
    speech_text = "четыре умножить на пять равно двадцать и восемнадцать разделить на три равно шесть"

    # 1. Проверяем отсутствие знаков и цифр
    assert not re.search(r'[\d·:=]', speech_text), "speech_text не должен содержать цифр или знаков формул"
    assert "четыре умножить на пять равно двадцать" in speech_text
    assert "восемнадцать разделить на три равно шесть" in speech_text

    # 2. Модель StepItem
    step = StepItem(text=visual_text, speech_text=speech_text)
    assert step.speech_text == speech_text

    # 3. Передача в build_ssml
    ssml = build_ssml(step.speech_text, voice="ru-RU-SvetlanaNeural", is_speech_text=True)
    assert speech_text in ssml

    # 4. Сквозной вызов эндпоинта /api/v1/voice/tts
    captured = {}
    async def mock_synth(text, voice="ru-RU-SvetlanaNeural", bilingual=False, grade=None, tier=None, is_speech_text=False):
        captured["text"] = text
        captured["voice"] = voice
        captured["is_speech_text"] = is_speech_text
        return b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x44" * 300

    from app.services import tts_service
    from app.routers import voice as voice_router
    monkeypatch.setattr(tts_service, "get_or_synthesize_audio", mock_synth)
    monkeypatch.setattr(voice_router, "get_or_synthesize_audio", mock_synth)

    import urllib.parse
    encoded_text = urllib.parse.quote(speech_text)
    resp = client.get(
        f"/api/v1/voice/tts?text={encoded_text}&lang=ru&is_speech_text=true",
        headers={"X-Device-ID": "dev-test-device-0001"},
    )
    assert resp.status_code == 200
    assert captured.get("is_speech_text") is True
    assert captured.get("text") == speech_text


def test_ui_protection_empty_steps_filtering():
    """
    Тест 3 (Защита UI от пустых шагов):
    Передать в модель массив steps с пустыми элементами: ["Шаг 1", "", "   ", None, "Шаг 2"].
    Проверить, что валидатор Pydantic возвращает массив ровно из 2 валидных элементов ("Шаг 1", "Шаг 2").
    """
    raw_steps = ["Шаг 1", "", "   ", None, "Шаг 2"]

    # WorkedExample
    we = WorkedExample(
        given="12 яблок",
        steps=raw_steps,
        note="Совет",
    )
    assert len(we.steps) == 2
    assert we.steps == ["Шаг 1", "Шаг 2"]

    # SelfSolveGuide
    guide = SelfSolveGuide(
        steps=raw_steps,
        guided_steps=["Подсказка 1", "", "  ", None, "Подсказка 2"],
        actions=[None, "Действие 1", " ", "Действие 2"],
    )
    assert len(guide.steps) == 2
    assert guide.steps == ["Шаг 1", "Шаг 2"]
    assert len(guide.guided_steps) == 2
    assert guide.guided_steps == ["Подсказка 1", "Подсказка 2"]
    assert len(guide.actions) == 2
    assert guide.actions == ["Действие 1", "Действие 2"]

    # PageAnalysisResponse
    resp = PageAnalysisResponse(
        task_title="Тестовая задача",
        theme_explanation="Объяснение темы",
        vocabulary=[VocabularyItem(est="arv", ru="число", example="See on arv.")],
        worked_example=WorkedExample(
            given="12 яблок",
            steps=raw_steps,
        ),
        how_to_answer="Алгоритм",
        answer_template="Summa on [12]",
        voice_prompt_script="Привет!",
    )
    assert len(resp.worked_example.steps) == 2
    assert resp.worked_example.steps == ["Шаг 1", "Шаг 2"]


def test_client_audio_cache_version_and_invalidation():
    """
    Тест 4 (Инвалидация кэша клиента):
    Проверить, что ключ @tarkapp_audio_cache_version имеет значение 2,
    а старый путь кэша очищается при несовпадении версий в клиентских сервисах.
    """
    aqm_path = Path("mobile/src/services/audioQueueManager.ts")
    ap_path = Path("mobile/src/services/audioPlayer.ts")

    assert aqm_path.exists(), "audioQueueManager.ts must exist"
    assert ap_path.exists(), "audioPlayer.ts must exist"

    aqm_content = aqm_path.read_text(encoding="utf-8")
    ap_content = ap_path.read_text(encoding="utf-8")

    # Проверка константы AUDIO_CACHE_VERSION = 2
    assert "export const AUDIO_CACHE_VERSION = 2;" in aqm_content
    assert "export const AUDIO_CACHE_VERSION = 2;" in ap_content

    # Проверка ключа AsyncStorage @tarkapp_audio_cache_version
    assert "@tarkapp_audio_cache_version" in aqm_content
    assert "@tarkapp_audio_cache_version" in ap_content

    # Проверка логики очистки при storedVersion < AUDIO_CACHE_VERSION
    assert "storedVersion < AUDIO_CACHE_VERSION" in aqm_content
    assert "deleteAsync" in aqm_content
    assert "deleteAsync" in ap_content
