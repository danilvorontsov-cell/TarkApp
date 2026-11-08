"""
Изолированный автотест двухконтурной системы нормализации и синтеза речи (Azure TTS).
Проверяет:
1. Русский контекст: расстановка ударений (\u0301) в омографах и адаптация брендов (Ро́блокс, вычита́ем, ша́га, велопутеше́ствие).
2. Эстонский контекст: нормализация сокращений единиц измерения (km -> kilomeetrit, kg -> kilogrammi, tk -> tükki, lk -> lehekülge).
3. Знак умножения (точка ·): замена на «умно́жить на».
4. Исправление падежей и ударений: «со зна́ком», «по три́», «в два кувши́на», «пёсик».
5. Исключение заголовков карточек из озвучки (Пример решения / Näidis).
6. Автоматическое распознавание и тегирование эстонских фраз без тегов (jagas võrdselt).
"""

import pytest
from app.services.tts_normalizer import (
    apply_phonetic_substitutions,
    prepare_speech_text,
    get_tts_lexicon,
    filter_card_headers_from_speech,
    auto_tag_estonian_phrases,
    normalize_text_for_estonian_tts,
)
from app.services.tts_service import parse_bilingual_segments, ESTONIAN_VOICE, DEFAULT_VOICE


def test_russian_phonetic_stress_and_brands():
    """Тест 1: Русский контекст — наличие символов ударения в брендах, математических глаголах и омографах."""
    text_in = "В игре Roblox мы вычитаем 5 км пути и делим на 2 шага, это велопутешествие."

    # Проверка через apply_phonetic_substitutions
    res_sub = apply_phonetic_substitutions(text_in, is_estonian=False)
    assert "Ро́блокс" in res_sub or "Ро\u0301блокс" in res_sub, f"Ро́блокс not in: {res_sub}"
    assert "вычита́ем" in res_sub or "вычита\u0301ем" in res_sub, f"вычита́ем not in: {res_sub}"
    assert "ша́га" in res_sub or "ша\u0301га" in res_sub, f"ша́га not in: {res_sub}"
    assert "велопутеше́ствие" in res_sub or "велопутеше\u0301ствие" in res_sub, f"велопутеше́ствие not in: {res_sub}"

    # Проверка через сквозной пайплайн prepare_speech_text
    res_prep = prepare_speech_text(text_in, is_russian_context=True)
    assert "Ро́блокс" in res_prep or "Ро\u0301блокс" in res_prep, f"Ро́блокс not in: {res_prep}"
    assert "вычита́ем" in res_prep or "вычита\u0301ем" in res_prep, f"вычита́ем not in: {res_prep}"
    assert "ша́га" in res_prep or "ша\u0301га" in res_prep, f"ша́га not in: {res_prep}"
    assert "велопутеше́ствие" in res_prep or "велопутеше\u0301ствие" in res_prep, f"велопутеше́ствие not in: {res_prep}"


def test_estonian_measurement_units():
    """Тест 2: Эстонский контекст — нормализация сокращений мер и обозначений (km, kg, tk, lk)."""
    text_in = "Rattur sõitis 15 km ja ostis poest 3 tk vihikut, 2 kg õunu, lk 42."
    expected = "Rattur sõitis 15 kilomeetrit ja ostis poest 3 tükki vihikut, 2 kilogrammi õunu, lehekülg 42."

    res_sub = apply_phonetic_substitutions(text_in, is_estonian=True)
    assert res_sub == expected, f"Expected '{expected}', got '{res_sub}'"

    # Проверка нормализатора эстонского текста с kg. и точкой
    res_norm = normalize_text_for_estonian_tts("Osta 5 kg kapsaid ja 1 kg suhkrut.")
    assert "5 kilogrammi kapsaid" in res_norm
    assert "1 kilogramm suhkrut" in res_norm

    # Проверка учета падежей: 1 km -> 1 kilomeeter, 5 km -> 5 kilomeetrit
    assert normalize_text_for_estonian_tts("Distants on 1 km.") == "Distants on 1 kilomeeter"
    assert normalize_text_for_estonian_tts("Distants on 5 km.") == "Distants on 5 kilomeetrit"

    # Проверка страниц: lk 12 -> lehekülg 12, 12 lk -> 12 lehekülge
    assert normalize_text_for_estonian_tts("Ava lk 12.") == "Ava lehekülg 12"
    assert normalize_text_for_estonian_tts("Raamatus on 12 lk.") == "Raamatus on 12 lehekülge"

    # Проверка математических формул с переменными: s = v · t не должно заменять s на sekundit и t на tonni
    formula_res = normalize_text_for_estonian_tts("s = v · t")
    assert "sekundit" not in formula_res
    assert "tonni" not in formula_res


