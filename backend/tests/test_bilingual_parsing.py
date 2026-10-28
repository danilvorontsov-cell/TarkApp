import pytest
from app.services.tts_service import parse_bilingual_segments, DEFAULT_VOICE, ESTONIAN_VOICE

def test_parse_quotes():
    segments = parse_bilingual_segments('Запомни слово «ohutus» и повтори «tere».')
    assert len(segments) == 4
    assert segments[0] == ('Запомни слово', DEFAULT_VOICE)
    assert segments[1] == ('ohutus', ESTONIAN_VOICE)
    assert segments[2] == ('и повтори', DEFAULT_VOICE)
    assert segments[3] == ('tere', ESTONIAN_VOICE)

def test_parse_parentheses():
    segments = parse_bilingual_segments('на уроке природоведения (loodusõpetus).')
    assert len(segments) == 2
    assert segments[0] == ('на уроке природоведения', DEFAULT_VOICE)
    assert segments[1] == ('loodusõpetus', ESTONIAN_VOICE)

def test_parse_parentheses_multi_words():
    segments = parse_bilingual_segments('забирают воду (vesi) и углекислый газ (süsihappegaas).')
    assert any(s[0] == 'vesi' and s[1] == ESTONIAN_VOICE for s in segments)
    assert any(s[0] == 'süsihappegaas' and s[1] == ESTONIAN_VOICE for s in segments)

def test_parse_slash_in_parentheses():
    segments = parse_bilingual_segments('на уроке (loodusõpetus / eesti keel).')
    assert any('loodusõpetus' in s[0] and s[1] == ESTONIAN_VOICE for s in segments)

def test_parse_standalone_latin_word():
    segments = parse_bilingual_segments('Запиши результат — это и будет summa.')
    assert any(s[0] == 'summa' and s[1] == ESTONIAN_VOICE for s in segments)

def test_russian_in_parentheses_stays_russian():
    segments = parse_bilingual_segments('Сложи два числа (первое и второе).')
    assert all(s[1] == DEFAULT_VOICE for s in segments)


def test_mixed_russian_estonian_in_parentheses_and_quotes():
    # Russian words inside parentheses/quotes with Estonian terms must NOT be sent to ESTONIAN_VOICE
    segments = parse_bilingual_segments('Запомни термин (по-эстонски: liidetav) и правило.')
    est_segments = [s[0] for s in segments if s[1] == ESTONIAN_VOICE]
    ru_segments = [s[0] for s in segments if s[1] == DEFAULT_VOICE]

    assert est_segments == ['liidetav']
    assert any('по-эстонски' in r for r in ru_segments)
    assert all('по-эстонски' not in e for e in est_segments)

    segments_quotes = parse_bilingual_segments('В учебнике написано «Слагаемое — liidetav».')
    est_q = [s[0] for s in segments_quotes if s[1] == ESTONIAN_VOICE]
    ru_q = [s[0] for s in segments_quotes if s[1] == DEFAULT_VOICE]
    assert est_q == ['liidetav']
    assert any('Слагаемое' in r for r in ru_q)


def test_bilingual_estonian_numeral_case_with_hyphen():
    segments = parse_bilingual_segments('Прочитай задание: «Korruta 5-ga ja loenda 10-ni».')
    est_segments = [s[0] for s in segments if s[1] == ESTONIAN_VOICE]
    assert est_segments == ['Korruta 5-ga ja loenda 10-ni']
