"""A-C Context Contract v0(docs/design/a-c-context-contract-draft.md) 전용 스키마.

역할: C(Tool Intelligence)가 확정한 A-C Context Contract v0 초안을 그대로 옮긴
Pydantic 모델. app.schemas의 동명 모델(PlaceCandidate, UserConditions)과 이름은
같지만 용도·필드가 다른 별개 타입이다(0단계 검토에서 확인: A의 PlaceCandidate는
TourAPI 지향 flat lat/lon + 분류 코드, C의 PlaceCandidate는 nested Coordinates +
운영정보 원본/정규화 필드로 구조가 다르다). 이름 충돌을 피하려고 app.schemas에
합치지 않고 이 모듈에 따로 둔다. Warning은 파이썬 내장 예외 클래스와 이름이 겹쳐서
ContextWarning으로 개명했다. ProviderMetadata도 app.providers.contracts의 동명
dataclass와 구조가 달라(그쪽은 ProviderSource/ProviderStatus enum 사용) 별개로 둔다.

계약 버전: draft-v0. C의 실제 구현 코드는 저장소 어디에도 없다 — 이 문서를 기준으로
A가 직접 정의한 계약 스키마이므로, 계약이 바뀌면 이 파일만 갱신하면 된다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Coordinates(BaseModel):
    latitude: float
    longitude: float


class UserConditions(BaseModel):
    """C 계약의 conditions 필드(문서 §4.1).

    app.schemas.UserConditions(A 쪽, enum 타입)와 14개 필드가 이름·개수·값 동일하되,
    place_types/place_tags는 enum 제약이 없는 list[str]이다.
    """

    current_location: str | None = None
    search_center: str | None = None
    place_types: list[str] = Field(default_factory=list)
    place_tags: list[str] = Field(default_factory=list)
    weather: Literal["rain", "snow", "hot", "cold", "good"] | None = None
    weather_intent: Literal["AVOID", "ENJOY", "IGNORE"] | None = None
    transport: Literal["walk", "public", "car"] | None = None
    max_travel_time: int | None = None
    time_available: int | None = None
    environment: Literal["indoor", "outdoor", "any"] | None = None
    companion: Literal["solo", "couple", "friend", "parent", "child", "pet"] | None = None
    budget: str | None = None
    exclude_tags: list[str] = Field(default_factory=list)
    special_requirements: list[str] = Field(default_factory=list)


class AgentContextRequest(BaseModel):
    request_id: str
    intent: Literal["RECOMMEND"]
    conditions: UserConditions


class ProviderMetadata(BaseModel):
    source: str
    status: Literal["success", "no_data", "unavailable"]
    retrieved_at: datetime


class ContextWarning(BaseModel):
    """계약 문서의 Warning. 파이썬 내장 Warning 예외와 이름이 겹쳐서 개명했다."""

    code: str
    message: str


class ContextError(BaseModel):
    code: str
    message: str
    retryable: bool


class Clarification(BaseModel):
    code: Literal[
        "location_required",
        "location_ambiguous",
        "place_required",
        "place_ambiguous",
    ]
    missing_fields: list[str] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list)


class ResolvedLocation(BaseModel):
    requested_query: str
    resolved_name: str
    location: Coordinates
    address: str | None = None


class WeatherForecast(BaseModel):
    """C가 Provider 응답을 정규화한 3단계 날씨(good/neutral/bad, 문서 §5.2).

    UserConditions.weather(사용자가 말한 5단계 rain/snow/hot/cold/good)와는 역할이
    달라서 서로 직접 대입하지 않는다.
    """

    condition: Literal["good", "neutral", "bad"]
    forecast_for: datetime
    temperature_celsius: float | None = None


class PlaceCandidate(BaseModel):
    """C 계약의 장소 후보(문서 §5.1). app.schemas.PlaceCandidate와는 이름만 같고
    구조가 다른 별개 모델이다 — 서로 바꿔 쓰지 않는다.
    """

    place_id: str
    name: str
    category: str
    location: Coordinates
    operating_hours_raw: str | None = None
    rest_date_raw: str | None = None
    operating_schedule: dict[str, object] | None = None


class HolidayInfo(BaseModel):
    date: str
    name: str


class ContextValue(BaseModel, Generic[T]):
    status: Literal["success", "no_data", "partial", "unsupported", "unavailable"]
    data: T | None = None
    error: ContextError | None = None
    warnings: list[ContextWarning] = Field(default_factory=list)
    provider_metadata: list[ProviderMetadata] = Field(default_factory=list)


class RecommendationContext(BaseModel):
    location: ContextValue[ResolvedLocation] | None = None
    weather: ContextValue[WeatherForecast] | None = None
    places: ContextValue[list[PlaceCandidate]] | None = None
    holidays: ContextValue[list[HolidayInfo]] | None = None


class ResponseMetadata(BaseModel):
    rule_versions: dict[str, str] = Field(default_factory=dict)
    provider_metadata: list[ProviderMetadata] = Field(default_factory=list)


class AgentContextResponse(BaseModel):
    request_id: str
    intent: Literal["RECOMMEND"]
    contract_version: Literal["draft-v0"]
    status: Literal[
        "success", "partial", "no_data", "needs_clarification", "unsupported", "unavailable"
    ]
    context: RecommendationContext | None = None
    clarification: Clarification | None = None
    # 최상위 warnings. RecommendationContext.weather/places 등 항목별 ContextValue.warnings와는
    # 별개 레벨이다 — 지금 단계(Runtime 골격)에서는 이 최상위 것만 보고 넘어간다.
    # TODO(자연어 응답 생성 단계): 항목별 warnings까지 합쳐서 사용자에게 보여줄지 다시 검토한다.
    warnings: list[ContextWarning] = Field(default_factory=list)
    error: ContextError | None = None
    metadata: ResponseMetadata


__all__ = [
    "AgentContextRequest",
    "AgentContextResponse",
    "Clarification",
    "ContextError",
    "ContextValue",
    "ContextWarning",
    "Coordinates",
    "HolidayInfo",
    "PlaceCandidate",
    "ProviderMetadata",
    "RecommendationContext",
    "ResolvedLocation",
    "ResponseMetadata",
    "UserConditions",
    "WeatherForecast",
]
