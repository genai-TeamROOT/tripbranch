"""Package B - State 저장소.

계약 문서: docs/package-b/agent-state-contract-v1.md (Phase 1 전제)

Phase 1은 인메모리 구현을 사용한다. 프로토콜을 분리해 두어
저장소를 교체할 때 상위 계층을 수정하지 않도록 한다.
"""

from typing import Protocol

from app.state.schema import (
    AgentState,
    ConditionChangeLog,
    RecommendationHistory,
)


class StateStore(Protocol):
    """State 저장소 인터페이스.

    구현체는 조회 시 복사본을 반환하고 저장 시 복사본을 보관해야 한다.
    호출 측이 save를 호출하지 않으면 변경이 반영되지 않아야,
    저장소 교체 시 동작이 달라지지 않는다.
    """

    # --- AgentState
    def get_state(self, session_id: str) -> AgentState | None: ...
    def save_state(self, state: AgentState) -> None: ...
    def delete_state(self, session_id: str) -> None: ...

    # --- RecommendationHistory
    def get_history(self, session_id: str) -> RecommendationHistory | None: ...
    def save_history(self, history: RecommendationHistory) -> None: ...
    def delete_history(self, session_id: str) -> None: ...

    # --- ConditionChangeLog (append-only)
    def append_change_logs(self, logs: list[ConditionChangeLog]) -> None: ...
    def get_change_logs(self, session_id: str) -> list[ConditionChangeLog]: ...


class InMemoryStateStore:
    """프로세스 메모리 기반 구현. (Phase 1)

    서버 재시작 시 모든 데이터가 소멸한다. 이는 의도된 제약이며
    저장소 교체 시 해소된다. (계약 5.4절)
    """

    def __init__(self) -> None:
        self._states: dict[str, AgentState] = {}
        self._histories: dict[str, RecommendationHistory] = {}
        self._change_logs: dict[str, list[ConditionChangeLog]] = {}

    # ------------------------------------------------------------ State

    def get_state(self, session_id: str) -> AgentState | None:
        state = self._states.get(session_id)
        return state.model_copy(deep=True) if state else None

    def save_state(self, state: AgentState) -> None:
        self._states[state.session_id] = state.model_copy(deep=True)

    def delete_state(self, session_id: str) -> None:
        self._states.pop(session_id, None)

    # ------------------------------------------------------------ History

    def get_history(self, session_id: str) -> RecommendationHistory | None:
        history = self._histories.get(session_id)
        return history.model_copy(deep=True) if history else None

    def save_history(self, history: RecommendationHistory) -> None:
        self._histories[history.session_id] = history.model_copy(deep=True)

    def delete_history(self, session_id: str) -> None:
        self._histories.pop(session_id, None)

    # ------------------------------------------------------------ ChangeLog

    def append_change_logs(self, logs: list[ConditionChangeLog]) -> None:
        """append-only. 기존 기록을 수정하거나 삭제하지 않는다."""
        for log in logs:
            self._change_logs.setdefault(log.session_id, []).append(
                log.model_copy(deep=True)
            )

    def get_change_logs(self, session_id: str) -> list[ConditionChangeLog]:
        logs = self._change_logs.get(session_id, [])
        return [log.model_copy(deep=True) for log in logs]

    # ------------------------------------------------------------ 테스트용

    def clear(self) -> None:
        """전체 초기화. 테스트에서만 사용한다."""
        self._states.clear()
        self._histories.clear()
        self._change_logs.clear()

    def session_ids(self) -> list[str]:
        """보관 중인 세션 목록. 디버깅·테스트용."""
        return list(self._states.keys())


# 프로세스 단위 기본 저장소.
# 저장소 교체 시 이 변수의 대입만 바꾸면 된다.
_default_store = InMemoryStateStore()


def get_store() -> StateStore:
    """기본 저장소를 반환한다.

    FastAPI 의존성 주입에서 이 함수를 사용하면,
    테스트에서 다른 구현으로 교체하기 쉽다.
    """
    return _default_store