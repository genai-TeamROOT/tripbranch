"""D-07: C 정규화 Context Fixture 기준 추천 품질 정밀 검증.

`test_recommendation_context_fixtures.py`(C 계약 검증, 순위·점수는 미검증)와
달리 이 테스트는 `recommendation_context_fixture_expectations.py`에 고정된
기대 순위·점수·가중치 재분배·제외 결과를 실제 파이프라인 산출값과 정확히
비교한다. `candidate_mapper.py`(거리 계산·environment_type 매핑·운영시간
파싱)를 포함한 D 전체 파이프라인을 대상으로 한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent_context.schemas import AgentContextResponse
from app.schemas import RecommendationItem, RecommendationResponse
from app.services.recommendation_pipeline import run_recommendation_pipeline_from_context
from tests.fixtures.recommendation_context_fixture_expectations import (
    CONTEXT_FIXTURE_EXPECTATIONS,
    ContextFixtureCase,
    ExpectedItem,
)

_FIXTURE_DIRECTORY = Path(__file__).parents[1] / "fixtures" / "agent_context"
_SCORE_TOLERANCE = 1e-3


def _load_response(filename: str) -> AgentContextResponse:
    with (_FIXTURE_DIRECTORY / filename).open(encoding="utf-8") as fixture_file:
        return AgentContextResponse.model_validate(json.load(fixture_file))


async def _run(case: ContextFixtureCase) -> RecommendationResponse:
    response = _load_response(case.filename)
    return await run_recommendation_pipeline_from_context(
        response.context,
        visit_at=case.visit_at,
        search_radius_km=case.search_radius_km,
        shown_place_ids=case.shown_place_ids,
        rejected_place_ids=case.rejected_place_ids,
    )


def _assert_item_matches(actual: RecommendationItem, expected: ExpectedItem) -> None:
    assert actual.place_id == expected.place_id
    assert actual.score == pytest.approx(expected.score, abs=_SCORE_TOLERANCE)

    assert set(actual.feature_scores) == set(expected.feature_scores)
    for feature, expected_value in expected.feature_scores.items():
        actual_value = actual.feature_scores[feature]
        if expected_value is None:
            assert actual_value is None, f"{expected.place_id}.{feature}는 결측이어야 한다"
        else:
            assert actual_value == pytest.approx(expected_value, abs=_SCORE_TOLERANCE), (
                f"{expected.place_id}.{feature} 불일치"
            )

    assert set(actual.weights_used) == set(expected.weights_used)
    for feature, expected_weight in expected.weights_used.items():
        actual_weight = actual.weights_used[feature]
        assert actual_weight == pytest.approx(expected_weight, abs=_SCORE_TOLERANCE), (
            f"{expected.place_id} weights_used.{feature} 불일치"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    CONTEXT_FIXTURE_EXPECTATIONS,
    ids=[case.name for case in CONTEXT_FIXTURE_EXPECTATIONS],
)
async def test_context_fixture_matches_expected_quality(case: ContextFixtureCase) -> None:
    result = await _run(case)

    actual_recommended_ids = tuple(item.place_id for item in result.recommendations)
    actual_unverified_ids = tuple(item.place_id for item in result.unverified_recommendations)

    assert actual_recommended_ids == tuple(item.place_id for item in case.expected_recommended)
    assert actual_unverified_ids == tuple(item.place_id for item in case.expected_unverified)

    for actual_item, expected_item in zip(
        result.recommendations, case.expected_recommended, strict=True
    ):
        _assert_item_matches(actual_item, expected_item)

    for actual_item, expected_item in zip(
        result.unverified_recommendations, case.expected_unverified, strict=True
    ):
        _assert_item_matches(actual_item, expected_item)

    returned_ids = set(actual_recommended_ids) | set(actual_unverified_ids)
    assert returned_ids.isdisjoint(case.expected_excluded_place_ids)


@pytest.mark.asyncio
async def test_shown_place_ids_are_excluded_from_results() -> None:
    """C Fixture엔 없는 필드라 D가 직접 값을 부여해 검증한다(README §실행 인자)."""

    response = _load_response("success.json")

    result = await run_recommendation_pipeline_from_context(
        response.context,
        visit_at=CONTEXT_FIXTURE_EXPECTATIONS[0].visit_at,
        search_radius_km=CONTEXT_FIXTURE_EXPECTATIONS[0].search_radius_km,
        shown_place_ids=frozenset({"126508"}),
    )

    returned_ids = {
        item.place_id for item in result.recommendations + result.unverified_recommendations
    }
    assert "126508" not in returned_ids
    assert "130100" in returned_ids


@pytest.mark.asyncio
async def test_rejected_place_ids_are_excluded_from_results() -> None:
    response = _load_response("success.json")

    result = await run_recommendation_pipeline_from_context(
        response.context,
        visit_at=CONTEXT_FIXTURE_EXPECTATIONS[0].visit_at,
        search_radius_km=CONTEXT_FIXTURE_EXPECTATIONS[0].search_radius_km,
        rejected_place_ids=frozenset({"130100"}),
    )

    returned_ids = {
        item.place_id for item in result.recommendations + result.unverified_recommendations
    }
    assert "130100" not in returned_ids
    assert "126508" in returned_ids


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    CONTEXT_FIXTURE_EXPECTATIONS,
    ids=[case.name for case in CONTEXT_FIXTURE_EXPECTATIONS],
)
async def test_context_fixture_is_deterministic_across_repeated_runs(
    case: ContextFixtureCase,
) -> None:
    """완료 기준: 동일 Fixture에서 점수와 순위가 일관되게 반환된다."""

    first_result = await _run(case)
    second_result = await _run(case)

    assert first_result.recommendations == second_result.recommendations
    assert first_result.unverified_recommendations == second_result.unverified_recommendations
