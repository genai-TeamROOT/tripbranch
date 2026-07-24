"""명시적으로 허용했을 때만 실제 외부 API를 호출하는 Provider Smoke Test."""

from __future__ import annotations

import os

import httpx
import pytest

from app.config import Settings
from app.providers.concentration import RealConcentrationProvider
from app.providers.geocoding import RealGeocodingProvider
from app.providers.holiday import RealHolidayProvider
from app.providers.real_place import RealPlaceProvider
from app.providers.weather import RealWeatherProvider
from app.tools.resolve_location import (
    ResolutionMethod,
    ResolveLocationQuery,
    ResolveLocationStatus,
    ResolveLocationTool,
)
from app.tools.weather_forecast import (
    GetWeatherForecastTool,
    WeatherForecastQuery,
    WeatherToolStatus,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.smoke,
    pytest.mark.skipif(
        os.getenv("RUN_REAL_PROVIDER_TESTS") != "true",
        reason="RUN_REAL_PROVIDER_TESTS=true일 때만 실제 Provider를 호출합니다.",
    ),
]

settings = Settings()


def _required_value(name: str, value: str) -> str:
    if not value:
        pytest.skip(f"{name} 환경변수가 없습니다.")
    return value


def _tour_api_service_key() -> str:
    return _required_value("TOUR_API_SERVICE_KEY", settings.tour_api_service_key)


async def test_naver_geocoding_real_smoke() -> None:
    async with httpx.AsyncClient() as client:
        provider = RealGeocodingProvider(
            api_key_id=_required_value("NAVER_MAP_CLIENT_ID", settings.naver_map_client_id),
            api_key=_required_value(
                "NAVER_MAP_CLIENT_SECRET", settings.naver_map_client_secret
            ),
            client=client,
        )
        result = await ResolveLocationTool(provider).execute(
            ResolveLocationQuery("경복궁")
        )

    assert result.status is ResolveLocationStatus.SUCCESS
    assert result.location is not None
    assert result.location.resolution_method is ResolutionMethod.ALIAS
    assert 37.0 < result.location.latitude < 38.0
    assert 126.0 < result.location.longitude < 128.0
    print(
        f"Naver Geocoding: {result.location.resolved_name} "
        f"({result.location.latitude:.4f}, {result.location.longitude:.4f})"
    )


async def test_kma_weather_real_smoke() -> None:
    async with httpx.AsyncClient() as client:
        provider = RealWeatherProvider(
            api_key=_required_value("WEATHER_API_KEY", settings.weather_api_key),
            client=client,
        )
        result = await GetWeatherForecastTool(provider).execute(
            WeatherForecastQuery(37.5788, 126.9770)
        )

    assert result.status is WeatherToolStatus.SUCCESS
    assert result.forecast is not None
    assert result.forecast.condition.value in {"good", "neutral", "bad"}
    assert result.forecast.data_type == "forecast"
    assert result.forecast.observed_at is None
    print(
        "KMA Weather: "
        f"condition={result.forecast.condition.value}, "
        f"forecast_for={result.forecast.forecast_for.isoformat()}"
    )


async def test_tour_api_place_real_smoke() -> None:
    async with httpx.AsyncClient() as client:
        provider = RealPlaceProvider(
            api_key=_tour_api_service_key(),
            client=client,
        )
        result = await provider.search_places(
            latitude=37.5788,
            longitude=126.9770,
            preferred_categories=[],
            search_radius_km=1.0,
        )
        result = result.data

    assert result
    assert all(candidate.place_id and candidate.name for candidate in result)
    sample_names = ", ".join(candidate.name for candidate in result[:3])
    print(f"TourAPI Places: count={len(result)}, samples=[{sample_names}]")


async def test_tour_api_keyword_and_details_real_smoke() -> None:
    async with httpx.AsyncClient() as client:
        provider = RealPlaceProvider(
            api_key=_tour_api_service_key(),
            client=client,
        )
        details = await provider.find_details_by_name(
            "경복궁", region_code="11", district_code="110"
        )
        details = details.data

    assert details.title == "경복궁"
    print(
        f"TourAPI Keyword: content_id={details.content_id}, "
        f"content_type_id={details.content_type_id}, title={details.title}"
    )


async def test_tour_api_concentration_real_smoke() -> None:
    async with httpx.AsyncClient() as client:
        provider = RealConcentrationProvider(
            api_key=_tour_api_service_key(),
            client=client,
        )
        result = await provider.get_forecast("11", "11110", "경복궁")
        result = result.data

    assert result.area_code == "11"
    assert result.district_code == "11110"
    assert result.requested_place_name == "경복궁"
    assert result.forecasts
    assert any(forecast.concentration_rate is not None for forecast in result.forecasts)
    print(f"TourAPI Concentration: forecasts={len(result.forecasts)}")


async def test_kasi_holiday_real_smoke() -> None:
    async with httpx.AsyncClient() as client:
        provider = RealHolidayProvider(
            api_key=_tour_api_service_key(),
            client=client,
        )
        result = await provider.get_holidays(2026)
        result = result.data

    assert result.entries
    assert all(entry.date.startswith("2026") for entry in result.entries)
    print(
        f"KASI Holidays: entries={len(result.entries)}, "
        f"holidays={len(result.holidays)}"
    )
