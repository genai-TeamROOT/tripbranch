from datetime import UTC, datetime

import pytest
from fixtures.recommendation_pipeline_fixture_v1 import (
    VISIT_AT,
    ManyPlacesProvider,
    RecordingConcentrationProvider,
    SucceedingWeatherProvider,
    UnavailableWeatherProvider,
    build_tools,
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
from app.domain.models import PlaceDetails, WeatherCondition
from app.domain.operating_hours import normalize_operating_schedule
from app.errors import AppError
from app.providers.contracts import ProviderResult, ProviderSource, provider_result
from app.schemas import PlaceCandidate
from app.services.recommendation_pipeline import (
    RecommendationPipelineRequest,
    run_recommendation_pipeline,
    run_recommendation_pipeline_from_context,
)
from app.tools.contracts import ToolStatus

_WEATHER_MISSING_WARNING = "현재 날씨 정보를 확인하지 못해 이 조건은 반영되지 않았어요."
_NO_NOTABLE_EXPLANATION_WARNING = (
    "이 장소는 특별히 강조할 만한 조건은 없지만, 조건에 맞아 추천했어요."
)


class _AllFeaturesBelowThresholdProvider:
    """weather·remaining_operating_time·distance가 모두 0.7 미만이 되도록
    설계한 단일 후보(약 1km 거리, 마감 60분 전, 실외+BAD 날씨 조합)를 반환한다.
    """

    async def search_places(
        self,
        latitude: float,
        longitude: float,
        preferred_categories: list[str],
        search_radius_km: float,
        category_filter=None,
        limit: int = 20,
    ) -> ProviderResult[list[PlaceCandidate]]:
        candidates = [
            PlaceCandidate(
                place_id="low-score-park",
                content_type_id="14",
                name="애매한 공원",
                category="park",
                latitude=latitude + 0.009,  # 약 1km
                longitude=longitude,
                raw_source="test",
            )
        ]
        return provider_result(candidates, source=ProviderSource.FAKE_PLACE)

    async def get_details(
        self,
        content_id: str,
        content_type_id: str,
    ) -> ProviderResult[PlaceDetails]:
        return provider_result(
            PlaceDetails(
                content_id=content_id,
                content_type_id=content_type_id,
                title=content_id,
                address=None,
                overview="상세정보",
                homepage=None,
                telephone=None,
                operating_hours="09:00~13:00",
                rest_date=None,
                raw_common={},
                raw_intro={},
                provider="fake_place",
                operating_schedule=normalize_operating_schedule(
                    content_type_id=content_type_id,
                    operating_hours="09:00~13:00",
                    rest_date=None,
                ),
            ),
            source=ProviderSource.FAKE_PLACE,
        )


@pytest.mark.asyncio
async def test_pipeline_scores_then_checks_only_top_five_concentrations() -> None:
    places = ManyPlacesProvider()
    concentration = RecordingConcentrationProvider()
    timer_values = iter((10.0, 10.25))
    result = await run_recommendation_pipeline(
        RecommendationPipelineRequest(
            location_query="경복궁",
            preferred_categories=("museum",),
            search_radius_km=2.0,
            visit_at=VISIT_AT,
        ),
        build_tools(
            places,
            concentration,
            weather_provider=SucceedingWeatherProvider(WeatherCondition.NEUTRAL),
        ),
        timer=lambda: next(timer_values),
    )

    returned = (
        result.response.recommendations
        + result.response.unverified_recommendations
    )
    assert len(returned) == 5
    assert concentration.place_names == [f"장소 {index}" for index in range(5)]
    assert len(result.concentrations) == 5
    assert result.context.location is not None
    assert result.context.location.status is ToolStatus.SUCCESS
    assert result.context.location.data is not None
    assert result.context.weather is not None
    assert result.context.weather.status is ToolStatus.SUCCESS
    assert result.context.weather.data is not None
    assert result.context.places is not None
    assert result.context.places.status is ToolStatus.SUCCESS
    assert result.context.places.data is not None
    assert result.context.concentration is not None
    assert result.context.concentration.status is ToolStatus.NO_DATA
    assert result.context.concentration.data is None
    assert result.context.holidays is not None
    assert result.context.holidays.status is ToolStatus.NO_DATA
    assert result.context.holidays.data is None
    assert result.context.provider_metadata
    assert result.response.elapsed_ms == 250.0


@pytest.mark.asyncio
async def test_pipeline_continues_with_redistributed_weights_when_weather_fails() -> None:
    places = ManyPlacesProvider()
    concentration = RecordingConcentrationProvider()
    result = await run_recommendation_pipeline(
        RecommendationPipelineRequest(
            location_query="경복궁",
            preferred_categories=("museum",),
            search_radius_km=2.0,
            visit_at=VISIT_AT,
        ),
        build_tools(
            places,
            concentration,
            weather_provider=UnavailableWeatherProvider(),
        ),
    )

    assert result.response.recommendations
    assert result.context.weather is not None
    assert result.context.weather.status is ToolStatus.UNAVAILABLE
    assert result.context.weather.data is None
    assert result.context.weather.error is not None
    assert all(
        "weather" not in item.weights_used
        for item in result.scoring.ranked
    )


@pytest.mark.asyncio
async def test_pipeline_includes_weather_weight_when_weather_succeeds() -> None:
    places = ManyPlacesProvider()
    concentration = RecordingConcentrationProvider()
    result = await run_recommendation_pipeline(
        RecommendationPipelineRequest(
            location_query="경복궁",
            preferred_categories=("museum",),
            search_radius_km=2.0,
            visit_at=VISIT_AT,
        ),
        build_tools(
            places,
            concentration,
            weather_provider=SucceedingWeatherProvider(WeatherCondition.GOOD),
        ),
    )

    assert result.context.weather is not None
    assert result.context.weather.status is ToolStatus.SUCCESS
    assert result.response.recommendations
    assert all(
        "weather" in item.weights_used
        for item in result.scoring.ranked
    )
    assert all(
        item.feature_scores["weather"] is not None
        for item in result.response.recommendations
        + result.response.unverified_recommendations
    )


@pytest.mark.asyncio
async def test_pipeline_is_deterministic_for_identical_input() -> None:
    request = RecommendationPipelineRequest(
        location_query="경복궁",
        preferred_categories=("museum",),
        search_radius_km=2.0,
        visit_at=VISIT_AT,
    )

    def _run():
        return run_recommendation_pipeline(
            request,
            build_tools(ManyPlacesProvider(), RecordingConcentrationProvider()),
        )

    result_1 = await _run()
    result_2 = await _run()

    def _normalize(response):
        return [
            (item.place_id, item.score, item.weights_used, tuple(item.warnings))
            for item in response.recommendations + response.unverified_recommendations
        ]

    assert _normalize(result_1.response) == _normalize(result_2.response)


@pytest.mark.asyncio
async def test_pipeline_warns_when_weather_is_missing() -> None:
    places = ManyPlacesProvider()
    concentration = RecordingConcentrationProvider()
    result = await run_recommendation_pipeline(
        RecommendationPipelineRequest(
            location_query="경복궁",
            preferred_categories=("museum",),
            search_radius_km=2.0,
            visit_at=VISIT_AT,
        ),
        build_tools(
            places,
            concentration,
            weather_provider=UnavailableWeatherProvider(),
        ),
    )

    returned = (
        result.response.recommendations + result.response.unverified_recommendations
    )
    assert returned
    assert all(_WEATHER_MISSING_WARNING in item.warnings for item in returned)


@pytest.mark.asyncio
async def test_pipeline_warns_when_no_feature_is_notable() -> None:
    places = _AllFeaturesBelowThresholdProvider()
    concentration = RecordingConcentrationProvider()
    result = await run_recommendation_pipeline(
        RecommendationPipelineRequest(
            location_query="경복궁",
            preferred_categories=("park",),
            search_radius_km=2.0,
            visit_at=VISIT_AT,
        ),
        build_tools(
            places,
            concentration,
            weather_provider=SucceedingWeatherProvider(WeatherCondition.BAD),
        ),
    )

    assert len(result.response.recommendations) == 1
    item = result.response.recommendations[0]
    assert item.explanations == []
    assert _NO_NOTABLE_EXPLANATION_WARNING in item.warnings


# --- run_recommendation_pipeline_from_context() ----------------------------
#
# A가 C에서 받은 RecommendationContext를 그대로 넘기는 신규 진입점 검증.
# package_D/[A] RecommendationContext → RecommendationResponse 진입점 요청.txt

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
async def test_pipeline_from_context_handles_missing_weather() -> None:
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

    assert response.recommendations
    assert _WEATHER_MISSING_WARNING in response.recommendations[0].warnings


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
