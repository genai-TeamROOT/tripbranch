# 환경변수 기반 앱 설정(Settings). pydantic-settings의 BaseSettings를 사용해 .env를 읽는다.
# 사용법: 코드에서는 직접 os.environ을 읽지 말고 `get_settings()`를 통해서만 값을 가져온다
# (lru_cache로 프로세스당 한 번만 파싱됨). 새 환경변수가 필요하면 여기 필드를 추가하고
# backend/.env.example에도 같이 반영할 것.
# TODO: real provider 전환 시 필요한 API 키 필드가 더 늘어날 수 있음(현재는 3개 서비스 키만 존재).

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderMode = Literal["fake", "real"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"

    llm_provider: ProviderMode = "fake"
    weather_provider: ProviderMode = "fake"
    place_provider: ProviderMode = "fake"
    geocoding_provider: ProviderMode = "fake"

    llm_api_key: str | None = None
    weather_api_key: str | None = None
    place_api_key: str | None = None

    database_url: str | None = None

    external_api_timeout_seconds: float = 10.0
    external_api_retry_count: int = 2

    fake_weather_condition: Literal["good", "neutral", "bad"] = "neutral"

    # ISO 8601 naive datetime string. Used by api/deps.py's get_clock() to build a
    # FixedClock when place_provider is fake, so recommendation results are
    # reproducible regardless of the real wall-clock time (see core/clock.py).
    # 2026-07-15 is a Wednesday; 14:00 is a normal weekday afternoon where most
    # fake places in providers/fake/places_data.py are open with plenty of time left.
    fake_current_datetime: str = "2026-07-15T14:00:00"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
