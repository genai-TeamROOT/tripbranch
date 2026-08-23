"""GENERAL 경로 그래프가 노드 사이에 돌리는 상태(강의 61-2의 "공유 서류철").

1단계 범위라 칸이 적다(docs/design/langgraph-adoption.md §6.1.2). 인텐트 분류·조건
병합은 아직 그래프 밖(`run_agent_flow()`)에서 끝난 뒤 결과만 넘어오므로, 여기서는
"답변을 만들어 담는" 데 필요한 것만 둔다.

`AgentState`(app/state/schema.py)를 그대로 쓰지 않는 이유: 그건 B가 세션에 보관하는
누적 상태이고, 이건 한 턴 안에서 노드끼리 주고받는 작업용 서류철이라 수명이 다르다.
3단계에서 그래프가 흐름 전체를 가지게 되면 두 개의 관계를 다시 정한다.
"""

from __future__ import annotations

from typing import TypedDict

from app.schemas import LLMOutput


class GeneralAnswerState(TypedDict):
    """GENERAL 답변 생성 한 턴의 작업 상태."""

    # 분류·추출이 끝난 결과. 그래프는 이 값을 읽기만 하고 바꾸지 않는다.
    llm_output: LLMOutput
    # 답변 노드가 채우는 칸.
    answer: str | None


__all__ = ["GeneralAnswerState"]
