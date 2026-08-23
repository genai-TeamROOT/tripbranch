"""인텐트 라우팅 그래프 — 조기 반환 경로(Tool/Scoring 없이 끝나는 턴)를 맡는다.

설계·단계 계획은 docs/design/langgraph-adoption.md 참고. 지금 범위는 §6.1의
2단계다 — 분류·조건 병합은 여전히 `run_agent_flow()`가 하고, 그 뒤 답변 문구를
만드는 일만 이 그래프가 맡는다. RECOMMEND/MODIFY/SCHEDULE은 Tool·Scoring이 붙어
있어 기존 경로 그대로다(3단계 대상).

**이 그래프는 출력이 기존과 같아야 한다.** 구조만 옮기는 작업이라 응답 문자열이나
SSE 이벤트 순서가 달라지면 그건 버그다(§6.2).
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.providers.protocols import LLMProvider
from app.schemas import AgentResponse, LLMOutput
from app.services.runtime.graph.nodes.general import general_answer_node
from app.services.runtime.graph.nodes.pipeline import (
    PipelineDeps,
    finalize_node,
    schedule_node,
    scoring_node,
    tool_fetch_node,
)
from app.services.runtime.graph.nodes.static_answer import static_answer_node
from app.services.runtime.graph.pipeline_state import RecommendPipelineState
from app.services.runtime.graph.routing import (
    ROUTE_DONE,
    ROUTE_FINALIZE,
    ROUTE_GENERAL,
    ROUTE_SCHEDULE,
    ROUTE_SCORING,
    ROUTE_STATIC,
    route_after_scoring,
    route_after_tool_fetch,
    route_early_return,
)
from app.services.runtime.graph.sink import DEPS_CONFIG_KEY, LLM_CONFIG_KEY, SINK_CONFIG_KEY
from app.services.runtime.graph.state import EarlyReturnState
from app.services.runtime.stream_events import StreamEventSink


def build_early_return_graph():
    """조기 반환 경로 그래프를 조립한다.

    ```
    START → ◇route_early_return
              ├─ general → [general_answer]  (조각으로 흘려보냄)
              └─ static  → [static_answer]   (한 번에 만듦)
                                 ↓
                                END
    ```

    갈래가 둘뿐이라 지금은 if/else로도 되지만(강의 61-2가 인정하는 지점), 3단계에서
    인텐트별 노드가 붙을 자리를 여기 만들어 둔다.
    """

    graph = StateGraph(EarlyReturnState)
    graph.add_node("general_answer", general_answer_node)
    graph.add_node("static_answer", static_answer_node)
    graph.add_conditional_edges(
        START,
        route_early_return,
        {ROUTE_GENERAL: "general_answer", ROUTE_STATIC: "static_answer"},
    )
    graph.add_edge("general_answer", END)
    graph.add_edge("static_answer", END)
    # checkpointer: 지금은 한 턴 안에서 끝나 상태를 이어받을 일이 없지만, 4단계에서
    # StateStore를 BaseCheckpointSaver로 바꿔 끼울 자리를 미리 만들어 둔다.
    # thread_id로는 우리 session_id를 그대로 쓴다(§7.4).
    return graph.compile(checkpointer=MemorySaver())


# 프로세스 수명 동안 한 번만 조립한다 — 그래프 컴파일은 요청마다 할 일이 아니다.
_EARLY_RETURN_GRAPH = build_early_return_graph()


async def run_early_return_graph(
    llm_output: LLMOutput,
    *,
    llm: LLMProvider,
    session_id: str,
    stream_event_sink: StreamEventSink | None = None,
    stream_general: bool = False,
) -> str:
    """조기 반환 경로의 답변 문구를 그래프로 만들어 문자열로 돌려준다.

    호출부(`run_agent_flow()`)가 기대하는 것은 기존 `compose_chat_message()`와 같은
    문자열 하나다 — 그래프로 바뀐 것을 호출부가 알 필요가 없게 시그니처를 맞췄다.
    """

    result = await _EARLY_RETURN_GRAPH.ainvoke(
        {"llm_output": llm_output, "stream_general": stream_general, "answer": None},
        config={
            "configurable": {
                "thread_id": session_id,
                SINK_CONFIG_KEY: stream_event_sink,
                LLM_CONFIG_KEY: llm,
            }
        },
    )
    return result["answer"] or ""


def build_recommend_pipeline_graph():
    """추천 파이프라인 그래프를 조립한다(3단계).

    ```
    START → [tool_fetch] → ◇route_after_tool_fetch
                              ├─ done    →────────────────┐  (C가 되묻기/no_data로 끝냄)
                              └─ scoring → [scoring]      │
                                              ↓            │
                                     ◇route_after_scoring  │
                                       ├─ schedule → [schedule] ┤
                                       └─ finalize → [finalize] ┤
                                                                ↓
                                                               END
    ```

    갈림길이 둘 생겼다 — 조기 반환 그래프(`build_early_return_graph`)와 달리 여기는
    단계가 순차로 이어지는 파이프라인이라, 조건부 엣지는 "중간에 끝나는가"와
    "SCHEDULE인가" 두 판정에만 쓴다(§9.8).
    """

    graph = StateGraph(RecommendPipelineState)
    graph.add_node("tool_fetch", tool_fetch_node)
    graph.add_node("scoring", scoring_node)
    graph.add_node("schedule", schedule_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "tool_fetch")
    graph.add_conditional_edges(
        "tool_fetch",
        route_after_tool_fetch,
        {ROUTE_DONE: END, ROUTE_SCORING: "scoring"},
    )
    graph.add_conditional_edges(
        "scoring",
        route_after_scoring,
        {ROUTE_SCHEDULE: "schedule", ROUTE_FINALIZE: "finalize"},
    )
    graph.add_edge("schedule", END)
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=MemorySaver())


_RECOMMEND_PIPELINE_GRAPH = build_recommend_pipeline_graph()


async def run_recommend_pipeline_graph(
    state: RecommendPipelineState,
    *,
    deps: PipelineDeps,
    session_id: str,
    stream_event_sink: StreamEventSink | None = None,
) -> AgentResponse:
    """Tool 조회부터 응답 조립까지를 그래프로 돌려 최종 응답을 돌려준다."""

    result = await _RECOMMEND_PIPELINE_GRAPH.ainvoke(
        state,
        config={
            "configurable": {
                "thread_id": session_id,
                SINK_CONFIG_KEY: stream_event_sink,
                LLM_CONFIG_KEY: deps.llm,
                DEPS_CONFIG_KEY: deps,
            }
        },
    )
    response = result.get("response")
    if response is None:  # 그래프가 응답 없이 끝나면 배선이 잘못된 것이다
        raise RuntimeError("추천 파이프라인 그래프가 응답을 만들지 못했습니다.")
    return response


__all__ = [
    "PipelineDeps",
    "build_early_return_graph",
    "build_recommend_pipeline_graph",
    "run_early_return_graph",
    "run_recommend_pipeline_graph",
]