def test_multiplication_dot_pronunciation():
    """Тест 3: Озвучивание знаков умножения (korda) и деления (jagatud) в эстонском и русском контекстах."""
    # Русский контекст: 4 · 5 = 20 -> умно́жить на
    text_in = "Вычисли: 4 · 5 = 20 и 3 • 6 = 18."
    res = prepare_speech_text(text_in, is_russian_context=True)
    assert (
        "четы́ре умно́жить на пять" in res
        or "четы\u0301ре умно\u0301жить на пять" in res
        or "4 умно́жить на 5" in res
        or "4 умно\u0301жить на 5" in res
    )
    assert (
        "три умно́жить на шесть" in res
        or "3 умно́жить на 6" in res
        or "3 умно\u0301жить на 6" in res
    )

    # Эстонский контекст: умножение -> korda, деление -> jagatud
    est_mult = normalize_text_for_estonian_tts("4 · 5 = 20")
    assert "4 korda 5" in est_mult

    est_div = normalize_text_for_estonian_tts("6 : 2 = 3")
    assert "6 jagatud 2 = 3" in est_div or "6 jagatud 2 3" in est_div
    assert "jagatud" in est_div

    assert "15 jagatud 3" in normalize_text_for_estonian_tts("15 ÷ 3 = 5")
    assert "10 jagatud 2" in normalize_text_for_estonian_tts("10 / 2 = 5")


def test_stress_cases_and_yo():
    """Тест 4: Проверка фиксации ударений (со зна́ком, зна́ком, раздели́, раздели́те), буквы ё (пёсик) и падежей (по три́, в два кувши́на, четыре кувшина)."""
    text_in = "Мальчик со знаком плюс взял шесть раз по трёх яблок и налил в две кувшина, а рядом бегал песик."
    res = prepare_speech_text(text_in, is_russian_context=True)

    assert "со зна́ком" in res or "со зна\u0301ком" in res
    assert "по три́" in res or "по три\u0301" in res
    assert "в два кувши́на" in res or "в два кувши\u0301на" in res
    assert "пёсик" in res

    # Проверка одиночного слова «знаком»
    res_sign = prepare_speech_text("Число перед знаком минус.", is_russian_context=True)
    assert "зна́ком" in res_sign or "зна\u0301ком" in res_sign

    # Проверка повелительного наклонения «раздели́» и «раздели́те»
    res_div = prepare_speech_text("Раздели это число на два и разделите поровну.", is_russian_context=True)
    assert "Раздели́" in res_div or "Раздели\u0301" in res_div
    assert "раздели́те" in res_div or "раздели\u0301те" in res_div

    # Проверка исправления ошибочного «четырёх» для неодушевленных существительных -> «четыре»
    res_chetyre1 = prepare_speech_text("Коробка содержит четырёх яблока и четырёх кубика.", is_russian_context=True)
    assert "четыре яблока" in res_chetyre1
    assert "четыре кубика" in res_chetyre1
    assert "четырёх" not in res_chetyre1 and "четырех" not in res_chetyre1

    res_chetyre2 = prepare_speech_text("В четырёх кувшина налили сок.", is_russian_context=True)
    assert "четыре кувшина" in res_chetyre2


def test_filter_card_headers_from_speech():
    """Тест 5: Исключение заголовков карточек («Пример решения», «Образец», «Näidis») из речевого слоя."""
    examples = [
        ("Пример решения с другими числами. В саду росло 5 яблонь.", "В саду росло 5 яблонь."),
        ("Образец: найдем периметр прямоугольника.", "найдем периметр прямоугольника."),
        ("Näidis: arvuta summa.", "arvuta summa."),
        ("Пример решения (Näidis). Шаг 1.", "Шаг 1."),
    ]
    for text_in, expected in examples:
        filtered = filter_card_headers_from_speech(text_in)
        assert filtered == expected, f"Expected '{expected}', got '{filtered}'"


