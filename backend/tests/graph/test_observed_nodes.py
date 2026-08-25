"""그래프 노드를 관측 span으로 감싸는 래퍼(`_observed`) 회귀 테스트.

**왜 콜백이 아니라 직접 감싸나**: Langfuse가 주는 LangChain `CallbackHandler`는
`langchain` **본체**를 import한다. 우리는 langgraph가 끌고 온 `langchain-core`만
두고 본체·통합 패키지는 의도적으로 안 넣었다(pyproject.toml). 2026-08-25에 콜백으로
붙여봤다가 `ModuleNotFoundError`로 **조용히 꺼지는 것**을 실측으로 확인했다 — 앱은
멀쩡했고 노드 span만 통째로 안 생겼다.

**여기서 잡는 것은 시그니처다.** LangGraph는 노드의 시그니처를 보고 `config`를
넘길지 정한다(`_internal/_runnable.py`). 감싼 함수가 `*args`로만 보이면 `state`
하나만 넘겨서 `TypeError: missing 1 required positional argument: 'config'`로 죽는다.
`functools.wraps`를 빠뜨렸을 때 실제로 스위트 103건이 깨졌다.
"""

from __future__ import annotations

import inspect
from typing import TypedDict

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.services.runtime.graph import _observed


class _State(TypedDict):
    value: int


async def _node_with_config(state: _State, config: RunnableConfig) -> dict[str, int]:
    return {"value": state["value"] + 1}


def test_wrapper_keeps_the_original_signature() -> None:
    """LangGraph가 `config`를 넘길지 판단하는 근거다 — 표시용이 아니다."""
    wrapped = _observed("tool_fetch", _node_with_config)

    assert list(inspect.signature(wrapped).parameters) == ["state", "config"]
    assert wrapped.__name__ == "_node_with_config"


@pytest.mark.asyncio
async def test_wrapped_node_still_runs_inside_a_real_graph() -> None:
    """시그니처가 깨지면 여기서 TypeError로 죽는다.

    관측이 꺼져 있어도(테스트 기본값) 래퍼는 그대로 통과해야 한다 — 감싼 것 자체가
    동작을 바꾸면 안 된다.
    """
    graph = StateGraph(_State)
    graph.add_node("tool_fetch", _observed("tool_fetch", _node_with_config))
    graph.add_node("scoring", _observed("scoring", _node_with_config))
    graph.add_edge(START, "tool_fetch")
    graph.add_edge("tool_fetch", "scoring")
    graph.add_edge("scoring", END)

    result = await graph.compile().ainvoke({"value": 1})

    assert result == {"value": 3}


@pytest.mark.asyncio
async def test_wrapper_does_not_swallow_node_failures() -> None:
    """관측이 삼켜도 되는 건 자기 실패지 노드의 실패가 아니다."""

    async def _broken(state: _State, config: RunnableConfig) -> dict[str, int]:
        raise ValueError("노드 실패")

    wrapped = _observed("scoring", _broken)

    with pytest.raises(ValueError, match="노드 실패"):
        await wrapped({"value": 1}, {})


def test_pipeline_nodes_are_registered_wrapped() -> None:
    """실제 파이프라인 그래프의 단계가 전부 감싸여 있는지 확인한다.

    이름은 B의 Trace `step`과 같아야 두 기록을 나란히 읽을 수 있다.
    """
    from app.services.runtime.graph import build_recommend_pipeline_graph

    compiled = build_recommend_pipeline_graph()

    assert {"tool_fetch", "scoring", "schedule", "finalize"} <= set(compiled.nodes)
