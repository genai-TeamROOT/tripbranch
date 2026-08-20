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

from app.domain.travel_route import TravelMode
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


class TranscriptionResponse(BaseModel):
    """음성 입력을 Gemini로 전사한 결과.

    전사 텍스트는 이 응답 이후 프론트 입력창에만 채워진다. AgentRequest로 바로
    전달하지 않으므로 사용자가 오인식된 고유명사를 확인·수정한 뒤 기존 채팅 흐름으로
    전송할 수 있다.
    """

    text: str = Field(min_length=1)
    elapsed_ms: int = Field(ge=0)
    model: str


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
    # 그 후보에 실제로 적용된 당일 운영 구간("09:00~18:00"). 프론트가
    # remaining_minutes만으로는 "언제부터"를 표시할 수 없어 함께 내려준다.
    # 운영시간 미확인 후보는 None이다.
    operating_hours_display: str | None = None
    # 실측 경로로 잰 값. 이 값이 있으면 거리 Feature 점수도 직선거리가 아니라 이
    # 소요시간으로 계산된 것이다. 조회에 실패했거나 그 이동수단의 경로 Provider가
    # 아직 없으면 세 필드 모두 None이고, 그때는 distance_km(직선거리)가 유일한
    # 거리 정보다. travel_mode는 어떤 이동수단으로 잰 값인지를 말한다 — 프론트가
    # "도보 이동"인지 다른 수단인지 스스로 추측하지 않게 하려고 함께 내려준다.
    travel_distance_m: int | None = None
    travel_duration_seconds: int | None = None
    travel_mode: TravelMode | None = None
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
    # 결과가 0건이고 그 이유가 전부 폐점 후보 제외였을 때만 True. A가 이 값으로
    # "운영중이 아닌 곳도 볼래요" 되묻기를 띄울지 판단한다(recommendation_pipeline.py).
    excluded_all_closed: bool = False
    # 이번 회차에 D의 하드 필터(_is_closed)가 폐점이라 걸러낸 후보 id 전체.
    # excluded_all_closed와 달리 결과가 0건이 아니어도(일부만 폐점) 채워진다.
    # A가 이 값을 B(상태 저장소)에 기록해 다음 회차 후보 수집 시 제외 목록에
    # 반영한다 — 그러지 않으면 노출 이력이 없는 폐점 후보가 매 회차 다시 수집된다
    # (TP-82, docs/design/... 참고). LLM이 생성하지 않고 D가 결정적으로 채운다.
    excluded_closed_place_ids: list[str] = Field(default_factory=list)


class ScheduleItem(BaseModel):
    """일정에 포함된 장소 1건. (docs/design/int-07-schedule.md 6.2절)"""

    order: int
    place_id: str
    place_name: str
    estimated_arrival: str
    estimated_duration_min: int
    travel_to_next_min: int | None
    reason: str
    # LLM이 생성하지 않는다 — 프롬프트가 항상 빈 배열로 두라고 지시하고,
    # app.schedule.planner가 estimated_arrival과 후보의 operating_hours_display를
    # 대조해 최종적으로 결정적으로 채운다("구조적 보장 우선" 원칙, basis_note와
    # 같은 이유). 폐점 시각이 지난 도착 예정 스탑을 사용자에게 알리는 용도다
    # (docs/design/int-07-schedule.md 9절, "폐점 스탑 감지" 항목 해소).
    warnings: list[str] = Field(default_factory=list)


