"""만료된 익명 세션 정리 스크립트(TP-134) 테스트."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.config import Settings
from app.state.schema import (
    AgentState,
    ConditionChangeLog,
    RecommendationHistory,
    TraceRecord,
    now_kst,
)
from app.state.store import InMemoryStateStore
from scripts import cleanup_expired_sessions as script


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> InMemoryStateStore:
    memory_store = InMemoryStateStore()
    monkeypatch.setattr(script, "get_store", lambda: memory_store)
    monkeypatch.setattr(
        script, "settings", Settings(_env_file=None, state_store_backend="supabase")
    )
    return memory_store


def _seed_session(store: InMemoryStateStore, session_id: str, *, days_old: int) -> None:
    last_active_at = now_kst() - timedelta(days=days_old)
    store.save_state(AgentState(session_id=session_id, last_active_at=last_active_at))
    store.save_history(RecommendationHistory(session_id=session_id))
    store.append_change_logs(
        [
            ConditionChangeLog(
                session_id=session_id, run_id="r1", seq=0, op="Update", field="budget"
            )
        ]
    )
    store.append_traces(
        [TraceRecord(session_id=session_id, run_id="r1", trace_id="t1", step="interpret")]
    )


def test_memory_백엔드는_즉시_종료한다(monkeypatch: pytest.MonkeyPatch, store) -> None:
    monkeypatch.setattr(
        script, "settings", Settings(_env_file=None, state_store_backend="memory")
    )

    with pytest.raises(SystemExit):
        script.cleanup(days=30, dry_run=False)


def test_대상이_없으면_아무것도_하지_않는다(store) -> None:
    assert script.cleanup(days=30, dry_run=False) == 0


def test_오래된_세션의_네_테이블을_전부_지운다(store) -> None:
    _seed_session(store, "sess_old", days_old=40)

    failed = script.cleanup(days=30, dry_run=False)

    assert failed == 0
    assert store.get_state("sess_old") is None
    assert store.get_history("sess_old") is None
    assert store.get_change_logs("sess_old") == []
    assert store.get_traces("sess_old") == []


def test_최근_세션은_지우지_않는다(store) -> None:
    _seed_session(store, "sess_recent", days_old=1)

    script.cleanup(days=30, dry_run=False)

    assert store.get_state("sess_recent") is not None
    assert store.get_history("sess_recent") is not None
    assert len(store.get_change_logs("sess_recent")) == 1
    assert len(store.get_traces("sess_recent")) == 1


def test_오래된_세션과_최근_세션이_섞여도_오래된_것만_지운다(store) -> None:
    _seed_session(store, "sess_old", days_old=40)
    _seed_session(store, "sess_recent", days_old=1)

    script.cleanup(days=30, dry_run=False)

    assert store.get_state("sess_old") is None
    assert store.get_state("sess_recent") is not None


def test_dry_run은_아무것도_지우지_않는다(store) -> None:
    _seed_session(store, "sess_old", days_old=40)

    failed = script.cleanup(days=30, dry_run=True)

    assert failed == 0
    assert store.get_state("sess_old") is not None
    assert store.get_change_logs("sess_old") != []


def test_days_인자로_기준을_조정할_수_있다(store) -> None:
    """10일 전 세션은 --days 30 기준으로는 안 지워지고 --days 5 기준으로는 지워진다."""
    _seed_session(store, "sess_10일전", days_old=10)

    script.cleanup(days=30, dry_run=False)
    assert store.get_state("sess_10일전") is not None

    script.cleanup(days=5, dry_run=False)
    assert store.get_state("sess_10일전") is None
