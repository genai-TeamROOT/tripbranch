"""조건부 엣지 — 상태를 보고 다음 노드 이름을 돌려준다(강의 61-2의 "길 안내원").

지금은 갈래가 둘이다. 3단계에서 인텐트별 노드가 붙으면 이 함수가
`run_agent_flow()`에 흩어진 인텐트 분기 40군데가 모이는 자리가 된다(§2).
"""

from __future__ import annotations

from app.schemas import Intent
from app.services.runtime.graph.pipeline_state import RecommendPipelineState
from app.services.runtime.graph.state import EarlyReturnState

# 조건부 엣지 매핑 키. add_conditional_edges의 변환표와 짝을 이룬다.
ROUTE_GENERAL = "general"
ROUTE_STATIC = "static"


def route_early_return(state: EarlyReturnState) -> str:
    """조각으로 흘려보낼 GENERAL 답변인지, 한 번에 만드는 나머지인지 가른다.

    GENERAL이라도 단발 `POST /api/chat`(sink 없음)에서는 흘려보낼 곳이 없어
    static으로 간다 — 기존 `run_agent_flow()`의 분기 조건과 같다.
    """

    if state["llm_output"].intent is Intent.GENERAL and state["stream_general"]:
        return ROUTE_GENERAL
    return ROUTE_STATIC


__all__ = [
    "ROUTE_DONE",
    "ROUTE_FINALIZE",
    "ROUTE_GENERAL",
    "ROUTE_SCHEDULE",
    "ROUTE_SCORING",
    "ROUTE_STATIC",
    "route_after_scoring",
    "route_after_tool_fetch",
    "route_early_return",
]


# ── 추천 파이프라인 조건부 엣지 ────────────────────────────────────────

ROUTE_DONE = "done"
ROUTE_SCORING = "scoring"
ROUTE_SCHEDULE = "schedule"
ROUTE_FINALIZE = "finalize"


def route_after_tool_fetch(state: RecommendPipelineState) -> str:
    """C가 되묻기·no_data·unsupported로 끝냈으면 여기서 종료한다."""

    if state.get("response") is not None:
        return ROUTE_DONE
    return ROUTE_SCORING


def route_after_scoring(state: RecommendPipelineState) -> str:
    """SCHEDULE이면 편성으로, 아니면 추천 마무리로 간다.

    `run_agent_flow()`에 남아 있던 `if is_schedule:` 하나가 여기로 옮겨온 것이다 —
    조기 반환 이후 구간의 인텐트 분기는 원래 이 하나뿐이었다(§9.8).
    """

    if state["llm_output"].intent is Intent.SCHEDULE:
        return ROUTE_SCHEDULE
    return ROUTE_FINALIZE
