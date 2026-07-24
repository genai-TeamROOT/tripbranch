from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.domain.models import (
    ConcentrationResult,
    PlaceDetails,
    WeatherCondition,
    WeatherForecastResult,
)
from app.domain.operating_hours import normalize_operating_schedule
from app.errors import ProviderUnavailableError
from app.providers.contracts import (
    ProviderResult,
    ProviderSource,
    ProviderStatus,
    provider_result,
)
from app.providers.geocoding import FakeGeocodingProvider
from app.providers.holiday import FakeHolidayProvider
from app.providers.stub import FakeWeatherProvider
from app.schemas import PlaceCandidate
from app.services.recommendation_pipeline import (
    RecommendationPipelineRequest,
    RecommendationTools,
    run_recommendation_pipeline,
)
from app.tools.concentration import GetConcentrationTool
from app.tools.contracts import ToolStatus
from app.tools.holiday import GetHolidaysTool
from app.tools.nearby_place_details import NearbyPlaceDetailsTool
from app.tools.resolve_location import ResolveLocationTool
from app.tools.weather_forecast import GetWeatherForecastTool

KST = ZoneInfo("Asia/Seoul")
VISIT_AT = datetime(2026, 7, 24, 12, tzinfo=KST)


class ManyPlacesProvider:
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
                place_id=f"place-{index}",
                content_type_id="14",
                name=f"장소 {index}",
                category="museum",
                latitude=latitude + index * 0.001,
                longitude=longitude,
                raw_source="test",
            )
            for index in range(7)
        ][:limit]
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
                operating_hours="09:00~18:00",
                rest_date=None,
                raw_common={},
                raw_intro={},
                provider="fake_place",
                operating_schedule=normalize_operating_schedule(
                    content_type_id=content_type_id,
                    operating_hours="09:00~18:00",
                    rest_date=None,
                ),
            ),
            source=ProviderSource.FAKE_PLACE,
        )


class RecordingConcentrationProvider:
    def __init__(self) -> None:
        self.place_names: list[str] = []

    async def get_forecast(
        self,
        area_code: str,
        district_code: str,
        place_name: str | None = None,
    ) -> ProviderResult[ConcentrationResult]:
        self.place_names.append(place_name or "")
        return provider_result(
            ConcentrationResult(
                area_code=area_code,
                district_code=district_code,
                requested_place_name=place_name,
                forecasts=(),
                provider="fake_concentration",
            ),
            source=ProviderSource.FAKE_CONCENTRATION,
            status=ProviderStatus.NO_DATA,
        )


class UnavailableWeatherProvider:
    async def get_current_condition(self, latitude: float, longitude: float):
        raise ProviderUnavailableError("weather")

    async def get_forecast_slots(
        self,
        latitude: float,
        longitude: float,
    ) -> ProviderResult[WeatherForecastResult]:
        raise ProviderUnavailableError("weather")


def _tools(
    places: ManyPlacesProvider,
    concentration: RecordingConcentrationProvider,
    *,
    weather_provider=None,
) -> RecommendationTools:
    return RecommendationTools(
        location=ResolveLocationTool(FakeGeocodingProvider()),
        weather=GetWeatherForecastTool(
            weather_provider
            or FakeWeatherProvider(WeatherCondition.NEUTRAL)
        ),
        places=NearbyPlaceDetailsTool(places, places),
        concentration=GetConcentrationTool(concentration),
        holidays=GetHolidaysTool(FakeHolidayProvider()),
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
        _tools(places, concentration),
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
        _tools(
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
