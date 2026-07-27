import pytest
from fixtures.recommendation_pipeline_fixture_v1 import (
    VISIT_AT,
    ManyPlacesProvider,
    RecordingConcentrationProvider,
    SucceedingWeatherProvider,
    UnavailableWeatherProvider,
    build_tools,
)

from app.domain.models import WeatherCondition
from app.services.recommendation_pipeline import (
    RecommendationPipelineRequest,
    run_recommendation_pipeline,
)
from app.tools.contracts import ToolStatus


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
