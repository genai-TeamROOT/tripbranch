"""Package B - Agent State 데이터 모델.

계약 문서: docs/package-b/agent-state-contract-v1.md (1절, 3절)
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    """타임존이 포함된 현재 시각."""
    return datetime.now(KST)


# ---------------------------------------------------------------- 조건

class UserConditions(BaseModel):
    """사용자 발화에서 추출된 조건 15개. (계약 1.2절)

    B는 각 필드의 허용값을 검증하지 않는다. 허용값 정의는 Package A의 책임이다.
    """

    current_location: str | None = None
    search_center: str | None = None
    place_types: list[str] = Field(default_factory=list)
    place_tags: list[str] = Field(default_factory=list)
    weather: str | None = None
    weather_intent: str | None = None
    concentration_intent: str | None = None
    transport: str | None = None
    max_travel_time: int | None = None   # 분
    time_available: int | None = None    # 분
    environment: str | None = None
    companion: str | None = None
    budget: str | None = None
    exclude_tags: list[str] = Field(default_factory=list)
    special_requirements: list[str] = Field(default_factory=list)


class ApiContext(BaseModel):
    """외부 API로 확보한 데이터. (계약 1.4절)

    operations 대상이 아니며 별도 경로로 갱신한다.
    condition_version 증가 판정에서 제외한다.
    """

    gps_location: str | None = None
    api_weather: str | None = None
    gps_location_updated_at: datetime | None = None
    api_weather_updated_at: datetime | None = None


# ---------------------------------------------------------------- 상태

class AgentState(BaseModel):
    """세션 단위 현재 상태. (계약 1.6절)"""

    session_id: str
    user_conditions: UserConditions = Field(default_factory=UserConditions)
    api_context: ApiContext = Field(default_factory=ApiContext)
    condition_version: int = 0
    last_run_id: str | None = None
    last_intent: str | None = None
    # 직전 턴이 되묻기로 끝났을 때 그 사유 코드(예: "location_required").
    # B는 판단하지 않고 A가 준 값을 보관만 한다 — 되묻기 판정은 LLM과 C가 하고,
    # 소비(부분 갱신 여부 결정)는 A의 state_transform이 한다.
    pending_clarification: str | None = None
    status: Literal["active", "expired"] = "active"
    created_at: datetime = Field(default_factory=now_kst)
    updated_at: datetime = Field(default_factory=now_kst)
    last_active_at: datetime = Field(default_factory=now_kst)


# ---------------------------------------------------------------- 이력

class RecommendedItem(BaseModel):
    """노출된 장소 1건. (계약 3.2절)"""

    place_id: str
    run_id: str
    rank: int
    shown_at: datetime = Field(default_factory=now_kst)


class RejectedItem(BaseModel):
    """거절된 장소 1건. (계약 3.2절)

    reason_code는 Package A가 해석한 값을 그대로 저장하며 검증하지 않는다.
    """

    place_id: str
    run_id: str
    reason_code: str | None = None
    rejected_at: datetime = Field(default_factory=now_kst)


class RecommendationHistory(BaseModel):
    """세션 단위 추천·거절 이력. append-only. (계약 3.2절)"""

    session_id: str
    recommended: list[RecommendedItem] = Field(default_factory=list)
    rejected: list[RejectedItem] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=now_kst)


# ---------------------------------------------------------------- 기록

class ConditionChangeLog(BaseModel):
    """조건 변경 기록 1건. append-only. (계약 2.8절, 5.5절)

    사용자 원문 발화와 LLM 원문 응답은 기록하지 않는다.
    """

    session_id: str
    run_id: str
    seq: int
    op: str                       # Add / Update / Remove / Reset
    field: str | None = None      # Reset인 경우 None
    before_value: Any = None
    after_value: Any = None
    reset_scope: str | None = None
    applied_at: datetime = Field(default_factory=now_kst)


class TraceRecord(BaseModel):
    """실행 단계 1건. append-only. (docs/package-b/llmops-trace-contract-v1.md 2절)

    step/prompt_version/scoring_version/variant_id/error_type은 호출자(A/C/D)가
    해석한 값을 그대로 저장하며 검증하지 않는다 — B는 값의 의미를 판단하지 않는다.
    """

    session_id: str
    run_id: str
    trace_id: str
    step: str
    prompt_version: str | None = None
    scoring_version: str | None = None
    variant_id: str | None = None
    latency_ms: int | None = None
    token_usage: int | None = None
    error_type: str | None = None
    recorded_at: datetime = Field(default_factory=now_kst)