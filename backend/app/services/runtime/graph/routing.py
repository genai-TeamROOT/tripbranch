"""조건부 엣지 — 상태를 보고 다음 노드 이름을 돌려준다(강의 61-2의 "길 안내원").

지금은 갈래가 둘이다. 3단계에서 인텐트별 노드가 붙으면 이 함수가
`run_agent_flow()`에 흩어진 인텐트 분기 40군데가 모이는 자리가 된다(§2).
"""

from __future__ import annotations

from app.schemas import Intent
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


__all__ = ["ROUTE_GENERAL", "ROUTE_STATIC", "route_early_return"]
