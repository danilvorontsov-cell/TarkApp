import pytest
from app.models.page_analysis import (
    AgeTier,
    PageAnalysisResponse,
    UserProfile,
    VocabularyItem,
    WorkedExample,
)
from app.services.analysis_cache import (
    clear_analysis_cache,
    compute_analysis_cache_key,
    get_cached_analysis,
    store_cached_analysis,
)


@pytest.fixture(autouse=True)
def clean_cache():
    clear_analysis_cache()
    yield
    clear_analysis_cache()


class TestCacheGradeDifferentiation:
    """
    Verifies that the analysis cache strictly differentiates by student grade and age tier.
    An 8th grader analyzing the exact same textbook page must NEVER receive a 2nd grader's
    simplified fairy-tale / Minecraft explanation from cache.
    """

    def test_cache_keys_differ_for_grade_2_and_grade_8_on_identical_image(self):
        # Exact identical image bytes from textbook
        identical_image_bytes = [b"\xff\xd8\xff\xe0" + b"identical_textbook_page_content" * 20]

        profile_grade_2 = UserProfile(
            grade=2,
            tier=AgeTier.PRIMARY,
            interests=["Игры", "Lego"],
            nickname="Саша",
        )

        profile_grade_8 = UserProfile(
            grade=8,
            tier=AgeTier.HIGH,
            interests=["Игры", "Lego"],
            nickname="Алекс",
        )

        key_grade_2 = compute_analysis_cache_key(identical_image_bytes, profile_grade_2)
        key_grade_8 = compute_analysis_cache_key(identical_image_bytes, profile_grade_8)

        # Keys MUST NOT match
        assert key_grade_2 != key_grade_8, (
            f"Cache collision! Keys should differ between Grade 2 and Grade 8: {key_grade_2} vs {key_grade_8}"
        )

    def test_cache_hit_isolation_between_tiers(self):
        identical_image = [b"textbook_page_exercise_42"]

        profile_primary = UserProfile(grade=2, tier=AgeTier.PRIMARY, interests=["Minecraft"])
        profile_high = UserProfile(grade=8, tier=AgeTier.HIGH, interests=["Minecraft"])

        key_primary = compute_analysis_cache_key(identical_image, profile_primary)
        key_high = compute_analysis_cache_key(identical_image, profile_high)

        # Create distinct responses for primary vs high
        primary_response = PageAnalysisResponse(
            task_title="Сложение для малышей (Liitmine)",
            theme_explanation="Представь, что мы строим домик из кубиков в Майнкрафте! 2 блока + 3 блока.",
            vocabulary=[VocabularyItem(est="liitma", ru="складывать", example="Liidame klotsid.")],
            worked_example=WorkedExample(
                title="Пример с кубиками",
                given="2 блока + 3 блока",
                steps=["1. Считаем вместе: 1, 2, 3, 4, 5"],
                note="Получилось 5 блоков!"
            ),
            how_to_answer="Сложи блоки вместе и напиши ответ.",
            answer_template="Klotside summa on [viis].",
            voice_prompt_script="Привет, малыш! Давай посчитаем кубики вместе!",
        )

        high_response = PageAnalysisResponse(
            task_title="Алгебраические выражения (Algebralised avaldised)",
            theme_explanation="Анализ линейной зависимости переменных в математической модели.",
            vocabulary=[VocabularyItem(est="muutuja", ru="переменная", example="Avaldis sisaldab muutujat x.")],
            worked_example=WorkedExample(
                title="Алгебраический пример",
                given="2x + 3x",
                steps=["1. Приводим подобные слагаемые: (2 + 3)x = 5x"],
                note="Ответ: 5x"
            ),
            how_to_answer="Приведи подобные члены и вырази неизвестную переменную.",
            answer_template="Koondatud avaldis on [viis x].",
            voice_prompt_script="Здорово! Разберём приведение подобных слагаемых.",
        )

        # Store primary student's analysis
        store_cached_analysis(key_primary, primary_response)

        # Verify that grade 8 student cache lookup results in a MISS (does not get primary answer)
        cached_for_high = get_cached_analysis(key_high)
        assert cached_for_high is None, (
            "Grade 8 student erroneously received Grade 2 cached response!"
        )

        # Store grade 8 student's analysis
        store_cached_analysis(key_high, high_response)

        # Now verify both can retrieve their own tailored responses
        assert get_cached_analysis(key_primary).task_title == "Сложение для малышей (Liitmine)"
        assert get_cached_analysis(key_high).task_title == "Алгебраические выражения (Algebralised avaldised)"

    def test_cache_keys_differ_by_student_nickname(self):
        identical_image = [b"textbook_page_same_grade_different_nickname"]
        profile_sasha = UserProfile(grade=4, tier=AgeTier.MIDDLE, interests=["Minecraft"], nickname="Саша")
        profile_masha = UserProfile(grade=4, tier=AgeTier.MIDDLE, interests=["Minecraft"], nickname="Маша")

        key_sasha = compute_analysis_cache_key(identical_image, profile_sasha)
        key_masha = compute_analysis_cache_key(identical_image, profile_masha)

        assert key_sasha != key_masha, "Cache key must isolate personalized responses by nickname"
