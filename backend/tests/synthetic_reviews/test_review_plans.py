from collections import Counter
from dataclasses import replace

import pytest

from app.synthetic_reviews.personas import PlacePersonaInput, generate_personas
from app.synthetic_reviews.review_plans import generate_review_plans


def _personas(count: int):
    return generate_personas(
        PlacePersonaInput(
            content_id="126508",
            content_type_id="14",
            operating_hours_raw="09:00~18:00",
            rest_date_raw="매주 화요일",
            parking_info_raw="불가능",
            parking_fee_raw="무료",
            use_fee_raw="3,000원",
            pet_raw="불가",
            baby_carriage_raw="없음",
        ),
        target_count=count,
    )


@pytest.mark.parametrize(
    ("persona_count", "expected_distribution"),
    [
        (3, [2, 2, 1]),
        (4, [2, 1, 1, 1]),
        (5, [1, 1, 1, 1, 1]),
    ],
)
def test_리뷰_5개를_페르소나에_균등하게_배분한다(
    persona_count: int, expected_distribution: list[int]
) -> None:
    personas = _personas(persona_count)
    plans = generate_review_plans(personas)
    counts = Counter(plan.persona_id for plan in plans)

    assert len(plans) == 5
    assert [counts[persona.persona_id] for persona in personas] == expected_distribution
    assert [plan.review_index for plan in plans] == list(range(5))


def test_같은_페르소나의_visit_context는_중복되지_않는다() -> None:
    plans = generate_review_plans(_personas(3))

    contexts_by_persona: dict[str, list[str]] = {}
    for plan in plans:
        contexts_by_persona.setdefault(plan.persona_id, []).append(plan.visit_context)

    assert all(
        len(contexts) == len(set(contexts))
        for contexts in contexts_by_persona.values()
    )


def test_구체적인_공식_평가_축을_우선순서대로_배정한다() -> None:
    personas = _personas(4)
    plans = generate_review_plans(personas)
    schedule_plans = [plan for plan in plans if plan.persona_id == personas[0].persona_id]

    assert schedule_plans[0].focus_axes == ("OPERATING_HOURS",)
    assert schedule_plans[1].focus_axes == ("REST_DATE",)
    assert schedule_plans[0].evidence_fields == (
        "operating_hours_raw",
        "rest_date_raw",
    )


def test_계획은_페르소나가_허용한_평가_축과_근거만_사용한다() -> None:
    personas = _personas(4)
    plans = generate_review_plans(personas)
    by_id = {persona.persona_id: persona for persona in personas}

    for plan in plans:
        persona = by_id[plan.persona_id]
        assert set(plan.focus_axes) <= set(persona.allowed_evaluation_axes)
        assert plan.evidence_fields == persona.evidence_fields


def test_같은_입력은_항상_같은_계획을_만든다() -> None:
    personas = _personas(4)

    assert generate_review_plans(personas) == generate_review_plans(personas)


def test_중복된_persona_id는_거부한다() -> None:
    personas = _personas(3)
    duplicated = (personas[0], replace(personas[1], persona_id=personas[0].persona_id), personas[2])

    with pytest.raises(ValueError, match="중복"):
        generate_review_plans(duplicated)


@pytest.mark.parametrize("persona_count", [2, 6])
def test_페르소나는_3개에서_5개만_받는다(persona_count: int) -> None:
    source = _personas(5)
    personas = source[:persona_count] if persona_count == 2 else (*source, source[0])

    with pytest.raises(ValueError, match="3~5"):
        generate_review_plans(tuple(personas))


def test_리뷰_수는_페르소나_수보다_작을_수_없다() -> None:
    with pytest.raises(ValueError, match="페르소나 수 이상"):
        generate_review_plans(_personas(4), review_count=3)


def test_페르소나당_visit_context_세_개를_초과하지_않는다() -> None:
    with pytest.raises(ValueError, match="최대 3개"):
        generate_review_plans(_personas(3), review_count=10)