class ScheduleResult(BaseModel):
    """일정 편성 모듈(app.schedule)의 최종 출력. AgentResponse.schedule에 실린다.

    basis_note는 LLM이 생성하지 않고 A/일정편성모듈이 visit_at 값을 넣어
    고정 템플릿으로 채운다 — 근거 데이터(운영시간·날씨)가 단일 시각 기준이라
    뒷 순서 스탑에는 부정확할 수 있다는 걸 사용자에게 알리는 안내 문구다.
    (docs/design/int-07-schedule.md 6.2.1절)
    """

    items: list[ScheduleItem]
    total_duration_min: int
    route_summary: str
    basis_note: str
    elapsed_ms: float = Field(
        ge=0,
        description="일정 편성 파이프라인 시작부터 응답 조립 완료까지의 총 처리시간(ms)",
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
    SCHEDULE = "SCHEDULE"
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
    REJECT_SPECIFIC = "REJECT_SPECIFIC"
    CHANGE_CONDITION = "CHANGE_CONDITION"


class WeatherIntent(StrEnum):
    AVOID = "AVOID"
    ENJOY = "ENJOY"
    NO_MENTION = "NO_MENTION"
    IGNORE = "IGNORE"


class ConcentrationIntent(StrEnum):
    """weather_intent와 동일 패턴. concentration-conditions.md §2.1 참고.

    null/IGNORE는 weather_intent와 달리 하드 필터에 관여하지 않으므로
    needs_clarification을 유발하지 않는다.
    """

    AVOID = "AVOID"
    SEEK = "SEEK"
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
    SERVICE_IDENTITY = "service_identity"
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
    CONCENTRATION = "concentration"
    # 서울시 실시간 도시데이터의 지역·업종별 카드 소비 활동. 특정 매장 자체의
    # 혼잡도가 아니라, 매장 좌표와 가까운 제공 상권의 대체 정보다.
    REALTIME_COMMERCIAL = "realtime_commercial"
    REALTIME_PARKING = "realtime_parking"
    REALTIME_SUBWAY = "realtime_subway"
    REALTIME_BUS = "realtime_bus"
    REALTIME_EVENT = "realtime_event"


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
    """conditions-schema.md §2의 15개 필드. LLM이 사용자 발화에서 추출한 값만 담는다."""

    current_location: str | None = None
    search_center: str | None = None
    place_types: list[PlaceType] = Field(default_factory=list)
    place_tags: list[PlaceTag] = Field(default_factory=list)
    weather: StatedWeather | None = None
    weather_intent: WeatherIntent | None = None
    concentration_intent: ConcentrationIntent | None = None
    transport: Transport | None = None
    max_travel_time: int | None = Field(
        default=None,
        ge=0,
        description="분(minute) 단위 정수. 사용자가 시간(hour) 단위로 말했으면 60을 곱해 "
        "환산한 값을 넣는다(예: '5시간' -> 300). 숫자만 그대로 옮기지 않는다.",
    )
    time_available: int | None = Field(
        default=None,
        ge=0,
        description="분(minute) 단위 정수. 사용자가 시간(hour) 단위로 말했으면 60을 곱해 "
        "환산한 값을 넣는다(예: '5시간' -> 300). 숫자만 그대로 옮기지 않는다.",
    )
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
    visit_time: str | None = None
    """YYYY-MM-DD. question_type == CONCENTRATION일 때만 사용 (concentration-conditions.md §3.2)."""


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

    `target_indices`는 SCHEDULE-09(부분 수정)에서 추가됐다. `modify_type ==
    REJECT_SPECIFIC`일 때만 의미가 있으며, COMPARE의 `ComparePayload.targets`와
    같은 1-indexed 순번 표현이다("all" 같은 전체 지정은 없다 — 전체 거절은
    REJECT_ALL이 이미 담당한다). REJECT_ALL/CHANGE_CONDITION일 때는 빈 배열이다.
    """

    modify_type: ModifyType
    condition_changes: UserConditions | None = None
    changed_fields: list[str] = Field(default_factory=list)
    target_indices: list[int] = Field(default_factory=list)

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


class ComparisonItem(BaseModel):
    """C의 비교 결과를 A가 LLM 요약·응답 표시용으로 정규화한 항목.

    추천 시점 Feature 스냅샷의 수치 자체는 B가 보관하고, C가 place_id를 사람이
    읽을 수 있는 장소명으로 해석해 이 모델로 반환한다. 이 모델은 C의 Tool 계약을
    중복 정의하려는 것이 아니라, A가 LLM에 넘길 수 있는 공개 비교 사실의 최소
    집합이다.
    """

    place_id: str
    place_name: str
    rank: int = Field(ge=1)
    distance_km: float | None = Field(default=None, ge=0)
    remaining_minutes: int | None = Field(default=None, ge=0)
    environment_type: str | None = None


class ComparisonResult(BaseModel):
    """COMPARE 답변 생성에 쓰는 검증된 사실 데이터.

    LLM은 이 모델에 담긴 값만 문장으로 바꾸며, 순위·점수·운영 상태를 새로
    계산하거나 추정하지 않는다.
    """

    criteria: CompareCriteria
    items: list[ComparisonItem] = Field(min_length=1)


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


class ClarificationOption(BaseModel):
    """되묻기에 붙는 버튼 하나. 프론트가 그대로 렌더링하고, 클릭 시 id를 그대로
    돌려보내면 서버가 결정적으로 처리한다(clarification_choice) — classify_intent()를
    다시 태우지 않는다. docs/design/clarification-options.md 3절."""

    id: str
    label: str
    resolved_intent: Intent


class ClarificationPayload(BaseModel):
    missing_fields: list[MissingField] = Field(default_factory=list)
    ambiguous_fields: list[AmbiguousField] = Field(default_factory=list)
    message: str
    options: list[ClarificationOption] = Field(default_factory=list)
    # 오케스트레이터가 분류 이전에 선제 차단으로 만드는 되묻기(예: 케이스 4/5의
    # "처음부터 다시")는 missing_fields/ambiguous_fields가 비어 있어 agent_runtime의
    # _llm_clarification_code()가 세션에 남길 코드를 이 값으로 명시한다. None이면
    # 기존처럼 missing/ambiguous_fields에서 코드를 유도한다(하위 호환).
    code: str | None = None


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

    # 아래 5개는 라우터가 B의 세션 컨텍스트로 채운다.
    # 호출자가 보낸 값은 무시되며, 하위 호환을 위해 필드만 유지한다.
    has_previous_recommendation: bool = False
    shown_place_count: int = Field(default=0, ge=0)
    current_conditions: UserConditions | None = None
    # 직전 턴이 되묻기로 끝났는지(B의 SessionContextResponse.pending_clarification 그대로)와
    # 그 되묻기가 어떤 Intent의 턴이었는지(SessionContextResponse.last_intent). SCHEDULE
    # 되묻기 답변이 새 MODIFY 요청으로 오분류되는 걸 막기 위해 classify_intent()까지
    # 전달한다(D-059) — RECOMMEND는 우선순위 fallback이라 이 정보 없이도 대체로 맞지만,
    # SCHEDULE은 키워드가 있어야만 선택되는 명시적 분류라 fallback이 없다.
    pending_clarification: str | None = None
    last_intent: str | None = None
    # SCHEDULE-09 후속(이름 지목): 현재 노출된 항목의 이름을 rank 순으로 담는다.
    # "두가헌 레스토랑은 빼줘"처럼 순번이 아니라 이름으로 REJECT_SPECIFIC 대상을
    # 지목할 때 MODIFY 추출기가 이름→순번을 매칭하는 데 쓴다. 이름이 없는 항목은
    # 빈 문자열로 채워 인덱스(=순번-1)가 어긋나지 않게 한다.
    shown_place_names: list[str] = Field(default_factory=list)
    # 직전 INFO 상세 카드에서 프론트가 보존한 장소명. "여기/이곳/거기"처럼
    # 추천 목록이 아닌 대화 속 장소를 가리키는 INFO 발화의 해소 후보로만 쓴다.
    # 상태 계약에 새 필드를 추가하지 않고도, 현재 대화 화면이 이미 받은 카드 정보를
    # 다음 턴의 해석에 재사용할 수 있게 한다.
    conversation_place_name: str | None = None


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
    # 직전 INFO 카드의 장소명. 현재 화면이 "여기/이곳"을 보낼 때에만 A가 INFO
    # from_conversation 해소 후보로 사용한다.
    conversation_place_name: str | None = None
    # 되묻기 버튼 클릭 시 ClarificationOption.id를 그대로 echo. user_input에는 버튼
    # label을 채워 보내되(채팅 이력 표시용) 라우팅은 이 필드만으로 결정한다 —
    # classify_intent()를 다시 태우지 않는다(docs/design/clarification-options.md 3절).
    clarification_choice: str | None = None
    # 개발자용 채팅(/dev-chat) 전용 디버그 스위치. True면 이번 턴은 폐점 후보도
    # 항상 채점에 포함한다 — no_data_closed 되묻기 자체를 재현/우회하려고 매번
    # 버튼을 누르지 않고 강제로 켤 수 있게 한다(실사용 피드백, 2026-08-13).
    # 세션 상태(ignore_operating_hours_until)는 건드리지 않는다 — 이 턴에만
    # 적용되는 일회성 오버라이드다.
    debug_ignore_operating_hours: bool = False


class LLMCallMetadata(BaseModel):
    """한 번의 Gemini 호출에서 실제로 시도·응답한 모델 기록.

    개발자용 Agent Runtime Audit에서만 실행 경로를 확인하는 용도다. 사용자 발화나
    프롬프트 본문은 포함하지 않아, 관측용 메타데이터가 입력 내용을 추가 노출하지 않는다.
    """

    operation: str
    attempted_models: list[str]
    served_model: str | None = None
    # 개발자용 Audit에서 Intent 분류·조건 추출 호출별 지연을 보여주기 위한 값이다.
    # 기존에 저장된 실행 이력과의 호환을 위해 누락 가능하게 둔다.
    latency_ms: int | None = None


class LLMExecutionMetadata(BaseModel):
    """한 Agent 요청 안에서 발생한 LLM 호출들의 모델 사용 이력."""

    calls: list[LLMCallMetadata] = Field(default_factory=list)


class ToolProviderDebug(BaseModel):
    """C가 한 번의 Context 수집에서 실제로 호출한 Provider 하나의 기록."""

    source: str
    status: str
    retrieved_at: str | None = None


class ToolContextItemDebug(BaseModel):
    """RecommendationContext의 항목(location/weather/places/holidays) 하나의 상태.

    fetched=False는 C가 그 항목을 아예 조회하지 않았다는 뜻이다(예: 발화에 날씨가
    이미 있어 조회를 생략한 경우). 조회했는데 실패한 것과 구분된다.
    """

    key: str
    fetched: bool
    status: str | None = None
    error_code: str | None = None
    warning_codes: list[str] = Field(default_factory=list)
    item_count: int | None = None


class CandidateConcentrationDebug(BaseModel):
    """개발자용 Audit 전용: 후보 한 건의 혼잡도가 어디서 온 값인지.

    건수만 세면 "5건 중 3건이 근사치"까지만 알고 어느 후보가 어디서 빌렸는지는
    모른다. 근사치의 타당성은 "어느 장소에서 얼마나 떨어진 값인가"로 판단하므로
    후보별로 남긴다.
    """

    place_id: str
    name: str
    status: str
    is_proxy: bool = False
    # 값을 빌려온 실제 장소와 후보로부터의 거리. is_proxy=False면 둘 다 None.
    proxy_place_name: str | None = None
    proxy_distance_km: float | None = None


class ToolExecutionDebug(BaseModel):
    """개발자용 Audit 전용: A→C 호출 한 단계가 실제로 무엇을 했는지.

    llm_execution과 같은 성격의 관측 전용 필드다 — 추천 판정에는 쓰이지 않으며,
    이 값이 없다고 해서 흐름이 달라지지 않는다. 특히 providers[].source는 실제로
    응답을 만든 Provider가 Real인지 Stub인지 드러내므로, D-042(Real 실패 시 Fake로
    자동 전환하지 않는다)가 지켜지고 있는지 화면에서 바로 확인하는 수단이 된다.
    """

    operation: Literal[
        "context_fetch",
        "info_concentration",
        "info_realtime_commercial",
        "info_realtime_citydata",
        "candidate_enrichment",
        "compare_fetch",
    ] = "context_fetch"
    request_id: str
    status: str
    latency_ms: int | None = None
    providers: list[ToolProviderDebug] = Field(default_factory=list)
    context_items: list[ToolContextItemDebug] = Field(default_factory=list)
    rule_versions: dict[str, str] = Field(default_factory=dict)
    resolved_location_name: str | None = None
    resolved_location_address: str | None = None
    error_code: str | None = None
    clarification_code: str | None = None
    is_proxy: bool | None = None
    candidate_status_counts: dict[str, int] = Field(default_factory=dict)
    # candidate_enrichment 전용. 매핑 없는 후보가 다수라(활성 844건 중 매핑 100건)
    # 근사치가 섞이는 게 정상 상태인데, 상태 집계만 보면 직접 조회한 값과 빌려온
    # 값이 "success 5건"으로 같아 보인다. 건수는 이 목록에서 세면 되므로 따로
    # 두지 않는다 — 같은 사실의 출처가 둘이면 어긋난다.
    candidate_concentration: list[CandidateConcentrationDebug] = Field(default_factory=list)


class InfoPlaceCard(BaseModel):
    """INFO 장소 상세 카드용 A의 최종 응답 모델.

    C의 ``PlaceInfoResult.fields``는 사용자가 물어본 정보가 실제로 있었는지를
    판정하는 용도이고, 이 모델은 그와 별개로 펼쳐서 보여줄 장소 전체 정보다.
    따라서 ``answer_fields``를 카드의 상세 필드와 합치지 않는다.
    """

    question_type: QuestionType
    answer_fields: dict[str, str] = Field(default_factory=dict)
    place_id: str | None = None
    place_name: str | None = None
    thumbnail_url: str | None = None
    overview: str | None = None
    operating_hours: str | None = None
    rest_date: str | None = None
    parking: str | None = None
    parking_fee: str | None = None
    fee: str | None = None
    baby_carriage: str | None = None
    pet: str | None = None
    credit_card: str | None = None
    restroom: str | None = None
    homepage: str | None = None
    population_current_level: str | None = None
    population_observed_at: str | None = None
    population_forecasts: list[PopulationForecastBar] = Field(default_factory=list)
    concentration_forecasts: list[ConcentrationForecastBar] = Field(default_factory=list)


class PopulationForecastBar(BaseModel):
    forecast_at: str
    congestion_level: str | None = None
    population_min: int | None = None
    population_max: int | None = None


class ConcentrationForecastBar(BaseModel):
    """관광지 집중률 API의 일 단위 예측을 카드 차트에 전달한다."""

    forecast_date: str
    concentration_rate: float = Field(ge=0)
    concentration_level: str
    concentration_label: str


class RecommendationPlaceDetailRequest(BaseModel):
    """추천 카드 클릭으로 여는 장소 상세조회 요청.

    대화 발화가 아니므로 LLM·세션 상태를 거치지 않는다. ``place_name``은 C의 기존
    INFO 상세조회 입력이고, ``place_id``는 이름 해석이 다른 장소로 빗나가지 않았는지
    A가 응답을 대조하는 기준이다.
    """

    place_id: str = Field(min_length=1, max_length=100)
    place_name: str = Field(min_length=1, max_length=200)

    @field_validator("place_id", "place_name")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("장소 정보는 비어 있을 수 없습니다.")
        return normalized


class RecommendationPlaceDetailResponse(BaseModel):
    """추천 카드 상세 모달이 소비하는 단건 PlaceDetails 조회 결과."""

    status: Literal["success", "no_data", "unavailable"]
    requested_place_id: str
    place_card: InfoPlaceCard | None = None


class AgentResponse(BaseModel):
    """TODO(D 계약 확정 시 필드 변경 가능): Agent Runtime의 임시 최종 응답.

    recommendations는 RECOMMEND/MODIFY이고 status가 complete일 때만 채워진다(그 외에는
    None — Tool/Recommendation 단계 자체를 건너뛰었다는 뜻).
    schedule은 SCHEDULE이고 status가 complete일 때만 채워진다(docs/design/
    int-07-schedule.md 7절) — recommendations와 동시에 채워지지 않는다.
    message는 사용자에게 보여줄 챗봇 말풍선 텍스트다(docs/design/agent-response-
    generation.md 참고) — 카드(recommendations)·일정(schedule) 상세는 이 문장에
    다시 풀어쓰지 않는다.
    """

    llm_output: LLMOutput
    state: StateApplyResponse
    recommendations: RecommendationResponse | None = None
    schedule: ScheduleResult | None = None
    # COMPARE에서 C가 이름으로 보강한 추천 시점 Feature 스냅샷. 사용자 말풍선은
    # 이를 바탕으로 A의 LLM이 만들며, 개발자 Audit은 원본 비교 사실도 확인할 수 있다.
    comparison: ComparisonResult | None = None
    # INFO의 장소 상세 질의에서만 채운다. 질문 답변(fields)과 펼침 카드 정보는
    # 목적이 달라 InfoPlaceCard.answer_fields와 카드 상세를 분리해 보존한다.
    info_place_card: InfoPlaceCard | None = None
    message: str
    # 개발자용 Audit에서 1차 Intent/2차 추출 호출의 실제 Gemini 모델·폴백 경로를
    # 확인한다. Fake LLM 등 실행 메타데이터를 제공하지 않는 구현체에서는 None이다.
    llm_execution: LLMExecutionMetadata | None = None
    # 개발자용 Audit에서 C가 실제로 호출한 Provider·항목별 상태를 확인한다.
    # C 단계에 도달하지 못한 요청(LLM 실패, needs_clarification 등)에서는 None이다.
    tool_execution: ToolExecutionDebug | None = None
    # 한 요청 안에서 C가 여러 번 호출될 수 있으므로, 감사 패널은 이 목록을 우선 사용한다.
    # tool_execution은 이전 개발자 클라이언트 호환을 위해 첫/주요 호출을 계속 제공한다.
    tool_executions: list[ToolExecutionDebug] = Field(default_factory=list)
