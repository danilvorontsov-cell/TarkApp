import pytest
from app.services.tts_service import (
    parse_bilingual_segments,
    build_ssml,
    clean_text_for_speech,
    DEFAULT_VOICE,
    ESTONIAN_VOICE,
)

def test_parse_est_tags():
    segments = parse_bilingual_segments('Запомни слово <est>ohutus</est> и повтори <est>tere</est>.')
    assert len(segments) == 4
    assert segments[0] == ('Запомни слово', DEFAULT_VOICE)
    assert segments[1] == ('ohutus', ESTONIAN_VOICE)
    assert segments[2] == ('и повтори', DEFAULT_VOICE)
    assert segments[3] == ('tere', ESTONIAN_VOICE)

def test_parse_parentheses_with_est_tags():
    segments = parse_bilingual_segments('на уроке природоведения (<est>loodusõpetus</est>).')
    assert len(segments) == 2
    assert segments[0] == ('на уроке природоведения', DEFAULT_VOICE)
    assert segments[1] == ('loodusõpetus', ESTONIAN_VOICE)

def test_parse_multi_est_tags():
    segments = parse_bilingual_segments('забирают воду (<est>vesi</est>) и углекислый газ (<est>süsihappegaas</est>).')
    assert any(s[0] == 'vesi' and s[1] == ESTONIAN_VOICE for s in segments)
    assert any(s[0] == 'süsihappegaas' and s[1] == ESTONIAN_VOICE for s in segments)

def test_parse_slash_in_est_tag():
    segments = parse_bilingual_segments('на уроке (<est>loodusõpetus / eesti keel</est>).')
    assert any('loodusõpetus' in s[0] and s[1] == ESTONIAN_VOICE for s in segments)

def test_parse_standalone_latin_word():
    # Without <est> tags, bare Latin words stay with Russian multilingual voice without chopping
    segments_no_tag = parse_bilingual_segments('Запиши результат — это и будет summa.')
    assert len(segments_no_tag) == 1
    assert segments_no_tag[0][1] == DEFAULT_VOICE

    # With <est> tag, Estonian term is cleanly extracted for Estonian voice
    segments_tagged = parse_bilingual_segments('Запиши результат — это и будет <est>summa</est>.')
    assert any(s[0] == 'summa' and s[1] == ESTONIAN_VOICE for s in segments_tagged)

def test_minecraft_and_est_tag_segmentation():
    # "Давай построим в Minecraft <est>maja</est>"
    # - "Давай построим в Minecraft" -> ru-RU-SvetlanaMultilingualNeural
    # - "maja" -> et-EE-AnuNeural
    text = "Давай построим в Minecraft <est>maja</est>"
    segments = parse_bilingual_segments(text)
    assert len(segments) == 2
    assert segments[0] == ("Давай построим в Minecraft", DEFAULT_VOICE)
    assert segments[1] == ("maja", ESTONIAN_VOICE)
    assert DEFAULT_VOICE == "ru-RU-SvetlanaMultilingualNeural"

def test_multiple_english_brands_no_tags_stay_intact():
    # Without <est> tags, text with multiple English terms (Minecraft, Roblox, YouTube, W/A/S/D) is not chopped
    text = "Сегодня мы играем в Minecraft и Roblox на клавишах W, A, S, D, а потом смотрим гайд на YouTube."
    segments = parse_bilingual_segments(text)
    assert len(segments) == 1
    assert segments[0][1] == DEFAULT_VOICE
    assert "Minecraft" in segments[0][0]
    assert "Roblox" in segments[0][0]
    assert "YouTube" in segments[0][0]
    assert "W, A, S, D" in segments[0][0]

def test_russian_in_parentheses_stays_russian():
    segments = parse_bilingual_segments('Сложи два числа (первое и второе).')
    assert all(s[1] == DEFAULT_VOICE for s in segments)

def test_mixed_russian_estonian_in_parentheses_and_quotes():
    segments = parse_bilingual_segments('Запомни термин (по-эстонски: <est>liidetav</est>) и правило.')
    est_segments = [s[0] for s in segments if s[1] == ESTONIAN_VOICE]
    ru_segments = [s[0] for s in segments if s[1] == DEFAULT_VOICE]
    assert est_segments == ['liidetav']
    assert any('по-эстонски' in r for r in ru_segments)

    segments_quotes = parse_bilingual_segments('В учебнике написано «Слагаемое — <est>liidetav</est>».')
    est_q = [s[0] for s in segments_quotes if s[1] == ESTONIAN_VOICE]
    ru_q = [s[0] for s in segments_quotes if s[1] == DEFAULT_VOICE]
    assert est_q == ['liidetav']
    assert any('Слагаемое' in r for r in ru_q)

def test_pure_estonian_example_with_brand_in_est_tag():
    # Если приводится пример чисто на эстонском языке, оборачивается всё предложение:
    text = "Пример предложения: <est>Ta mängib Minecrafti mängu</est>."
    segments = parse_bilingual_segments(text)
    assert len(segments) == 2
    assert segments[0] == ("Пример предложения:", DEFAULT_VOICE)
    assert segments[1] == ("Ta mängib Minecrafti mängu", ESTONIAN_VOICE)

def test_pure_estonian_without_cyrillic():
    # Чистый эстонский термин без кириллицы (например, одиночное слово из словаря)
    segments = parse_bilingual_segments("kass")
    assert len(segments) == 1
    assert segments[0] == ("kass", ESTONIAN_VOICE)


