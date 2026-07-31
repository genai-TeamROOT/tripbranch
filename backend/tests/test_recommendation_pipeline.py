from datetime import UTC, datetime

import pytest

from app.agent_context.schemas import (
    ContextError,
    RecommendationContext,
    ResolvedLocation,
    WeatherForecast,
)
from app.agent_context.schemas import ContextValue as AgentContextValue
from app.agent_context.schemas import Coordinates as AgentCoordinates
from app.agent_context.schemas import PlaceCandidate as AgentPlaceCandidate
from app.errors import AppError
from app.services.recommendation_pipeline import run_recommendation_pipeline_from_context

_WEATHER_MISSING_WARNING = "현재 날씨 정보를 확인하지 못해 이 조건은 반영되지 않았어요."
_WEATHER_IGNORED_WARNING = "날씨 조건을 따로 말씀하지 않으셔서 이번 추천에는 반영하지 않았어요."
_NO_NOTABLE_EXPLANATION_WARNING = (
    "이 장소는 특별히 강조할 만한 조건은 없지만, 조건에 맞아 추천했어요."
)


# --- run_recommendation_pipeline_from_context() ----------------------------
#
# A가 C에서 받은 RecommendationContext를 그대로 넘기는 D의 유일한 공개 진입점
# 검증([TECH-02] C-D 직접 의존 제거 및 RecommendationContext 경계 정리).
# D-03(추천 파이프라인 1차 E2E 통합)의 완료 기준(하드 필터, 이전 노출·거절
# 제외, 결정성)은 여기서 E2E로, score_candidates() 자체는 test_scoring.py가
# 단위 테스트로 커버한다.

_CONTEXT_VISIT_AT = datetime(2026, 7, 28, 15, 0, tzinfo=UTC)


def _context_location() -> AgentContextValue:
    return AgentContextValue(
        status="success",
        data=ResolvedLocation(
            requested_query="경복궁",
            resolved_name="경복궁",
            location=AgentCoordinates(latitude=37.5796, longitude=126.9770),
        ),
    )


def _context_place(place_id: str = "place-1") -> AgentPlaceCandidate:
    return AgentPlaceCandidate(
        place_id=place_id,
        name="근처 카페",
        category="cafe",
        location=AgentCoordinates(latitude=37.5806, longitude=126.9770),
        operating_schedule={"availability": "all_day", "rules": [], "closure_rules": []},
    )


@pytest.mark.asyncio
async def test_pipeline_from_context_builds_recommendation_with_explanations() -> None:
    context = RecommendationContext(
        location=_context_location(),
        weather=AgentContextValue(
            status="success",
            data=WeatherForecast(condition="bad", forecast_for=_CONTEXT_VISIT_AT),
        ),
        places=AgentContextValue(status="success", data=[_context_place()]),
    )

    response = await run_recommendation_pipeline_from_context(
        context,
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
    )

    assert len(response.recommendations) == 1
    assert response.unverified_recommendations == []
    assert response.recommendations[0].explanations


@pytest.mark.asyncio
async def test_pipeline_from_context_reports_weather_ignored_when_not_requested() -> None:
    """weather_intent=IGNORE면 C가 Weather Tool을 아예 실행하지 않아 weather가 없다.

    정상 흐름이므로 "확인하지 못했다"(조회 실패)와 다른 문구를 써야 한다.
    """
    context = RecommendationContext(
        location=_context_location(),
        weather=None,
        places=AgentContextValue(status="success", data=[_context_place()]),
    )

    response = await run_recommendation_pipeline_from_context(
        context,
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
    )

    warnings = response.recommendations[0].warnings
    assert _WEATHER_IGNORED_WARNING in warnings
    assert _WEATHER_MISSING_WARNING not in warnings


