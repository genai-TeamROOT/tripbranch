"""GENERAL 답변 생성 노드.

강의 91-3의 "부품을 노드로 포장한다"를 그대로 따른다 — 이미 동작하는
`compose_chat_message()`를 노드 안에서 **호출만** 하고 속은 건드리지 않는다.
이 노드가 하는 일은 (1) 서류철에서 입력을 꺼내고 (2) 부품에 넣고 (3) 결과를
자기 칸에 담아 돌려주는 것뿐이다.

SSE 이벤트는 노드가 직접 낸다(langgraph-adoption.md §9.6 "방식 1"). 그래프
스트리밍을 쓰지 않는 이유는 그 절에 적어뒀다.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from app.providers.protocols import LLMProvider
from app.schemas import Intent
from app.services.runtime.graph.sink import llm_from_config, sink_from_config
from app.services.runtime.graph.state import GeneralAnswerState
from app.services.runtime.response_composer import compose_chat_message
from app.services.runtime.stream_events import begin_streamed_message, emit_stream_event

# 기존 run_agent_flow()가 GENERAL에 쓰던 문구 그대로. 이관은 출력이 바뀌면 안 된다.
_PROGRESS_MESSAGE = "답변을 정리하고 있어요."


async def general_answer_node(
    state: GeneralAnswerState, config: RunnableConfig
) -> dict[str, object]:
    """GENERAL 답변을 만들어 ``answer`` 칸에 담는다.

    sink가 있으면(SSE 경로) 기존과 같은 순서로 이벤트를 낸다:
    ``progress`` → ``message_start`` → ``message_delta`` × N.
    sink가 없으면(단발 ``POST /api/chat``) 이벤트 없이 문자열만 만든다 — 기존
    `run_agent_flow()`의 `stream_recommendation_summary` 분기와 같은 동작이다.

    ``config``는 반드시 ``RunnableConfig``로 어노테이션해야 LangGraph가 주입한다
    (sink.py 참고).
    """

    sink = sink_from_config(config)
    llm: LLMProvider = llm_from_config(config)
    llm_output = state["llm_output"]

    if sink is not None:
        await begin_streamed_message(
            sink, intent=Intent.GENERAL, progress_message=_PROGRESS_MESSAGE
        )

        async def on_delta(text: str) -> None:
            await emit_stream_event(sink, "message_delta", {"text": text})

    else:
        on_delta = None  # type: ignore[assignment]

    message = await compose_chat_message(
        llm_output,
        llm=llm,
        on_message_delta=on_delta,
    )
    return {"answer": message}


__all__ = ["general_answer_node"]
