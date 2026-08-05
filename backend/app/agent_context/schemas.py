"""A가 조건을 전달하고 C가 추천 Context를 반환하는 Pydantic 계약."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class StrictModel(BaseModel):
    """계약에 정의하지 않은 필드는 수신하지 않는다."""

    model_config = ConfigDict(extra="forbid")


class UserConditions(StrictModel):
    current_location: str | None = None
    search_center: str | None = None
    place_types: list[str] = Field(default_factory=list)
    place_tags: list[str] = Field(default_factory=list)
    weather: Literal["rain", "snow", "hot", "cold", "good"] | None = None
    weather_intent: Literal["AVOID", "ENJOY", "NO_MENTION", "IGNORE"] | None = None
    transport: Literal["walk", "public", "car"] | None = None
    max_travel_time: int | None = Field(default=None, gt=0)
    time_available: int | None = Field(default=None, gt=0)
    environment: Literal["indoor", "outdoor", "any"] | None = None
    companion: (
        Literal["solo", "couple", "friend", "parent", "child", "pet"] | None
    ) = None
    budget: str | None = None
    exclude_tags: list[str] = Field(default_factory=list)
    special_requirements: list[str] = Field(default_factory=list)

    @field_validator("current_location", "search_center", "budget")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("문자열 조건은 공백일 수 없습니다.")
        return normalized

    @field_validator(
        "place_types",
        "place_tags",
        "exclude_tags",
        "special_requirements",
    )
    @classmethod
    def normalize_text_list(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("복수 조건에는 빈 문자열을 포함할 수 없습니다.")
        return normalized


class AgentContextRequest(StrictModel):
    request_id: str = Field(min_length=1)
    intent: Literal["RECOMMEND"]
    conditions: UserConditions
    # 사용자 발화 위치와 별도로, A가 검증한 기기 GPS를 좌표 객체로 전달한다.
    gps_location: Coordinates | None = None

    @field_validator("request_id")
    @classmethod
    def normalize_request_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("request_id는 공백일 수 없습니다.")
        return normalized


class Coordinates(StrictModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class ProviderMetadata(StrictModel):
    source: str = Field(min_length=1)
    status: Literal["success", "no_data", "partial", "unavailable"]
    retrieved_at: datetime

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("source는 공백일 수 없습니다.")
        return normalized

    @field_validator("retrieved_at")
    @classmethod
    def validate_retrieved_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("retrieved_at은 timezone-aware datetime이어야 합니다.")
        return value


class ContextWarning(StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ContextError(StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool


class Clarification(StrictModel):
    code: Literal[
        "location_required",
        "location_ambiguous",
        "place_required",
        "place_ambiguous",
    ]
    missing_fields: list[str] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list)


class ResolvedLocation(StrictModel):
    requested_query: str
    resolved_name: str
    location: Coordinates
    address: str | None = None


class WeatherForecast(StrictModel):
    condition: Literal["good", "neutral", "bad"]
    forecast_for: datetime
    temperature_celsius: float | None = None

    @field_validator("forecast_for")
    @classmethod
    def validate_forecast_for(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("forecast_for는 timezone-aware datetime이어야 합니다.")
        return value


class PlaceCandidate(StrictModel):
    place_id: str
    name: str
    category: str
    # TourAPI 3단계 분류. category(대분류)만으로는 실내외를 가릴 수 없어 D가 판정에
    # 쓴다 — 관광지(12)에 고궁과 체험관이, 쇼핑(38)에 면세점과 시장이 함께 들어온다.
    lcls_systm1: str | None = None
    lcls_systm2: str | None = None
    lcls_systm3: str | None = None
    location: Coordinates
    operating_hours_raw: str | None = None
    rest_date_raw: str | None = None
    operating_schedule: dict[str, Any] | None = None


class HolidayInfo(StrictModel):
    date: str
    name: str


T = TypeVar("T")


class ContextValue(StrictModel, Generic[T]):
    status: Literal["success", "no_data", "partial", "unsupported", "unavailable"]
    data: T | None = None
    error: ContextError | None = None
    warnings: list[ContextWarning] = Field(default_factory=list)
    provider_metadata: list[ProviderMetadata] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_state(self) -> ContextValue[T]:
        if self.status in {"success", "partial"}:
            if self.data is None:
                raise ValueError(f"{self.status} Context에는 data가 필요합니다.")
            if self.error is not None:
                raise ValueError(f"{self.status} Context에는 error를 넣을 수 없습니다.")
        elif self.status == "no_data":
            if not _is_empty_data(self.data):
                raise ValueError("no_data Context에는 비어 있는 data만 허용됩니다.")
            if self.error is not None:
                raise ValueError("no_data Context에는 error를 넣을 수 없습니다.")
        else:
            if self.data is not None:
                raise ValueError(f"{self.status} Context에는 data를 넣을 수 없습니다.")
            if self.error is None:
                raise ValueError(f"{self.status} Context에는 error가 필요합니다.")
        return self


def _is_empty_data(value: object) -> bool:
    """목록형 no_data는 빈 컬렉션, 단건형 no_data는 null을 사용한다."""

    return value is None or (
        isinstance(value, (list, tuple, dict, set)) and not value
    )


class RecommendationContext(StrictModel):
    location: ContextValue[ResolvedLocation] | None = None
    weather: ContextValue[WeatherForecast] | None = None
    places: ContextValue[list[PlaceCandidate]] | None = None
    holidays: ContextValue[list[HolidayInfo]] | None = None


class ResponseMetadata(StrictModel):
    rule_versions: dict[str, str] = Field(default_factory=dict)
    provider_metadata: list[ProviderMetadata] = Field(default_factory=list)


class AgentContextResponse(StrictModel):
    request_id: str = Field(min_length=1)
    intent: Literal["RECOMMEND"]
    contract_version: Literal["draft-v0"] = "draft-v0"
    status: Literal[
        "success",
        "partial",
        "no_data",
        "needs_clarification",
        "unsupported",
        "unavailable",
    ]
    context: RecommendationContext | None = None
    clarification: Clarification | None = None
    warnings: list[ContextWarning] = Field(default_factory=list)
    error: ContextError | None = None
    metadata: ResponseMetadata

    @field_validator("request_id")
    @classmethod
    def normalize_response_request_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("request_id는 공백일 수 없습니다.")
        return normalized

    @model_validator(mode="after")
    def validate_state(self) -> AgentContextResponse:
        if self.status in {"success", "partial"}:
            if self.context is None:
                raise ValueError(f"{self.status} 응답에는 context가 필요합니다.")
            if self.clarification is not None or self.error is not None:
                raise ValueError(
                    f"{self.status} 응답에는 clarification/error를 넣을 수 없습니다."
                )
        elif self.status == "needs_clarification":
            if self.context is not None or self.error is not None:
                raise ValueError(
                    "needs_clarification 응답에는 context/error를 넣을 수 없습니다."
                )
            if self.clarification is None:
                raise ValueError(
                    "needs_clarification 응답에는 clarification이 필요합니다."
                )
        elif self.status == "unsupported":
            if self.context is not None or self.clarification is not None:
                raise ValueError(
                    "unsupported 응답에는 context/clarification을 넣을 수 없습니다."
                )
            if self.error is None:
                raise ValueError("unsupported 응답에는 error가 필요합니다.")
        elif self.status == "unavailable":
            if self.clarification is not None:
                raise ValueError(
                    "unavailable 응답에는 clarification을 넣을 수 없습니다."
                )
            if self.error is None:
                raise ValueError("unavailable 응답에는 error가 필요합니다.")
        elif self.clarification is not None:
            raise ValueError("no_data 응답에는 clarification을 넣을 수 없습니다.")
        return self
