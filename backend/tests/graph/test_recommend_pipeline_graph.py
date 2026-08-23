"""추천 파이프라인 그래프(3단계) 회귀 테스트.

조기 반환 그래프와 마찬가지로, 고정하는 것은 "그래프가 동작한다"가 아니라
**"그래프를 켜도 기존 경로와 결과가 같다"**는 쪽이다
(docs/design/langgraph-adoption.md §6.2).
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.schemas import AgentRequest, Intent
from app.services.runtime import run_agent


@pytest.fixture(autouse=True)
def _restore_flag():
    original = settings.use_langgraph_pipeline
    yield
    settings.use_langgraph_pipeline = original


async def _run(*, flag: bool, text: str):
    settings.use_langgraph_pipeline = flag
    return await run_agent(AgentRequest(user_input=text))


@pytest.mark.parametrize(
    ("label", "text", "expected_intent"),
    [
        ("recommend", "경복궁 근처 카페 추천해줘", Intent.RECOMMEND),
        ("schedule", "경복궁이랑 인사동 3시간 일정 짜줘", Intent.SCHEDULE),
    ],
)
@pytest.mark.asyncio
async def test_graph_matches_legacy_pipeline(
    label: str, text: str, expected_intent: Intent
) -> None:
    """Tool·Scoring을 거치는 경로에서 그래프 on/off 결과가 같아야 한다."""

    legacy = await _run(flag=False, text=text)
    through_graph = await _run(flag=True, text=text)

    assert legacy.llm_output.intent is expected_intent
    assert through_graph.llm_output.intent is expected_intent
    assert through_graph.message == legacy.message
    assert (through_graph.recommendations is None) == (legacy.recommendations is None)
    assert (through_graph.schedule is None) == (legacy.schedule is None)


@pytest.mark.asyncio
async def test_flag_off_skips_the_graph() -> None:
    """플래그를 끄면 파이프라인 그래프를 아예 부르지 않는다 — 되돌리기 경로 확인."""

    from unittest.mock import patch

    import app.services.runtime.agent_runtime as agent_runtime

    settings.use_langgraph_pipeline = False
    with patch.object(agent_runtime, "run_recommend_pipeline_graph") as spy:
        response = await run_agent(AgentRequest(user_input="경복궁 근처 카페 추천해줘"))

    spy.assert_not_called()
    assert response.message


@pytest.mark.asyncio
async def test_flag_on_routes_through_the_graph() -> None:
    """플래그가 켜져 있으면 Tool 경로가 그래프를 탄다."""

    from unittest.mock import patch

    import app.services.runtime.agent_runtime as agent_runtime

    settings.use_langgraph_pipeline = True
    real = agent_runtime.run_recommend_pipeline_graph
    seen: list[str] = []

    async def spy(state, **kwargs):
        seen.append(state["llm_output"].intent.value)
        return await real(state, **kwargs)

    with patch.object(agent_runtime, "run_recommend_pipeline_graph", spy):
        await run_agent(AgentRequest(user_input="경복궁 근처 카페 추천해줘"))

    assert seen == ["RECOMMEND"]


def test_pipeline_routing_table() -> None:
    """조건부 엣지 판정을 표로 고정한다."""

    from app.schemas import LLMOutput, OutputStatus
    from app.services.runtime.graph.routing import (
        ROUTE_DONE,
        ROUTE_FINALIZE,
        ROUTE_SCHEDULE,
        ROUTE_SCORING,
        route_after_scoring,
        route_after_tool_fetch,
    )

    assert route_after_tool_fetch({"response": object()}) == ROUTE_DONE
    assert route_after_tool_fetch({"response": None}) == ROUTE_SCORING

    schedule = LLMOutput(intent=Intent.SCHEDULE, status=OutputStatus.COMPLETE)
    recommend = LLMOutput(intent=Intent.RECOMMEND, status=OutputStatus.COMPLETE)
    assert route_after_scoring({"llm_output": schedule}) == ROUTE_SCHEDULE
    assert route_after_scoring({"llm_output": recommend}) == ROUTE_FINALIZE
