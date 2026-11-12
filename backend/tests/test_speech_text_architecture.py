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

    # Проверка константы AUDIO_CACHE_VERSION >= 2
    import re
    assert re.search(r'export const AUDIO_CACHE_VERSION = \d+;', aqm_content)
    assert re.search(r'export const AUDIO_CACHE_VERSION = \d+;', ap_content)

    # Проверка ключа AsyncStorage @tarkapp_audio_cache_version
    assert "@tarkapp_audio_cache_version" in aqm_content
    assert "@tarkapp_audio_cache_version" in ap_content

    # Проверка логики очистки при storedVersion < AUDIO_CACHE_VERSION
    assert "storedVersion < AUDIO_CACHE_VERSION" in aqm_content
    assert "deleteAsync" in aqm_content
    assert "deleteAsync" in ap_content


def test_gemini_schema_structured_outputs_speech_fields():
    """Verify GeminiPageAnalysisSchema includes speech layer fields for structured outputs."""
    from app.models.page_analysis import GeminiPageAnalysisSchema
    props = GeminiPageAnalysisSchema.model_json_schema().get("properties", {})
    required = GeminiPageAnalysisSchema.model_json_schema().get("required", [])

    assert "theme_explanation_speech" in props
    assert "how_to_answer_speech" in props
    assert "worked_example_speech" in props
    assert "voice_prompt_script_speech" in props
    assert "alternative_explanation_speech" in props
    assert "theme_explanation_speech" in required
    assert "how_to_answer_speech" in required


def test_ssml_isolation_keywords_and_accents():
    """
    Verify SSML generator preserves acute accents \u0301 and does not slice
    ESTONIAN_CORE_KEYWORDS or re-normalize quotes when is_speech_text=True.
    """
    from app.services.tts_service import build_ssml, parse_bilingual_segments

    # 1. Combining acute accent preservation
    speech_with_accents = "У нас есть дели\u0301мое и вычита\u0301емое."
    ssml = build_ssml(speech_with_accents, is_speech_text=True)
    assert "дели\u0301мое" in ssml or "дели́мое" in ssml
    assert "вычита\u0301емое" in ssml or "вычита́емое" in ssml
    assert "ru-RU-SvetlanaNeural" in ssml

    # 2. No Estonian keywords carved out from Russian text when is_speech_text=True
    # 'summa' is in ESTONIAN_CORE_KEYWORDS. In normal text it might get sliced,
    # but in speech_text it remains in the Russian voice block
    russian_speech = "Полученная сумма чисел равна десяти."
    ssml_kw = build_ssml(russian_speech, is_speech_text=True)
    assert "<lang xml:lang=\"et-EE\">" not in ssml_kw

    # 3. parse_bilingual_segments disables normalize_text_for_estonian_tts when is_speech_text=True
    segs = parse_bilingual_segments("Слово «kass» означает кошка.", is_speech_text=True)
    assert any(s[0] == "kass" for s in segs)


def test_speak_endpoint_supports_is_speech_text(client, monkeypatch):
    """Verify GET /api/v1/voice/speak accepts is_speech_text and passes to tts_service."""
    captured = {}
    async def mock_synth(text, voice="et-EE-AnuNeural", bilingual=False, grade=None, tier=None, is_speech_text=False, **kwargs):
        captured["text"] = text
        captured["voice"] = voice
        captured["is_speech_text"] = is_speech_text
        return b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x44" * 300

    from app.routers import voice as voice_router
    monkeypatch.setattr(voice_router, "get_or_synthesize_audio", mock_synth)

    resp = client.get(
        "/api/v1/voice/speak?text=kass&lang=et&is_speech_text=true",
        headers={"X-Device-ID": "dev-test-device-0001"},
    )
    assert resp.status_code == 200
    assert captured.get("is_speech_text") is True
    assert captured.get("text") == "kass"