def test_auto_detect_untagged_estonian_phrases():
    """Тест 6: Автоматическое определение эстонских слов и фраз без тегов (jagas võrdselt, lemmikloomad)."""
    text_in = "В задаче сказано jagas võrdselt на двоих, а lemmikloomad сидели дома."
    tagged = auto_tag_estonian_phrases(text_in)
    assert "<est>jagas võrdselt</est>" in tagged
    assert "<est>lemmikloomad</est>" in tagged

    # Проверка, что английские бренды не тегируются ошибочно как эстонские
    text_brands = "В Roblox играли через Discord и жали клавиши WASD."
    tagged_brands = auto_tag_estonian_phrases(text_brands)
    assert "<est>" not in tagged_brands

    # Проверка маршрутизации в SSML сегменты
    segments = parse_bilingual_segments("Мама jagas võrdselt яблоки.")
    est_segments = [s for s, voice in segments if voice == ESTONIAN_VOICE]
    assert len(est_segments) > 0
    assert "jagas võrdselt" in est_segments[0]


def test_lexicon_structure():
    """Тест 7: Проверка структуры конфигурационного словаря tts_lexicon.json."""
    lexicon = get_tts_lexicon()
    assert "estonian_units" in lexicon
    assert "russian_stress_homographs" in lexicon
    assert "brand_fallbacks" in lexicon
    assert len(lexicon["estonian_units"]) >= 15
    assert len(lexicon["russian_stress_homographs"]) >= 16
    assert len(lexicon["brand_fallbacks"]) >= 17


def test_ssml_sub_alias_and_math_pipeline():
    """Тест 8: Проверка SSML с тегами <sub alias="..."> и сохранения формул."""
    from app.services.tts_service import apply_ssml_sub_alias, build_ssml

    escaped = "Познакомься со знаком плюс"
    with_sub = apply_ssml_sub_alias(escaped, "знаком", "зна\u0301ком")
    assert '<sub alias="зна\u0301ком">знаком</sub>' in with_sub

    # Проверка, что build_ssml сохраняет теги sub alias
    ssml = build_ssml(f"Внимание, {with_sub}.")
    assert '<sub alias="зна\u0301ком">знаком</sub>' in ssml


def test_ssml_veloputeshestvie_and_vychitaem_sub_aliases():
    """Тест 9: Проверка генерации SSML с тегами <sub alias="..."> для 'велопутешествие' и 'вычитаем'."""
    from app.services.tts_service import build_ssml

    # Проверка устранения двойного ударения в 'велопутешествие' (дефисный алиас вело-путеше́ствие)
    text_velo = "Наше велопутешествие продолжается, и правила велопутешествия просты."
    ssml_velo = build_ssml(text_velo)
    assert '<sub alias="вело-путеше́ствие">' in ssml_velo or '<sub alias="вело-путеше\u0301ствие">' in ssml_velo
    assert '<sub alias="вело-путеше́ствия">' in ssml_velo or '<sub alias="вело-путеше\u0301ствия">' in ssml_velo

    # Проверка фиксации ударения в 'вычитаем' и смежных словоформах (вычитает, вычитайте)
    text_vychit = "Мы вычитаем 5, он вычитает 3, а вы вычитайте остаток."
    ssml_vychit = build_ssml(text_vychit)
    assert '<sub alias="вычита́ем">' in ssml_vychit or '<sub alias="вычита\u0301ем">' in ssml_vychit
    assert '<sub alias="вычита́ет">' in ssml_vychit or '<sub alias="вычита\u0301ет">' in ssml_vychit
    assert '<sub alias="вычита́йте">' in ssml_vychit or '<sub alias="вычита\u0301йте">' in ssml_vychit

    # Проверка отсутствия дублирования тегов при наличии существующего <sub ...>
    with_sub = '<sub alias="вычита́ем">вычитаем</sub>'
    ssml_existing = build_ssml(f"Шаг: {with_sub}.")
    assert ssml_existing.count('<sub alias="вычита́ем">') == 1
    assert "<sub <sub" not in ssml_existing


