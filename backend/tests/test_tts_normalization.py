import pytest
from app.services.tts_service import (
    DEFAULT_VOICE,
    ESTONIAN_VOICE,
    normalize_text_for_estonian_tts,
    normalize_roman_numerals,
    normalize_math_expressions,
    normalize_text_for_speech,
    parse_bilingual_segments,
)

def test_normalize_crosses_and_multiplication():
    # Eliminates crosses and multiplication symbols
    assert normalize_text_for_estonian_tts("12 \u00d7 2") == "12 2"
    assert normalize_text_for_estonian_tts("12 \u2715") == "12"
    assert normalize_text_for_estonian_tts("12 \u2716") == "12"
    assert normalize_text_for_estonian_tts("12 * 2") == "12 2"

def test_normalize_brackets():
    # Eliminates brackets and braces
    assert normalize_text_for_estonian_tts("[12]") == "12"
    assert normalize_text_for_estonian_tts("Vastus on [12].") == "Vastus on 12"

def test_normalize_dot_after_integer_prevents_ordinal():
    # 12. -> 12 so that cardinal kaksteist is spoken instead of ordinal kaheteistkumnes
    assert normalize_text_for_estonian_tts("Vastus on 12.") == "Vastus on 12"
    assert normalize_text_for_estonian_tts("Minul on 12.") == "Minul on 12"
    assert normalize_text_for_estonian_tts("12.") == "12"
    assert normalize_text_for_estonian_tts("12 .") == "12"

def test_normalize_punctuation_in_contact():
    # Separates punctuation in direct contact with digits
    assert normalize_text_for_estonian_tts("12,") == "12 ,"
    assert normalize_text_for_estonian_tts("12!") == "12 !"
    assert normalize_text_for_estonian_tts("12?") == "12 ?"
    assert normalize_text_for_estonian_tts("12-ne") == "12 ne"


def test_estonian_numeral_case_suffixes_preserve_hyphen():
    # Preserves hyphens for Estonian numeral case endings so Edge-TTS inflects the numeral (e.g. 5-ga -> viiega)
    assert normalize_text_for_estonian_tts("Korruta 5-ga") == "Korruta 5-ga"
    assert normalize_text_for_estonian_tts("Loenda 10-ni") == "Loenda 10-ni"
    assert normalize_text_for_estonian_tts("Lahuta 3-st") == "Lahuta 3-st"
    assert normalize_text_for_estonian_tts("Liida 2-le") == "Liida 2-le"
    assert normalize_text_for_estonian_tts("4-lt ja 1-sse") == "4-lt ja 1-sse"
    assert normalize_text_for_estonian_tts("5-s, 6-l, 7-ks, 8-na, 9-ta") == "5-s, 6-l, 7-ks, 8-na, 9-ta"
    # En-dash before case suffix is normalized to standard hyphen
    assert normalize_text_for_estonian_tts("Korruta 5–ga") == "Korruta 5-ga"
    # Numeric range still separates dashes
    assert normalize_text_for_estonian_tts("10-12") == "10 12"

def test_empty_string():
    assert normalize_text_for_estonian_tts("") == ""
    assert normalize_text_for_estonian_tts("   ") == ""


# --- Тесты нормализации римских цифр и математических выражений ---

def test_roman_numerals_normalization():
    text = "В XXI веке и в III тысячелетии ученые открыли..."
    norm = normalize_text_for_speech(text)
    assert norm == "В двадцать первом веке и в третьем тысячелетии ученые открыли..."

    # Проверка полной озвучки русским голосом без ошибочного разделения
    segments = parse_bilingual_segments(text)
    assert len(segments) == 1
    assert segments[0][1] == DEFAULT_VOICE
    assert "двадцать первом веке" in segments[0][0]
    assert "третьем тысячелетии" in segments[0][0]


