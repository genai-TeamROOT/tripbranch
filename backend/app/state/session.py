"""Package B - 익명 세션 관리.

계약 문서: docs/package-b/agent-state-contract-v1.md (4절, 5절)

세션 만료는 오류가 아니라 정상적인 생애주기이므로,
어떤 경우에도 예외를 발생시키지 않고 신규 세션을 발급한다.
"""

import uuid
from datetime import datetime, timedelta

from app.state import history as history_module
from app.state.schema import AgentState, now_kst
from app.state.store import StateStore

# ---------------------------------------------------------------- 설정

# TODO(P2): 설정 파일로 이동 검토. 팀 합의로 조정 가능한 값이다.
SESSION_TTL = timedelta(minutes=30)
API_CONTEXT_TTL = timedelta(hours=1)

PREFIX_SESSION = "sess"
PREFIX_RUN = "run"
PREFIX_TRACE = "trace"

RESET_SOFT = "soft"
RESET_HISTORY = "history"
RESET_FULL = "full"


# ---------------------------------------------------------------- 식별자

def _generate_id(prefix: str) -> str:
    """접두어 + 정렬 가능한 고유 문자열. (계약 4.4절)

    접두어는 로그 판독성과 오사용 탐지를 위해 사용한다.
    앞부분에 생성 시각을 두어 문자열 정렬만으로 시간순이 되도록 한다.

    TODO(P1-5): ULID 도입 여부 확정 시 이 함수만 교체한다.
    """
    ts = f"{int(now_kst().timestamp() * 1000):013d}"
    rand = uuid.uuid4().hex[:12]
    return f"{prefix}_{ts}{rand}"


def new_session_id() -> str:
    return _generate_id(PREFIX_SESSION)


def new_run_id() -> str:
    return _generate_id(PREFIX_RUN)


def new_trace_id() -> str:
    return _generate_id(PREFIX_TRACE)


# ---------------------------------------------------------------- 만료 판정

def is_session_expired(state: AgentState, *, at: datetime | None = None) -> bool:
    """세션 TTL 초과 여부. (계약 5.4절)"""
    now = at or now_kst()
    return (now - state.last_active_at) > SESSION_TTL


def is_gps_expired(state: AgentState, *, at: datetime | None = None) -> bool:
    """GPS 유효 기간 초과 여부.

    확보된 적이 없으면 만료로 간주해 A가 확보하도록 알린다.
    """
    if state.api_context.gps_location_updated_at is None:
        return True
    now = at or now_kst()
    return (now - state.api_context.gps_location_updated_at) > API_CONTEXT_TTL


def is_weather_expired(state: AgentState, *, at: datetime | None = None) -> bool:
    """날씨 유효 기간 초과 여부.

    확보된 적이 없으면 만료로 간주한다.
    """
    if state.api_context.api_weather_updated_at is None:
        return True
    now = at or now_kst()
    return (now - state.api_context.api_weather_updated_at) > API_CONTEXT_TTL


# ---------------------------------------------------------------- 생성·조회

def create_session(store: StateStore) -> AgentState:
    """새 세션과 빈 State를 만든다. (계약 5.2절)"""
    state = AgentState(session_id=new_session_id())
    store.save_state(state)
    return state


def get_or_create_session(
    store: StateStore,
    session_id: str | None,
) -> tuple[AgentState, bool]:
    """세션을 확보한다. (계약 5.2절)

    다음 세 경우 모두 신규 세션을 발급하며, 오류를 반환하지 않는다.
      1. session_id가 없음
      2. 저장소에 존재하지 않음 (서버 재시작 등)
      3. TTL 초과로 만료됨

    Returns:
        (state, created) - created가 True면 신규 발급된 세션이다.
    """
    if not session_id:
        return create_session(store), True

    state = store.get_state(session_id)
    if state is None:
        return create_session(store), True

    if is_session_expired(state):
        state.status = "expired"
        store.save_state(state)
        return create_session(store), True

    return state, False


def peek_session(store: StateStore, session_id: str | None) -> AgentState | None:
    """세션을 조회만 한다. 없거나 만료면 None. (계약 6.3절)

    get_or_create_session과 달리 세션을 생성하지 않으며
    last_active_at도 갱신하지 않는다.
    """
    if not session_id:
        return None

    state = store.get_state(session_id)
    if state is None or state.status == "expired":
        return None

    if is_session_expired(state):
        return None

    return state


def touch(state: AgentState) -> None:
    """활동 시각을 갱신한다.

    조건 변경 여부와 무관하게 요청 수신 시마다 호출한다.
    updated_at은 갱신하지 않는다. (계약 5.3절)
    """
    state.last_active_at = now_kst()


# ---------------------------------------------------------------- 초기화

def apply_reset(
    store: StateStore,
    state: AgentState,
    reset_scope: str | None,
) -> tuple[AgentState, bool]:
    """초기화를 적용한다. (계약 5.5절)

    조건 초기화는 merge 단계에서 수행되므로, 이 함수는
    이력 초기화와 세션 재발급만 담당한다.

    Returns:
        (state, session_created)
    """
    if reset_scope is None:
        return state, False

    if reset_scope == RESET_SOFT:
        # 조건만 초기화. 이력은 유지한다. 조건 초기화는 merge가 수행한다.
        return state, False

    if reset_scope == RESET_HISTORY:
        # 추천 이력만 비우고 거절 이력은 유지한다.
        history_module.clear_recommended(store, state.session_id)
        return state, False

    if reset_scope == RESET_FULL:
        # 기존 세션을 만료 처리하고 신규 세션을 발급한다.
        state.status = "expired"
        store.save_state(state)
        history_module.clear_all(store, state.session_id)
        return create_session(store), True

    # 알 수 없는 값은 무시한다. B는 값의 의미를 판단하지 않는다.
    return state, False