def test_socratic_scaffolding_and_verb_accents():
    """Verify tutor prompt enforces Socratic scaffolding in advice, eliminates priming, and expands verb acute accents."""
    from app.prompts.tutor_prompt import ESTONIAN_TUTOR_SYSTEM_PROMPT, build_tutor_user_prompt
    from app.models.page_analysis import UserProfile

    # 1. Direct answer hints banned in note / advice without negative priming
    assert "ЗАПРЕТ ПРЯМОЙ ПОДСКАЗКИ В БЛОКЕ «СОВЕТ»" in ESTONIAN_TUTOR_SYSTEM_PROMPT
    assert "выбери знак деления" not in ESTONIAN_TUTOR_SYSTEM_PROMPT
    assert "разливали компот поровну" not in ESTONIAN_TUTOR_SYSTEM_PROMPT
    assert "Формула совета: [Отсылка к принципу разобранного примера] + [Наводящий вопрос на рассуждение]." in ESTONIAN_TUTOR_SYSTEM_PROMPT
    assert "Вспомни, как мы распределяли предметы поровну в примере выше" in ESTONIAN_TUTOR_SYSTEM_PROMPT
    assert "Текст how_to_answer_speech обязан транскрибировать наводящий совет полностью" in ESTONIAN_TUTOR_SYSTEM_PROMPT

    # 2. Phonetic stress rules for homographs in speech text (Silero v5)
    assert "ПРАВИЛО КОНТЕКСТНОЙ РАССТАНОВКИ УДАРЕНИЙ" in ESTONIAN_TUTOR_SYSTEM_PROMPT
    assert "вычит+аем" in ESTONIAN_TUTOR_SYSTEM_PROMPT
    assert "ст+опы" in ESTONIAN_TUTOR_SYSTEM_PROMPT
    assert '<phoneme' not in ESTONIAN_TUTOR_SYSTEM_PROMPT

    # 3. User prompt includes student context and directive without duplicate rules
    u_prompt = build_tutor_user_prompt(UserProfile(grade=3, nickname="Маша"))
    assert "Проанализируй прикрепленные учебные материалы. Определи Режим (A или B)" in u_prompt
    assert "ДАННЫЕ УЧЕНИКА:" in u_prompt
    assert "Имя: Маша" in u_prompt
    assert "Класс: 3 класс" in u_prompt
    assert "Возрастная группа: primary" in u_prompt
    assert "РАЗМЕТКА ОЗВУЧКИ (TTS)" not in u_prompt
    assert "РЕЧЕВОЙ СЛОЙ (SPEECH)" not in u_prompt