def test_math_expressions_normalization():
    text = "Чему равен x, если x + y = 15?"
    norm = normalize_text_for_speech(text)
    assert norm == "Чему равен икс, если икс плюс игрек равно 15?"

    # Проверка озвучки русским голосом
    segments = parse_bilingual_segments(text)
    assert len(segments) == 1
    assert segments[0][1] == DEFAULT_VOICE
    assert "икс плюс игрек равно 15" in segments[0][0]


def test_estonian_vocabulary_preserved():
    # Чистый эстонский текст не должен ломаться и озвучивается эстонским диктором
    est_sample = "üks"
    segments = parse_bilingual_segments(est_sample)
    assert len(segments) == 1
    assert segments[0][1] == ESTONIAN_VOICE
    assert segments[0][0] == "üks"

    est_sample2 = "kass"
    segments2 = parse_bilingual_segments(est_sample2)
    assert len(segments2) == 1
    assert segments2[0][1] == ESTONIAN_VOICE
    assert segments2[0][0] == "kass"


def test_russian_ordinals_with_dot():
    text = "Ребенок учится в 4. классе и делает 2. задание."
    norm = normalize_text_for_speech(text)
    assert norm == "Ребенок учится в четвертом классе и делает второе задание."

    segments = parse_bilingual_segments(text)
    assert len(segments) == 1
    assert segments[0][1] == DEFAULT_VOICE
    assert segments[0][0] == "Ребенок учится в четвертом классе и делает второе задание."


def test_estonian_ordinals_with_dot():
    # 4. klassis -> neljandas klassis
    text = "Ta õpib 4. klassis."
    norm = normalize_text_for_estonian_tts(text)
    assert norm == "Ta õpib neljandas klassis."

    # Harjutus 5. -> Harjutus 5
    assert normalize_text_for_estonian_tts("Harjutus 5.") == "Harjutus 5"
    assert normalize_text_for_estonian_tts("1. klass") == "esimene klass"
    assert normalize_text_for_estonian_tts("2. harjutus") == "teine harjutus"
    assert normalize_text_for_estonian_tts("2. ülesandes") == "teises ülesandes"


def test_list_numbering_dot_removal():
    text = "1. Сложи числа\n2. Запиши ответ"
    norm = normalize_text_for_speech(text)
    assert "1." not in norm
    assert "2." not in norm
    assert "Первое, Сложи числа" in norm
    assert "Второе, Запиши ответ" in norm


def test_math_division_colon_and_symbols():
    # 15 : 3 = 5 -> 15 разделить на 3 равно 5 (вместо 'соотношение')
    assert normalize_math_expressions("15 : 3 = 5") == "15 разделить на 3 равно 5"
    assert normalize_math_expressions("24:6") == "24 разделить на 6"
    assert normalize_math_expressions("x : 2 = 10") == "икс разделить на 2 равно 10"
    assert normalize_math_expressions("15 ÷ 3 = 5") == "15 разделить на 3 равно 5"

    # Словесное описание знака деления
    assert "знак «разделить»" in normalize_math_expressions("Посмотри на знак : в примере")

    # Сохранение стандартного времени (14:30 не превращается в деление)
    assert "14:30" in normalize_math_expressions("Встреча в 14:30")


def test_numbered_examples_and_steps_ordinal():
    # Пример 1, Пример 2 -> Первый пример, Второй пример
    text = "Пример 1: 15 : 3 = 5\nПример 2: 24 : 6 = 4"
    norm = normalize_text_for_speech(text)
    assert "Первый пример, 15 разделить на 3 равно 5" in norm
    assert "Второй пример, 24 разделить на 6 равно 4" in norm

    # Скобочная нумерация: 1), 2)
    text_paren = "1) 15 : 3 = 5\n2) 20 : 4 = 5"
    norm_paren = normalize_text_for_speech(text_paren)
    assert "Первое, 15 разделить на 3 равно 5" in norm_paren
    assert "Второе, 20 разделить на 4 равно 5" in norm_paren

    # Шаги решения с двоеточием перед списком
    text_steps = "Шаги решения: 1. Вычисли 15 : 3\n2. Запиши ответ"
    norm_steps = normalize_text_for_speech(text_steps)
    assert "Шаги решения, Первое, Вычисли 15 разделить на 3" in norm_steps
    assert "Второе, Запиши ответ" in norm_steps


