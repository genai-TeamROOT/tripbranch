import pytest
from fixtures.recommendation_pipeline_fixture_v1 import (
    VISIT_AT,
    ManyPlacesProvider,
    RecordingConcentrationProvider,
    SucceedingWeatherProvider,
    UnavailableWeatherProvider,
    build_tools,
)

from app.domain.models import PlaceDetails, WeatherCondition
from app.domain.operating_hours import normalize_operating_schedule
from app.providers.contracts import ProviderResult, ProviderSource, provider_result
from app.schemas import PlaceCandidate
from app.services.recommendation_pipeline import (
    RecommendationPipelineRequest,
    run_recommendation_pipeline,
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
        build_tools(places, concentration),
        timer=lambda: next(timer_values),
    )

    returned = (
        result.response.recommendations
        + result.response.unverified_recommendations
    )
    assert len(returned) == 5
    assert concentration.place_names == [f"장소 {index}" for index in range(5)]
    assert len(result.concentrations) == 5
    assert result.context.concentration is not None
    assert result.context.concentration.status is ToolStatus.NO_DATA
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
