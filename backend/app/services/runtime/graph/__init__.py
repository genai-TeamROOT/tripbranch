"""인텐트 라우팅 그래프 — 조기 반환 경로(Tool/Scoring 없이 끝나는 턴)를 맡는다.

설계·단계 계획은 docs/design/langgraph-adoption.md 참고. 지금 범위는 §6.1의
2단계다 — 분류·조건 병합은 여전히 `run_agent_flow()`가 하고, 그 뒤 답변 문구를
만드는 일만 이 그래프가 맡는다. RECOMMEND/MODIFY/SCHEDULE은 Tool·Scoring이 붙어
있어 기존 경로 그대로다(3단계 대상).

**이 그래프는 출력이 기존과 같아야 한다.** 구조만 옮기는 작업이라 응답 문자열이나
SSE 이벤트 순서가 달라지면 그건 버그다(§6.2).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from functools import wraps
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.observability.langfuse_tracing import observe_step, trace_attributes
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

logger = logging.getLogger(__name__)


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
    # checkpointer는 달지 않는다(§9.9). 우리 그래프는 한 턴 안에서 시작하고 끝나며,
    # 턴 사이 상태는 B(StateStore)가 이미 자기 계약으로 관리한다. 보관함을 달면
    # 같은 session_id의 다음 턴에 이전 턴 값이 남아 섞이고(실측 확인), 세션마다
    # 체크포인트가 RAM에 무한정 쌓인다.
    return graph.compile()


# 한 span에 실을 후보 수 상한. 1차 Scoring 후보 예산이 10이라 그 이상은 안 나오지만,
# 예산이 늘어도 span 하나가 수 KB로 부풀지 않게 막아 둔다.
_SUMMARY_ITEM_LIMIT = 10


def _round_scores(scores: Mapping[str, float | None] | None) -> dict[str, float | None]:
    """소수점을 줄여 화면에서 읽히게 한다. 0.7234891은 볼 때 방해만 된다."""
    if not scores:
        return {}
    return {
        key: (round(value, 3) if isinstance(value, int | float) else None)
        for key, value in scores.items()
    }


def _summarize_tool_fetch(result: Mapping[str, Any]) -> dict[str, Any] | None:
    """`tool_fetch` span에 실을 값을 고른다.

    **여기는 원래 비워 뒀던 자리다.** 좌표와 외부 API 자격증명이 흐르는 경로라
    이름·지연만 남겼는데, 그 결과 span 하나가 빈 상자였다 — C가 Provider를 몇 개
    불렀고 무엇이 실패했는지 화면에서 알 수 없었다. 지금은 **인자와 응답 원문은
    그대로 빼고 상태·개수만** 싣는다. 그 값들은 `ToolExecutionDebug`가 이미
    개발자 Audit용으로 만들어 두고 있어서 새로 수집하는 게 아니다.

    **`resolved_location_name`·`resolved_location_address`는 일부러 뺀다.** C가
    발화에서 풀어낸 장소명·주소라 사용자가 어디 있는지/어디를 찾는지를 그대로
    드러낸다 — `capture_content`를 꺼도 여긴 안 새야 한다.

    조기 종료(`response`만 채워 그 턴을 끝낸 경우)는 Tool 기록이 아예 없으므로
    `terminal`만 남긴다 — 값이 없는 것과 단계를 건너뛴 것이 구분돼야 한다.
    """
    executions = list(result.get("tool_executions") or [])
    terminal = result.get("response") is not None
    if not executions and not terminal:
        return None
    return {
        "terminal": terminal,
        "call_count": len(executions),
        "calls": [
            {
                "operation": execution.operation,
                "status": execution.status,
                "latency_ms": execution.latency_ms,
                "providers": [
                    {"source": provider.source, "status": provider.status}
                    for provider in execution.providers
                ],
                # fetched=False는 실패가 아니라 "아예 조회하지 않음"이다
                # (발화에 이미 값이 있어 생략한 경우 등). 둘을 구분해 적는다.
                "items": {
                    item.key: (item.status or "unknown") if item.fetched else "skipped"
                    for item in execution.context_items
                },
                "item_errors": {
                    item.key: item.error_code for item in execution.context_items if item.error_code
                },
                "rule_versions": dict(execution.rule_versions),
            }
            for execution in executions[:_SUMMARY_ITEM_LIMIT]
        ],
    }


def _summarize_scoring(result: Mapping[str, Any]) -> dict[str, Any] | None:
    """`scoring` span에 실을 값을 고른다.

    **통째로 넣지 않는다.** `RecommendationItem`은 필드가 17개라 후보 10곳이면 한 span이
    수 KB가 되고, 그중 `taste_evidence`(근거 문장 원문)와 `explanations`는 화면에서
    점수를 읽는 데 방해만 된다. 여기서 보고 싶은 건 **"어느 축이 몇 점이었나"**다 —
    2026-08-25에 거리 점수가 0으로 나오는 원인을 쫓을 때, 이 값이 없어서 실제 API
    응답을 따로 받아야 했다.

    좌표는 애초에 여기 없다. C가 장소를 찾을 때만 쓰고 D로 넘어올 땐 `distance_km`로
    접힌다(`ScoringCandidate`) — 그래서 이 span은 열어도 위치가 새지 않는다.
    """
    response = result.get("recommendations")
    if response is None:
        return None
    items = list(getattr(response, "recommendations", []) or [])
    return {
        "ranked": [
            {
                "place_id": item.place_id,
                "name": item.name,
                "score": round(item.score, 3),
                "features": _round_scores(item.feature_scores),
                # 취향·혼잡도가 켜졌는지에 따라 세트가 달라지는데 지금은 눈에 안 보인다.
                "weights": _round_scores(item.weights_used),
            }
            for item in items[:_SUMMARY_ITEM_LIMIT]
        ],
        "ranked_count": len(items),
        "unverified_count": len(getattr(response, "unverified_recommendations", []) or []),
        "excluded_closed_count": len(getattr(response, "excluded_closed_place_ids", []) or []),
        "excluded_all_closed": getattr(response, "excluded_all_closed", False),
    }


def _summarize_finalize(result: Mapping[str, Any]) -> dict[str, Any] | None:
    """`finalize` span에 실을 값을 고른다.

    **답변 문장은 길이만 남긴다.** 원문은 발화만큼이나 사용자 것이고, 여기서 알고 싶은
    건 "문장이 나갔나"와 "카드가 몇 장 어떤 순서로 나갔나"다. 원문이 필요하면
    generation의 output에 이미 있다.
    """
    response = result.get("response")
    if response is None:
        return None
    recommendations = getattr(response, "recommendations", None)
    shown = list(getattr(recommendations, "recommendations", []) or [])
    unverified = list(getattr(recommendations, "unverified_recommendations", []) or [])
    message = getattr(response, "message", None)
    return {
        "card_order": [item.place_id for item in (shown + unverified)[:_SUMMARY_ITEM_LIMIT]],
        "card_count": len(shown) + len(unverified),
        "message_length": len(message) if message else 0,
        "has_schedule": getattr(response, "schedule", None) is not None,
        "has_comparison": getattr(response, "comparison", None) is not None,
    }


def _observed(
    name: str,
    node: Callable[..., Awaitable[Any]],
    summarize: Callable[[Mapping[str, Any]], dict[str, Any] | None] | None = None,
) -> Callable[..., Awaitable[Any]]:
    """노드 하나를 관측 span 하나로 감싼다.

    **Langfuse가 주는 LangChain CallbackHandler를 안 쓰는 이유**: 그 핸들러가
    `langchain` **본체**를 import한다. 우리는 langgraph가 끌고 온 `langchain-core`만
    두고 본체·통합 패키지는 의도적으로 안 넣었다(pyproject.toml). 2026-08-25에
    콜백으로 붙여봤다가 `ModuleNotFoundError`로 조용히 꺼지는 걸 실측으로 확인했다 —
    앱은 멀쩡했고 노드 span만 통째로 안 생겼다.

    직접 감싸면 의존성도 안 늘고 **이름을 우리가 정한다.** `tool_fetch`·`scoring`은
    B의 Trace `step`과 같은 이름이라 두 기록을 나란히 읽을 수 있다.

    `summarize`를 주면 노드 결과에서 **고른 값만** span에 남긴다. 주지 않으면 이름과
    지연만 남는다 — `schedule`이 그렇다. 고르는 일은 요약 함수가 하고, 좌표·발화
    원문처럼 실으면 안 되는 값은 거기서 걸러낸다(`_summarize_tool_fetch` 참고).

    관측이 꺼져 있으면(기본값) `observe_step()`이 no-op이라 호출 한 겹만 는다.

    `wraps`는 표시용이 아니라 **동작 조건이다.** LangGraph는 노드의 시그니처를 보고
    `config`를 넘길지 정하는데(`_internal/_runnable.py`), 감싼 함수가 `*args`로만
    보이면 `state` 하나만 넘겨서 `TypeError: missing 1 required positional argument:
    'config'`로 죽는다. `wraps`가 남기는 `__wrapped__`를 `inspect.signature`가 따라가
    원본 시그니처를 보게 한다.
    """

    @wraps(node)
    async def _run(*args: Any, **kwargs: Any) -> Any:
        with observe_step(name) as step:
            result = await node(*args, **kwargs)
            if summarize is not None and isinstance(result, Mapping):
                # 요약이 터져도 노드 결과는 그대로 나가야 한다 — 관측이 삼켜도 되는
                # 건 자기 실패뿐이다(langfuse_tracing._guard와 같은 원칙).
                try:
                    step.record(output=summarize(result))
                except Exception:
                    logger.warning("관측 요약 실패(응답 흐름에는 영향 없음)", exc_info=True)
            return result

    return _run


# 프로세스 수명 동안 한 번만 조립한다 — 그래프 컴파일은 요청마다 할 일이 아니다.
_EARLY_RETURN_GRAPH = build_early_return_graph()


def _intent_tag(llm_output: LLMOutput) -> list[str]:
    """이 턴의 intent를 trace 태그로 만든다.

    **태그는 trace를 열 때 정해지는 게 아니다.** 2026-08-25 실측으로 확인했다 —
    루트 span을 연 뒤에 `trace_attributes(tags=...)`를 열어도 trace 태그에 합쳐진다.
    그 전까지는 "intent는 분류 이후에나 알 수 있으니 태그로 못 싣는다"고 적어뒀는데
    틀린 진단이었다.

    **다만 그 범위 안에 observation이 하나는 생겨야 한다** — 태그는 observation에
    실려 올라가고 trace 태그는 그것들을 합친 결과다. 그래서 여기(그래프 진입)에
    두었다. 안에서 노드 span이 반드시 생기고, intent는 이미 인자로 들어와 있다.

    이게 있으면 화면에서 **intent별 비용·지연을 가를 수 있다.** 지금은 `scoring:`과
    `env:` 태그뿐이라 RECOMMEND와 INFO가 한 덩어리로 섞여 있다.
    """
    return [f"intent:{llm_output.intent.value}"]


async def run_early_return_graph(
    llm_output: LLMOutput,
    *,
    llm: LLMProvider,
    stream_event_sink: StreamEventSink | None = None,
    stream_general: bool = False,
) -> str:
    """조기 반환 경로의 답변 문구를 그래프로 만들어 문자열로 돌려준다.

    호출부(`run_agent_flow()`)가 기대하는 것은 기존 `compose_chat_message()`와 같은
    문자열 하나다 — 그래프로 바뀐 것을 호출부가 알 필요가 없게 시그니처를 맞췄다.
    """

    with trace_attributes(tags=_intent_tag(llm_output)):
        result = await _EARLY_RETURN_GRAPH.ainvoke(
            {"llm_output": llm_output, "stream_general": stream_general, "answer": None},
            config={
                "configurable": {
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
    graph.add_node("tool_fetch", _observed("tool_fetch", tool_fetch_node, _summarize_tool_fetch))
    graph.add_node("scoring", _observed("scoring", scoring_node, _summarize_scoring))
    graph.add_node("schedule", _observed("schedule", schedule_node))
    graph.add_node("finalize", _observed("finalize", finalize_node, _summarize_finalize))

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
    # checkpointer 미사용 — 이유는 build_early_return_graph() 주석과 §9.9 참고.
    return graph.compile()


_RECOMMEND_PIPELINE_GRAPH = build_recommend_pipeline_graph()


async def run_recommend_pipeline_graph(
    state: RecommendPipelineState,
    *,
    deps: PipelineDeps,
    stream_event_sink: StreamEventSink | None = None,
) -> AgentResponse:
    """Tool 조회부터 응답 조립까지를 그래프로 돌려 최종 응답을 돌려준다."""

    with trace_attributes(tags=_intent_tag(state["llm_output"])):
        result = await _RECOMMEND_PIPELINE_GRAPH.ainvoke(
            state,
            config={
                "configurable": {
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