def test_colon_not_mistaken_for_division_in_lists_and_parentheses():
    from app.services.tts_service import parse_bilingual_segments, build_ssml

    # Случай из баг-репорта: (sadad): 4 сотни
    text = "Смотрим на верхний узелок — это сотни (sadad): 4 сотни."
    norm = normalize_text_for_speech(text)
    assert "разделить" not in norm
    assert "sadad), 4 сотни" in norm

    # Сегменты для дикторов: sadad отправляется эстонскому диктору, а остальной текст - русскому
    segs = parse_bilingual_segments(text)
    for seg_text, voice in segs:
        assert "разделить" not in seg_text

    # Прямая речь и списки: "Учитель спрашивает: 4 сотни"
    teacher_text = "Учитель спрашивает: 4 сотни ребят пришли в школу."
    teacher_norm = normalize_text_for_speech(teacher_text)
    assert "разделить" not in teacher_norm
    assert "Учитель спрашивает, 4 сотни" in teacher_norm


# --- Тесты сквозной нормализации TTS: ударения, ё, слэш и эстонские числительные ---

def test_russian_accents_and_yo_normalization():
    from app.services.tts_service import normalize_russian_accents_and_yo

    # 1. Восстановление 'ё'
    assert normalize_russian_accents_and_yo("еще не все готово") == "ещё не всё готово"
    assert normalize_russian_accents_and_yo("счет со счета") == "счёт со счёта"
    assert normalize_russian_accents_and_yo("четный и нечетный") == "чётный и нечётный"
    assert normalize_russian_accents_and_yo("перенес объем трех и четырех") == "перенёс объём трёх и четырёх"
    assert normalize_russian_accents_and_yo("вот и все") == "вот и всё"
    assert normalize_russian_accents_and_yo("прежде всего") == "прежде всего"

    # 2. ПОЛНОЕ УДАЛЕНИЕ принудительных знаков ударения (\u0301) — нейросеть Azure Лия знает ударения сама
    norm = normalize_russian_accents_and_yo("Мы вычитаем и складываем слагаемое.")
    assert "\u0301" not in norm
    assert "вычитаем" in norm
    assert "слагаемое" in norm

    norm_math = normalize_russian_accents_and_yo("Сложение, вычитание, умножение и деление: делитель и делимое.")
    assert "\u0301" not in norm_math
    assert "Сложение" in norm_math
    assert "вычитание" in norm_math
    assert "умножение" in norm_math
    assert "деление" in norm_math
    assert "делитель" in norm_math
    assert "делимое" in norm_math

    norm_study = normalize_russian_accents_and_yo("Разбираем пример, смотрим правило и пишем ответ.")
    assert "\u0301" not in norm_study
    assert "Разбираем" in norm_study
    assert "пример" in norm_study
    assert "правило" in norm_study
    assert "ответ" in norm_study


def test_slash_normalization():
    from app.services.tts_service import clean_text_for_speech, build_ssml

    # В русском тексте '/' заменяется на ' или '
    text_ru = "Сложение/вычитание чисел: шаг 1 / шаг 2"
    cleaned = clean_text_for_speech(text_ru)
    assert "Сложение или вычитание" in cleaned
    assert "шаг 1 или шаг 2" in cleaned
    assert "/" not in cleaned

    # В SSML русском блоке слэш озвучивается как 'или' (без принудительного знака ударения \u0301)
    ssml_ru = build_ssml("Сложение/вычитание")
    assert "Сложение или вычитание" in ssml_ru
    assert "Сложение/вычитание" not in ssml_ru
    assert "\u0301" not in ssml_ru

    # В эстонском блоке слэш заменяется на 'või'
    ssml_est = build_ssml("leib/sai", voice="et-EE")
    assert "leib või sai" in ssml_est
    assert "leib/sai" not in ssml_est