# ==============================================================================
# Новые unit-тесты по ТЗ комплексного рефакторинга аудиоподсистемы (Аудит ARGON)
# ==============================================================================


def test_decimals_fractions_and_time_protection():
    """P0.1: Защита десятичных дробей (3,5 + 2,5), обыкновенных дробей (1/2, 1/4, 3/4) и времени (14:30)."""
    from app.services.tts_service import build_ssml

    # 1. Десятичные дроби в русском тексте: 3,5 + 2,5
    ru_dec = prepare_speech_text("Сложи десятичные дроби: 3,5 + 2,5 = 6.", is_russian_context=True)
    assert "три целых пять десятых" in ru_dec or "3 запятая 5" in ru_dec
    assert "две целых пять десятых" in ru_dec or "2 запятая 5" in ru_dec
    assert "плюс" in ru_dec
    assert "3 , 5" not in ru_dec

    # Десятичные дроби и знаки в эстонском режиме: 3,5 + 2,5 = 6 -> koma, pluss, võrdub
    et_dec = normalize_text_for_estonian_tts("3,5 + 2,5 = 6", verbalize_math_signs=True)
    assert "3 koma 5 pluss 2 koma 5 võrdub 6" in et_dec
    et_ssml = build_ssml("3,5 + 2,5 = 6 ja 10 - 4 = 6", voice=ESTONIAN_VOICE)
    assert "koma" in et_ssml and "pluss" in et_ssml and "miinus" in et_ssml and "võrdub" in et_ssml

    # 2. Обыкновенные дроби (не превращаются в союз «или»)
    ru_frac = prepare_speech_text("Возьми 1/2 пирога, 1/4 яблока и 3/4 стакана.", is_russian_context=True)
    assert "одна вторая" in ru_frac
    assert "одна четвертая" in ru_frac
    assert "три четвертых" in ru_frac
    assert " или " not in ru_frac

    et_frac = normalize_text_for_estonian_tts("Lisa 1/2 liitrit, 1/4 teelusikat ja 3/4 klaasi.")
    assert "üks kahendik" in et_frac
    assert "üks neljandik" in et_frac
    assert "kolm neljandikku" in et_frac
    assert "jagatud" not in et_frac

    # 3. Время 14:30 (не разрывается пробелами вокруг двоеточия и не озвучивается как деление)
    ru_time = prepare_speech_text("Урок начинается в 14:30.", is_russian_context=True)
    assert "четырнадцать тридцать" in ru_time or "14:30" in ru_time
    assert "14 : 30" not in ru_time
    assert "разделить" not in ru_time.lower()

    et_time = normalize_text_for_estonian_tts("Tund algab kell 14:30.")
    assert "14:30" in et_time
    assert "14 : 30" not in et_time
    assert "jagatud" not in et_time

    et_time_ssml = build_ssml("Tund algab kell 14:30.", voice=ESTONIAN_VOICE)
    assert '<say-as interpret-as="time" format="hm24">14:30</say-as>' in et_time_ssml


def test_estonian_area_volume_units_and_ordinals():
    """P1.3: Единицы площади/объёма (25 m² -> ruutmeetrit, cm³ -> kuupsentimeetrit) и порядковые > 12 (15. harjutus)."""
    from app.services.tts_service import build_ssml

    # Единицы площади и объёма с учётом числа (1 vs >1)
    assert normalize_text_for_estonian_tts("Pindala on 25 m².") == "Pindala on 25 ruutmeetrit"
    assert normalize_text_for_estonian_tts("Pindala on 1 m².") == "Pindala on 1 ruutmeeter"
    assert normalize_text_for_estonian_tts("Ruumala on 10 cm³.") == "Ruumala on 10 kuupsentimeetrit"

    # Порядковые числительные > 12: 15. harjutus -> <say-as interpret-as="ordinal">15</say-as>
    ord_ssml = build_ssml("Ava 15. harjutus ja loe.", voice=ESTONIAN_VOICE)
    assert '<say-as interpret-as="ordinal">15</say-as> harjutus' in ord_ssml

    # Количественное числительное в конце предложения не становится порядковым
    card_ssml = build_ssml("Vastus on 15.", voice=ESTONIAN_VOICE)
    assert 'interpret-as="ordinal"' not in card_ssml