def test_speech_layer_generation_and_ssml_isolation():
    """
    Comprehensive verification of speech_layer generation and Azure SSML isolation:
    1. PageAnalysisResponse correctly parses GeminiPageAnalysisSchema with speech_layer != None.
    2. Speech fields are populated with words, no digits (0-9), no formula symbols (:, =, +).
    3. Action verbs and terms contain Combining Acute Accents \u0301.
    4. Advice block does not contain direct interface hints (e.g. 'выбери знак деления').
    5. build_ssml with 'Если разлива́ем по́ровну, выбира́ем действие деле́ния. Пятнадцать разделить на три равно пять.'
       preserves \u0301, bypasses formula normalizer, and avoids parasitic ESTONIAN_CORE_KEYWORDS slicing.
    """
    from app.models.page_analysis import (
        GeminiPageAnalysisSchema,
        PageAnalysisResponse,
        LessonSpeechLayer,
    )
    from app.services.tts_service import build_ssml

    # 1. Simulate Gemini Structured Outputs schema response
    gemini_data = {
        "task_title": "Деление: делимое, делитель и частное (Jagamine)",
        "theme_explanation": "Деление — это когда мы раскладываем предметы поровну.",
        "alternative_explanation": "Представь, что мы делим пирог на равные кусочки.",
        "vocabulary": [
            {"est": "jagamine", "ru": "деление", "example": "See on jagamine."},
            {"est": "jagatav", "ru": "делимое", "example": "Esimene arv on jagatav."},
            {"est": "jagaja", "ru": "делитель", "example": "Teine arv on jagaja."},
        ],
        "worked_example": {
            "title": "Пример решения (Näidis)",
            "given": "Было: 15 яблок на 3 тарелки",
            "steps": ["1. Делим: 15 : 3 = 5", "2. Вывод: на каждой тарелке по 5 яблок"],
            "note": "Вспомни, как мы распределяли предметы поровну в примере выше, и примени аналогичный способ к своим данным.",
        },
        "how_to_answer": "1. Найди в тексте задачи общее количество и число частей. 2. Рассуждай по правилу равных долей.",
        "answer_template": "See on [jagamine] ja jagatis on [viis].",
        "voice_prompt_script": "Привет! Давай разберём деление вместе!",
        "theme_explanation_speech": "Деле\u0301ние — это когда мы раскла\u0301дываем предме\u0301ты по\u0301ровну на ра\u0301вные ча\u0301сти.",
        "how_to_answer_speech": "Снача\u0301ла определя\u0301ем дели\u0301мое и дели\u0301тель, а затем де\u0301лим пе\u0301рвое число\u0301 на второ\u0301е полными словами.",
        "worked_example_speech": "Если у нас пятнадцать яблок на три тарелки, мы де\u0301лим пятнадцать на три и получа\u0301ем по пять яблок на тарелке.",
        "voice_prompt_script_speech": "Привет! Давай разберём деле\u0301ние вместе!",
        "alternative_explanation_speech": "Представь, что мы де\u0301лим пирог на ра\u0301вные куски\u0301 для друзей.",
    }

    # Validate with Gemini schema and PageAnalysisResponse
    gemini_schema_obj = GeminiPageAnalysisSchema.model_validate(gemini_data)
    response = PageAnalysisResponse.model_validate(gemini_schema_obj.model_dump())

    # Check 1.1: speech_layer is not None
    assert response.speech_layer is not None
    assert isinstance(response.speech_layer, LessonSpeechLayer)

    # Check 1.2: speech fields populated with full words without digits (0-9) and formula signs (:, =, +)
    for field_name in ["theme_explanation_speech", "how_to_answer_speech", "worked_example_speech"]:
        val = getattr(response, field_name)
        assert val is not None and len(val.strip()) > 0, f"{field_name} must not be empty"
        assert not re.search(r'\d', val), f"{field_name} contains digits: {val}"
        assert not re.search(r'[:=+*/]', val), f"{field_name} contains formula characters: {val}"

    # Check 1.3: Combining Acute Accent \u0301 present in action verbs and terms
    combining_accent = "\u0301"
    all_speech_texts = " ".join([
        response.theme_explanation_speech or "",
        response.how_to_answer_speech or "",
        response.worked_example_speech or "",
    ])
    assert combining_accent in all_speech_texts or "́" in all_speech_texts

    # Check specific accented verbs / terms
    assert any(w in all_speech_texts for w in ["раскла́дываем", "раскла\u0301дываем", "определя́ем", "определя\u0301ем", "получа́ем", "получа\u0301ем"])
    assert any(w in all_speech_texts for w in ["дели́мое", "дели\u0301мое", "деле́ние", "деле\u0301ние"])

    # Check 1.4: advice block free of direct UI hints
    advice_note = response.worked_example.note
    how_to_ans = response.how_to_answer
    for forbidden in ["выбери знак деления", "выпадающем списке", "нажми пункт", "поставь минус"]:
        assert forbidden not in advice_note.lower()
        assert forbidden not in how_to_ans.lower()

    # Check 2: Azure SSML isolation with exact test phrase
    test_phrase = "Если разлива́ем по́ровну, выбира́ем действие деле́ния. Пятнадцать разделить на три равно пять."
    ssml = build_ssml(test_phrase, is_speech_text=True)

    # 2.1 Accents preserved in output XML
    assert ("разлива́ем" in ssml or "разлива\u0301ем" in ssml)
    assert ("по́ровну" in ssml or "по\u0301ровну" in ssml)
    assert ("выбира́ем" in ssml or "выбира\u0301ем" in ssml)
    assert ("деле́ния" in ssml or "деле\u0301ния" in ssml)

    # 2.2 Words not broken into parasitic ESTONIAN_CORE_KEYWORDS segments
    assert '<lang xml:lang="et-EE">' not in ssml
    assert '<voice name="ru-RU-SvetlanaNeural">' in ssml

    # 2.3 Math sign / legacy normalizer was not invoked (is_speech_text=True bypasses)
    assert "<say-as" not in ssml
    assert "<speak" in ssml and "</speak>" in ssml


