"""인텐트 라우팅 그래프 — 1단계(GENERAL 경로)만 담당한다.

설계·단계 계획은 docs/design/langgraph-adoption.md 참고. 지금 범위는 §6.1의
1단계다 — 분류·조건 병합은 여전히 `run_agent_flow()`가 하고, 그 뒤 GENERAL
답변 생성만 이 그래프가 맡는다. 나머지 6개 인텐트는 기존 경로 그대로다.

**이 그래프는 출력이 기존과 같아야 한다.** 구조만 옮기는 작업이라 응답 문자열이나
SSE 이벤트 순서가 달라지면 그건 버그다(§6.2).
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.providers.protocols import LLMProvider
from app.schemas import LLMOutput
from app.services.runtime.graph.nodes.general import general_answer_node
from app.services.runtime.graph.sink import LLM_CONFIG_KEY, SINK_CONFIG_KEY
from app.services.runtime.graph.state import GeneralAnswerState
from app.services.runtime.stream_events import StreamEventSink


def build_general_graph():
    """GENERAL 답변 그래프를 조립한다.

    지금은 노드 하나짜리 외길이다 — 1단계 목적이 "그래프가 실제 SSE 경로를 통해
    기존과 똑같이 동작하는가"를 증명하는 것이라, 갈림길을 먼저 늘리지 않는다.
    2단계에서 OUT_OF_SCOPE·되묻기가 붙으면서 조건부 엣지가 생긴다.
    """

    graph = StateGraph(GeneralAnswerState)
    graph.add_node("general_answer", general_answer_node)
    graph.add_edge(START, "general_answer")
    graph.add_edge("general_answer", END)
    # checkpointer: 지금은 한 턴 안에서 끝나 상태를 이어받을 일이 없지만, 4단계에서
    # StateStore를 BaseCheckpointSaver로 바꿔 끼울 자리를 미리 만들어 둔다.
    # thread_id로는 우리 session_id를 그대로 쓴다(§7.4).
    return graph.compile(checkpointer=MemorySaver())


# 프로세스 수명 동안 한 번만 조립한다 — 그래프 컴파일은 요청마다 할 일이 아니다.
_GENERAL_GRAPH = build_general_graph()


async def run_general_answer_graph(
    llm_output: LLMOutput,
    *,
    llm: LLMProvider,
    session_id: str,
    stream_event_sink: StreamEventSink | None = None,
) -> str:
    """GENERAL 답변을 그래프로 만들어 문자열로 돌려준다.

    호출부(`run_agent_flow()`)가 기대하는 것은 기존 `compose_chat_message()`와 같은
    문자열 하나다 — 그래프로 바뀐 것을 호출부가 알 필요가 없게 시그니처를 맞췄다.
    """

    result = await _GENERAL_GRAPH.ainvoke(
        {"llm_output": llm_output, "answer": None},
        config={
            "configurable": {
                "thread_id": session_id,
                SINK_CONFIG_KEY: stream_event_sink,
                LLM_CONFIG_KEY: llm,
            }
        },
    )
    return result["answer"] or ""


__all__ = ["build_general_graph", "run_general_answer_graph"]
