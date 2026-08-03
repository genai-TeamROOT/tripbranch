"""INFO(question_type=concentration) 전용 A–C 계약.

INFO 혼잡도 질의는 RECOMMEND Context와 입력·응답 형태가 달라 별도 모델로 둔다.
실제 Tool 호출과 근접치 fallback 여부는 C 서비스가 결정하며, A는 이 계약만 사용한다.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.agent_context.schemas import Clarification, ContextError


class InfoContextRequest(BaseModel):
    """A가 C에 보내는 단일 장소 혼잡도 질의 요청."""

    request_id: str = Field(min_length=1)
    intent: Literal["INFO"] = "INFO"
    place_name: str | None = None
    place_context: Literal["explicit", "from_recommendation", "from_conversation"]
    question_type: Literal["concentration"] = "concentration"
    visit_time: str | None = None

    @field_validator("request_id")
    @classmethod
    def normalize_request_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("request_id는 공백일 수 없습니다.")
        return normalized

    @field_validator("place_name")
    @classmethod
    def normalize_place_name(cls, value: str | None) -> str | None:
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


class InfoContextResponse(BaseModel):
    """C가 반환하는 INFO 혼잡도 질의 응답."""

    request_id: str
    intent: Literal["INFO"] = "INFO"
    contract_version: Literal["draft-v0"] = "draft-v0"
    status: Literal[
        "success", "no_data", "needs_clarification", "unsupported", "unavailable"
    ]
    result: ConcentrationInfoResult | None = None
    clarification: Clarification | None = None
    error: ContextError | None = None


__all__ = [
    "ConcentrationInfoResult",
    "InfoContextRequest",
    "InfoContextResponse",
]
