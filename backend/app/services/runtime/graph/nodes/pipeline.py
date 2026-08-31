"""추천 파이프라인 노드 — 이미 함수로 떼어낸 4단계를 그래프에 붙인다.

강의 91-3의 "부품을 노드로 포장한다"를 그대로 따른다. 각 노드가 하는 일은
(1) 서류철에서 입력을 꺼내고 (2) `agent_runtime`의 단계 함수를 **호출만** 하고
(3) 결과를 자기 칸에 담아 돌려주는 것뿐이다 — 단계 함수의 속은 건드리지 않는다.

노드가 얇아야 하는 이유는 실용적이다. 두꺼워지면 "이관"이 아니라 "재작성"이 되고,
기존 테스트가 지켜주던 범위를 벗어난다(langgraph-adoption.md §6.2).
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.runnables import RunnableConfig

from app.providers.protocols import LLMProvider
from app.services.runtime.graph.pipeline_state import RecommendPipelineState
from app.services.runtime.graph.sink import deps_from_config, sink_from_config
from app.services.runtime.protocols import (
    EnrichmentProvider,
    RecommendationProvider,
    ToolProvider,
    TravelRouteToolProvider,
)
from app.state.store import StateStore


@dataclass(frozen=True)
class PipelineDeps:
    """요청마다 달라지지 않고 주입되는 것들. 서류철이 아니라 config로 넘긴다."""

    llm: LLMProvider
    tool_provider: ToolProvider
    recommendation_provider: RecommendationProvider
    enrichment_provider: EnrichmentProvider
    travel_route_tool: TravelRouteToolProvider | None
    store: StateStore | None
    principal: object | None


async def tool_fetch_node(
    state: RecommendPipelineState, config: RunnableConfig
) -> dict[str, object]:
    """A → C Tool 조회(5단계). 종료 상태면 ``response``를 채워 그 턴을 끝낸다."""

    from app.services.runtime.agent_runtime import (
        _fetch_tool_context,
        _revivable_place_ids,
    )

    deps: PipelineDeps = deps_from_config(config)
    outcome = await _fetch_tool_context(
        state["request"],
        state["llm_output"],
        state["state_response"],
        valid_gps=state["valid_gps"],
        effective_ignore_operating_hours=state["effective_ignore_operating_hours"],
        llm=deps.llm,
        tool_provider=deps.tool_provider,
        travel_route_tool=deps.travel_route_tool,
        store=deps.store,
        shown_place_ids=_revivable_place_ids(
            state["llm_output"], state["session_context"]
        ),
        stream_event_sink=sink_from_config(config),
    )
    if outcome.terminal is not None:
        return {"response": outcome.terminal}
    return {
        "tool_context": outcome.tool_context,
        "agent_conditions": outcome.agent_conditions,
        "context_gps": outcome.context_gps,
        "tool_execution": outcome.tool_execution,
        "tool_executions": outcome.tool_executions,
    }


async def scoring_node(
    state: RecommendPipelineState, config: RunnableConfig
) -> dict[str, object]:
    """A → D 1차 Scoring과 후보 보충·혼잡도 재정렬(6단계)."""

    from app.schemas import Intent
    from app.services.runtime.agent_runtime import (
        _revivable_place_ids,
        _score_recommendations,
    )

    deps: PipelineDeps = deps_from_config(config)
    recommendations = await _score_recommendations(
        state["state_response"],
        tool_context=state["tool_context"],
        agent_conditions=state["agent_conditions"],
        context_gps=state["context_gps"],
        is_schedule=state["llm_output"].intent is Intent.SCHEDULE,
        shown_place_ids=_revivable_place_ids(
            state["llm_output"], state["session_context"]
        ),
        tool_provider=deps.tool_provider,
        recommendation_provider=deps.recommendation_provider,
        enrichment_provider=deps.enrichment_provider,
        travel_route_tool=deps.travel_route_tool,
        store=deps.store,
        principal=deps.principal,
        tool_executions=state["tool_executions"],
        effective_ignore_operating_hours=state["effective_ignore_operating_hours"],
        stream_event_sink=sink_from_config(config),
    )
    return {"recommendations": recommendations}


async def schedule_node(
    state: RecommendPipelineState, config: RunnableConfig
) -> dict[str, object]:
    """SCHEDULE 편성(6-2단계)."""

    from app.services.runtime.agent_runtime import _run_schedule_branch

    deps: PipelineDeps = deps_from_config(config)
    response = await _run_schedule_branch(
        state["llm_output"],
        state["state_response"],
        state["recommendations"],
        tool_context=state["tool_context"],
        agent_conditions=state["agent_conditions"],
        session_context=state["session_context"],
        llm=deps.llm,
        store=deps.store,
        principal=deps.principal,
        tool_execution=state["tool_execution"],
        tool_executions=state["tool_executions"],
        effective_ignore_operating_hours=state["effective_ignore_operating_hours"],
        stream_event_sink=sink_from_config(config),
    )
    return {"response": response}


async def finalize_node(
    state: RecommendPipelineState, config: RunnableConfig
) -> dict[str, object]:
    """노출 이력 기록과 카드·요약 방출(7·8단계)."""

    from app.services.runtime.agent_runtime import _finalize_recommendation_response

    deps: PipelineDeps = deps_from_config(config)
    response = await _finalize_recommendation_response(
        state["llm_output"],
        state["state_response"],
        state["recommendations"],
        llm=deps.llm,
        store=deps.store,
        principal=deps.principal,
        tool_context=state["tool_context"],
        tool_execution=state["tool_execution"],
        tool_executions=state["tool_executions"],
        effective_ignore_operating_hours=state["effective_ignore_operating_hours"],
        stream_recommendation_summary=state["stream_recommendation_summary"],
        stream_event_sink=sink_from_config(config),
    )
    return {"response": response}


__all__ = [
    "PipelineDeps",
    "finalize_node",
    "schedule_node",
    "scoring_node",
    "tool_fetch_node",
]
