"""INFO(question_type=concentration)의 A→C 계약 초안 (A 제안, C 확인 필요).

concentration-conditions.md §2.4/§3.3, a-c-context-contract-draft.md §3이
스케치해둔 discriminated union(RecommendContextRequest | InfoContextRequest |
CompareContextRequest)의 첫 실제 구현이다.

이 모듈은 C가 소유한 app.agent_context.schemas에 아직 반영되지 않은 상태라
A(이 파일)가 임시로 정의를 들고 있다 — C가 계약을 확정해 자기 스키마에 채택하면
이 파일은 app.services.runtime.context_schemas처럼 단순 재노출로 바뀔 예정이다.
근접치(nearest-attraction) fallback 오케스트레이션 자체는 전부 C 내부 구현이며,
A는 요청을 보내고 구조화된 결과(특히 is_proxy)만 받는다 — agent_runtime.py는
Tool을 직접 호출하지 않는다는 기존 원칙(ToolProvider Protocol 경유)을 그대로
따른다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.services.runtime.context_schemas import Clarification, ContextError


class InfoContextRequest(BaseModel):
    """A가 C에 보내는 INFO 혼잡도 질의 요청."""

    request_id: str
    intent: Literal["INFO"] = "INFO"
    place_name: str | None = None
    place_context: Literal["explicit", "from_recommendation", "from_conversation"]
    question_type: Literal["concentration"] = "concentration"
    visit_time: str | None = None
    """YYYY-MM-DD. concentration-conditions.md §3.2."""


class ConcentrationInfoResult(BaseModel):
    """C가 반환하는 혼잡도 조회 결과 한 건."""

    status: Literal["success", "no_data", "unavailable"]
    is_proxy: bool = False
    """True면 requested_place_name이 아니라 근처 관광지(resolved_place_name)의
    예측치라는 뜻 — concentration-conditions.md §3.3의 고지 규칙 판단 근거."""
    requested_place_name: str | None = None
    resolved_place_name: str | None = None
    forecast_date: str | None = None
    concentration_rate: float | None = Field(default=None, ge=0)
    concentration_level: Literal["quiet", "normal", "slightly_crowded", "crowded"] | None = None
    concentration_label: str | None = None
    error: ContextError | None = None


class InfoContextResponse(BaseModel):
    """C가 반환하는 INFO 혼잡도 질의 응답."""

    request_id: str
    intent: Literal["INFO"] = "INFO"
    contract_version: Literal["draft-v0"] = "draft-v0"
    status: Literal["success", "no_data", "needs_clarification", "unsupported", "unavailable"]
    result: ConcentrationInfoResult | None = None
    clarification: Clarification | None = None
    error: ContextError | None = None


__all__ = [
    "ConcentrationInfoResult",
    "InfoContextRequest",
    "InfoContextResponse",
]