def test_znakom_homograph_and_chemical_formulas():
    """P1.3: Контекстный омограф «со зна́ком» vs «знако́м с темой» и исключение формул (CO2) из <est>."""
    from app.services.tts_service import build_ssml

    # Омограф «знаком»
    sign_res = prepare_speech_text("Число со знаком минус стоит перед скобкой.", is_russian_context=True)
    topic_res = prepare_speech_text("Ты уже хорошо знаком с темой дробей.", is_russian_context=True)

    assert "со зна\u0301ком" in sign_res
    assert "знако\u0301м с темой" in topic_res
    assert "зна\u0301ком с темой" not in topic_res

    ssml_both = build_ssml("Ты уже знаком с темой чисел со знаком минус.", voice=DEFAULT_VOICE, bilingual=True)
    assert "знако\u0301м" in ssml_both
    assert "зна\u0301ком" in ssml_both

    # Химические формулы (CO2), (H2O) НЕ должны тегироваться как <est> или уходить в эстонский голос
    chem_text = "Растения поглощают углекислый газ (CO2) и воду (H2O)."
    tagged_chem = auto_tag_estonian_phrases(chem_text)
    assert "<est>" not in tagged_chem

    segments = parse_bilingual_segments(chem_text)
    est_segments = [seg for seg, voice in segments if voice == ESTONIAN_VOICE]
    assert est_segments == [], f"Unexpected Estonian segments for chemical formulas: {est_segments}"

    # Градусы Цельсия и знаки неравенств (<, >)
    temp_res = prepare_speech_text("Зимой температура опустилась до -5 °C, а -5 < 0 и 5 > 3.", is_russian_context=True)
    assert "минус пять градусов Цельсия" in temp_res
    assert "меньше" in temp_res
    assert "больше" in temp_res


