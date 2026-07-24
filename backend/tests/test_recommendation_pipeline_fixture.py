import pytest
from fixtures.recommendation_pipeline_fixture_v1 import (
    RECOMMENDATION_PIPELINE_FIXTURE_V1,
    VISIT_AT,
    ManyPlacesProvider,
    RecommendationPipelineFixtureCase,
    RecordingConcentrationProvider,
    build_tools,
    weather_provider_for,
)

from app.services.recommendation_pipeline import (
    RecommendationPipelineRequest,
    run_recommendation_pipeline,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", RECOMMENDATION_PIPELINE_FIXTURE_V1, ids=lambda case: case.name
)
async def test_pipeline_fixture_weather_weight_matches_expectation(
    case: RecommendationPipelineFixtureCase,
) -> None:
    result = await run_recommendation_pipeline(
        RecommendationPipelineRequest(
            location_query="경복궁",
            preferred_categories=("museum",),
            search_radius_km=2.0,
            visit_at=VISIT_AT,
        ),
        build_tools(
            ManyPlacesProvider(),
            RecordingConcentrationProvider(),
            weather_provider=weather_provider_for(case),
        ),
    )

    returned = (
        result.response.recommendations + result.response.unverified_recommendations
    )
    assert returned
    assert all(
        ("weather" in item.weights_used) == case.expect_weather_in_weights
        for item in returned
    )
