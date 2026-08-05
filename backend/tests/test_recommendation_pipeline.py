from datetime import UTC, datetime

import pytest

from app.agent_context.enrichment_schemas import (
    CandidateEnrichmentResponse,
    CandidateEnrichmentResult,
    ConcentrationForecastData,
)
from app.agent_context.schemas import (
    ContextError,
    RecommendationContext,
    ResolvedLocation,
    WeatherForecast,
)
from app.agent_context.schemas import ContextValue as AgentContextValue
from app.agent_context.schemas import Coordinates as AgentCoordinates
from app.agent_context.schemas import PlaceCandidate as AgentPlaceCandidate
from app.concentration_policy import normalize_concentration
from app.errors import AppError
from app.schemas import (
    RecommendationItem,
    RecommendationResponse,
    StatedWeather,
    UserConditions,
    WeatherIntent,
)
from app.services.recommendation_pipeline import (
    rerank_with_concentration,
    run_recommendation_pipeline_from_context,
)

_WEATHER_MISSING_WARNING = "현재 날씨 정보를 확인하지 못해 이 조건은 반영되지 않았어요."
_WEATHER_IGNORED_WARNING = "날씨 조건을 반영하지 않기로 하셔서 이번 추천에는 제외했어요."
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
async def test_pipeline_accepts_conditions_without_using_them_yet() -> None:
    """A가 넘긴 conditions를 받되 아직 날씨 판정에는 쓰지 않는다.

    D가 conditions.weather와 weather_intent로 판정하도록 바꿀 때 쓸 입력이다(D-051).
    지금은 전달 경로만 열어두고, 넘겨도 기존 동작(context.weather 사용)이 바뀌지
    않는 것을 고정한다.
    """
    context = RecommendationContext(
        location=_context_location(),
        weather=None,
        places=AgentContextValue(status="success", data=[_context_place()]),
    )

    response = await run_recommendation_pipeline_from_context(
        context,
        conditions=UserConditions(
            weather_intent=WeatherIntent.AVOID, weather=StatedWeather.RAIN
        ),
        visit_at=_CONTEXT_VISIT_AT,
        search_radius_km=2.0,
    )

    # context.weather가 없으므로 날씨 Feature는 빠진다 — 발화 값을 쓰지 않는다.
    item = response.recommendations[0]
    assert item.feature_scores["weather"] is None
    assert "weather" not in item.weights_used


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


# --- rerank_with_concentration() (D-040, 2차 Scoring) ------------------------
#
# 1차 결과(RecommendationResponse, 이미 5개로 좁혀진 상태)에 concentration
# Feature를 더해 재채점하는 D의 신규 진입점. weather/remaining_operating_time을
# 둘 다 결측(None)으로 고정해 순수하게 "distance vs concentration"만으로
# 재순위가 실제로 뒤집히는지 검증한다.


def _first_pass_item(
    place_id: str, *, distance_km: float, distance_score: float
) -> RecommendationItem:
    return RecommendationItem(
        place_id=place_id,
        name=f"장소-{place_id}",
        category="cafe",
        distance_km=distance_km,
        remaining_minutes=None,
        environment_type="indoor",
        recommendation_reason="테스트용 1차 추천입니다.",
        explanations=[],
        warnings=[],
        score=distance_score,
        feature_scores={
            "weather": None,
            "remaining_operating_time": None,
            "distance": distance_score,
        },
        weights_used={"distance": 1.0},
    )


def _concentration_result(place_id: str, *, rate: float) -> CandidateEnrichmentResult:
    normalized = normalize_concentration(rate)
    return CandidateEnrichmentResult(
        place_id=place_id,
        name=f"장소-{place_id}",
        latitude=37.58,
        longitude=126.97,
        status="success",
        concentration=[
            ConcentrationForecastData(
                place_name=f"장소-{place_id}",
                forecast_date=None,
                concentration_rate=rate,
                concentration_level=normalized.level,
                concentration_label=normalized.label,
            )
        ],
    )


