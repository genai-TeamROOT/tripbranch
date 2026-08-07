"""요청 단위 LLM 모델 실행 메타데이터를 모은다.

RealGeminiProvider는 호출마다 실제 시도 모델을 여기 기록하고, Agent Runtime과
공통 오류 핸들러는 같은 async 요청 문맥에서 이를 읽는다. ContextVar를 사용해
동시 요청의 모델 이력이 서로 섞이지 않게 한다.
"""

from __future__ import annotations

from contextvars import ContextVar

from app.schemas import LLMCallMetadata, LLMExecutionMetadata

_calls: ContextVar[tuple[LLMCallMetadata, ...]] = ContextVar(
    "tripbranch_llm_execution_calls", default=()
)


def reset_llm_execution_metadata() -> None:
    """새 Agent 요청을 시작하며 이전 호출 이력을 비운다."""

    _calls.set(())


def record_llm_call(
    *, operation: str, attempted_models: list[str], served_model: str | None
) -> None:
    """모델 선택 루프 1회의 최종 결과를 현재 요청 이력에 추가한다."""

    call = LLMCallMetadata(
        operation=operation,
        attempted_models=attempted_models,
        served_model=served_model,
    )
    _calls.set((*_calls.get(), call))


def get_llm_execution_metadata() -> LLMExecutionMetadata | None:
    """현재 요청의 LLM 모델 이력. LLM 호출이 없으면 None."""

    calls = _calls.get()
    return LLMExecutionMetadata(calls=list(calls)) if calls else None


__all__ = [
    "get_llm_execution_metadata",
    "record_llm_call",
    "reset_llm_execution_metadata",
]
