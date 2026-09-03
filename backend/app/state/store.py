"""Package B - State 저장소.

계약 문서: docs/package-b/agent-state-contract-v1.md (Phase 1 전제)
설계 문서: docs/package-b/db-store-design-v2.md (Phase 2 Supabase 전환)

Phase 1은 인메모리 구현을 사용한다. 프로토콜을 분리해 두어
저장소를 교체할 때 상위 계층을 수정하지 않도록 한다.
STATE_STORE_BACKEND 설정(memory/supabase)으로 get_store()가 반환하는
구현체를 고른다 — 호출부(service.py 등)는 이 전환을 알 필요가 없다.
"""

from datetime import datetime
from typing import Protocol

import httpx

from app.config import settings
from app.state.schema import (
    AgentState,
    ConditionChangeLog,
    FeedbackRecord,
    RecommendationHistory,
    SavedPlaceList,
    SessionMessage,
    TraceRecord,
    UserPreferenceList,
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

    # --- SavedPlaceList (가변 — 담기/빼기, SCHEDULE-12)
    # RecommendationHistory와 같은 read-modify-write 패턴이지만 별도
    # 엔티티다(SavedPlaceList docstring 참고).
    def get_saved_places(self, session_id: str) -> SavedPlaceList | None: ...
    def save_saved_places(self, saved: SavedPlaceList) -> None: ...
    def delete_saved_places(self, session_id: str) -> None: ...

    # -- UserPreferenceList (계정 단위) --
    # 이 둘만 session_id가 아니라 user_id로 조회한다. 삭제 메서드를 두지 않은
    # 이유는 "취향을 비운다"가 빈 목록 저장이기 때문이다 — 행을 지우면 다음
    # 조회에서 "아직 고른 적 없음"과 "다 지웠음"이 구분되지 않는다.
    def get_preferences(self, user_id: str) -> UserPreferenceList | None: ...
    def save_preferences(self, preferences: UserPreferenceList) -> None: ...

    # -- 사용자의 대화 목록 --
    # 사이드바 채팅 히스토리가 쓴다. 제목이 없는 세션(대화를 시작하지 않고
    # 만들어지기만 한 세션)은 목록에 넣지 않는다 — 사용자가 보기에 그건
    # 대화가 아니다.
    #
    # **만료(status='expired') 여부로는 거르지 않는다.** 만료는 "낡은 조건을
    # 버렸다"는 뜻이지 "그 대화가 없었다"는 뜻이 아니고, 지난 대화를 열어
    # 이어가는 것이 이 목록의 목적이다. 거르면 오래된 대화일수록 안 보인다.
    def list_sessions_for_user(self, user_id: str, limit: int) -> list[AgentState]: ...

    # --- ConditionChangeLog (append-only)
    def append_change_logs(self, logs: list[ConditionChangeLog]) -> None: ...
    def get_change_logs(self, session_id: str) -> list[ConditionChangeLog]: ...

    # --- TraceRecord (append-only)
    def append_traces(self, records: list[TraceRecord]) -> None: ...
    def get_traces(self, session_id: str) -> list[TraceRecord]: ...
    # 집계(TP-157)용. get_traces와 달리 세션 하나로 좁히지 않고 전체
    # 테이블을 대상으로 한다 — "최근 에러가 뭐였는지", "step별 평균
    # 지연시간"은 세션 단위로 물을 수 있는 질문이 아니다. since/until은
    # recorded_at 기준 반열린구간이며 둘 다 선택이다.
    def list_traces_for_stats(
        self, since: datetime | None = None, until: datetime | None = None
    ) -> list[TraceRecord]: ...

    # --- SessionMessage (append-only, TP-222 후속 — 화면 기록)
    # recent_turns(모델 맥락)·추천 이력(제외 목록)과 달리 자르지도 비우지도
    # 않는다. 지난 대화를 화면에 그대로 되돌리는 유일한 근거다.
    def append_session_messages(self, messages: list[SessionMessage]) -> None: ...
    def get_session_messages(self, session_id: str) -> list[SessionMessage]: ...
    def delete_session_messages(self, session_id: str) -> None: ...

    # --- FeedbackRecord (append-only)
    def append_feedback(self, records: list[FeedbackRecord]) -> None: ...
    def get_feedback(self, session_id: str) -> list[FeedbackRecord]: ...
    # 다른 메서드와 달리 세션 범위가 아니라 테이블 전체를 대상으로 한다 —
    # "나쁜 답변 찾기"는 특정 세션이 아니라 전체 응답 중에서 찾는 분석
    # 작업이라, session_id로 좁힐 수 없다.
    def list_dislike_feedback(self, limit: int) -> list[FeedbackRecord]: ...
    # 집계(TP-146)용. list_dislike_feedback과 달리 rating을 가리지 않고
    # (like까지 포함) limit도 없이 전량을 반환한다 — 통계는 상위 N건이
    # 아니라 전체 합이어야 의미가 있다. since/until은 recorded_at 기준
    # 반열린구간([since, until))이며 둘 다 선택이다.
    def list_feedback_for_stats(
        self, since: datetime | None = None, until: datetime | None = None
    ) -> list[FeedbackRecord]: ...

    # --- 정리(만료 세션 삭제, TP-134)
    # response_feedback은 세션 생애주기와 무관한 별도 분석 데이터라 대상에서
    # 제외한다 — 이 네 메서드는 scripts/cleanup_expired_sessions.py 전용이다.
    def list_stale_session_ids(self, cutoff: datetime) -> list[str]: ...
    def delete_change_logs(self, session_id: str) -> None: ...
    def delete_traces(self, session_id: str) -> None: ...
    # delete_session_messages는 위 SessionMessage 섹션에 있다.
    # delete_saved_places는 위 SavedPlaceList 섹션에 있다 — 만료 세션 정리
    # (scripts/cleanup_expired_sessions.py)도 같은 메서드를 쓴다.


class InMemoryStateStore:
    """프로세스 메모리 기반 구현. (Phase 1)

    서버 재시작 시 모든 데이터가 소멸한다. 이는 의도된 제약이며
    저장소 교체 시 해소된다. (계약 5.4절)
    """

    def __init__(self) -> None:
        self._states: dict[str, AgentState] = {}
        self._histories: dict[str, RecommendationHistory] = {}
        self._saved_places: dict[str, SavedPlaceList] = {}
        self._preferences: dict[str, UserPreferenceList] = {}
        self._change_logs: dict[str, list[ConditionChangeLog]] = {}
        self._traces: dict[str, list[TraceRecord]] = {}
        self._feedback: dict[str, list[FeedbackRecord]] = {}
        self._session_messages: dict[str, list[SessionMessage]] = {}

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

    # ------------------------------------------------------------ SavedPlaces

    def get_saved_places(self, session_id: str) -> SavedPlaceList | None:
        saved = self._saved_places.get(session_id)
        return saved.model_copy(deep=True) if saved else None

    def save_saved_places(self, saved: SavedPlaceList) -> None:
        self._saved_places[saved.session_id] = saved.model_copy(deep=True)

    def delete_saved_places(self, session_id: str) -> None:
        self._saved_places.pop(session_id, None)

    # ------------------------------------------------------------ Preferences

    def list_sessions_for_user(self, user_id: str, limit: int) -> list[AgentState]:
        owned = [
            state
            for state in self._states.values()
            if state.user_id == user_id and state.title is not None
        ]
        owned.sort(key=lambda state: state.last_active_at, reverse=True)
        return [state.model_copy(deep=True) for state in owned[:limit]]

    def get_preferences(self, user_id: str) -> UserPreferenceList | None:
        preferences = self._preferences.get(user_id)
        return preferences.model_copy(deep=True) if preferences else None

    def save_preferences(self, preferences: UserPreferenceList) -> None:
        self._preferences[preferences.user_id] = preferences.model_copy(deep=True)

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

    # ------------------------------------------------------------ Trace

    def append_traces(self, records: list[TraceRecord]) -> None:
        """append-only. 기존 기록을 수정하거나 삭제하지 않는다."""
        for record in records:
            self._traces.setdefault(record.session_id, []).append(
                record.model_copy(deep=True)
            )

    def get_traces(self, session_id: str) -> list[TraceRecord]:
        records = self._traces.get(session_id, [])
        return [record.model_copy(deep=True) for record in records]

    def list_traces_for_stats(
        self, since: datetime | None = None, until: datetime | None = None
    ) -> list[TraceRecord]:
        all_records = [
            record for records in self._traces.values() for record in records
        ]
        if since is not None:
            all_records = [r for r in all_records if r.recorded_at >= since]
        if until is not None:
            all_records = [r for r in all_records if r.recorded_at < until]
        return [record.model_copy(deep=True) for record in all_records]

    # ------------------------------------------------------------ 화면 기록

    def append_session_messages(self, messages: list[SessionMessage]) -> None:
        """append-only. 기존 기록을 수정하거나 삭제하지 않는다."""
        for message in messages:
            self._session_messages.setdefault(message.session_id, []).append(
                message.model_copy(deep=True)
            )

    def get_session_messages(self, session_id: str) -> list[SessionMessage]:
        messages = self._session_messages.get(session_id, [])
        return [message.model_copy(deep=True) for message in messages]

    def delete_session_messages(self, session_id: str) -> None:
        self._session_messages.pop(session_id, None)

    # ------------------------------------------------------------ Feedback

    def append_feedback(self, records: list[FeedbackRecord]) -> None:
        """append-only. 기존 기록을 수정하거나 삭제하지 않는다."""
        for record in records:
            self._feedback.setdefault(record.session_id, []).append(
                record.model_copy(deep=True)
            )

    def get_feedback(self, session_id: str) -> list[FeedbackRecord]:
        records = self._feedback.get(session_id, [])
        return [record.model_copy(deep=True) for record in records]

    def list_dislike_feedback(self, limit: int) -> list[FeedbackRecord]:
        all_records = [
            record for records in self._feedback.values() for record in records
        ]
        dislikes = [record for record in all_records if record.rating == "dislike"]
        dislikes.sort(key=lambda record: record.recorded_at, reverse=True)
        return [record.model_copy(deep=True) for record in dislikes[:limit]]

    def list_feedback_for_stats(
        self, since: datetime | None = None, until: datetime | None = None
    ) -> list[FeedbackRecord]:
        all_records = [
            record for records in self._feedback.values() for record in records
        ]
        if since is not None:
            all_records = [r for r in all_records if r.recorded_at >= since]
        if until is not None:
            all_records = [r for r in all_records if r.recorded_at < until]
        return [record.model_copy(deep=True) for record in all_records]

    # ------------------------------------------------------------ 정리(TP-134)

    def list_stale_session_ids(self, cutoff: datetime) -> list[str]:
        return [
            session_id
            for session_id, state in self._states.items()
            if state.last_active_at < cutoff
        ]

    def delete_change_logs(self, session_id: str) -> None:
        self._change_logs.pop(session_id, None)

    def delete_traces(self, session_id: str) -> None:
        self._traces.pop(session_id, None)

    # ------------------------------------------------------------ 테스트용

    def clear(self) -> None:
        """전체 초기화. 테스트에서만 사용한다."""
        self._states.clear()
        self._histories.clear()
        self._saved_places.clear()
        self._change_logs.clear()
        self._session_messages.clear()
        self._traces.clear()
        self._feedback.clear()

    def session_ids(self) -> list[str]:
        """보관 중인 세션 목록. 디버깅·테스트용."""
        return list(self._states.keys())


# 프로세스 단위 기본 저장소(Phase 1, memory 백엔드).
_default_store = InMemoryStateStore()

# Phase 2(supabase 백엔드) 지연 생성 캐시. STATE_STORE_BACKEND=memory인 환경
# (테스트 등)에서는 한 번도 안 만들어진다 — Supabase 자격증명이 없어도
# 이 모듈을 import할 수 있어야 하기 때문이다.
_supabase_store: StateStore | None = None


def _build_supabase_store() -> StateStore:
    """SupabaseStateStore를 최초 호출 시 한 번만 만들어서 재사용한다.

    httpx.Client는 프로세스 생애주기 동안 재사용한다(연결 재사용 방식은
    설계 문서 db-store-design-v2.md 6절의 미결 사항 중 가장 단순한 선택 —
    실제 부하 확인 후 조정 가능). timeout은 다른 real provider와 동일하게
    EXTERNAL_API_TIMEOUT_SECONDS를 따른다.
    """
    global _supabase_store
    if _supabase_store is None:
        from app.state.supabase_store import SupabaseStateStore

        client = httpx.Client()
        _supabase_store = SupabaseStateStore(
            supabase_url=settings.supabase_url,
            secret_key=settings.supabase_secret_key,
            client=client,
            timeout_seconds=settings.external_api_timeout_seconds,
        )
    return _supabase_store


def get_store() -> StateStore:
    """기본 저장소를 반환한다.

    STATE_STORE_BACKEND 설정에 따라 InMemory(memory, 기본값) 또는
    Supabase(supabase) 구현체를 고정 반환한다. FastAPI 의존성 주입에서
    이 함수를 사용하면, 테스트에서 다른 구현으로 교체하기 쉽다.
    """
    if settings.state_store_backend == "supabase":
        return _build_supabase_store()
    return _default_store


def _reset_supabase_store_for_tests() -> None:
    """지연 생성된 Supabase 저장소 캐시를 초기화한다. 테스트에서만 사용한다."""
    global _supabase_store
    _supabase_store = None