"""RealRecommendationProvider 단위 테스트.

D의 실제 recommendation_pipeline을 호출하되, Tool을 직접 호출하지 않는
run_recommendation_pipeline_from_context() 경로만 쓰므로 외부 API 없이 순수하게
테스트 가능하다.
"""

from __future__ import annotations

import pytest

from app.agent_context.enrichment_schemas import (
    CandidateEnrichmentResponse,
    CandidateEnrichmentResult,
)
from app.agent_context.schemas import ContextError
from app.domain.models import WeatherCondition
from app.domain.travel_route import RouteSource, RouteStatus, WalkingRoute
from app.errors import AppError
from app.schemas import (
    ConcentrationIntent,
    RecommendationResponse,
    StatedWeather,
    Transport,
    UserConditions,
    WeatherIntent,
)
from app.services.runtime import real_recommendation_provider as module
from app.services.runtime.context_schemas import (
    ContextValue,
    Coordinates,
    PlaceCandidate,
    RecommendationContext,
    ResolvedLocation,
)
from app.services.runtime.real_recommendation_provider import RealRecommendationProvider


def _context(*, place_ids: list[str]) -> RecommendationContext:
    return RecommendationContext(
        location=ContextValue(
            status="success",
            data=ResolvedLocation(
                requested_query="경복궁",
                resolved_name="경복궁",
                location=Coordinates(latitude=37.5796, longitude=126.9770),
            ),
        ),
        places=ContextValue(
            status="success",
            data=[
                PlaceCandidate(
                    place_id=place_id,
                    name=f"장소-{place_id}",
                    category="cafe",
                    location=Coordinates(latitude=37.58, longitude=126.978),
                    operating_hours_raw="09:00~22:00",
                )
                for place_id in place_ids
            ],
        ),
    )


@pytest.mark.asyncio
async def test_recommend_returns_response_for_valid_context() -> None:
    provider = RealRecommendationProvider()
    conditions = UserConditions(max_travel_time=30)
    context = _context(place_ids=["a", "b"])

    result = await provider.recommend(conditions, context, excluded_place_ids=[])

    all_items = [*result.recommendations, *result.unverified_recommendations]
    assert {item.place_id for item in all_items} == {"a", "b"}


@pytest.mark.asyncio
async def test_recommend_excludes_given_place_ids() -> None:
    provider = RealRecommendationProvider()
    conditions = UserConditions()
    context = _context(place_ids=["a", "b", "c"])

    result = await provider.recommend(conditions, context, excluded_place_ids=["a", "b"])

    all_items = [*result.recommendations, *result.unverified_recommendations]
    assert {item.place_id for item in all_items} == {"c"}


@pytest.mark.asyncio
async def test_recommend_respects_limit_parameter() -> None:
    """SCHEDULE-03: limit을 넘기면 그 개수만큼만 반환돼야 한다."""
    provider = RealRecommendationProvider()
    conditions = UserConditions()
    context = _context(place_ids=[f"p{i}" for i in range(10)])

    result = await provider.recommend(conditions, context, excluded_place_ids=[], limit=10)

    all_items = [*result.recommendations, *result.unverified_recommendations]
    assert len(all_items) == 10


@pytest.mark.asyncio
async def test_recommend_defaults_to_five_when_limit_not_given() -> None:
    """limit을 안 넘기면 기존 RECOMMEND 흐름과 동일하게 5개로 제한돼야 한다."""
    provider = RealRecommendationProvider()
    conditions = UserConditions()
    context = _context(place_ids=[f"p{i}" for i in range(10)])

    result = await provider.recommend(conditions, context, excluded_place_ids=[])

    all_items = [*result.recommendations, *result.unverified_recommendations]
    assert len(all_items) == 5


@pytest.mark.asyncio
async def test_provider_merges_multiple_prepared_batches() -> None:
    provider = RealRecommendationProvider()
    conditions = UserConditions()
    visit_at = module.datetime.now(module._KST)
    first = await provider.prepare(
        conditions,
        _context(place_ids=["a"]),
        excluded_place_ids=[],
        visit_at=visit_at,
    )
    second = await provider.prepare(
        conditions,
        _context(place_ids=["b"]),
        excluded_place_ids=[],
        visit_at=visit_at,
    )

    merged = provider.merge_prepared([first, second])
    result = await provider.score_prepared(conditions, merged)

    assert {
        item.place_id
        for item in [*result.recommendations, *result.unverified_recommendations]
    } == {"a", "b"}


