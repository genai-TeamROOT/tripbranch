"""설정에 따라 공통 계약을 만족하는 Stub/Real Provider를 생성한다.

provider 모드 문자열 자체의 유효성은 Settings(app.config)가 Literal로 보장하므로
여기서는 "real" 모드에 필요한 자격증명 유무만 확인한다. 부팅 시점 일괄 검증은
validate_provider_config()가 담당한다.
"""

from __future__ import annotations

import httpx

from app.config import Settings, settings
from app.providers.concentration import FakeConcentrationProvider, RealConcentrationProvider
from app.providers.gemini import RealGeminiProvider
from app.providers.geocoding import FakeGeocodingProvider, RealGeocodingProvider
from app.providers.holiday import FakeHolidayProvider, RealHolidayProvider
from app.providers.protocols import (
    ConcentrationProvider,
    GeocodingProvider,
    HolidayProvider,
    LLMProvider,
    PlaceProvider,
    WeatherProvider,
)
from app.providers.real_place import RealPlaceProvider
from app.providers.stub import FakeLLMProvider, FakePlaceProvider, FakeWeatherProvider
from app.providers.weather import RealWeatherProvider


def _require_key(value: str, variable_name: str) -> str:
    if not value:
        raise ValueError(f"{variable_name} 환경변수가 필요합니다.")
    return value


def get_llm_provider() -> LLMProvider:
    if settings.resolved_llm_provider == "fake":
        return FakeLLMProvider()
    return RealGeminiProvider(
        api_key=_require_key(settings.llm_api_key, "LLM_API_KEY"),
        model_name=settings.llm_model_name,
        timeout_seconds=settings.external_api_timeout_seconds,
        max_retries=settings.external_api_retry_count,
    )


def get_geocoding_provider(client: httpx.AsyncClient) -> GeocodingProvider:
    if settings.resolved_geocoding_provider == "fake":
        return FakeGeocodingProvider()
    return RealGeocodingProvider(
        api_key_id=_require_key(settings.naver_map_client_id, "NAVER_MAP_CLIENT_ID"),
        api_key=_require_key(settings.naver_map_client_secret, "NAVER_MAP_CLIENT_SECRET"),
        client=client,
        timeout_seconds=settings.external_api_timeout_seconds,
    )


def get_weather_provider(client: httpx.AsyncClient) -> WeatherProvider:
    if settings.resolved_weather_provider == "fake":
        return FakeWeatherProvider(settings.fake_weather_condition)
    return RealWeatherProvider(
        api_key=_require_key(settings.weather_api_key, "WEATHER_API_KEY"),
        client=client,
        timeout_seconds=settings.external_api_timeout_seconds,
    )


def get_place_provider(client: httpx.AsyncClient) -> PlaceProvider:
    if settings.resolved_place_provider == "fake":
        return FakePlaceProvider()
    return RealPlaceProvider(
        api_key=_require_key(settings.tour_api_service_key, "TOUR_API_SERVICE_KEY"),
        client=client,
        timeout_seconds=settings.external_api_timeout_seconds,
    )


def get_concentration_provider(client: httpx.AsyncClient) -> ConcentrationProvider:
    if settings.resolved_concentration_provider == "fake":
        return FakeConcentrationProvider()
    return RealConcentrationProvider(
        api_key=_require_key(settings.tour_api_service_key, "TOUR_API_SERVICE_KEY"),
        client=client,
        timeout_seconds=settings.external_api_timeout_seconds,
    )


def get_holiday_provider(client: httpx.AsyncClient) -> HolidayProvider:
    if settings.resolved_holiday_provider == "fake":
        return FakeHolidayProvider()
    return RealHolidayProvider(
        api_key=_require_key(settings.tour_api_service_key, "TOUR_API_SERVICE_KEY"),
        client=client,
        timeout_seconds=settings.external_api_timeout_seconds,
    )


# (환경변수명, 값 getter) — "real" 모드에서 반드시 채워져야 하는 자격증명 목록.
_REQUIRED_KEYS: dict[str, tuple[tuple[str, str], ...]] = {
    "LLM_PROVIDER": (("LLM_API_KEY", "llm_api_key"),),
    "WEATHER_PROVIDER": (("WEATHER_API_KEY", "weather_api_key"),),
    "PLACE_PROVIDER": (("TOUR_API_SERVICE_KEY", "tour_api_service_key"),),
    "CONCENTRATION_PROVIDER": (("TOUR_API_SERVICE_KEY", "tour_api_service_key"),),
    "HOLIDAY_PROVIDER": (("TOUR_API_SERVICE_KEY", "tour_api_service_key"),),
    "GEOCODING_PROVIDER": (
        ("NAVER_MAP_CLIENT_ID", "naver_map_client_id"),
        ("NAVER_MAP_CLIENT_SECRET", "naver_map_client_secret"),
    ),
}

_RESOLVED_ATTRS: dict[str, str] = {
    "LLM_PROVIDER": "resolved_llm_provider",
    "WEATHER_PROVIDER": "resolved_weather_provider",
    "PLACE_PROVIDER": "resolved_place_provider",
    "CONCENTRATION_PROVIDER": "resolved_concentration_provider",
    "HOLIDAY_PROVIDER": "resolved_holiday_provider",
    "GEOCODING_PROVIDER": "resolved_geocoding_provider",
}


def validate_provider_config(target: Settings | None = None) -> None:
    """real 모드 provider에 필요한 자격증명이 모두 있는지 부팅 시점에 확인한다.

    누락된 항목을 하나씩 발견해 재배포하는 왕복을 없애기 위해 전부 모아서 보고한다.
    Settings 자체에 넣지 않는 이유: 설정 해석만 검증하는 테스트가 자격증명 없이
    Settings(provider_mode="real")을 만들 수 있어야 한다.
    """
    current = target if target is not None else settings
    # 같은 키를 여러 provider가 공유하므로(TOUR_API_SERVICE_KEY) 키 기준으로 모아
    # 어느 provider 때문에 필요한지 함께 보고한다.
    required_by: dict[str, list[str]] = {}
    for provider_variable, required in _REQUIRED_KEYS.items():
        if getattr(current, _RESOLVED_ATTRS[provider_variable]) != "real":
            continue
        for variable_name, attribute in required:
            if not getattr(current, attribute):
                required_by.setdefault(variable_name, []).append(provider_variable)
    if required_by:
        missing = [
            f"{variable_name} ({', '.join(providers)}=real)"
            for variable_name, providers in required_by.items()
        ]
        raise ValueError(
            "real provider 설정에 필요한 환경변수가 비어 있습니다: " + ", ".join(missing)
        )
