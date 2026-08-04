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
from app.providers.local_search import FakeLocalSearchProvider, RealLocalSearchProvider
from app.providers.protocols import (
    ConcentrationProvider,
    GeocodingProvider,
    HolidayProvider,
    LLMProvider,
    LocalSearchProvider,
    PlaceDetailsProvider,
    PlaceProvider,
    PlaceSearchProvider,
    WeatherProvider,
)
from app.providers.real_place import RealPlaceProvider
from app.providers.stub import FakeLLMProvider, FakePlaceProvider, FakeWeatherProvider
from app.providers.supabase_place_details import SupabasePlaceDetailsProvider
from app.providers.weather import RealWeatherProvider
from app.repositories.fake_places import FakePlaceLocationRepository
from app.repositories.supabase_places import SupabasePlaceRepository


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


def get_local_search_provider(client: httpx.AsyncClient) -> LocalSearchProvider:
    if settings.resolved_local_search_provider == "fake":
        return FakeLocalSearchProvider()
    return RealLocalSearchProvider(
        api_key_id=_require_key(
            settings.naver_local_search_client_id, "NAVER_LOCAL_SEARCH_CLIENT_ID"
        ),
        api_key=_require_key(
            settings.naver_local_search_client_secret,
            "NAVER_LOCAL_SEARCH_CLIENT_SECRET",
        ),
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


def get_place_search_provider(client: httpx.AsyncClient) -> PlaceSearchProvider:
    """장소 후보 목록 검색 provider. 상세조회 출처와 무관하게 기존 경로를 유지한다."""
    return get_place_provider(client)


def get_place_location_repository(
    client: httpx.AsyncClient,
) -> SupabasePlaceRepository | FakePlaceLocationRepository | None:
    """검색 중심점 해석에 사용할 places 저장소를 준비한다.

    Supabase 설정이 없는 개발·테스트 환경은 종로구 대표 장소를 담은 fake 저장소를
    쓴다. 집중률 조회는 매핑된 장소명으로만 나가므로(D-043) 저장소가 없으면 INFO
    혼잡도가 전부 no_data로 떨어져 fake 환경에서 경로 확인이 불가능해진다.
    """
    if (
        settings.resolved_place_provider != "real"
        or not settings.supabase_url.strip()
        or not settings.supabase_secret_key.strip()
    ):
        return FakePlaceLocationRepository()
    return SupabasePlaceRepository(
        supabase_url=settings.supabase_url,
        secret_key=settings.supabase_secret_key,
        client=client,
        timeout_seconds=settings.external_api_timeout_seconds,
    )


def get_place_details_provider(client: httpx.AsyncClient) -> PlaceDetailsProvider:
    """후보별 상세·운영정보 provider를 PLACE_DETAILS_SOURCE에 따라 고른다.

    supabase 모드는 요청 시 TourAPI fallback을 하지 않는다 — 저장소 장애는
    Tool에서 unavailable로 그대로 노출된다.
    """
    if settings.resolved_place_details_source == "supabase":
        return SupabasePlaceDetailsProvider(
            SupabasePlaceRepository(
                supabase_url=_require_key(settings.supabase_url, "SUPABASE_URL"),
                secret_key=_require_key(
                    settings.supabase_secret_key, "SUPABASE_SECRET_KEY"
                ),
                client=client,
                timeout_seconds=settings.external_api_timeout_seconds,
            )
        )
    return get_place_provider(client)


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
    "LOCAL_SEARCH_PROVIDER": (
        ("NAVER_LOCAL_SEARCH_CLIENT_ID", "naver_local_search_client_id"),
        ("NAVER_LOCAL_SEARCH_CLIENT_SECRET", "naver_local_search_client_secret"),
    ),
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
    "LOCAL_SEARCH_PROVIDER": "resolved_local_search_provider",
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

    # 상세조회 출처는 provider 모드와 축이 다르므로 별도로 검증한다.
    if current.resolved_place_details_source == "supabase":
        missing_supabase = [
            variable_name
            for variable_name, attribute in (
                ("SUPABASE_URL", "supabase_url"),
                ("SUPABASE_SECRET_KEY", "supabase_secret_key"),
            )
            if not getattr(current, attribute)
        ]
        if missing_supabase:
            raise ValueError(
                "PLACE_DETAILS_SOURCE=supabase에 필요한 환경변수가 비어 있습니다: "
                + ", ".join(missing_supabase)
            )

    # Package B State 저장소 백엔드도 provider 모드와 축이 다른 별도 설정이다.
    if current.state_store_backend == "supabase":
        missing_state_store = [
            variable_name
            for variable_name, attribute in (
                ("SUPABASE_URL", "supabase_url"),
                ("SUPABASE_SECRET_KEY", "supabase_secret_key"),
            )
            if not getattr(current, attribute)
        ]
        if missing_state_store:
            raise ValueError(
                "STATE_STORE_BACKEND=supabase에 필요한 환경변수가 비어 있습니다: "
                + ", ".join(missing_state_store)
            )