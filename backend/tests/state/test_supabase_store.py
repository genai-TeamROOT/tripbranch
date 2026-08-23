from __future__ import annotations

import json

import httpx
import pytest

from app.state.errors import StateStoreError
from app.state.schema import (
    AgentState,
    ConditionChangeLog,
    RecommendationHistory,
    UserConditions,
)
from app.state.supabase_store import SupabaseStateStore

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
        "pending_clarification": "location_required",
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
    assert state.pending_clarification == "location_required"


def test_get_state_defaults_pending_clarification_when_column_absent() -> None:
    """08-03 마이그레이션 이전 행(컬럼 없음)을 읽어도 깨지지 않아야 한다."""
    row = {
        "session_id": SESSION_ID,
        "user_conditions": {},
        "api_context": {},
        "condition_version": 0,
        "status": "active",
        "created_at": "2026-07-28T00:00:00+09:00",
        "updated_at": "2026-07-28T00:00:00+09:00",
        "last_active_at": "2026-07-28T00:00:00+09:00",
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[row]))
    state = _store(transport).get_state(SESSION_ID)
    assert state is not None
    assert state.pending_clarification is None


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

def test_save_state_includes_pending_clarification_in_body() -> None:
    """save_state가 model_dump()를 그대로 보내므로, 값이 있으면 body에 실려야 한다."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(201)

    transport = httpx.MockTransport(handler)
    state = AgentState(
        session_id=SESSION_ID,
        user_conditions=UserConditions(),
        pending_clarification="location_required",
    )
    _store(transport).save_state(state)

    request = seen["request"]
    assert isinstance(request, httpx.Request)
    body = json.loads(request.content)
    assert body["pending_clarification"] == "location_required"


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


# ------------------------------------------------------------ Feedback


def test_append_feedback_skips_empty_list() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(201)

    transport = httpx.MockTransport(handler)
    _store(transport).append_feedback([])
    assert calls == []


def test_get_feedback_parses_rows_into_feedback_records() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "session_id": SESSION_ID,
                    "run_id": "run-1",
                    "rating": "like",
                    "user_input": "경복궁 근처 카페 추천해줘",
                    "assistant_message": "이런 곳들을 찾아봤어요.",
                    "recorded_at": "2026-08-21T00:00:00+09:00",
                }
            ],
        )
    )
    feedback = _store(transport).get_feedback(SESSION_ID)
    assert len(feedback) == 1
    assert feedback[0].rating == "like"
    assert feedback[0].user_input == "경복궁 근처 카페 추천해줘"
    assert feedback[0].assistant_message == "이런 곳들을 찾아봤어요."


def test_get_feedback_parses_rows_without_turn_text() -> None:
    """202608210001 마이그레이션 이전 행(컬럼 없음)을 읽어도 깨지지 않아야 한다."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "session_id": SESSION_ID,
                    "run_id": "run-1",
                    "rating": "like",
                    "recorded_at": "2026-08-21T00:00:00+09:00",
                }
            ],
        )
    )
    feedback = _store(transport).get_feedback(SESSION_ID)
    assert feedback[0].user_input is None
    assert feedback[0].assistant_message is None


def test_get_feedback_parses_intent_and_comment() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "session_id": SESSION_ID,
                    "run_id": "run-1",
                    "rating": "dislike",
                    "intent": "RECOMMEND",
                    "comment": "추천 장소가 너무 멀어요",
                    "recorded_at": "2026-08-21T00:00:00+09:00",
                }
            ],
        )
    )
    feedback = _store(transport).get_feedback(SESSION_ID)
    assert feedback[0].intent == "RECOMMEND"
    assert feedback[0].comment == "추천 장소가 너무 멀어요"


def test_get_feedback_parses_rows_without_intent_or_comment() -> None:
    """202608210003 마이그레이션 이전 행(컬럼 없음)을 읽어도 깨지지 않아야 한다."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "session_id": SESSION_ID,
                    "run_id": "run-1",
                    "rating": "like",
                    "recorded_at": "2026-08-21T00:00:00+09:00",
                }
            ],
        )
    )
    feedback = _store(transport).get_feedback(SESSION_ID)
    assert feedback[0].intent is None
    assert feedback[0].comment is None


def test_list_dislike_feedback_filters_by_rating_and_limit() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "session_id": SESSION_ID,
                    "run_id": "run-1",
                    "rating": "dislike",
                    "recorded_at": "2026-08-21T00:00:00+09:00",
                }
            ],
        )

    transport = httpx.MockTransport(handler)
    dislikes = _store(transport).list_dislike_feedback(10)

    request = seen["request"]
    assert request.url.params["rating"] == "eq.dislike"
    assert request.url.params["limit"] == "10"
    assert request.url.params["order"] == "recorded_at.desc"
    assert len(dislikes) == 1
    assert dislikes[0].rating == "dislike"


# ------------------------------------------------------------ 에러 처리


def test_http_error_raises_state_store_error() -> None:
    """B의 SupabaseStateStore는 B 소유 오류(StateStoreError)로 실패를 알린다.

    이전에는 app.repositories.supabase_places.SupabaseRepositoryError(장소 동기화
    기능 쪽 예외, 메시지가 "장소 데이터 저장 중...")를 빌려 썼는데, B의 세션 상태
    저장 실패에 엉뚱한 메시지가 나가는 문제가 있어 B 소유 StateStoreError로 교체했다.
    """
    transport = httpx.MockTransport(
        lambda request: httpx.Response(500, json={"message": "boom"})
    )
    with pytest.raises(StateStoreError):
        _store(transport).get_state(SESSION_ID)