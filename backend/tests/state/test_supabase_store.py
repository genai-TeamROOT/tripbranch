from __future__ import annotations

import httpx
import pytest

from app.state.schema import (
    AgentState,
    ConditionChangeLog,
    RecommendationHistory,
    UserConditions,
)
from app.state.supabase_store import SupabaseRepositoryError, SupabaseStateStore

SESSION_ID = "session-1"


def _store(transport: httpx.MockTransport) -> SupabaseStateStore:
    client = httpx.Client(transport=transport)
    return SupabaseStateStore(
        supabase_url="https://project.supabase.co/",
        secret_key="sb_secret_test",
        client=client,
    )


# ------------------------------------------------------------ AgentState


def test_get_state_returns_none_when_not_found() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    assert _store(transport).get_state(SESSION_ID) is None


def test_get_state_parses_row_into_agent_state() -> None:
    row = {
        "session_id": SESSION_ID,
        "user_conditions": {"weather": "sunny"},
        "api_context": {"gps_location": "37.5,127.0"},
        "condition_version": 2,
        "last_run_id": "run-1",
        "last_intent": "RECOMMEND",
        "status": "active",
        "created_at": "2026-07-28T00:00:00+09:00",
        "updated_at": "2026-07-28T00:00:00+09:00",
        "last_active_at": "2026-07-28T00:00:00+09:00",
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[row]))
    state = _store(transport).get_state(SESSION_ID)
    assert state is not None
    assert state.session_id == SESSION_ID
    assert state.user_conditions.weather == "sunny"
    assert state.condition_version == 2


def test_get_state_uses_secret_key_and_filter() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    _store(transport).get_state(SESSION_ID)

    request = seen["request"]
    assert isinstance(request, httpx.Request)
    assert request.url.path == "/rest/v1/agent_states"
    assert request.headers["apikey"] == "sb_secret_test"
    assert request.url.params["session_id"] == f"eq.{SESSION_ID}"


def test_save_state_upserts_with_on_conflict_session_id() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(201)

    transport = httpx.MockTransport(handler)
    state = AgentState(session_id=SESSION_ID, user_conditions=UserConditions())
    _store(transport).save_state(state)

    request = seen["request"]
    assert isinstance(request, httpx.Request)
    assert request.method == "POST"
    assert request.url.params["on_conflict"] == "session_id"
    assert request.headers["prefer"] == "resolution=merge-duplicates,return=minimal"


def test_delete_state_filters_by_session_id() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    _store(transport).delete_state(SESSION_ID)

    request = seen["request"]
    assert isinstance(request, httpx.Request)
    assert request.method == "DELETE"
    assert request.url.params["session_id"] == f"eq.{SESSION_ID}"


# ------------------------------------------------------------ History


def test_get_history_returns_none_when_not_found() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    assert _store(transport).get_history(SESSION_ID) is None


def test_save_history_sends_whole_object() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(201)

    transport = httpx.MockTransport(handler)
    history = RecommendationHistory(session_id=SESSION_ID)
    _store(transport).save_history(history)

    request = seen["request"]
    assert isinstance(request, httpx.Request)
    assert request.url.params["on_conflict"] == "session_id"


# ------------------------------------------------------------ ChangeLog


def test_append_change_logs_skips_empty_list() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(201)

    transport = httpx.MockTransport(handler)
    _store(transport).append_change_logs([])
    assert calls == []


def test_append_change_logs_posts_all_records() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(201)

    transport = httpx.MockTransport(handler)
    logs = [
        ConditionChangeLog(session_id=SESSION_ID, run_id="run-1", seq=1, op="Add"),
        ConditionChangeLog(session_id=SESSION_ID, run_id="run-1", seq=2, op="Update"),
    ]
    _store(transport).append_change_logs(logs)

    request = seen["request"]
    assert isinstance(request, httpx.Request)
    assert request.method == "POST"
    assert request.url.path == "/rest/v1/condition_change_logs"
    assert request.headers["prefer"] == "return=minimal"


def test_get_change_logs_orders_by_id_ascending() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "session_id": SESSION_ID,
                    "run_id": "run-1",
                    "seq": 1,
                    "op": "Add",
                    "applied_at": "2026-07-28T00:00:00+09:00",
                }
            ],
        )

    transport = httpx.MockTransport(handler)
    logs = _store(transport).get_change_logs(SESSION_ID)

    request = seen["request"]
    assert isinstance(request, httpx.Request)
    assert request.url.params["order"] == "id.asc"
    assert len(logs) == 1
    assert logs[0].op == "Add"


# ------------------------------------------------------------ Trace


def test_append_traces_skips_empty_list() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(201)

    transport = httpx.MockTransport(handler)
    _store(transport).append_traces([])
    assert calls == []


def test_get_traces_parses_rows_into_trace_records() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "session_id": SESSION_ID,
                    "run_id": "run-1",
                    "trace_id": "trace-1",
                    "step": "llm_interpret",
                    "recorded_at": "2026-07-28T00:00:00+09:00",
                }
            ],
        )
    )
    traces = _store(transport).get_traces(SESSION_ID)
    assert len(traces) == 1
    assert traces[0].step == "llm_interpret"


# ------------------------------------------------------------ 에러 처리


def test_http_error_raises_supabase_repository_error() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(500, json={"message": "boom"})
    )
    with pytest.raises(SupabaseRepositoryError):
        _store(transport).get_state(SESSION_ID)