def test_estonian_term_in_parentheses_without_tag():
    text = "Каждая кнопка (klahv) здесь работает как микропереключатель."
    segments = parse_bilingual_segments(text)
    assert len(segments) == 3
    assert segments[0] == ("Каждая кнопка", DEFAULT_VOICE)
    assert segments[1] == ("klahv", ESTONIAN_VOICE)
    assert segments[2] == ("здесь работает как микропереключатель", DEFAULT_VOICE)

def test_estonian_quote_in_given_condition():
    text = "Учитель на уроке спрашивает: 'Mis seade see on ja milleks sa seda kasutad?'"
    segments = parse_bilingual_segments(text)
    assert len(segments) == 2
    assert segments[0] == ("Учитель на уроке спрашивает:", DEFAULT_VOICE)
    assert segments[1] == ("Mis seade see on ja milleks sa seda kasutad?", ESTONIAN_VOICE)

def test_estonian_russian_pair_in_parentheses():
    text = "Перед нами крутая игровая клавиатура (<est>klaviatuur</est>) с яркой подсветкой!"
    segments = parse_bilingual_segments(text)
    assert len(segments) == 3
    assert segments[0] == ("Перед нами крутая игровая клавиатура", DEFAULT_VOICE)
    assert segments[1] == ("klaviatuur", ESTONIAN_VOICE)
    assert segments[2] == ("с яркой подсветкой!", DEFAULT_VOICE)


def test_build_ssml_with_est_tag():
    text = "Привет! Запомни слово <est>klaviatuur</est> и повтори."
    ssml = build_ssml(text)
    assert '<speak version="1.0"' in ssml
    assert 'xml:lang="ru-RU"' in ssml
    assert f'<voice name="{DEFAULT_VOICE}">' in ssml
    assert 'Привет! <break time="500ms" /> Запомни слово' in ssml
    assert f'<voice name="{ESTONIAN_VOICE}">' in ssml
    assert 'klaviatuur' in ssml
    assert 'и повтори. <break time="500ms" />' in ssml


def test_build_ssml_pure_estonian():
    text = "Tere tulemast kooli!"
    ssml = build_ssml(text, voice=ESTONIAN_VOICE)
    assert 'xml:lang="et-EE"' in ssml
    assert f'<voice name="{ESTONIAN_VOICE}">' in ssml
    assert 'Tere tulemast kooli! <break time="500ms" />' in ssml


def test_build_ssml_escapes_special_characters():
    text = "Знаки & формулы <est>tere & aed</est>"
    ssml = build_ssml(text)
    assert "&amp;" in ssml
    assert "&lt;" not in ssml.split("<speak>")[0]


def test_clean_text_for_speech_sanitization():
    # Стрелки -> затем, <- -> ранее
    raw = "Шаг 1 -> шаг 2 => шаг 3 ==> финал."
    assert clean_text_for_speech(raw) == "Шаг 1 затем шаг 2 затем шаг 3 затем финал."

    raw_back = "Действие 2 <-- действие 1, шаг <= ранее."
    assert "ранее" in clean_text_for_speech(raw_back)

    # Дедупликация -> затем
    assert clean_text_for_speech("нажми -> затем кнопку") == "нажми затем кнопку"

    # Математические знаки сравнения сохраняются
    math_text = "5 > 3 и 2 < 7, а также 5 <= 10"
    cleaned_math = clean_text_for_speech(math_text)
    assert "5 > 3" in cleaned_math
    assert "2 < 7" in cleaned_math
    assert "меньше или равно" in cleaned_math

    # Очистка Markdown
    md_text = "**Жирный** и *курсив*, `код`, [ссылка](http://test.com) # Заголовок ~тильда~ _подчеркивание_ [список]"
    cleaned_md = clean_text_for_speech(md_text)
    assert "**" not in cleaned_md
    assert "*" not in cleaned_md
    assert "`" not in cleaned_md
    assert "#" not in cleaned_md
    assert "~" not in cleaned_md
    assert "_" not in cleaned_md
    assert "[" not in cleaned_md and "]" not in cleaned_md
    assert "Жирный и курсив, код, ссылка Заголовок тильда подчеркивание список" in cleaned_md


def test_phonetic_replacements_in_clean_text():
    raw = "В игре Minecraft и Roblox нажми Enter, затем Space и Shift, посмотри в Google и на YouTube."
    cleaned = clean_text_for_speech(raw)
    assert "Майнкрафт" in cleaned
    assert "Роблокс" in cleaned
    assert "Энтер" in cleaned
    assert "Пробел" in cleaned
    assert "Шифт" in cleaned
    assert "Гугл" in cleaned
    assert "Ютуб" in cleaned

    # Проверка, что эстонские теги защищены от русской фонетической замены
    est_tag_text = "Игра <est>Minecraft</est> по-эстонски."
    cleaned_est = clean_text_for_speech(est_tag_text)
    assert "<est>Minecraft</est>" in cleaned_est


def test_target_phrase_ssml_pipeline():
    phrase = "В игре Minecraft нажми 5 > 3 -> затем клавишу <est>klaviatuur</est>."
    ssml = build_ssml(phrase)
    assert "Майнкрафт" in ssml
    assert "5 &gt; 3" in ssml
    assert "затем клавишу" in ssml
    assert '<break time="500ms" />' in ssml
    assert f'<voice name="{DEFAULT_VOICE}">' in ssml
    assert f'<voice name="{ESTONIAN_VOICE}">' in ssml
    assert "klaviatuur. <break time=\"500ms\" />" in ssml