@pytest.mark.asyncio
async def test_pipeline_from_context_reports_weather_failure_when_lookup_failed() -> None:
    """조회를 시도했으나 실패한 경우에만 "확인하지 못했다"가 사실이다."""
    context = RecommendationContext(
        location=_context_location(),
        weather=AgentContextValue(
            status="unavailable",
            data=None,
            error=ContextError(
                code="unavailable", message="날씨를 조회하지 못했습니다.", retryable=True
            ),
        ),
        places=AgentContextValue(status="success", data=[_context_place()]),
    )

    response = await run_recommendation_pipeline_from_context(
        context,
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
    )

    warnings = response.recommendations[0].warnings
    assert _WEATHER_MISSING_WARNING in warnings
    assert _WEATHER_IGNORED_WARNING not in warnings


@pytest.mark.asyncio
async def test_pipeline_from_context_returns_empty_when_places_have_no_data() -> None:
    context = RecommendationContext(
        location=_context_location(),
        places=AgentContextValue(status="no_data", data=[]),
    )

    response = await run_recommendation_pipeline_from_context(
        context,
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
    )

    assert response.recommendations == []
    assert response.unverified_recommendations == []


@pytest.mark.asyncio
async def test_pipeline_from_context_raises_when_places_unavailable() -> None:
    context = RecommendationContext(
        location=_context_location(),
        places=AgentContextValue(
            status="unavailable",
            error=ContextError(
                code="place_search_failed", message="장소 조회 실패", retryable=True
            ),
        ),
    )

    with pytest.raises(AppError) as exc_info:
        await run_recommendation_pipeline_from_context(
            context,
            visit_at=_CONTEXT_VISIT_AT,
            search_radius_km=2.0,
        )

    assert exc_info.value.code == "place_search_failed"


@pytest.mark.asyncio
async def test_pipeline_from_context_raises_when_location_missing() -> None:
    context = RecommendationContext(location=None, places=None)

    with pytest.raises(AppError) as exc_info:
        await run_recommendation_pipeline_from_context(
            context,
            visit_at=_CONTEXT_VISIT_AT,
            search_radius_km=2.0,
        )

    assert exc_info.value.code == "location_unavailable"


@pytest.mark.asyncio
async def test_pipeline_from_context_raises_when_context_is_none() -> None:
    """AgentContextResponse.status가 needs_clarification/unsupported/unavailable이면
    AgentContextResponse.context 자체가 None일 수 있다 — 이 경우도 AppError로
    처리해야 한다(속성 접근 시 AttributeError가 그대로 터지면 안 된다).
    """
    with pytest.raises(AppError) as exc_info:
        await run_recommendation_pipeline_from_context(
            None,
            visit_at=_CONTEXT_VISIT_AT,
            search_radius_km=2.0,
        )

    assert exc_info.value.code == "context_unavailable"


@pytest.mark.asyncio
async def test_pipeline_from_context_excludes_shown_place_ids() -> None:
    context = RecommendationContext(
        location=_context_location(),
        places=AgentContextValue(
            status="success",
            data=[_context_place("place-1"), _context_place("place-2")],
        ),
    )

    response = await run_recommendation_pipeline_from_context(
        context,
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
        shown_place_ids=frozenset({"place-1"}),
    )

    place_ids = {item.place_id for item in response.recommendations}
    assert place_ids == {"place-2"}


@pytest.mark.asyncio
async def test_pipeline_from_context_is_deterministic_for_identical_input() -> None:
    context = RecommendationContext(
        location=_context_location(),
        weather=AgentContextValue(
            status="success",
            data=WeatherForecast(condition="good", forecast_for=_CONTEXT_VISIT_AT),
        ),
        places=AgentContextValue(
            status="success",
            data=[_context_place("place-1"), _context_place("place-2")],
        ),
    )

    def _run():
        return run_recommendation_pipeline_from_context(
            context,
            visit_at=_CONTEXT_VISIT_AT,
            search_radius_km=2.0,
        )

    response_1 = await _run()
    response_2 = await _run()

    def _normalize(response):
        return [
            (item.place_id, item.score, item.weights_used, tuple(item.warnings))
            for item in response.recommendations + response.unverified_recommendations
        ]

    assert _normalize(response_1) == _normalize(response_2)
