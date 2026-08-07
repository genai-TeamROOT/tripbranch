"""INFO 전용 A–C 계약.

INFO 질의는 RECOMMEND Context와 입력·응답 형태가 달라 별도 모델로 둔다.
실제 Tool 호출과 근접치 fallback 여부는 C 서비스가 결정하며, A는 이 계약만 사용한다.

question_type은 두 갈래로 나뉜다(int-02-info.md §6).

- ``concentration`` — 집중률 API 경로. ConcentrationInfoResult를 돌려준다.
- 그 외 — 장소 상세 경로. PlaceInfoResult를 돌려준다.

두 결과는 채우는 필드가 전혀 겹치지 않아 하나로 합치면 대부분이 None인 모델이
된다. 소비 측(A의 response_composer)이 어느 필드를 읽어야 하는지 result의 타입만
보고 알 수 있도록 union으로 둔다.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.agent_context.schemas import Clarification, ContextError, ResponseMetadata

# int-02-info.md §6의 QuestionType. A의 app.schemas.QuestionType과 값이 일치해야
# 한다 — A가 InfoPayload.question_type.value를 그대로 실어 보낸다.
InfoQuestionType = Literal[
    "operating_hours",
    "fee",
    "parking",
    "facility",
    "event",
    "location_info",
    "general_info",
    "concentration",
]


class InfoContextRequest(BaseModel):
    """A가 C에 보내는 단일 장소 INFO 질의 요청."""

    request_id: str = Field(min_length=1)
    intent: Literal["INFO"] = "INFO"
    place_name: str | None = None
    place_context: Literal["explicit", "from_recommendation", "from_conversation"]
    # 기존 호출부(집중률 전용)와의 호환을 위해 기본값을 유지한다.
    question_type: InfoQuestionType = "concentration"
    # 사용자 원문 질문. C는 판정에 쓰지 않고 응답 조립 참고용으로 실어 보낸다.
    specific_question: str | None = None
    visit_time: str | None = None

    @field_validator("request_id")
    @classmethod
    def normalize_request_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("request_id는 공백일 수 없습니다.")
        return normalized

    @field_validator("place_name", "specific_question")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("visit_time")
    @classmethod
    def validate_visit_time(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return date.fromisoformat(normalized).isoformat()
        except ValueError as exc:
            raise ValueError("visit_time은 YYYY-MM-DD 형식이어야 합니다.") from exc


class ConcentrationInfoResult(BaseModel):
    """C가 반환하는 혼잡도 조회 결과 한 건."""

    status: Literal["success", "no_data", "unavailable"]
    is_proxy: bool = False
    requested_place_name: str | None = None
    resolved_place_name: str | None = None
    forecast_date: str | None = None
    concentration_rate: float | None = Field(default=None, ge=0)
    concentration_level: (
        Literal["quiet", "normal", "slightly_crowded", "crowded"] | None
    ) = None
    concentration_label: str | None = None
    error: ContextError | None = None


class PlaceInfoResult(BaseModel):
    """C가 반환하는 장소 상세 조회 결과 한 건(concentration 외 question_type).

    ``fields``는 question_type별로 C가 채우는 정규화된 키-값이다. TourAPI의
    detailIntro2는 contentTypeId마다 필드명이 달라(``usetime``/``usetimeculture``/
    ``opentime`` …) 유형별 전용 모델을 두면 소비 측이 8가지 모양을 모두 알아야
    한다. C가 키 이름을 고정해 넘기고(INFO_FIELD_KEYS), A는 키만 보고 렌더한다.

    값이 하나도 없으면 status="no_data"이고 fields는 빈 dict다 — 빈 문자열이나
    "정보 없음" 같은 문구를 C가 지어내지 않는다.
    """

    status: Literal["success", "no_data", "unavailable"]
    question_type: InfoQuestionType
    requested_place_name: str | None = None
    resolved_place_name: str | None = None
    place_id: str | None = None
    fields: dict[str, str] = Field(default_factory=dict)
    error: ContextError | None = None


class InfoContextResponse(BaseModel):
    """C가 반환하는 INFO 질의 응답."""

    request_id: str
    intent: Literal["INFO"] = "INFO"
    contract_version: Literal["draft-v0"] = "draft-v0"
    status: Literal[
        "success", "no_data", "needs_clarification", "unsupported", "unavailable"
    ]
    result: ConcentrationInfoResult | PlaceInfoResult | None = None
    clarification: Clarification | None = None
    error: ContextError | None = None
    metadata: ResponseMetadata = Field(default_factory=ResponseMetadata)


__all__ = [
    "ConcentrationInfoResult",
    "InfoContextRequest",
    "InfoContextResponse",
    "InfoQuestionType",
    "PlaceInfoResult",
]