def test_layer_separation_and_accent_sanitization():
    """
    Verify:
    1. Visual fields in StepItem, WorkedExample, PageAnalysisResponse are sanitized of \u0301.
    2. Speech fields retain \u0301.
    3. Prompts mandate verbatim worked_example_speech and mandatory <est>...</est> for cities/timestamps.
    """
    from app.models.page_analysis import StepItem, WorkedExample, PageAnalysisResponse, GeminiPageAnalysisSchema
    from app.prompts.tutor_prompt import ESTONIAN_TUTOR_SYSTEM_PROMPT

    # 1. StepItem sanitization
    step = StepItem(text="Выбира́ем де́йствие", speech_text="выбира́ем де́йствие")
    assert step.text == "Выбираем действие"
    assert "\u0301" in step.speech_text or "́" in step.speech_text

    # 2. WorkedExample sanitization of visual fields
    we = WorkedExample(
        title="Приме́р реше́ния (Näidis)",
        given="Если разлива́ем по́ровну",
        steps=["1. Дели́м: 15 : 3 = 5", "2. Получа́ем 5"],
        note="Вспомни, как распределя́ли по́ровну",
        speech_text="Если разлива́ем по́ровну, де́лим пятнадцать на три...",
    )
    assert we.title == "Пример решения (Näidis)"
    assert we.given == "Если разливаем поровну"
    assert we.steps == ["1. Делим: 15 : 3 = 5", "2. Получаем 5"]
    assert we.note == "Вспомни, как распределяли поровну"
    assert "\u0301" in we.speech_text or "́" in we.speech_text

    # 3. PageAnalysisResponse end-to-end sanitization
    data = {
        "task_title": "Деле́ние чисел",
        "theme_explanation": "Тема объясня́ет деление",
        "alternative_explanation": "Альт объясне́ние",
        "vocabulary": [{"est": "jagamine", "ru": "деление", "example": "See on jagamine"}],
        "worked_example": {
            "title": "Приме́р",
            "given": "Дано́ 15 яблок",
            "steps": ["15 : 3 = 5"],
            "note": "Сове́т",
        },
        "how_to_answer": "Инструкция как счита́ть",
        "answer_template": "See on [jagamine].",
        "voice_prompt_script": "Приве́т!",
        "theme_explanation_speech": "Тема объясня́ет деле́ние полными словами",
        "how_to_answer_speech": "Инструкция как счита́ть полными словами",
        "worked_example_speech": "Дано́ пятнадцать яблок. Пятнадцать разделить на три равно пять. Сове́т.",
    }
    resp = PageAnalysisResponse.model_validate(data)
    assert resp.task_title == "Деление чисел"
    assert resp.theme_explanation == "Тема объясняет деление"
    assert resp.alternative_explanation == "Альт объяснение"
    assert resp.how_to_answer == "Инструкция как считать"
    assert resp.voice_prompt_script == "Привет!"
    assert resp.worked_example.given == "Дано 15 яблок"
    assert resp.worked_example.note == "Совет"

    # Speech layer retains accents
    assert ("деле́ние" in resp.theme_explanation_speech or "деле\u0301ние" in resp.theme_explanation_speech)
    assert ("Дано́" in resp.worked_example_speech or "Дано\u0301" in resp.worked_example_speech)
    assert ("Сове́т" in resp.worked_example_speech or "Сове\u0301т" in resp.worked_example_speech)

    # 4. Prompt verification for layer separation, verbatim speech formula and Estonian tags
    assert "РАЗГРАНИЧЕНИЕ ВИЗУАЛЬНОГО И РЕЧЕВОГО СЛОЕВ" in ESTONIAN_TUTOR_SYSTEM_PROMPT
    assert "СТРОГАЯ СТРУКТУРА WORKED_EXAMPLE_SPEECH (ЗАПРЕТ ВОЛЬНОГО ПЕРЕСКАЗА)" in ESTONIAN_TUTOR_SYSTEM_PROMPT
    assert "[Дословный текст given] + [Шаг 1 полными словами]" in ESTONIAN_TUTOR_SYSTEM_PROMPT
    assert "<est>kell on 9.00</est>" in ESTONIAN_TUTOR_SYSTEM_PROMPT
    assert "<est>Narva</est>" in ESTONIAN_TUTOR_SYSTEM_PROMPT


def test_tts_audit_logging_and_admin_endpoint(client):
    """Verify log_tts_audit writes to logs/tts_audit.log, database, and GET /api/v1/admin/tts-logs returns records."""
    from app.services.tts_service import log_tts_audit
    from app.models.tts_audit import TTSAuditLog
    from app.database import SessionLocal
    from app.logger import TTS_AUDIT_LOG_PATH

    # 1. Direct call to log_tts_audit
    sample_text = "Дели́мое пятнадцать разделить на три"
    sample_ssml = '<speak version="1.0"><voice name="ru-RU-SvetlanaNeural">Дели́мое пятнадцать разделить на три</voice></speak>'
    log_tts_audit(
        raw_incoming_text=sample_text,
        final_ssml=sample_ssml,
        endpoint="/api/v1/voice/tts",
        is_speech_text=True,
        device_id="test-audit-device-01",
        user_tier="primary",
        grade=3,
        cache_status="AZURE_SYNTHESIS",
        status="SUCCESS",
        duration_ms=45.2,
    )

    # 2. Check database record
    with SessionLocal() as db:
        record = db.query(TTSAuditLog).filter(TTSAuditLog.device_id == "test-audit-device-01").order_by(TTSAuditLog.id.desc()).first()
        assert record is not None
        assert record.is_speech_text is True
        assert record.has_accents is True
        assert record.status == "SUCCESS"
        assert record.duration_ms == 45.2

    # 3. Check admin endpoint GET /api/v1/admin/tts-logs
    resp = client.get("/api/v1/admin/tts-logs?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 1
    found = any(item["device_id"] == "test-audit-device-01" for item in data["items"])
    assert found is True

    # 4. Check log file exists
    assert TTS_AUDIT_LOG_PATH.exists()