def test_idempotency_ssml_breaks_and_compact_schema():
    """P0.3, P0.4, P1.1, P1.2: Идемпотентность нормализации, отсутствие двойных <break/>, короткие MP3 и схема Gemini."""
    import time
    from starlette.requests import Request
    from app.limiter import get_device_or_ip
    from app.services.tts_service import build_ssml, is_valid_mp3_buffer, MIN_VALID_AUDIO_BYTES
    from app.models.page_analysis import GeminiPageAnalysisSchema, PageAnalysisResponse, VocabularyItem

    # 1. Строгая идемпотентность prepare_speech_text
    raw = "Привет! В Roblox температура -5 °C, 3,5 + 1/2, время 14:30, со знаком плюс, знаком с темой (CO2)."
    once = prepare_speech_text(raw, is_russian_context=True)
    twice = prepare_speech_text(once, is_russian_context=True)
    assert once == twice

    # 2. Отсутствие дублирующихся <break/> перед закрывающим </lang></voice>
    ssml = build_ssml("Переведи слово <est>kass, koer.</est> и ответь.", voice=DEFAULT_VOICE, bilingual=True)
    assert '<break time="250ms" /></lang></voice><break' not in ssml
    assert "kass," in ssml and '<break time="250ms" />' in ssml

    # 3. Порог валидации MP3 снижен до 800 байт с проверкой заголовка ID3 / 0xFF
    assert MIN_VALID_AUDIO_BYTES == 800
    short_valid_mp3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + (b"\xff\xfb\x90\x44" * 210)
    assert 800 <= len(short_valid_mp3) < 4096
    assert is_valid_mp3_buffer(short_valid_mp3) is True
    assert is_valid_mp3_buffer(b"NOT_MP3" * 200) is False
    assert is_valid_mp3_buffer(b"ID3" + b"\x00" * 100) is False

    # 4. Ключ рейт-лимитера SlowAPI связывает IP и device_id: f"{ip}:{device_id}"
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/voice/tts",
        "headers": [(b"x-device-id", b"dev-abc-123")],
        "query_string": b"",
        "client": ("203.0.113.10", 54321),
    }
    req = Request(scope)
    assert get_device_or_ip(req) == "203.0.113.10:dev-abc-123"

    # 5. GeminiPageAnalysisSchema содержит поля речевого слоя, но не контейнер speech_layer
    schema_props = GeminiPageAnalysisSchema.model_json_schema().get("properties", {})
    assert "speech_layer" not in schema_props
    assert "voice_prompt_script_speech" in schema_props
    assert "theme_explanation_speech" in schema_props

    # А PageAnalysisResponse детерминированно заполняет speech_layer менее чем за 5 мс
    t0 = time.perf_counter()
    parsed = PageAnalysisResponse(
        task_title="Дроби",
        theme_explanation="Складываем 3,5 + 2,5 в игре Roblox.",
        vocabulary=[VocabularyItem(est="murrud", ru="дроби", example="Harjutus 15. harjutus")],
        how_to_answer="1. Запиши число со знаком плюс.",
        answer_template="Vastus on [6].",
        voice_prompt_script="Привет! Ты уже знаком с темой!",
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert elapsed_ms < 20.0
    assert parsed.speech_layer is not None
    assert "Ро\u0301блокс" in parsed.speech_layer.theme_explanation
    assert "три целых пять десятых" in parsed.speech_layer.theme_explanation
    assert "знако\u0301м" in parsed.speech_layer.voice_prompt_script
    assert "со зна\u0301ком" in parsed.speech_layer.how_to_answer


def test_voice_endpoint_auth_500_sanitization_and_inflight_cleanup(monkeypatch):
    """P0.2 & P0.3: Изолированная без-сокетная проверка очистки _IN_FLIGHT_TASKS, device_id и отсутствия утечки str(e)."""
    import asyncio
    from unittest.mock import patch
    from fastapi import HTTPException
    from starlette.requests import Request
    from app.database import SessionLocal
    from app.routers.voice import verify_voice_device_access, text_to_speech
    from app.services import tts_service

    def _drive_coro_no_sockets(coro):
        try:
            while True:
                coro.send(None)
        except StopIteration as stop:
            return stop.value

    class _SyncTask:
        def __init__(self, coro):
            self._exc = None
            self._res = None
            try:
                self._res = _drive_coro_no_sockets(coro)
            except BaseException as exc:
                self._exc = exc

        def done(self):
            return True

        def add_done_callback(self, cb):
            cb(self)

        def __await__(self):
            if False:
                yield None
            if self._exc is not None:
                raise self._exc
            return self._res

    async def _fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    async def _fake_wait_for(aw, timeout=None):
        return await aw

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(asyncio, "wait_for", _fake_wait_for)
    monkeypatch.setattr(asyncio, "shield", lambda aw: aw)
    monkeypatch.setattr(asyncio, "create_task", lambda c: _SyncTask(c))

    # 1. Гарантированная очистка _IN_FLIGHT_TASKS при исключении синтеза (исключает вечный дедлок)
    tts_service._IN_FLIGHT_TASKS.clear()
    tts_service._TTS_STREAM_CACHE.clear()

    def failing_synth(ssml: str) -> bytes:
        raise RuntimeError("INTERNAL_AZURE_SECRET_KEY_FAILURE_XYZ")

    monkeypatch.setattr(tts_service, "_synthesize_azure_ssml", failing_synth)

    with pytest.raises(RuntimeError):
        _drive_coro_no_sockets(
            tts_service.get_or_synthesize_audio("Тест очистки дедлока уник 991", voice=DEFAULT_VOICE)
        )

    assert len(tts_service._IN_FLIGHT_TASKS) == 0, "_IN_FLIGHT_TASKS must be cleaned up in finally!"

    # 2. HTTP 500 на /api/v1/voice/tts НЕ должен раскрывать внутренний текст исключения str(e)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/voice/tts",
        "headers": [(b"x-device-id", b"test-dev-1")],
        "query_string": b"text=%D0%9F%D1%80%D0%B8%D0%B2%D0%B5%D1%82&lang=ru",
        "client": ("127.0.0.1", 50000),
    }
    req = Request(scope)
    with pytest.raises(HTTPException) as exc_info:
        _drive_coro_no_sockets(
            text_to_speech(
                request=req,
                text="Тест маскировки ошибки 992",
                lang="ru",
                bilingual=False,
                grade=None,
                tier=None,
            )
        )
    assert exc_info.value.status_code == 500
    assert "INTERNAL_AZURE_SECRET_KEY_FAILURE_XYZ" not in str(exc_info.value.detail)

    # 3. В production отсутствующий или незарегистрированный device_id блокируется с HTTP 403
    db = SessionLocal()
    try:
        with patch("app.config.settings.APP_ENV", "production"):
            with pytest.raises(HTTPException) as missing_exc:
                _drive_coro_no_sockets(verify_voice_device_access(device_id=None, x_device_id=None, db=db))
            assert missing_exc.value.status_code == 403

            with pytest.raises(HTTPException) as unreg_exc:
                _drive_coro_no_sockets(
                    verify_voice_device_access(device_id="unknown-bot-device-999", x_device_id=None, db=db)
                )
            assert unreg_exc.value.status_code == 403
    finally:
        db.close()


