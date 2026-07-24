"""TripBranch 백엔드 환경 설정 진입점.

역할: 환경 변수 기반 설정을 한 곳에서 읽어 서비스와 앱 초기화에 제공한다.
입력: 프로세스 환경 변수와 선택적인 .env 값.
출력: 앱 전역에서 재사용할 Settings 인스턴스.
호출 시점: 앱 부팅 또는 provider/API 키가 필요한 서비스 초기화 시 사용된다.
TODO: 실제 외부 API 연동 시 provider별 캐시 설정을 추가한다.
"""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    app_env: str = "local"

    # Provider selection: 개별 값이 비어 있으면 provider_mode를 공통 기본값으로 사용한다.
    provider_mode: str = "fake"
    llm_provider: str | None = None
    weather_provider: str | None = None
    place_provider: str | None = None
    geocoding_provider: str | None = None
    concentration_provider: str | None = None
    holiday_provider: str | None = None

    # LLM_PROVIDER=real일 때 사용할 Gemini 모델명.
    llm_model_name: str = "gemini-2.5-flash"

    # Only required when the corresponding *_provider above is set to "real".
    llm_api_key: str = Field(default="", repr=False, exclude=True)
    weather_api_key: str = Field(default="", repr=False, exclude=True)
    tour_api_service_key: str = Field(
        default="",
        validation_alias=AliasChoices("TOUR_API_SERVICE_KEY", "PLACE_API_KEY"),
        repr=False,
        exclude=True,
    )
    naver_map_client_id: str = Field(default="", repr=False, exclude=True)
    naver_map_client_secret: str = Field(default="", repr=False, exclude=True)
    supabase_url: str = ""
    supabase_secret_key: str = Field(default="", repr=False, exclude=True)

    # Real provider HTTP behavior (ignored by fake providers).
    external_api_timeout_seconds: float = 10.0
    external_api_retry_count: int = 2

    # Recommendation pipeline budgets
    recommendation_result_limit: int = 5
    recommendation_candidate_limit: int = 10

    # Place synchronization policy.
    place_sync_page_size: int = 100
    place_sync_detail_concurrency: int = 5
    place_sync_detail_ttl_days: int = 30
    place_sync_area_code: str = "11"
    place_sync_district_code: str = "110"

    # Fake-provider-only knobs
    fake_weather_condition: str = "neutral"
    fake_current_datetime: str = "2026-07-15T14:00:00"

    @property
    def resolved_llm_provider(self) -> str:
        return self.llm_provider or self.provider_mode

    @property
    def resolved_weather_provider(self) -> str:
        return self.weather_provider or self.provider_mode

    @property
    def resolved_place_provider(self) -> str:
        return self.place_provider or self.provider_mode

    @property
    def resolved_geocoding_provider(self) -> str:
        return self.geocoding_provider or self.provider_mode

    @property
    def resolved_concentration_provider(self) -> str:
        return self.concentration_provider or self.provider_mode

    @property
    def resolved_holiday_provider(self) -> str:
        return self.holiday_provider or self.provider_mode


settings = Settings()
