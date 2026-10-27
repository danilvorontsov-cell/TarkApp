import pytest
from app.services.gemini_service import GeminiTutorService
from app.models.page_analysis import VocabularyItem, AgeTier

def test_generate_more_examples_mock():
    service = GeminiTutorService(api_key="mock")
    templates = service._generate_mock_more_examples(
        task_title="Liitmine",
        vocabulary=[VocabularyItem(est="liidetav", ru="слагаемое", example="ex")],
        current_template="Esimene [liidetav]",
        tier=AgeTier.PRIMARY
    )
    assert len(templates) > 0
    for t in templates:
        assert "[" in t and "]" in t
