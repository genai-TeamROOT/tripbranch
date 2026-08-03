"""D가 A 없이 사용할 수 있는 C 정규화 Context Fixture를 검증한다."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.agent_context.schemas import AgentContextResponse
from app.services.recommendation_pipeline import run_recommendation_pipeline_from_context

_FIXTURE_DIRECTORY = Path(__file__).parents[1] / "fixtures" / "agent_context"
_VISIT_AT = datetime.fromisoformat("2026-08-15T11:00:00+09:00")

_D_FIXTURE_CASES = {
    "success.json": ("success", 2),
    "success_bad_weather.json": ("success", 2),
    "success_operating_schedule.json": ("success", 3),
    "partial_weather_unavailable.json": ("partial", 2),
    "partial_place_details.json": ("partial", 2),
    "missing_weather.json": ("success", 2),
    "missing_operating_hours.json": ("partial", 2),
    "insufficient_candidates.json": ("partial", 1),
    "no_place_candidates.json": ("no_data", 0),
}


def _load_response(filename: str) -> AgentContextResponse:
    with (_FIXTURE_DIRECTORY / filename).open(encoding="utf-8") as fixture_file:
        return AgentContextResponse.model_validate(json.load(fixture_file))


@pytest.mark.parametrize(("filename", "expected"), _D_FIXTURE_CASES.items())
def test_d_context_fixtures_match_c_contract(
    filename: str,
    expected: tuple[str, int],
) -> None:
    """모든 Fixture가 현재 C 응답 계약과 시나리오별 후보 수를 지키는지 확인한다."""

    expected_status, expected_place_count = expected
    response = _load_response(filename)

    assert response.status == expected_status
    assert response.context is not None
    assert response.context.places is not None
    assert len(response.context.places.data or []) == expected_place_count


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", _D_FIXTURE_CASES)
async def test_d_context_fixtures_can_run_recommendation_pipeline(filename: str) -> None:
    """정규화 Context만으로 D 공개 파이프라인을 실행할 수 있는지 확인한다."""

    response = _load_response(filename)
    result = await run_recommendation_pipeline_from_context(
        response.context,
        visit_at=_VISIT_AT,
        search_radius_km=2.0,
    )

    if filename == "no_place_candidates.json":
        assert result.recommendations == []
        assert result.unverified_recommendations == []
    else:
        assert result.recommendations or result.unverified_recommendations


@pytest.mark.asyncio
async def test_operating_schedule_fixture_excludes_closed_candidate() -> None:
    response = _load_response("success_operating_schedule.json")

    result = await run_recommendation_pipeline_from_context(
        response.context,
        visit_at=_VISIT_AT,
        search_radius_km=2.0,
    )

    returned_ids = {
        item.place_id
        for item in result.recommendations + result.unverified_recommendations
    }
    assert "schedule-open-1" in returned_ids
    assert "schedule-all-day-1" in returned_ids
    assert "schedule-closed-1" not in returned_ids


@pytest.mark.asyncio
async def test_missing_operating_hours_fixture_returns_unverified_candidates() -> None:
    response = _load_response("missing_operating_hours.json")

    result = await run_recommendation_pipeline_from_context(
        response.context,
        visit_at=_VISIT_AT,
        search_radius_km=2.0,
    )

    assert result.recommendations == []
    assert len(result.unverified_recommendations) == 2


@pytest.mark.asyncio
async def test_missing_weather_fixture_is_distinct_from_provider_failure() -> None:
    ignored_response = _load_response("missing_weather.json")
    failed_response = _load_response("partial_weather_unavailable.json")

    ignored_result = await run_recommendation_pipeline_from_context(
        ignored_response.context,
        visit_at=_VISIT_AT,
        search_radius_km=2.0,
    )
    failed_result = await run_recommendation_pipeline_from_context(
        failed_response.context,
        visit_at=_VISIT_AT,
        search_radius_km=2.0,
    )

    ignored_warnings = ignored_result.recommendations[0].warnings
    failed_warnings = failed_result.recommendations[0].warnings
    assert any("말씀하지 않으셔서" in warning for warning in ignored_warnings)
    assert any("확인하지 못해" in warning for warning in failed_warnings)