@pytest.mark.asyncio
async def test_recommend_raises_app_error_when_context_is_none() -> None:
    provider = RealRecommendationProvider()
    conditions = UserConditions()

    with pytest.raises(AppError):
        await provider.recommend(conditions, None, excluded_place_ids=[])  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_search_radius_km_passed_to_pipeline_matches_to_search_radius_km(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D 호출에 실제로 넘어가는 search_radius_km이 to_search_radius_km() 값과 같은지 확인."""
    captured: dict[str, object] = {}
    original = module.score_prepared_recommendation

    async def _capture(prepared, **kwargs):
        captured["visit_at"] = prepared.visit_at
        captured.update(kwargs)
        return await original(prepared, **kwargs)

    monkeypatch.setattr(module, "score_prepared_recommendation", _capture)

    provider = RealRecommendationProvider()
    conditions = UserConditions(max_travel_time=30)
    context = _context(place_ids=["a"])

    await provider.recommend(conditions, context, excluded_place_ids=[])

    assert captured["search_radius_km"] == pytest.approx(module.to_search_radius_km(conditions))
    assert captured["visit_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_conditions_are_passed_to_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A는 발화 조건을 줄이지 않고 그대로 D에 넘긴다.

    AVOID/ENJOY면 C가 날씨를 조회하지 않으므로 D는 conditions.weather로 날씨를
    판정한다. 여기서 A가 3단계로 미리 줄이면 의도와 발화 값이 함께 사라져 D가 다시
    판단할 수 없다(D-051).
    """
    captured: dict[str, object] = {}
    original = module.prepare_recommendation_from_context

    async def _capture(context, **kwargs):
        captured.update(kwargs)
        return await original(context, **kwargs)

    monkeypatch.setattr(module, "prepare_recommendation_from_context", _capture)

    provider = RealRecommendationProvider()
    conditions = UserConditions(
        weather_intent=WeatherIntent.AVOID, weather=StatedWeather.RAIN
    )

    await provider.recommend(conditions, _context(place_ids=["a"]), excluded_place_ids=[])

    assert captured["conditions"] is conditions


def _empty_first_pass() -> RecommendationResponse:
    return RecommendationResponse(recommendations=[], unverified_recommendations=[], elapsed_ms=0)


def _unavailable_concentration() -> CandidateEnrichmentResponse:
    return CandidateEnrichmentResponse(
        request_id="req-1",
        status="unavailable",
        candidates=[
            CandidateEnrichmentResult(
                place_id="a",
                name="장소-a",
                latitude=37.58,
                longitude=126.97,
                status="unavailable",
                error=ContextError(code="unavailable", message="실패", retryable=True),
            )
        ],
    )


@pytest.mark.asyncio
async def test_rerank_with_concentration_derives_seek_true_from_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-040: RealRecommendationProvider가 conditions.concentration_intent를
    올바르게 seek(bool)로 변환해 recommendation_pipeline.rerank_with_concentration()에
    넘기는지 확인한다(실제 재채점 로직은 test_recommendation_pipeline.py가 커버)."""
    captured: dict[str, object] = {}

    async def _fake_rerank(
        first_pass, weather_condition, concentration, *, seek, weather_reason=None
    ):
        captured["seek"] = seek
        return first_pass

    monkeypatch.setattr(module, "rerank_with_concentration", _fake_rerank)

    provider = RealRecommendationProvider()
    conditions = UserConditions(concentration_intent=ConcentrationIntent.SEEK)
    context = _context(place_ids=["a"])

    await provider.rerank_with_concentration(
        conditions, context, _empty_first_pass(), _unavailable_concentration()
    )

    assert captured["seek"] is True


@pytest.mark.asyncio
async def test_rerank_with_concentration_derives_seek_false_from_avoid_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_rerank(
        first_pass, weather_condition, concentration, *, seek, weather_reason=None
    ):
        captured["seek"] = seek
        return first_pass

    monkeypatch.setattr(module, "rerank_with_concentration", _fake_rerank)

    provider = RealRecommendationProvider()
    conditions = UserConditions(concentration_intent=ConcentrationIntent.AVOID)
    context = _context(place_ids=["a"])

    await provider.rerank_with_concentration(
        conditions, context, _empty_first_pass(), _unavailable_concentration()
    )

    assert captured["seek"] is False


@pytest.mark.asyncio
async def test_rerank_with_concentration_uses_resolve_weather_condition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-051: 2차 Scoring도 1차와 동일하게 resolve_weather_condition()으로 날씨를
    판정해야 한다. 옛 to_weather_condition()(C가 조회 당시 내린 3단계 condition을
    그대로 읽는 방식)은 weather_intent(AVOID/ENJOY) 재해석을 반영하지 못했다 —
    여기서는 ENJOY + 비 예보가 GOOD으로 반전되는지로 그 재해석이 실제로 적용됐는지
    확인한다(그대로 BAD가 나오면 옛 방식으로 되돌아간 것).
    """
    captured: dict[str, object] = {}

    async def _fake_rerank(
        first_pass, weather_condition, concentration, *, seek, weather_reason=None
    ):
        captured["weather_condition"] = weather_condition
        captured["weather_reason"] = weather_reason
        return first_pass

    monkeypatch.setattr(module, "rerank_with_concentration", _fake_rerank)

    provider = RealRecommendationProvider()
    # context.weather는 비워둔다 — AVOID/ENJOY라 C가 조회를 생략하고 발화 값을 쓴
    # 상황(tool_rules.py)을 재현한다. resolve_weather_condition()은 이때
    # conditions.weather로 대신 판정해야 한다.
    conditions = UserConditions(
        weather_intent=WeatherIntent.ENJOY, weather=StatedWeather.RAIN
    )
    context = _context(place_ids=["a"])

    await provider.rerank_with_concentration(
        conditions, context, _empty_first_pass(), _unavailable_concentration()
    )

    assert captured["weather_condition"] == WeatherCondition.GOOD
    assert captured["weather_reason"] == "rain"


# --- 도보 실측 전달 가드 (feat/walking-duration-scoring) --------------------

_WALKING_ROUTE = WalkingRoute(
    place_id="a",
    status=RouteStatus.SUCCESS,
    source=RouteSource.KAKAO_WALKING,
    distance_m=400,
    duration_seconds=340,
)


async def _captured_walking_routes(
    monkeypatch: pytest.MonkeyPatch,
    conditions: UserConditions,
) -> object:
    captured: dict[str, object] = {}
    original = module.score_prepared_recommendation

    async def _capture(prepared, **kwargs):
        captured.update(kwargs)
        return await original(prepared, **kwargs)

    monkeypatch.setattr(module, "score_prepared_recommendation", _capture)

    provider = RealRecommendationProvider()
    prepared = await provider.prepare(
        conditions,
        _context(place_ids=["a"]),
        excluded_place_ids=[],
        visit_at=module.datetime.now(module._KST),
    )
    await provider.score_prepared(
        conditions, prepared, walking_routes=(_WALKING_ROUTE,)
    )
    return captured["walking_routes"]


@pytest.mark.asyncio
async def test_walking_routes_are_used_when_transport_is_walk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes = await _captured_walking_routes(
        monkeypatch, UserConditions(transport=Transport.WALK, max_travel_time=30)
    )

    assert routes == (_WALKING_ROUTE,)


@pytest.mark.asyncio
async def test_walking_routes_are_used_when_travel_time_is_unspecified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """이동시간을 말하지 않으면 기본 반경(2.0km)이라 도보 시간으로 재도 맞는다."""
    routes = await _captured_walking_routes(monkeypatch, UserConditions())

    assert routes == (_WALKING_ROUTE,)


@pytest.mark.asyncio
async def test_walking_routes_are_dropped_for_non_walking_travel_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """차·대중교통 + 이동시간이면 반경이 20km/h 기준이라 도보 시간과 단위가 안 맞는다.

    이때 실측을 쓰면 차로 금방 가는 곳까지 멀다고 깎이므로 직선거리를 유지한다.
    """
    routes = await _captured_walking_routes(
        monkeypatch, UserConditions(transport=Transport.CAR, max_travel_time=30)
    )

    assert routes == ()
