"""설정에 따라 공통 계약을 만족하는 Stub/Real Provider를 생성한다."""

from __future__ import annotations

import httpx

from app.config import settings
from app.domain.models import WeatherCondition
from app.providers.concentration import FakeConcentrationProvider, RealConcentrationProvider
from app.providers.geocoding import FakeGeocodingProvider, RealGeocodingProvider
from app.providers.holiday import FakeHolidayProvider, RealHolidayProvider
from app.providers.protocols import (
    ConcentrationProvider,
    GeocodingProvider,
    HolidayProvider,
    PlaceProvider,
    WeatherProvider,
)
from app.providers.real_place import RealPlaceProvider
from app.providers.stub import FakePlaceProvider, FakeWeatherProvider
from app.providers.weather import RealWeatherProvider


def _require_key(value: str, variable_name: str) -> str:
    if not value:
        raise ValueError(f"{variable_name} 환경변수가 필요합니다.")
    return value


def get_geocoding_provider(client: httpx.AsyncClient) -> GeocodingProvider:
    mode = settings.resolved_geocoding_provider
    if mode == "fake":
        return FakeGeocodingProvider()
    if mode == "real":
        return RealGeocodingProvider(
            api_key_id=_require_key(settings.naver_map_client_id, "NAVER_MAP_CLIENT_ID"),
            api_key=_require_key(settings.naver_map_client_secret, "NAVER_MAP_CLIENT_SECRET"),
            client=client,
            timeout_seconds=settings.external_api_timeout_seconds,
        )
    raise ValueError(f"지원하지 않는 GEOCODING_PROVIDER: {mode}")


def get_weather_provider(client: httpx.AsyncClient) -> WeatherProvider:
    mode = settings.resolved_weather_provider
    if mode == "fake":
        try:
            condition = WeatherCondition(settings.fake_weather_condition)
        except ValueError as exc:
            raise ValueError(
                f"지원하지 않는 FAKE_WEATHER_CONDITION: {settings.fake_weather_condition}"
            ) from exc
        return FakeWeatherProvider(condition)
    if mode == "real":
        return RealWeatherProvider(
            api_key=_require_key(settings.weather_api_key, "WEATHER_API_KEY"),
            client=client,
            timeout_seconds=settings.external_api_timeout_seconds,
        )
    raise ValueError(f"지원하지 않는 WEATHER_PROVIDER: {mode}")


def get_place_provider(client: httpx.AsyncClient) -> PlaceProvider:
    mode = settings.resolved_place_provider
    if mode == "fake":
        return FakePlaceProvider()
    if mode == "real":
        return RealPlaceProvider(
            api_key=_require_key(settings.tour_api_service_key, "TOUR_API_SERVICE_KEY"),
            client=client,
            timeout_seconds=settings.external_api_timeout_seconds,
        )
    raise ValueError(f"지원하지 않는 PLACE_PROVIDER: {mode}")


def get_concentration_provider(client: httpx.AsyncClient) -> ConcentrationProvider:
    mode = settings.resolved_concentration_provider
    if mode == "fake":
        return FakeConcentrationProvider()
    if mode == "real":
        return RealConcentrationProvider(
            api_key=_require_key(settings.tour_api_service_key, "TOUR_API_SERVICE_KEY"),
            client=client,
            timeout_seconds=settings.external_api_timeout_seconds,
        )
    raise ValueError(f"지원하지 않는 CONCENTRATION_PROVIDER: {mode}")


def get_holiday_provider(client: httpx.AsyncClient) -> HolidayProvider:
    mode = settings.resolved_holiday_provider
    if mode == "fake":
        return FakeHolidayProvider()
    if mode == "real":
        return RealHolidayProvider(
            api_key=_require_key(settings.tour_api_service_key, "TOUR_API_SERVICE_KEY"),
            client=client,
            timeout_seconds=settings.external_api_timeout_seconds,
        )
    raise ValueError(f"지원하지 않는 HOLIDAY_PROVIDER: {mode}")
