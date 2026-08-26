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
    # 서울시 실시간 데이터는 특정 INFO 질문에서만 필요하고 별도 키를 쓰므로, 공통
    # PROVIDER_MODE=real을 따라 자동 호출하지 않는다. 사용할 환경에서만 명시적으로
    # SEOUL_CITYDATA_PROVIDER=real로 켠다.
    seoul_citydata_provider: ProviderMode = "fake"
    holiday_provider: ProviderMode | None = None
    # 비용이 발생할 수 있으므로 공통 PROVIDER_MODE를 상속하지 않고 명시적으로
    # real을 켤 때만 외부 경로 API를 호출한다.
    #
    # 이동수단마다 벤더가 다르므로(도보 카카오, 자동차 네이버) 하나씩 따로 켠다.
    # 상속 관계를 두지 않는 이유도 같다 — 한 값이 여러 벤더를 켜면, 한쪽 키만 가진
    # 설정이 쓰지도 않는 벤더의 키를 요구하며 부팅에 실패한다. 새 이동수단은 여기에
    # 한 줄씩 추가하고, 기존 이름(TRAVEL_ROUTE_PROVIDER)은 도보 스위치로 유지한다.
    travel_route_provider: ProviderMode = "fake"
    travel_route_driving_provider: ProviderMode = "fake"
    travel_route_transit_provider: ProviderMode = "fake"
    # 직선거리 fallback 예상시간에 쓸 보행속도(m/s).
    walking_speed_mps: float = Field(default=1.2, gt=0)
    # 자동차 fake의 직선거리 예상시간에 쓸 속도(m/s). 20km/h는 반경 산정이 비도보
    # 요청에 쓰는 가정과 같은 값이다(recommendation_transform._OTHER_KM_PER_MIN).
    # fake 값은 채점에 쓰이지 않으므로(STRAIGHT_LINE_ESTIMATE는 걸러진다) 정밀도가
    # 아니라 반경 가정과의 일관성만 맞춘다.
    driving_speed_mps: float = Field(default=5.5, gt=0)
    # 대중교통 fake도 같은 20km/h 가정을 쓴다 — 반경 산정이 비도보 요청을
    # 이동수단으로 가르지 않고 _OTHER_KM_PER_MIN 하나로 처리하기 때문이다.
    transit_speed_mps: float = Field(default=5.5, gt=0)
    travel_route_max_concurrency: int = Field(default=5, ge=1, le=10)

    # 상세·운영정보 조회 출처. PLACE_PROVIDER=fake이면 Fake Provider가 상세까지
    # 담당하므로 이 값은 무시된다.
    place_details_source: PlaceDetailsSource = "tour_api"

    # Package B State 저장소 백엔드. 기본값은 Phase 1 인메모리다.
    state_store_backend: StateStoreBackend = "memory"

    # 조기 반환 경로(Tool/Scoring 없이 끝나는 턴 — GENERAL·OUT_OF_SCOPE·되묻기 등)를
    # LangGraph 그래프로 태울지 여부(docs/design/langgraph-adoption.md §6.1).
    # 기본 on이지만, 이관은 출력이 같아야 하는 작업이라 문제가 보이면 이 값 하나로
    # 즉시 기존 경로로 되돌린다 — off면 compose_chat_message()를 직접 호출한다.
    use_langgraph_early_return: bool = True

    # 추천 파이프라인(Tool 조회 -> Scoring -> SCHEDULE 편성/추천 마무리)을 그래프로
    # 태울지 여부(3단계). 위와 같은 이유로 되돌릴 스위치를 따로 둔다 — 조기 반환과
    # 파이프라인은 범위가 달라 한쪽만 끄고 싶을 수 있다.
    use_langgraph_pipeline: bool = True

    # 취향 근거 벡터 검색 사용 여부. 기본 off인 이유는 임베딩 모델이 선택
    # 의존성(`pip install -e ".[embeddings]"`)이고 서버 프로세스에 상주하기
    # 때문이다 — 실측 RSS 537MB, 적재 9.4초(2026-08-19). 모델을 올릴 수 없는
    # 배포에서도 서버는 떠야 하므로 켜는 쪽을 명시적 선택으로 둔다.
    taste_evidence_enabled: bool = False

    # LLMOps 관측(Langfuse) 스위치. **두 개로 나눠 둔 것이 요점이다.**
    # langfuse_enabled는 "전송을 하느냐", langfuse_capture_content는 "발화·응답
    # 원문을 실어 보내느냐"다. 하나로 묶으면 배포 환경에서 지연·토큰만 보고
    # 원문은 빼는 선택을 할 수 없다.
    #
    # 둘 다 기본 off다. 지금은 실사용자가 없어(로컬 개발만) 나가는 게 팀원 자기
    # 발화뿐이지만, 그 조건에서 정한 기본값이 배포 이후까지 살아남으면 남의
    # 발화가 그대로 외부로 나간다. 켜는 쪽을 명시적 선택으로 둔다.
    # 자세한 근거는 package_D/[계획] Langfuse 도입 §6.3.
    langfuse_enabled: bool = False
    langfuse_capture_content: bool = False
    # 세 번째 스위치. `Principal.user_id`(Supabase 신원 토큰의 sub)를 trace에
    # 실을지다. 이걸 켜면 사용자별 비용·지연·실패율이 보이고, 한 사람이 같은 걸
    # 몇 번 다시 물었는지도 보인다.
    #
    # **원문과 별개 축이라 스위치를 나눴다.** capture_content가 꺼져 있어도
    # user_id는 mask를 타지 않는다(trace 속성이다). 즉 "발화는 가리고 신원만
    # 외부에 쌓는" 상태가 실수로 만들어질 수 있어, 묶어두면 오히려 위험하다.
    #
    # 기본 off다 — 개인정보를 외부 SaaS에 올리는 것은 팀 합의가 먼저다.
    # 코드는 먼저 들어가되 켜는 결정은 사람이 한다.
    langfuse_capture_user_id: bool = False
    langfuse_public_key: str = Field(default="", repr=False, exclude=True)
    langfuse_secret_key: str = Field(default="", repr=False, exclude=True)
    # 리전별로 호스트가 다르다. 한국에서는 JP가 지연이 가장 낮다.
    langfuse_base_url: str = "https://jp.cloud.langfuse.com"

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
    seoul_open_data_api_key: str = Field(default="", repr=False, exclude=True)
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
    # 상세조회 동시성과 호출 간 최소 간격(초). 둘 다 TourAPI의 초당 한도를 피하려고
    # 있고, 역할이 다르다 — 동시성은 동시에 떠 있는 요청 수, 간격은 초당 몇 개가
    # 나가는지를 정한다. detailIntro2 응답이 100ms대라 동시성 1에서도 간격이 없으면
    # 초당 8회쯤 나간다(2026-08-10 실측). 그래서 429를 실제로 막는 것은 간격 쪽이다.
    #
    # 기본값을 5 / 0에서 1 / 0.5로 내렸다. 그 조합이 이 서비스키에서 두 번 연속
    # 429를 냈다 — 2026-08-20 중구 892건 중 669건 실패, 2026-08-22 종로구 16건과
    # 중구 2건 실패. 1 / 0.5는 추측이 아니라 중구 892건을 실패 0으로 끝낸 값이다
    # (6분 16초. 5 / 0은 3분 01초였지만 669건을 다시 불러야 했다).
    #
    # 빠르게 돌려야 하면 .env에서 올린다. 기본값은 안전한 쪽에 둔다.
    place_sync_detail_concurrency: int = 1
    place_sync_detail_min_interval_seconds: float = 0.5
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
    def resolved_seoul_citydata_provider(self) -> ProviderMode:
        return self.seoul_citydata_provider

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