def test_number_ranges_normalization():
    from app.services.tts_service import normalize_number_ranges, normalize_text_for_speech

    assert normalize_number_ranges("1-9") == "от 1 до 9"
    assert normalize_number_ranges("выбери числа 1-10") == "выбери числа от 1 до 10"
    assert normalize_number_ranges("страницы 10-20") == "страницы от 10 до 20"
    # Математические выражения с вычитанием не должны превращаться в диапазоны
    assert normalize_number_ranges("9 - 3 = 6") == "9 - 3 = 6"

    # В сквозном пайплайне
    assert "от 1 до 9" in normalize_text_for_speech("выбери числа 1-9")


def test_math_subtraction_minus():
    from app.services.tts_service import normalize_math_expressions

    norm = normalize_math_expressions("9 - 3 = 6")
    assert "9 минус 3 равно 6" in norm


def test_ssml_unified_multilingual_document():
    from app.services.tts_service import build_ssml
    import xml.etree.ElementTree as ET

    text = "Смотрим на термин liidetav и summa: мы играем в Minecraft с клавишами WASD."
    ssml = build_ssml(text)

    # Единый голос SvetlanaNeural
    assert "ru-RU-SvetlanaNeural" in ssml or "ru-RU-SvetlanaMultilingualNeural" in ssml
    # Эстонские термины в voice et-EE-AnuNeural
    assert '<voice name="et-EE-AnuNeural">liidetav</voice>' in ssml
    assert '<voice name="et-EE-AnuNeural">summa</voice>' in ssml
    # Английские бренды в <lang xml:lang="en-US">
    assert '<lang xml:lang="en-US">Minecraft</lang>' in ssml
    # Клавиши в <say-as interpret-as="characters">
    assert '<say-as interpret-as="characters">W A S D</say-as>' in ssml
    # Никаких знаков ударения \u0301
    assert "\u0301" not in ssml

    # Валидность XML
    root = ET.fromstring(ssml)
    assert root.tag.endswith("speak")


def test_estonian_numerals_ssml_cardinal():
    from app.services.tts_service import build_ssml

    # Эстонские числа оборачиваются в <say-as interpret-as="cardinal">
    ssml = build_ssml("Harjutus 10. Loe lehekülg 4.", voice="et-EE")
    assert '<say-as interpret-as="cardinal">10</say-as>' in ssml
    assert '<say-as interpret-as="cardinal">4</say-as>' in ssml

    # Числительные с падежными окончаниями через дефис (5-ga) не ломаются
    ssml_case = build_ssml("Korruta 5-ga ja liida 2-le.", voice="et-EE")
    assert "5-ga" in ssml_case
    assert "2-le" in ssml_case
    assert '<say-as interpret-as="cardinal">5-ga</say-as>' not in ssml_case




def test_homograph_shaga_accent():
    from app.services.tts_service import normalize_russian_accents_and_yo, build_ssml

    # Омограф «ша́га»: устойчивые выражения сохраняют явное ударение \u0301 на 'а'
    res_dva = normalize_russian_accents_and_yo("Решение в два шага")
    assert "в два ша\u0301га" in res_dva

    res_tri = normalize_russian_accents_and_yo("Сделай за три шага")
    assert "за три ша\u0301га" in res_tri

    res_num = normalize_russian_accents_and_yo("за 2 шага")
    assert "за два ша\u0301га" in res_num

    ssml = build_ssml("Решение задачи в два шага.")
    assert "в два ша\u0301га" in ssml


def test_isolated_digits_and_math_nominative():
    from app.services.tts_service import normalize_text_for_speech, normalize_math_expressions

    # «4 и 3» -> именительный падеж «четыре и три» вместо ошибочного родительного («четырёх и трёх»)
    assert "четыре и три" in normalize_text_for_speech("Нужно складывать 4 и 3")
    assert "четыре и три" in normalize_math_expressions("4 и 3")

    # «9 + 3» -> именительный падеж «девять плюс три»
    assert "девять плюс три" in normalize_math_expressions("9 + 3")
    assert "девять плюс три" in normalize_text_for_speech("Пример: 9 + 3")
