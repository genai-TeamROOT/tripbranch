"""명시적으로 허용했을 때만 실제 외부 API를 호출하는 Provider Smoke Test."""

from __future__ import annotations

import os

import httpx
import pytest

from app.config import Settings
from app.providers.concentration import RealConcentrationProvider
from app.providers.geocoding import RealGeocodingProvider
from app.providers.real_place import RealPlaceProvider
from app.providers.weather import RealWeatherProvider

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
        result = await provider.geocode("경복궁")

    assert 37.0 < result.latitude < 38.0
    assert 126.0 < result.longitude < 128.0
    print(
        f"Naver Geocoding: {result.resolved_name} "
        f"({result.latitude:.4f}, {result.longitude:.4f})"
    )


async def test_kma_weather_real_smoke() -> None:
    async with httpx.AsyncClient() as client:
        provider = RealWeatherProvider(
            api_key=_required_value("WEATHER_API_KEY", settings.weather_api_key),
            client=client,
        )
        result = await provider.get_current_condition(37.5788, 126.9770)

    assert result.value in {"good", "neutral", "bad"}
    print(f"KMA Weather: condition={result.value}")


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

    assert result
    assert all(candidate.place_id and candidate.name for candidate in result)
    sample_names = ", ".join(candidate.name for candidate in result[:3])
    print(f"TourAPI Places: count={len(result)}, samples=[{sample_names}]")


async def test_tour_api_concentration_real_smoke() -> None:
    async with httpx.AsyncClient() as client:
        provider = RealConcentrationProvider(
            api_key=_tour_api_service_key(),
            client=client,
        )
        result = await provider.get_forecast("11", "11110", "경복궁")

    assert result.area_code == "11"
    assert result.district_code == "11110"
    assert result.requested_place_name == "경복궁"
    assert result.forecasts
    assert any(forecast.concentration_rate is not None for forecast in result.forecasts)
    print(f"TourAPI Concentration: forecasts={len(result.forecasts)}")