def _no_data_result(place_id: str) -> CandidateEnrichmentResult:
    return CandidateEnrichmentResult(
        place_id=place_id,
        name=f"장소-{place_id}",
        latitude=37.58,
        longitude=126.97,
        status="no_data",
        concentration=[],
    )


@pytest.mark.asyncio
async def test_rerank_with_concentration_avoid_prefers_quiet_place() -> None:
    """place-1이 더 가깝지만(1차 1위) 훨씬 붐비고, place-2는 멀지만 한적하다.

    AVOID(seek=False)면 2차 Scoring 후 순위가 뒤집혀야 한다.
    """
    first_pass = RecommendationResponse(
        recommendations=[
            _first_pass_item("place-1", distance_km=0.1, distance_score=0.95),
            _first_pass_item("place-2", distance_km=1.2, distance_score=0.4),
        ],
        unverified_recommendations=[],
        elapsed_ms=0,
    )
    concentration = CandidateEnrichmentResponse(
        request_id="req-1",
        status="success",
        candidates=[
            _concentration_result("place-1", rate=95.0),
            _concentration_result("place-2", rate=5.0),
        ],
    )

    result = await rerank_with_concentration(first_pass, None, concentration, seek=False)

    assert [item.place_id for item in result.recommendations] == ["place-2", "place-1"]
    quiet_item = result.recommendations[0]
    assert "지금 이 근처는 한적한 편이에요." in quiet_item.explanations


@pytest.mark.asyncio
async def test_rerank_with_concentration_seek_prefers_crowded_place() -> None:
    first_pass = RecommendationResponse(
        recommendations=[
            _first_pass_item("place-1", distance_km=0.1, distance_score=0.95),
            _first_pass_item("place-2", distance_km=1.2, distance_score=0.4),
        ],
        unverified_recommendations=[],
        elapsed_ms=0,
    )
    concentration = CandidateEnrichmentResponse(
        request_id="req-2",
        status="success",
        candidates=[
            _concentration_result("place-1", rate=5.0),
            _concentration_result("place-2", rate=95.0),
        ],
    )

    result = await rerank_with_concentration(first_pass, None, concentration, seek=True)

    assert [item.place_id for item in result.recommendations] == ["place-2", "place-1"]


@pytest.mark.asyncio
async def test_rerank_with_concentration_handles_partial_no_data() -> None:
    """concentration이 일부 후보만 결측(no_data)이어도 크래시 없이 개별 재분배된다."""
    first_pass = RecommendationResponse(
        recommendations=[
            _first_pass_item("place-1", distance_km=0.1, distance_score=0.95),
            _first_pass_item("place-2", distance_km=1.2, distance_score=0.4),
        ],
        unverified_recommendations=[],
        elapsed_ms=0,
    )
    concentration = CandidateEnrichmentResponse(
        request_id="req-3",
        status="partial",
        candidates=[
            _concentration_result("place-1", rate=50.0),
            _no_data_result("place-2"),
        ],
    )

    result = await rerank_with_concentration(first_pass, None, concentration, seek=True)

    place_ids = {item.place_id for item in result.recommendations}
    assert place_ids == {"place-1", "place-2"}
    place_2 = next(item for item in result.recommendations if item.place_id == "place-2")
    assert place_2.feature_scores.get("concentration") is None
    assert "concentration" not in place_2.weights_used


@pytest.mark.asyncio
async def test_rerank_with_concentration_preserves_unverified_split() -> None:
    first_pass = RecommendationResponse(
        recommendations=[_first_pass_item("place-1", distance_km=0.1, distance_score=0.95)],
        unverified_recommendations=[
            _first_pass_item("place-2", distance_km=1.2, distance_score=0.4)
        ],
        elapsed_ms=0,
    )
    concentration = CandidateEnrichmentResponse(
        request_id="req-4",
        status="success",
        candidates=[
            _concentration_result("place-1", rate=50.0),
            _concentration_result("place-2", rate=50.0),
        ],
    )

    result = await rerank_with_concentration(first_pass, None, concentration, seek=True)

    assert [item.place_id for item in result.recommendations] == ["place-1"]
    assert [item.place_id for item in result.unverified_recommendations] == ["place-2"]
