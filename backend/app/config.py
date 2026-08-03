"""TripBranch 백엔드 환경 설정 진입점.

역할: 환경 변수 기반 설정을 한 곳에서 읽어 서비스와 앱 초기화에 제공한다.
입력: 프로세스 환경 변수와 선택적인 .env 값.
출력: 앱 전역에서 재사용할 Settings 인스턴스.
호출 시점: 앱 부팅 또는 provider/API 키가 필요한 서비스 초기화 시 사용된다.
TODO: 실제 외부 API 연동 시 provider별 캐시 설정을 추가한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.models import WeatherCondition
from app.recommendation_limits import (
    DEFAULT_RECOMMENDATION_CANDIDATE_LIMIT,
    DEFAULT_RECOMMENDATION_RESULT_LIMIT,
    MAX_RECOMMENDATION_CANDIDATE_LIMIT,
    MIN_RECOMMENDATION_LIMIT,
)

ProviderMode = Literal["fake", "real"]
# 장소 후보 "검색"은 항상 PLACE_PROVIDER를 따르고, 후보별 상세·운영정보만 이 값으로
# 출처를 고른다. supabase는 미리 구축된 places 테이블, tour_api는 상세 API 직접 호출.
PlaceDetailsSource = Literal["supabase", "tour_api"]


# backend/.env. 상대경로로 두면 저장소 루트에서 서버를 띄웠을 때 .env를 찾지 못하고
# 오류 없이 전 Provider가 fake로 뜨므로, 실행 위치와 무관하게 같은 파일을 읽는다.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, extra="ignore", env_ignore_empty=True
    )

    app_env: str = "local"

    # Provider selection: 개별 값이 비어 있으면 provider_mode를 공통 기본값으로 사용한다.
    provider_mode: ProviderMode = "fake"
    llm_provider: ProviderMode | None = None
    weather_provider: ProviderMode | None = None
    place_provider: ProviderMode | None = None
    geocoding_provider: ProviderMode | None = None
    concentration_provider: ProviderMode | None = None
    holiday_provider: ProviderMode | None = None

    # 상세·운영정보 조회 출처. PLACE_PROVIDER=fake이면 Fake Provider가 상세까지
    # 담당하므로 이 값은 무시된다.
    place_details_source: PlaceDetailsSource = "tour_api"

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
    recommendation_result_limit: int = Field(
        default=DEFAULT_RECOMMENDATION_RESULT_LIMIT,
        ge=MIN_RECOMMENDATION_LIMIT,
        le=MAX_RECOMMENDATION_CANDIDATE_LIMIT,
    )
    recommendation_candidate_limit: int = Field(
        default=DEFAULT_RECOMMENDATION_CANDIDATE_LIMIT,
        ge=MIN_RECOMMENDATION_LIMIT,
        le=MAX_RECOMMENDATION_CANDIDATE_LIMIT,
    )

    # Place synchronization policy.
    place_sync_page_size: int = 100
    place_sync_detail_concurrency: int = 5
    place_sync_detail_ttl_days: int = 30
    place_sync_area_code: str = "11"
    place_sync_district_code: str = "110"

    # Fake-provider-only knobs
    fake_weather_condition: WeatherCondition = WeatherCondition.NEUTRAL
    fake_current_datetime: str = "2026-07-15T14:00:00"

    @model_validator(mode="after")
    def validate_recommendation_limits(self) -> Settings:
        if self.recommendation_result_limit > self.recommendation_candidate_limit:
            raise ValueError(
                "RECOMMENDATION_RESULT_LIMIT은 "
                "RECOMMENDATION_CANDIDATE_LIMIT 이하여야 합니다."
            )
        return self

    @property
    def resolved_llm_provider(self) -> ProviderMode:
        return self.llm_provider or self.provider_mode

    @property
    def resolved_weather_provider(self) -> ProviderMode:
        return self.weather_provider or self.provider_mode

    @property
    def resolved_place_provider(self) -> ProviderMode:
        return self.place_provider or self.provider_mode

    @property
    def resolved_geocoding_provider(self) -> ProviderMode:
        return self.geocoding_provider or self.provider_mode

    @property
    def resolved_concentration_provider(self) -> ProviderMode:
        return self.concentration_provider or self.provider_mode

    @property
    def resolved_holiday_provider(self) -> ProviderMode:
        return self.holiday_provider or self.provider_mode

    @property
    def resolved_place_details_source(self) -> PlaceDetailsSource:
        """fake 장소 모드에서는 상세도 Fake Provider가 담당한다."""
        if self.resolved_place_provider == "fake":
            return "tour_api"
        return self.place_details_source


settings = Settings()