def test_russian_math_nominative_stresses():
    """Тест 15: Проверка именит. падежа и ударений в русской арифметике (4 · 5 = 20 -> четы́ре ... два́дцать)."""
    res = prepare_speech_text("4 · 5 = 20", is_russian_context=True)
    assert "четы́ре" in res or "четы\u0301ре" in res
    assert "два́дцать" in res or "два\u0301дцать" in res
    assert "четырёх" not in res and "четырех" not in res
    assert "двадцати" not in res
    assert "умно́жить" in res or "умно\u0301жить" in res


def test_estonian_units_mid_sentence_and_pirne():
    """Тест 16: Нормализация единиц измерения перед словами в эстонском тексте (20 kg pirne -> 20 kilogrammi pirne)."""
    res = normalize_text_for_estonian_tts("20 kg pirne")
    assert res == "20 kilogrammi pirne"

    res_single = normalize_text_for_estonian_tts("1 kg pirne")
    assert res_single == "1 kilogramm pirne"

    res_km = normalize_text_for_estonian_tts("15 km teed")
    assert res_km == "15 kilomeetrit teed"


def test_estonian_pure_sentence_no_raw_kg():
    """Тест 17: Полное предложение на эстонском через prepare_speech_text не должно содержать сырого сокращения kg."""
    res = prepare_speech_text("Kauplusesse toodi 20 kg pirne.")
    assert "kilogrammi" in res
    # Проверяем отсутствие отдельного токена "kg"
    tokens = [t.strip(".,!?:;") for t in res.split()]
    assert "kg" not in tokens
    assert "kg." not in res


def test_pydantic_empty_steps_filtration():
    """Тест 18: Фильтрация пустых шагов в Pydantic моделях и отсутствие лишних порядковых номеров в речи."""
    from app.models.page_analysis import SelfSolveGuide, WorkedExample, PageAnalysisResponse
    from app.services.tts_normalizer import prepare_worked_example_speech

    guide = SelfSolveGuide(
        steps=["Шаг 1", "", "   ", "Шаг 2"],
        guided_steps=["Подсказка 1", "", "Подсказка 2"],
        actions=["", "Действие 1", "  "]
    )
    assert guide.steps == ["Шаг 1", "Шаг 2"]
    assert guide.guided_steps == ["Подсказка 1", "Подсказка 2"]
    assert guide.actions == ["Действие 1"]

    we = WorkedExample(
        given="Условие",
        steps=["Шаг 1", "", "   ", "Шаг 2"],
        solution="Решение",
        answer="Ответ"
    )
    assert we.steps == ["Шаг 1", "Шаг 2"]

    speech = prepare_worked_example_speech(we)
    assert "Первое" in speech and ("Шаг 1" in speech or "Первый шаг" in speech)
    assert "Второе" in speech and ("Шаг 2" in speech or "Второй шаг" in speech)
    assert "Третье" not in speech
    assert "Четвертое" not in speech
    assert "Третий шаг" not in speech



