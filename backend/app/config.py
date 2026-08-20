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
# Package B의 State 저장소 백엔드. memory는 Phase 1 인메모리, supabase는
# Phase 2 DB 저장소(app/state/supabase_store.py). 서버 재시작 시 상태 보존이
# 필요해지는 시점에 supabase로 전환한다.
StateStoreBackend = Literal["memory", "supabase"]


# backend/.env. 상대경로로 두면 저장소 루트에서 서버를 띄웠을 때 .env를 찾지 못하고
# 오류 없이 전 Provider가 fake로 뜨므로, 실행 위치와 무관하게 같은 파일을 읽는다.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    # populate_by_name: validation_alias가 붙은 필드(TOUR_API_SERVICE_KEY, 폐지된 LLM
    # 모델 설정)를 테스트에서 필드명으로도 넣을 수 있게 한다. 별칭만 받으면 필드명을 쓴
    # 인자가 extra="ignore"에 조용히 먹혀 기본값인 채로 통과한다.
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, extra="ignore", env_ignore_empty=True, populate_by_name=True
    )

    app_env: str = "local"

    # Provider selection: 개별 값이 비어 있으면 provider_mode를 공통 기본값으로 사용한다.
    provider_mode: ProviderMode = "fake"
    llm_provider: ProviderMode | None = None
    weather_provider: ProviderMode | None = None
    place_provider: ProviderMode | None = None
    geocoding_provider: ProviderMode | None = None
    local_search_provider: ProviderMode | None = None
    concentration_provider: ProviderMode | None = None
    holiday_provider: ProviderMode | None = None
    # 비용이 발생할 수 있으므로 공통 PROVIDER_MODE를 상속하지 않고 명시적으로
    # real을 켤 때만 카카오맵 도보 API를 호출한다.
    travel_route_provider: ProviderMode = "fake"
    # 직선거리 fallback 예상시간에 쓸 보행속도(m/s).
    walking_speed_mps: float = Field(default=1.2, gt=0)
    travel_route_max_concurrency: int = Field(default=5, ge=1, le=10)

    # 상세·운영정보 조회 출처. PLACE_PROVIDER=fake이면 Fake Provider가 상세까지
    # 담당하므로 이 값은 무시된다.
    place_details_source: PlaceDetailsSource = "tour_api"

    # Package B State 저장소 백엔드. 기본값은 Phase 1 인메모리다.
    state_store_backend: StateStoreBackend = "memory"

    # 취향 근거 벡터 검색 사용 여부. 기본 off인 이유는 임베딩 모델이 선택
    # 의존성(`pip install -e ".[embeddings]"`)이고 서버 프로세스에 상주하기
    # 때문이다 — 실측 RSS 537MB, 적재 9.4초(2026-08-19). 모델을 올릴 수 없는
    # 배포에서도 서버는 떠야 하므로 켜는 쪽을 명시적 선택으로 둔다.
    taste_evidence_enabled: bool = False

    # 짧고 구조화된 판단(의도 분류·조건 추출)에 사용할 모델 묶음. 비용·지연이
    # 중요한 경로라 Lite를 기본으로 두되, 일시적 5xx/타임아웃에는 Flash로 폴백한다.
    llm_fast_model_name: str = "gemini-3.5-flash-lite"
    llm_fast_fallback_model_names: str = "gemini-3.5-flash"

    # 사용자에게 보여 줄 문장·비교·일정처럼 품질 비중이 큰 생성 경로의 모델 묶음.
    # 5xx/타임아웃 시에는 Lite로만 폴백하며, Real→Fake 전환은 하지 않는다(D-042).
    llm_generation_model_name: str = "gemini-3.5-flash"
    llm_generation_fallback_model_names: str = "gemini-3.5-flash-lite"

    # 음성 입력을 텍스트로 바꿀 때 사용할 Gemini 모델. 음성 전사는 채팅 답변 생성과
    # 독립 호출이라, 비용·지연 특성에 맞는 멀티모달 모델을 따로 둔다. gemini-3.5-flash는
    # 2026-08-18 한국어 대표 발화 실측에서 전사를 확인한 기본값이다.
    gemini_audio_model_name: str | None = None

    # 폐지된 단일 모델 설정. 값을 읽어 쓰는 곳은 없고, .env에 남아 있는지 감지하려고만
    # 선언한다 — extra="ignore"라 그냥 지우면 옛 설정이 조용히 안 먹는 상태가 되고,
    # `.env`만 보고 "이 모델로 돌고 있다"고 오판하게 된다. 실제로 역할별 설정이
    # 도입된 뒤 이 두 값은 파싱만 되고 아무도 읽지 않는 상태로 남아 있었다.
    # 검사는 validate_provider_config()에 있다(실패는 첫 요청이 아니라 부팅에서, D-042).
    legacy_llm_model_name: str | None = Field(
        default=None, validation_alias=AliasChoices("LLM_MODEL_NAME")
    )
    legacy_llm_fallback_model_names: str | None = Field(
        default=None, validation_alias=AliasChoices("LLM_FALLBACK_MODEL_NAMES")
    )

    # Only required when the corresponding *_provider above is set to "real".
    llm_api_key: str = Field(default="", repr=False, exclude=True)
    weather_api_key: str = Field(default="", repr=False, exclude=True)
    tour_api_service_key: str = Field(default="", repr=False, exclude=True)
    naver_map_client_id: str = Field(default="", repr=False, exclude=True)
    naver_map_client_secret: str = Field(default="", repr=False, exclude=True)
    naver_local_search_client_id: str = Field(default="", repr=False, exclude=True)
    naver_local_search_client_secret: str = Field(default="", repr=False, exclude=True)
    kakao_map_rest_api_key: str = Field(default="", repr=False, exclude=True)
    supabase_url: str = ""
    supabase_secret_key: str = Field(default="", repr=False, exclude=True)

    # Real provider HTTP behavior (ignored by fake providers).
    external_api_timeout_seconds: float = 10.0
    external_api_retry_count: int = 2

    # LLM(Gemini) 호출 전용 타임아웃(초). 비어 있으면(기본값) EXTERNAL_API_TIMEOUT_SECONDS를
    # 그대로 쓴다(하위 호환) — 팀이 Gemini 호출 지연 때문에 EXTERNAL_API_TIMEOUT_SECONDS를
    # 25로 올렸다가, TourAPI/Naver/Supabase(장소 상세·상태 저장소 등)까지 같은 값을
    # 물려받아 실패 시 사용자가 그만큼 오래 기다리게 된다는 문제가 논의로 나와 분리했다
    # (2026-08-11). LLM은 구조화 출력 생성 특성상 원래도 오래 걸릴 수 있고 재시도·모델
    # 폴백까지 있어 더 긴 값이 자연스럽지만, Tool/DB 조회는 원래 짧게 끝나야 해서 같은
    # 값을 강제하면 안 된다.
    llm_api_timeout_seconds: float | None = None

    # 관측용 일일 호출 한도. data.go.kr은 오퍼레이션 단위로 한도가 걸리므로
    # (2026-08-07 areaBasedList2 소진) 게이지도 오퍼레이션별로 이 값과 대조한다.
    # 호출을 막는 값이 아니라 개발자 패널 게이지의 기준선이다.
    tour_api_daily_call_limit: int = 1000
    concentration_daily_call_limit: int = 1000

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
    # 상세조회 호출 간 최소 간격(초). 0이면 간격을 두지 않는다(기존 동작).
    # TourAPI는 초당 한도와 일일 한도를 따로 두는데, detailIntro2 응답이 100ms대라
    # 동시성만으로는 초당 속도를 잡을 수 없다 — 대량 재조회 때만 올려 쓴다.
    place_sync_detail_min_interval_seconds: float = 0.0
    place_sync_detail_ttl_days: int = 30
    place_sync_area_code: str = "11"
    place_sync_district_code: str = "110"

    # Fake-provider-only knobs
    # 기상청 코드 그대로 받는다(D-051) — 4 흐림 / 0 강수 없음이 중립 조합이다.
    fake_weather_sky_code: str = "4"
    fake_weather_precipitation_type: str = "0"
    fake_current_datetime: str = "2026-07-15T14:00:00"

    @model_validator(mode="after")
    def validate_recommendation_limits(self) -> Settings:
        if self.recommendation_result_limit > self.recommendation_candidate_limit:
            raise ValueError(
                "RECOMMENDATION_RESULT_LIMIT은 RECOMMENDATION_CANDIDATE_LIMIT 이하여야 합니다."
            )
        return self

    @property
    def resolved_llm_provider(self) -> ProviderMode:
        return self.llm_provider or self.provider_mode

    @property
    def resolved_llm_timeout_seconds(self) -> float:
        """LLM_API_TIMEOUT_SECONDS가 없으면 EXTERNAL_API_TIMEOUT_SECONDS로 폴백한다
        (하위 호환 — 기존에 EXTERNAL_API_TIMEOUT_SECONDS만 설정해 쓰던 환경도 그대로
        동작한다)."""
        return self.llm_api_timeout_seconds or self.external_api_timeout_seconds

    @property
    def resolved_llm_fast_models(self) -> list[str]:
        """의도 분류·조건 추출에 사용할 Gemini 시도 순서."""
        return self._model_list(self.llm_fast_model_name, self.llm_fast_fallback_model_names)

    @property
    def resolved_llm_generation_models(self) -> list[str]:
        """사용자 응답·비교·일정 생성에 사용할 Gemini 시도 순서."""
        return self._model_list(
            self.llm_generation_model_name,
            self.llm_generation_fallback_model_names,
        )

    @property
    def resolved_gemini_audio_model_name(self) -> str:
        """음성 전사용 모델. 미설정 시 빠른 판단 모델 1순위를 재사용한다."""
        return self.gemini_audio_model_name or self.llm_fast_model_name

    @staticmethod
    def _model_list(primary: str, fallback_names: str) -> list[str]:
        fallbacks = [name.strip() for name in fallback_names.split(",") if name.strip()]
        return [primary, *fallbacks]

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
    def resolved_local_search_provider(self) -> ProviderMode:
        return self.local_search_provider or self.provider_mode

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
