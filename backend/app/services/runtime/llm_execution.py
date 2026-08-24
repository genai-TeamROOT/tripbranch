"""요청 단위 LLM 모델 실행 메타데이터를 모은다.

RealGeminiProvider는 호출마다 실제 시도 모델을 여기 기록하고, Agent Runtime과
공통 오류 핸들러는 같은 async 요청 문맥에서 이를 읽는다. ContextVar를 사용해
동시 요청의 모델 이력이 서로 섞이지 않게 한다.

**기록은 리스트에 제자리로 붙인다 — 값을 갈아끼우지 않는다.** 이게 취향이 아니라
정확성 조건인 이유는 LangGraph 때문이다. 노드는 별도 asyncio 태스크에서 도는데,
파이썬은 태스크를 만들 때 그 시점 ContextVar 값을 **복사해서** 넘긴다. 그래서
`_calls.set(...)`으로 새 값을 넣으면 갈리는 것은 복사본이고, 노드가 남긴 기록은
노드가 끝나는 순간 함께 버려진다. 리스트를 하나 두고 거기 붙이면 태스크가 복사해
가는 것은 "그 리스트를 가리키는 참조"라, 노드 안에서 붙인 항목이 노드 밖에서도
보인다(D-074, langgraph-adoption.md §9.13).

기본값을 `None`으로 둔 것도 같은 이유의 뒷면이다. 기본값에 리스트를 두면 모든
요청이 같은 리스트를 공유해 이력이 섞인다 — ContextVar를 쓰는 목적 자체가 깨진다.
"""

from __future__ import annotations

from contextvars import ContextVar

from app.schemas import LLMCallMetadata, LLMExecutionMetadata

# 기본값은 불변 센티널이어야 한다. 리스트를 두면 요청 간에 공유되고, 기본값을 아예
# 지우면 reset을 거치지 않은 문맥의 get()이 LookupError를 낸다 — 전역 AppError
# 핸들러(main.py)가 그런 문맥에서 이 값을 읽으므로 502 계약이 500으로 깨진다.
_calls: ContextVar[list[LLMCallMetadata] | None] = ContextVar(
    "tripbranch_llm_execution_calls", default=None
)


def reset_llm_execution_metadata() -> None:
    """새 Agent 요청을 시작하며 이전 호출 이력을 비운다.

    여기서 리스트를 새로 만들어 둔다. 이후 `record_llm_call()`은 이 리스트에만
    붙이므로, 이 함수를 부른 문맥과 그 아래 태스크들이 같은 이력을 공유한다.
    """

    _calls.set([])


def record_llm_call(
    *,
    operation: str,
    attempted_models: list[str],
    served_model: str | None,
    latency_ms: int | None = None,
) -> None:
    """모델 선택 루프 1회의 최종 결과를 현재 요청 이력에 추가한다."""

    call = LLMCallMetadata(
        operation=operation,
        attempted_models=attempted_models,
        served_model=served_model,
        latency_ms=latency_ms,
    )
    calls = _calls.get()
    if calls is None:
        # reset을 거치지 않은 문맥(Agent 흐름 밖에서 LLM을 직접 쓰는 경로). 이력을
        # 읽는 쪽이 없으므로 여기서 만들어 두기만 한다 — 태스크 경계를 넘지 못하는
        # 것은 이 경우뿐이고, 그건 이전 구현과 같은 동작이다.
        calls = []
        _calls.set(calls)
    calls.append(call)


def get_llm_execution_metadata() -> LLMExecutionMetadata | None:
    """현재 요청의 LLM 모델 이력. LLM 호출이 없으면 None."""

    calls = _calls.get()
    return LLMExecutionMetadata(calls=list(calls)) if calls else None


__all__ = [
    "get_llm_execution_metadata",
    "record_llm_call",
    "reset_llm_execution_metadata",
]
