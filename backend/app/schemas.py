"""TripBranch 백엔드 API의 요청/응답 스키마 정의.

역할: Pydantic 모델로 API 계약과 프론트엔드가 기대하는 데이터 형태를 고정한다.
입력: 라우터로 들어온 원시 JSON payload와 서비스가 반환하는 dict/model 값.
출력: 검증된 요청 모델, 직렬화 가능한 응답 모델, 공통 오류 모델.
호출 시점: FastAPI 요청 검증, 응답 직렬화, 서비스/테스트 타입 확인 때 사용된다.
TODO: 실제 도메인 확정 후 문자열 카테고리와 날씨 값은 Enum으로 좁힌다.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.state.service import StateApplyResponse


class HealthResponse(BaseModel):
    status: str


class ErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: object | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class InterpretedConditions(BaseModel):
    location_query: str
    preferred_categories: list[str]
    weather_condition: str | None
    search_radius_km: float


class RecommendationRequest(InterpretedConditions):
    session_id: str | None = None
    run_id: str | None = None
    # 하위 호환용. session_id가 있으면 B가 조회한 값으로 대체된다.
    shown_place_ids: list[str] = Field(default_factory=list)


class RecommendationItem(BaseModel):
    place_id: str
    name: str
    category: str
    distance_km: float
    remaining_minutes: int | None
    environment_type: str
    recommendation_reason: str
    explanations: list[str]
    warnings: list[str]
    score: float
    feature_scores: dict[str, float | None]
    weights_used: dict[str, float]


class RecommendationResponse(BaseModel):
    recommendations: list[RecommendationItem]
    unverified_recommendations: list[RecommendationItem]
    elapsed_ms: float = Field(
        ge=0,
        description="추천 파이프라인 시작부터 응답 조립 완료까지의 총 처리시간(ms)",
    )

class PlaceCandidate(BaseModel):
    """장소 API 원본 응답을 정규화한 공통 후보 모델.

    역할: 어떤 장소 API(TourAPI, 카카오 등)를 쓰든 Mapper가 이 모양으로
    변환해서 Recommendation Service에 넘긴다. Service는 이 모델만 알면 되고
    원본 API 응답 구조를 몰라도 된다.
    """

    place_id: str
    content_type_id: str | None = None
    lcls_systm1: str | None = None
    lcls_systm2: str | None = None
    lcls_systm3: str | None = None
    name: str
    category: str
    latitude: float
    longitude: float
    address: str | None = None
    operating_hours: str | None = None
    raw_source: str = Field(description="어떤 provider가 만든 후보인지 (예: 'tour_api')")


# === LLM Output Schema ===
#
# 아래는 docs/design/conditions-schema.md(§2, §4)와 docs/design/llm-output-schema.md(§3~8)의
# Pydantic 초안을 프로젝트 컨벤션(StrEnum)에 맞춰 옮긴 것. 필드 의미·예시는 두 문서를 참조.
# StatedWeather는 app.domain.models.WeatherCondition(good/neutral/bad, API 날씨)과 이름이
# 겹치지 않도록 사용자 발화 날씨(rain/snow/hot/cold/good)를 가리키는 이름으로 분리했다.


class Intent(StrEnum):
    RECOMMEND = "RECOMMEND"
    INFO = "INFO"
    MODIFY = "MODIFY"
    COMPARE = "COMPARE"
    GENERAL = "GENERAL"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class OutputStatus(StrEnum):
    COMPLETE = "complete"
    NEEDS_CLARIFICATION = "needs_clarification"


class ModifyType(StrEnum):
    REJECT_ALL = "REJECT_ALL"
    CHANGE_CONDITION = "CHANGE_CONDITION"


class WeatherIntent(StrEnum):
    AVOID = "AVOID"
    ENJOY = "ENJOY"
    IGNORE = "IGNORE"


class StatedWeather(StrEnum):
    RAIN = "rain"
    SNOW = "snow"
    HOT = "hot"
    COLD = "cold"
    GOOD = "good"


class Transport(StrEnum):
    WALK = "walk"
    PUBLIC = "public"
    CAR = "car"


class Environment(StrEnum):
    INDOOR = "indoor"
    OUTDOOR = "outdoor"
    ANY = "any"


class Companion(StrEnum):
    SOLO = "solo"
    COUPLE = "couple"
    FRIEND = "friend"
    PARENT = "parent"
    CHILD = "child"
    PET = "pet"


class CompareCriteria(StrEnum):
    DISTANCE = "distance"
    TIME = "time"
    OVERALL = "overall"


class OutOfScopeCategory(StrEnum):
    HARMFUL = "harmful"
    UNRELATED = "unrelated"
    ROLE_REQUEST = "role_request"
    PROMPT_INJECTION = "prompt_injection"


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class GeneralTopic(StrEnum):
    TRAVEL_TIP = "travel_tip"
    SEASON_INFO = "season_info"
    AREA_INFO = "area_info"
    PLACE_KNOWLEDGE = "place_knowledge"
    PLANNING_TIP = "planning_tip"
    FOOD_CULTURE = "food_culture"
    TRANSPORT_INFO = "transport_info"


class QuestionType(StrEnum):
    OPERATING_HOURS = "operating_hours"
    FEE = "fee"
    PARKING = "parking"
    FACILITY = "facility"
    EVENT = "event"
    LOCATION_INFO = "location_info"
    GENERAL_INFO = "general_info"


class PlaceContext(StrEnum):
    EXPLICIT = "explicit"
    FROM_RECOMMENDATION = "from_recommendation"
    FROM_CONVERSATION = "from_conversation"


class PlaceType(StrEnum):
    ATTRACTION = "attraction"
    CULTURAL_FACILITY = "cultural_facility"
    FESTIVAL = "festival"
    LEISURE = "leisure"
    SHOPPING = "shopping"
    RESTAURANT = "restaurant"


class PlaceTag(StrEnum):
    # attraction 하위
    PARK = "공원"
    PALACE = "궁궐"
    MOUNTAIN = "산"
    BEACH = "해변"
    LAKE = "호수"
    VALLEY = "계곡"
    VIEWPOINT = "전망대"
    THEME_PARK = "테마파크"
    ZOO = "동물원"
    ARBORETUM = "수목원"
    TEMPLE = "사찰"
    FORTRESS = "성곽"
    VILLAGE = "마을"
    TRAIL = "둘레길"
    TRADITIONAL_EXPERIENCE = "전통체험"
    CRAFT_EXPERIENCE = "공예체험"
    WELLNESS = "웰니스"
    # cultural_facility 하위
    MUSEUM = "박물관"
    ART_GALLERY = "미술관"
    LIBRARY = "도서관"
    PERFORMANCE_HALL = "공연장"
    SCIENCE_MUSEUM = "과학관"
    EXHIBITION_HALL = "전시관"
    # festival 하위
    FESTIVAL = "축제"
    EXHIBITION = "전시회"
    PERFORMANCE = "공연"
    CONCERT = "콘서트"
    # shopping 하위
    MARKET = "시장"
    SHOPPING_MALL = "쇼핑몰"
    DUTY_FREE = "면세점"
    DEPARTMENT_STORE = "백화점"
    # restaurant 하위
    KOREAN_FOOD = "한식"
    JAPANESE_FOOD = "일식"
    CHINESE_FOOD = "중식"
    WESTERN_FOOD = "양식"
    CAFE = "카페"
    TEA_HOUSE = "찻집"
    BAR = "주점"
    SNACK = "분식"


class UserConditions(BaseModel):
    """conditions-schema.md §2의 14개 필드. LLM이 사용자 발화에서 추출한 값만 담는다."""

    current_location: str | None = None
    search_center: str | None = None
    place_types: list[PlaceType] = Field(default_factory=list)
    place_tags: list[PlaceTag] = Field(default_factory=list)
    weather: StatedWeather | None = None
    weather_intent: WeatherIntent | None = None
    transport: Transport | None = None
    max_travel_time: int | None = Field(default=None, ge=0)
    time_available: int | None = Field(default=None, ge=0)
    environment: Environment | None = None
    companion: Companion | None = None
    budget: str | None = None
    exclude_tags: list[str] = Field(default_factory=list)
    special_requirements: list[str] = Field(default_factory=list)

    @field_validator("current_location", "search_center", mode="before")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        """공백/빈 문자열은 None으로 낮춘다.

        A-C Context Contract v0 §4.4: "빈 문자열과 공백 문자열은 허용하지 않는다."
        C로 넘어가기 전에 A 쪽에서 미리 차단한다.
        """
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("max_travel_time", "time_available", mode="before")
    @classmethod
    def _zero_to_none(cls, value: object) -> object:
        """0은 "시간 제한 없음"이 아니라 None으로 정규화한다.

        "시간 제한 없음"은 max_travel_time=0이 아니라 None으로 표현하기로
        확정됐다. mode="before"라 Field(ge=0) 검사보다 먼저 실행되므로,
        음수는 이 함수를 그대로 통과해 여전히 ValidationError로 막힌다.
        C(app.agent_context.schemas.UserConditions)의 max_travel_time/
        time_available은 Field(gt=0)이라 0을 애초에 거부하는데, 이 정규화
        덕분에 A에서 C로 0이 넘어갈 일 자체가 없어진다.
        """
        return None if value == 0 else value


class RecommendPayload(BaseModel):
    conditions: UserConditions


class InfoPayload(BaseModel):
    place_name: str | None = None
    place_context: PlaceContext
    question_type: QuestionType
    specific_question: str | None = None


class ModifyPayload(BaseModel):
    """llm-output-schema.md 초안 + 구현 시 확정 사항(§10 #3) 반영.

    문서 초안은 `condition_changes: Partial<UserConditions> | null`만 정의하지만,
    구조화 출력에서는 UserConditions의 모든 필드가 항상 채워지므로 "언급 안 해서 유지"와
    "명시적으로 null로 해제"를 값만으로 구분할 수 없다(§10 #3이 "구현 시 확정"으로 남긴 지점).
    `changed_fields`에 실제로 변경(Update/Remove)된 UserConditions 필드명만 명시하고,
    나머지는 condition_changes에 어떤 값이 있든 Keep으로 처리한다.

    `_clear_unlisted_fields`가 이 불변식을 생성 시점에 구조적으로 강제한다 — LLM이
    changed_fields 밖 필드에 값을 채워 보내도(예: 호출자가 current_conditions에 실제
    null이 아닌 값을 실어 보내서 LLM이 그 값을 그대로 carry-forward한 경우) 여기서
    null/빈 배열로 정리되므로, 이 필드를 나중에 직접 읽는 소비자가 생겨도 안전하다.
    """

    modify_type: ModifyType
    condition_changes: UserConditions | None = None
    changed_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _clear_unlisted_fields(self) -> ModifyPayload:
        if self.condition_changes is None:
            return self

        allowed = set(self.changed_fields)
        updates: dict[str, object] = {}
        for name, field_info in UserConditions.model_fields.items():
            if name in allowed:
                continue  # changed_fields에 있는 필드는 절대 건드리지 않는다.
            empty = (
                field_info.default_factory()  # type: ignore[call-arg]
                if field_info.default_factory is not None
                else field_info.default
            )
            if getattr(self.condition_changes, name) != empty:
                updates[name] = empty

        if updates:
            self.condition_changes = self.condition_changes.model_copy(update=updates)
        return self


class ComparePayload(BaseModel):
    targets: Literal["all"] | list[int]
    criteria: CompareCriteria


class GeneralPayload(BaseModel):
    topic: GeneralTopic
    original_question: str


class OutOfScopePayload(BaseModel):
    category: OutOfScopeCategory
    severity: Severity


class MissingField(BaseModel):
    field: str
    reason: str


class AmbiguousField(BaseModel):
    field: str
    user_input: str
    candidates: list[str]
    reason: str


class ClarificationPayload(BaseModel):
    missing_fields: list[MissingField] = Field(default_factory=list)
    ambiguous_fields: list[AmbiguousField] = Field(default_factory=list)
    message: str


class LLMOutput(BaseModel):
    """모든 Intent가 담기는 단일 envelope (llm-output-schema.md §3)."""

    intent: Intent
    status: OutputStatus
    recommend: RecommendPayload | None = None
    info: InfoPayload | None = None
    modify: ModifyPayload | None = None
    compare: ComparePayload | None = None
    general: GeneralPayload | None = None
    out_of_scope: OutOfScopePayload | None = None
    clarification: ClarificationPayload | None = None

class SessionState(BaseModel):
    """Package B가 관리하는 세션 상태 스냅샷.

    프론트엔드는 session_id만 보관하면 되고, 조건과 이력은 서버가 들고 있다.
    run_id는 /api/recommendations 요청에 실어 보내야 조건 변경 기록과
    추천 이력이 같은 실행으로 묶인다.
    """

    session_id: str
    run_id: str
    session_created: bool
    condition_version: int
    condition_changed: bool
    user_conditions: UserConditions
    shown_place_ids: list[str] = Field(default_factory=list)
    excluded_place_ids: list[str] = Field(default_factory=list)
    gps_expired: bool = True
    weather_expired: bool = True


class InterpretResponse(BaseModel):
    """/api/interpret 응답. 해석 결과와 세션 상태를 함께 반환한다."""

    output: LLMOutput
    state: SessionState

class IntentClassificationResult(BaseModel):
    """1단계 LLM 호출(Intent 분류) 전용 최소 스키마. 문서에 없는 신규 모델.

    OUT_OF_SCOPE는 1단계 판정만으로 차단에 필요한 정보가 다 나오므로
    category/severity를 여기서 함께 받아 2단계(조건 추출) 호출을 생략한다.
    """

    intent: Intent
    out_of_scope_category: OutOfScopeCategory | None = None
    out_of_scope_severity: Severity | None = None


class InterpretRequest(BaseModel):
    user_input: str = Field(..., min_length=1)

    # 세션 식별자. 없으면 B가 첫 apply()에서 발급한다.
    session_id: str | None = None
    # 브라우저에서 확보한 "위도,경도". api_context.gps_location과 동일 포맷.
    device_location: str | None = None

    # 아래 3개는 라우터가 B의 세션 컨텍스트로 채운다.
    # 호출자가 보낸 값은 무시되며, 하위 호환을 위해 필드만 유지한다.
    has_previous_recommendation: bool = False
    shown_place_count: int = Field(default=0, ge=0)
    current_conditions: UserConditions | None = None


# === Agent Runtime (A-03) ===
#
# Agent Runtime(app.services.runtime.agent_runtime)이 쓰는 요청/응답 모델. Tool 결과
# (C)는 app.agent_context.schemas.AgentContextResponse/RecommendationContext로
# 이미 계약이 확정됐다(A-C Context Contract v0). D(Recommendation)는 아직 확정 전이라
# AgentResponse는 여전히 임시 모델이다 — 계약이 확정되면 필드가 바뀔 수 있다.


class AgentRequest(BaseModel):
    """run_agent()의 입력. has_previous_recommendation 등은 더 이상 호출자가 넣지 않는다 —
    Runtime이 B의 SessionContextResponse에서 직접 계산한다."""

    user_input: str = Field(..., min_length=1)
    session_id: str | None = None
    device_location: str | None = None  # "위도,경도" 문자열, api_context.gps_location과 동일 포맷


class AgentResponse(BaseModel):
    """TODO(D 계약 확정 시 필드 변경 가능): Agent Runtime의 임시 최종 응답.

    recommendations는 RECOMMEND/MODIFY이고 status가 complete일 때만 채워진다(그 외에는
    None — Tool/Recommendation 단계 자체를 건너뛰었다는 뜻).
    message는 사용자에게 보여줄 챗봇 말풍선 텍스트다(docs/design/agent-response-
    generation.md 참고) — 카드(recommendations) 상세는 이 문장에 다시 풀어쓰지 않는다.
    """

    llm_output: LLMOutput
    state: StateApplyResponse
    recommendations: RecommendationResponse | None = None
    message: str
