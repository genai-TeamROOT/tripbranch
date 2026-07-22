from __future__ import annotations

import pytest

from app.domain.models import GeocodeResult, WeatherCondition
from app.providers.concentration import FakeConcentrationProvider
from app.providers.geocoding import FakeGeocodingProvider
from app.providers.stub import FakePlaceProvider, FakeWeatherProvider


@pytest.mark.asyncio
async def test_fake_geocoding_provider_uses_common_result() -> None:
    result = await FakeGeocodingProvider().geocode("경복궁")

    assert result == GeocodeResult(
        query="경복궁",
        resolved_name="경복궁",
        latitude=37.5788,
        longitude=126.9770,
    )


@pytest.mark.asyncio
async def test_fake_weather_provider_uses_common_condition() -> None:
    result = await FakeWeatherProvider(WeatherCondition.BAD).get_current_condition(
        37.5796, 126.9770
    )

    assert result is WeatherCondition.BAD


@pytest.mark.asyncio
async def test_fake_place_provider_uses_common_candidate() -> None:
    result = await FakePlaceProvider().search_places(
        latitude=37.5796,
        longitude=126.9770,
        preferred_categories=["museum"],
        search_radius_km=1.0,
    )

    assert result[0].raw_source == "fake_place"
    assert result[0].latitude == 37.5796


@pytest.mark.asyncio
async def test_fake_concentration_provider_uses_common_result() -> None:
    result = await FakeConcentrationProvider().get_forecast("11", "11110", "경복궁")

    assert result.provider == "fake_concentration"
    assert result.forecasts
