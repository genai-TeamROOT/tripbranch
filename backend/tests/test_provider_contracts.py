from __future__ import annotations

import pytest

from app.domain.models import GeocodeResult, PlaceCategoryFilter, WeatherCondition
from app.providers.concentration import FakeConcentrationProvider
from app.providers.geocoding import FakeGeocodingProvider
from app.providers.holiday import FakeHolidayProvider
from app.providers.stub import FakePlaceProvider, FakeWeatherProvider


@pytest.mark.asyncio
async def test_fake_geocoding_provider_uses_common_result() -> None:
    result = await FakeGeocodingProvider().geocode("경복궁")

    assert result == GeocodeResult(
        query="경복궁",
        resolved_name="경복궁",
        latitude=37.5788,
        longitude=126.9770,
        administrative_district="종로구",
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

    cafe_result = await FakePlaceProvider().search_places(
        latitude=37.5796,
        longitude=126.9770,
        preferred_categories=["cafe"],
        search_radius_km=1.0,
        category_filter=PlaceCategoryFilter(
            content_type_id="39",
            lcls_systm1="FD",
            lcls_systm2="FD05",
            lcls_systm3="FD050100",
        ),
    )
    assert [candidate.content_type_id for candidate in cafe_result] == ["39"]
    assert cafe_result[0].lcls_systm1 == "FD"
    assert cafe_result[0].lcls_systm2 == "FD05"
    assert cafe_result[0].lcls_systm3 == "FD050100"

    keyword_result = await FakePlaceProvider().search_by_keyword("박물관")
    assert keyword_result[0].content_type_id == "14"

    details = await FakePlaceProvider().get_details("fake-museum-1", "14")
    assert details.title == "테스트 박물관"
    assert details.rest_date == "매주 월요일"

    named_details = await FakePlaceProvider().find_details_by_name("테스트 박물관")
    assert named_details.title == "테스트 박물관"


@pytest.mark.asyncio
async def test_fake_concentration_provider_uses_common_result() -> None:
    result = await FakeConcentrationProvider().get_forecast("11", "11110", "경복궁")

    assert result.provider == "fake_concentration"
    assert result.forecasts


@pytest.mark.asyncio
async def test_fake_holiday_provider_uses_common_result() -> None:
    result = await FakeHolidayProvider().get_holidays(2026)

    assert result.provider == "fake_holiday"
    assert result.entries
    assert result.holidays
