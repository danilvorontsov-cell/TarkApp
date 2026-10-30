import pytest
from app.models.page_analysis import (
    AgeTier,
    UserProfile,
    PageAnalysisResponse,
    is_visual_template_enabled,
    MathBlocksVisual,
    MathBlockGroup,
    MatchPairsVisual,
    MatchPairItem,
    StepSequenceVisual,
    StepSequenceItem,
    BalanceScaleVisual,
    BalanceScaleSide,
    BalanceScaleItem,
    UniversalCardVisual,
)
from app.services.gemini_service import gemini_tutor_service


def test_is_visual_template_enabled():
    # Enabled for grades 1–6 (Primary & Middle school I)
    for g in range(1, 7):
        assert is_visual_template_enabled(g) is True
    assert is_visual_template_enabled(AgeTier.PRIMARY) is True
    assert is_visual_template_enabled(AgeTier.MIDDLE) is True

    # Strictly disabled for grades 7–12 (High school & Gymnasium)
    for g in range(7, 13):
        assert is_visual_template_enabled(g) is False
    assert is_visual_template_enabled(AgeTier.HIGH) is False
    assert is_visual_template_enabled(AgeTier.GYMNASIUM) is False


def test_math_blocks_visual_model():
    vis = MathBlocksVisual(
        title="Счет блоков",
        groups=[
            MathBlockGroup(label="Group A", count=3, color="#3B82F6"),
            MathBlockGroup(label="Group B", count=4, color="#10B981"),
        ],
        operation="+",
        target_count=7,
    )
    assert vis.type == "math_blocks"
    assert len(vis.groups) == 2
    assert vis.groups[0].count == 3


def test_match_pairs_visual_model():
    vis = MatchPairsVisual(
        title="Сопоставление",
        pairs=[
            MatchPairItem(id="1", left="kass", right="кот"),
            MatchPairItem(id="2", left="koer", right="собака"),
        ],
    )
    assert vis.type == "match_pairs"
    assert len(vis.pairs) == 2


def test_step_sequence_visual_model():
    vis = StepSequenceVisual(
        title="Алгоритм",
        steps=[
            StepSequenceItem(step_number=1, title="Шаг 1", description="Сначала"),
            StepSequenceItem(step_number=2, title="Шаг 2", description="Затем"),
        ],
    )
    assert vis.type == "step_sequence"
    assert len(vis.steps) == 2


def test_balance_scale_visual_model():
    vis = BalanceScaleVisual(
        title="Весы",
        left_side=BalanceScaleSide(label="Слева", value=8),
        right_side=BalanceScaleSide(label="Справа", value=10),
        comparison="<",
    )
    assert vis.type == "balance_scale"
    assert vis.comparison == "<"


def test_universal_card_visual_model():
    vis = UniversalCardVisual(
        title="Правило",
        icon="⚡",
        badge="ВАЖНО",
        highlight_text="a + b = b + a",
        explanation="Переместительный закон",
    )
    assert vis.type == "universal_card"
    assert vis.highlight_text == "a + b = b + a"


def test_mock_adaptation_visual_policy():
    # Grade 2 (Primary) -> Has MathBlocksVisual
    p2 = UserProfile(grade=2, nickname="Алиса", interests=["LEGO"])
    res2 = gemini_tutor_service._generate_mock_adaptation(p2)
    assert res2.visual is not None
    assert res2.visual.type == "math_blocks"

    # Grade 5 (Middle) -> Has StepSequenceVisual
    p5 = UserProfile(grade=5, nickname="Марк", interests=["Роботы"])
    res5 = gemini_tutor_service._generate_mock_adaptation(p5)
    assert res5.visual is not None
    assert res5.visual.type == "step_sequence"

    # Grade 8 (High school) -> Strictly None
    p8 = UserProfile(grade=8, nickname="Даниил", interests=["Гаджеты"])
    res8 = gemini_tutor_service._generate_mock_adaptation(p8)
    assert res8.visual is None

    # Grade 11 (Gymnasium) -> Strictly None
    p11 = UserProfile(grade=11, nickname="Елена", interests=["IT"])
    res11 = gemini_tutor_service._generate_mock_adaptation(p11)
    assert res11.visual is None
