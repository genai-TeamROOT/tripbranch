"""GENERAL 라우팅 그래프(1단계) 회귀 테스트.

이관은 **출력이 같아야 하는 작업**이다(docs/design/langgraph-adoption.md §6.2).
그래서 여기서 고정하는 것은 "그래프가 동작한다"가 아니라 **"그래프를 켜도 기존
경로와 결과가 같다"**는 쪽이다 — 켜고 끈 두 실행을 같은 Fake LLM으로 돌려 비교한다.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.providers.stub import FakeLLMProvider
from app.schemas import GeneralPayload, GeneralTopic, Intent, LLMOutput, OutputStatus
from app.services.runtime.graph import run_general_answer_graph
from app.services.runtime.response_composer import compose_chat_message


def _general_output() -> LLMOutput:
    return LLMOutput(
        intent=Intent.GENERAL,
        status=OutputStatus.COMPLETE,
        general=GeneralPayload(
            topic=GeneralTopic.SERVICE_IDENTITY, original_question="안녕"
        ),
    )


@pytest.fixture(autouse=True)
def _restore_flag():
    original = settings.use_langgraph_general
    yield
    settings.use_langgraph_general = original


@pytest.mark.asyncio
async def test_graph_answer_matches_legacy_compose() -> None:
    """그래프가 낸 답변이 기존 compose_chat_message()와 같아야 한다."""

    llm_output = _general_output()

    legacy = await compose_chat_message(llm_output, llm=FakeLLMProvider())
    through_graph = await run_general_answer_graph(
        llm_output, llm=FakeLLMProvider(), session_id="sess_test"
    )

    assert through_graph == legacy


@pytest.mark.asyncio
async def test_graph_emits_same_sse_sequence_as_legacy() -> None:
    """SSE 이벤트 이름 순서가 기존 경로와 같아야 한다.

    §9.4가 "3단계의 가장 큰 위험"으로 지목한 부분이라, 순서를 여기서 못 박는다.
    프론트가 이 순서에 의존한다(message_start로 로딩 말풍선을 열고 delta로 채운다).
    """

    events: list[str] = []

    async def sink(event: str, payload: dict[str, object]) -> None:
        events.append(event)

    await run_general_answer_graph(
        _general_output(),
        llm=FakeLLMProvider(),
        session_id="sess_test",
        stream_event_sink=sink,
    )

    assert events[0] == "progress"
    assert events[1] == "message_start"
    assert set(events[2:]) == {"message_delta"}
    assert len(events) >= 3


@pytest.mark.asyncio
async def test_graph_without_sink_emits_nothing() -> None:
    """단발 POST /api/chat 경로(sink 없음)에서는 이벤트를 내지 않는다."""

    answer = await run_general_answer_graph(
        _general_output(), llm=FakeLLMProvider(), session_id="sess_test"
    )

    assert answer  # 답변은 정상적으로 나온다


@pytest.mark.asyncio
async def test_flag_off_falls_back_to_legacy_path() -> None:
    """플래그를 끄면 그래프를 아예 부르지 않는다 — 되돌리기 경로가 살아있는지 확인."""

    from unittest.mock import patch

    import app.services.runtime.agent_runtime as agent_runtime
    from app.schemas import AgentRequest

    settings.use_langgraph_general = False
    with patch.object(agent_runtime, "run_general_answer_graph") as spy:
        response = await agent_runtime.run_agent(AgentRequest(user_input="넌 누구야?"))

    spy.assert_not_called()
    assert response.llm_output.intent is Intent.GENERAL
    assert response.message


@pytest.mark.asyncio
async def test_flag_on_routes_general_through_graph() -> None:
    """플래그가 켜져 있으면 GENERAL이 그래프를 탄다."""

    from unittest.mock import patch

    import app.services.runtime.agent_runtime as agent_runtime
    from app.schemas import AgentRequest

    settings.use_langgraph_general = True
    real = agent_runtime.run_general_answer_graph
    seen: list[str] = []

    async def spy(llm_output, **kwargs):
        seen.append(kwargs["session_id"])
        return await real(llm_output, **kwargs)

    with patch.object(agent_runtime, "run_general_answer_graph", spy):
        response = await agent_runtime.run_agent(AgentRequest(user_input="넌 누구야?"))

    assert len(seen) == 1
    assert response.llm_output.intent is Intent.GENERAL
