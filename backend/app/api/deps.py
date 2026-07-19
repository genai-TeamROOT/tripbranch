# FastAPI 의존성 주입(Depends) 조립 지점.
# 역할: Settings.*_provider 값(fake/real)에 따라 Provider 구현체를 고르고, 그걸 주입받은
# Service 인스턴스를 만들어 라우트 핸들러에 넘겨준다. `Depends`는 프로젝트 전체에서
# 오직 이 파일과 routes/*.py에서만 사용한다 (services/domain은 절대 FastAPI를 모름).
# 사용법: 라우트에서 `service: XxxService = Depends(get_xxx_service)` 형태로 받는다.
# TODO: real provider가 늘어나면 provider 인스턴스 생성 비용이 커질 수 있으니,
# 요청마다 새로 만들지 말고 앱 시작 시 한 번만 생성하는 방식으로 바꾸는 걸 고려할 것
# (현재는 Settings가 pydantic BaseModel이라 단순 lru_cache가 안 먹어서 매번 생성함).

"""FastAPI dependency wiring.

`Depends` is only used at this layer (API), never inside services/domain.
Services always receive their Provider dependencies via constructor
injection, wired up here based on Settings.*_provider.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import Depends

from app.core.clock import Clock, FixedClock, SystemClock
from app.core.config import Settings, get_settings
from app.domain.models import WeatherCondition
from app.providers.fake.geocoding import FakeGeocodingProvider
from app.providers.fake.llm import FakeLlmProvider
from app.providers.fake.places import FakePlaceProvider
from app.providers.fake.weather import FakeWeatherProvider
from app.providers.protocols.geocoding import GeocodingProvider
from app.providers.protocols.llm import LlmProvider
from app.providers.protocols.place import PlaceProvider
from app.providers.protocols.weather import WeatherProvider
from app.providers.real.geocoding import RealGeocodingProvider
from app.providers.real.llm import RealLlmProvider
from app.providers.real.places import RealPlaceProvider
from app.providers.real.weather import RealWeatherProvider
from app.services.interpret_service import InterpretService
from app.services.recommendation_service import RecommendationService


def _get_geocoding_provider(settings: Settings) -> GeocodingProvider:
    if settings.geocoding_provider == "real":
        return RealGeocodingProvider(
            api_key=settings.place_api_key, timeout_seconds=settings.external_api_timeout_seconds
        )
    return FakeGeocodingProvider()


def _get_weather_provider(settings: Settings) -> WeatherProvider:
    if settings.weather_provider == "real":
        return RealWeatherProvider(
            api_key=settings.weather_api_key, timeout_seconds=settings.external_api_timeout_seconds
        )
    return FakeWeatherProvider(condition=WeatherCondition(settings.fake_weather_condition))


def _get_place_provider(settings: Settings) -> PlaceProvider:
    if settings.place_provider == "real":
        return RealPlaceProvider(
            api_key=settings.place_api_key, timeout_seconds=settings.external_api_timeout_seconds
        )
    return FakePlaceProvider()


def _get_llm_provider(settings: Settings) -> LlmProvider:
    if settings.llm_provider == "real":
        return RealLlmProvider(
            api_key=settings.llm_api_key, timeout_seconds=settings.external_api_timeout_seconds
        )
    return FakeLlmProvider()


def get_clock(settings: Settings = Depends(get_settings)) -> Clock:
    """Real provider environments get real time. Fake-place environments
    (local dev, tests, demos) get a fixed reproducible time by default, so
    recommendation results don't flip to empty depending on when someone
    happens to run the app (see core/clock.py)."""
    if settings.place_provider == "real":
        return SystemClock()
    return FixedClock(datetime.fromisoformat(settings.fake_current_datetime))


def get_interpret_service(settings: Settings = Depends(get_settings)) -> InterpretService:
    return InterpretService(llm_provider=_get_llm_provider(settings))


def get_recommendation_service(
    settings: Settings = Depends(get_settings),
) -> RecommendationService:
    return RecommendationService(
        geocoding_provider=_get_geocoding_provider(settings),
        weather_provider=_get_weather_provider(settings),
        place_provider=_get_place_provider(settings),
    )
