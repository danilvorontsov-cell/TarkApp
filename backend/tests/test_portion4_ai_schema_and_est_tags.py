import threading
import pytest
from app.services import tts_normalizer
from app.services.tts_normalizer import (
    _load_tts_lexicon,
    _LEXICON_LOCK,
    transliterate_isolated_latin_words,
)
from app.services.page_analysis import (
    normalize_est_tags,
    _enforce_est_tags,
    sanitize_answer_template,
    GeminiPageAnalysisSchema,
    PageAnalysisResponse,
)


def test_load_tts_lexicon_threading_lock():
    """Verifies that _load_tts_lexicon is protected by a threading.Lock."""
    assert isinstance(_LEXICON_LOCK, type(threading.Lock()))

    # Concurrent invocations should all return identical dictionary without deadlocks
    results = []

    def worker():
        res = _load_tts_lexicon()
        results.append(res)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 10
    assert all(r is results[0] for r in results)


def test_transliterate_isolated_latin_words_protects_est_tags_without_umlauts():
    """
    Verifies that Estonian words without diacritics/umlauts inside <est>...</est> and <et>...</et>
    are NOT transliterated into Cyrillic (e.g. 'kass' remains 'kass', not 'касс').
    Words outside <est> tags in Russian text (e.g. 'Minecraft') are transliterated.
    """
    # 1. Estonian words without umlauts inside <est>...</est>
    text_est = "В предложении слово <est>kass</est> означает кошка, а <est>tere tulemast</est> — добро пожаловать."
    res_est = transliterate_isolated_latin_words(text_est)
    assert "<est>kass</est>" in res_est
    assert "<est>tere tulemast</est>" in res_est
    assert "касс" not in res_est

    # 2. Estonian words inside <et>...</et>
    text_et = "Посмотри на слово <et>kool</et> и <et>arvuti</et>."
    res_et = transliterate_isolated_latin_words(text_et)
    assert "<et>kool</et>" in res_et
    assert "<et>arvuti</et>" in res_et
    assert "коол" not in res_et

    # 3. Mixed: Latin brands outside tags are transliterated, while Estonian inside tags is untouched
    mixed = "Игра <est>kass</est> в Roblox и Minecraft."
    res_mixed = transliterate_isolated_latin_words(mixed)
    assert "<est>kass</est>" in res_mixed
    assert "Майнкрафт" in res_mixed
    assert "блокс" in res_mixed.lower()


def test_normalize_and_enforce_est_tags():
    """
    Verifies that normalize_est_tags and _enforce_est_tags:
    1. Replaces <et> and </et> with <est> and </est>.
    2. Automatically closes an unclosed <est> at the end of a line.
    3. Deletes a dangling orphan </est> without an opening tag.
    """
    # 1. Replace <et> and </et>
    text_et = "See on <et>tere</et> ja teine <et>kool</et>."
    norm_et = normalize_est_tags(text_et)
    assert norm_et == "See on <est>tere</est> ja teine <est>kool</est>."

    # 2. Close unclosed <est> at end of line
    text_unclosed = "Шаг 1: Назови предмет <est>minu käsi\nШаг 2: Teine samm"
    norm_unclosed = normalize_est_tags(text_unclosed)
    expected_unclosed = "Шаг 1: Назови предмет <est>minu käsi</est>\nШаг 2: Teine samm"
    assert norm_unclosed == expected_unclosed

    # 3. Delete dangling orphan </est>
    text_orphan = "Текст без открытия </est> продолжается дальше."
    norm_orphan = normalize_est_tags(text_orphan)
    assert "</est>" not in norm_orphan
    assert norm_orphan == "Текст без открытия  продолжается дальше."

    # 4. _enforce_est_tags applies normalization + Estonian math verbalization
    raw_mixed = "Arvutus: <et>12 + 4 = 16</et> ja <est>kass"
    enf = _enforce_est_tags(raw_mixed)
    assert "<est>" in enf
    assert "</est>" in enf
    assert "<et>" not in enf
    assert "kass</est>" in enf
    # Math inside <est> verbalized (plus -> pluss, võrdub)
    assert "pluss" in enf or "+" not in enf


def test_sanitize_answer_template():
    """
    Verifies that sanitize_answer_template:
    1. Removes empty brackets [] and [  ].
    2. Cuts out Russian explanations in parentheses inside square bracket slots:
       [liidetav (слагаемое)] -> [liidetav].
       [jagaja (делитель)] -> [jagaja].
    3. Handles multiple slots and cleans up extra whitespace.
    """
    # 1. Basic slot with Russian explanation
    sample1 = "Esimene liidetav on [liidetav (слагаемое)], teine liidetav on [liidetav (второе слагаемое)] ja summa on [summa]."
    clean1 = sanitize_answer_template(sample1)
    assert clean1 == "Esimene liidetav on [liidetav], teine liidetav on [liidetav] ja summa on [summa]."

    # 2. Empty brackets removed
    sample2 = "See on [] vastus [5] ja [   ]."
    clean2 = sanitize_answer_template(sample2)
    assert "[]" not in clean2
    assert "[   ]" not in clean2
    assert clean2 == "See on vastus [5] ja."

    # 3. Slot containing only a Russian explanation becomes empty and is removed
    sample3 = "Valem: [a] + [ (слагаемое) ] = [b]."
    clean3 = sanitize_answer_template(sample3)
    assert clean3 == "Valem: [a] + = [b]."

    # 4. Complex example
    sample4 = "Jagatis on [jagatis (частное)], jagatav on [jagatav (делимое)] ja jagaja on [jagaja (делитель)]."
    clean4 = sanitize_answer_template(sample4)
    assert clean4 == "Jagatis on [jagatis], jagatav on [jagatav] ja jagaja on [jagaja]."


def test_model_validation_sanitizes_answer_template_and_tags():
    """
    Verifies that GeminiPageAnalysisSchema and PageAnalysisResponse automatically apply
    sanitization to answer_template and enforce valid <est> tags.
    """
    raw_data = {
        "task_title": "Урок 5: Сложение <et>liitmine</et>",
        "theme_explanation": "Складываем числа <est>arvud",
        "vocabulary": [
            {
                "est": "liitmine",
                "ru": "сложение",
                "example": "See on liitmine."
            }
        ],
        "answer_template": "Esimene [liidetav (слагаемое)] on [liidetav], [] summa on [summa].",
        "voice_prompt_script": "Привет! Давай сложим <et>arvud</et>.",
        "theme_explanation_speech": "Складываем числа.",
        "how_to_answer_speech": "Смотри на первое слагаемое.",
    }

    resp = PageAnalysisResponse.model_validate(raw_data)

    # 1. answer_template is sanitized
    assert resp.answer_template == "Esimene [liidetav] on [liidetav], summa on [summa]."
    assert "слагаемое" not in resp.answer_template
    assert "[]" not in resp.answer_template

    # 2. Visual tags normalized: <et> -> <est>, unclosed <est> closed
    assert "<est>liitmine</est>" in resp.task_title
    assert "<est>arvud</est>" in resp.theme_explanation
    assert "<est>arvud</est>" in resp.voice_prompt_script
