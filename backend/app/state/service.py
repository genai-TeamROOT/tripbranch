"""Package B - 계약 진입점.

계약 문서: docs/package-b/agent-state-contract-v1.md (6절)

Phase 1에서는 동일 프로세스 내 함수 호출로 제공한다.
HTTP 엔드포인트는 AF-05 Agent Runtime의 책임이므로 여기서 정의하지 않는다.
"""

import functools
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.errors import AppError
from app.state import history as history_module
from app.state import session as session_module
from app.state import trace as trace_module
from app.state.errors import StateStoreError
from app.state.merge import merge_conditions
from app.state.operations import IgnoredOperation, Operation, validate_all
from app.state.schema import UserConditions, now_kst
from app.state.store import StateStore, get_store

# ================================================================ 요청·응답

class RejectedPlace(BaseModel):
    """거절된 장소 1건. (계약 6.1절)"""

    place_id: str
    reason_code: str | None = None


class StateApplyRequest(BaseModel):
    """조건 적용 요청. (계약 6.1절)"""

    session_id: str | None = None
    intent: str
    confirmed: bool
    reset_scope: str | None = None
    operations: list[Operation] = Field(default_factory=list)
    rejected_places: list[RejectedPlace] = Field(default_factory=list)
    prompt_version: str | None = None


class AppliedOperation(BaseModel):
    """적용된 연산과 전후 값. (계약 6.2절)

    Package A가 사용자에게 변경 내용을 안내할 때 사용한다.
    """

    op: str
    field: str | None
    before_value: Any = None
    after_value: Any = None


class ApiContextView(BaseModel):
    """만료 플래그가 포함된 api_context. (계약 6.2절)"""

    gps_location: str | None = None
    api_weather: str | None = None
    gps_expired: bool = True
    weather_expired: bool = True


class StateApplyResponse(BaseModel):
    """조건 적용 응답. (계약 6.2절)"""

    session_id: str
    run_id: str
    session_created: bool
    user_conditions: UserConditions
    api_context: ApiContextView
    condition_version: int
    condition_changed: bool
    applied_operations: list[AppliedOperation] = Field(default_factory=list)
    ignored_operations: list[IgnoredOperation] = Field(default_factory=list)
    excluded_place_ids: list[str] = Field(default_factory=list)
    reset_applied: str | None = None


class SessionContextResponse(BaseModel):
    """세션 컨텍스트 조회 응답. (계약 6.3절)"""

    session_id: str | None
    session_exists: bool
    has_recommendation: bool
    recommended_count: int
    shown_place_ids: list[str] = Field(default_factory=list)
    excluded_place_ids: list[str] = Field(default_factory=list)
    last_recommended_run_id: str | None = None
    last_intent: str | None = None
    # 직전 턴이 되묻기로 끝났다면 그 사유 코드. A가 이번 턴의 조건 병합 방식을
    # 정할 때 읽는다.
    pending_clarification: str | None = None
    user_conditions: UserConditions = Field(default_factory=UserConditions)
    api_context: ApiContextView = Field(default_factory=ApiContextView)
    condition_version: int = 0


class DeleteSessionResponse(BaseModel):
    """세션 삭제 응답.

    session_id에 해당하는 상태/이력을 삭제했는지 여부를 반환한다.
    """

    session_id: str
    deleted: bool


class RecommendedPlace(BaseModel):
    """노출된 장소 1건. (계약 6.4절)"""

    place_id: str
    rank: int


class RecordRecommendationRequest(BaseModel):
    session_id: str
    run_id: str
    recommended: list[RecommendedPlace] = Field(default_factory=list)


class RecordRecommendationResponse(BaseModel):
    recorded: int


class UpdateApiContextRequest(BaseModel):
    """api_context 갱신 요청. (계약 6.5절)

    전달된 필드만 갱신하며, 생략된 필드는 기존 값을 유지한다.
    """

    session_id: str
    gps_location: str | None = None
    gps_location_updated_at: datetime | None = None
    api_weather: str | None = None
    api_weather_updated_at: datetime | None = None


class UpdateApiContextResponse(BaseModel):
    session_id: str
    api_context: ApiContextView


class SetPendingClarificationRequest(BaseModel):
    """되묻기 사유 저장 요청.

    A가 이번 턴이 되묻기로 끝났다고 판단했을 때만 호출한다. B는 code를 해석하지
    않고 그대로 보관한다. api_context와 마찬가지로 조건 변경이 아니므로
    condition_version을 올리지 않는다.
    """

    session_id: str
    code: str | None = None


class SetPendingClarificationResponse(BaseModel):
    session_id: str
    pending_clarification: str | None


class RecordTraceRequest(BaseModel):
    """실행 단계 기록 요청. (llmops-trace-contract-v1.md 4절)

    prompt_version/scoring_version/variant_id/error_type은 호출자가 해석한
    값을 그대로 받으며, B는 검증하지 않는다.
    """

    session_id: str
    run_id: str
    step: str
    prompt_version: str | None = None
    scoring_version: str | None = None
    variant_id: str | None = None
    latency_ms: int | None = None
    token_usage: int | None = None
    error_type: str | None = None


class RecordTraceResponse(BaseModel):
    trace_id: str


# ================================================================ 헬퍼

def _build_api_context_view(state) -> ApiContextView:
    """만료 판정을 포함한 api_context 뷰를 만든다. (계약 5.4절)

    B는 만료를 알릴 뿐 갱신을 실행하지 않는다.
    만료된 값을 응답에서 제거하지 않고 플래그만 함께 반환한다.
    """
    return ApiContextView(
        gps_location=state.api_context.gps_location,
        api_weather=state.api_context.api_weather,
        gps_expired=session_module.is_gps_expired(state),
        weather_expired=session_module.is_weather_expired(state),
    )


def _wrap_store_errors(fn):
    """저장소 호출 중 예상 못한 예외를 B 공통 오류(StateStoreError)로 감싼다.

    이미 AppError인 경우(SupabaseRepositoryError 등)는 의미가 있으므로
    그대로 전달한다. "세션 없음"은 예외가 아니라 정상 반환값이므로
    영향받지 않는다 (계약 5.2/6.7절).
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except AppError:
            raise
        except Exception as exc:
            raise StateStoreError(str(exc)) from exc

    return wrapper


# ================================================================ 6.1 / 6.2

@_wrap_store_errors
def apply(
    request: StateApplyRequest,
    store: StateStore | None = None,
) -> StateApplyResponse:
    """조건 변경을 적용하고 현재 상태를 반환한다. (계약 6.1 / 6.2절)"""
    store = store or get_store()

    # 1) 세션 확보
    state, session_created = session_module.get_or_create_session(
        store, request.session_id
    )

    # 2) run_id 발급 — 조건 병합 이전 (계약 4.3절)
    #    변경 기록과 추천 이력이 run_id를 필수로 포함하기 때문이다.
    run_id = session_module.new_run_id()

    # 3) confirmed=false 이면 State를 변경하지 않고 현재 상태만 반환 (계약 2.6절)
    if not request.confirmed:
        session_module.touch(state)
        state.last_intent = request.intent
        store.save_state(state)
        return _build_response(
            store, state, run_id, session_created,
            changed=False, applied=[], ignored=[], reset_applied=None,
        )

    # 4) reset 적용 — operations 보다 먼저 (계약 2.4절)
    #    조건 초기화는 merge가, 이력 초기화와 세션 재발급은 session이 담당한다.
    state, reset_created_session = session_module.apply_reset(
        store, state, request.reset_scope
    )
    session_created = session_created or reset_created_session

    # 5) 활동 시각 갱신
    session_module.touch(state)
    state.last_intent = request.intent

    # 6) 검증
    valid_ops, ignored_ops = validate_all(request.operations)

    # 7) 병합
    result = merge_conditions(
        state.user_conditions,
        valid_ops,
        session_id=state.session_id,
        run_id=run_id,
        reset_scope=request.reset_scope,
    )

    state.user_conditions = result.conditions
    if result.changed:
        state.condition_version += 1
        state.updated_at = now_kst()
    state.last_run_id = run_id

    # 8) 거절 장소 기록
    if request.rejected_places:
        history_module.record_rejected(
            store,
            state.session_id,
            run_id,
            [(p.place_id, p.reason_code) for p in request.rejected_places],
        )

    # 9) 저장
    store.save_state(state)
    if result.change_logs:
        store.append_change_logs(result.change_logs)

    applied = [
        AppliedOperation(
            op=log.op,
            field=log.field,
            before_value=log.before_value,
            after_value=log.after_value,
        )
        for log in result.change_logs
    ]

    return _build_response(
        store, state, run_id, session_created,
        changed=result.changed,
        applied=applied,
        ignored=ignored_ops,
        reset_applied=result.reset_applied or request.reset_scope,
    )


def _build_response(
    store: StateStore,
    state,
    run_id: str,
    session_created: bool,
    *,
    changed: bool,
    applied: list[AppliedOperation],
    ignored: list[IgnoredOperation],
    reset_applied: str | None,
) -> StateApplyResponse:
    return StateApplyResponse(
        session_id=state.session_id,
        run_id=run_id,
        session_created=session_created,
        user_conditions=state.user_conditions,
        api_context=_build_api_context_view(state),
        condition_version=state.condition_version,
        condition_changed=changed,
        applied_operations=applied,
        ignored_operations=ignored,
        excluded_place_ids=history_module.get_exclusion_place_ids(
            store, state.session_id
        ),
        reset_applied=reset_applied,
    )


# ================================================================ 6.3

@_wrap_store_errors
def get_session_context(
    session_id: str | None,
    store: StateStore | None = None,
) -> SessionContextResponse:
    """인텐트 분류에 필요한 정보를 조회한다. (계약 6.3절)

    State를 변경하지 않는다. run_id를 발급하지 않으며
    last_active_at도 갱신하지 않는다.

    세션이 없거나 만료된 경우에도 오류를 반환하지 않고
    session_exists: false로 응답하며, 세션을 새로 만들지 않는다.
    """
    store = store or get_store()

    state = session_module.peek_session(store, session_id)
    if state is None:
        return SessionContextResponse(
            session_id=session_id,
            session_exists=False,
            has_recommendation=False,
            recommended_count=0,
        )

    sid = state.session_id
    return SessionContextResponse(
        session_id=sid,
        session_exists=True,
        has_recommendation=history_module.has_recommendation(store, sid),
        recommended_count=history_module.count_recommended(store, sid),
        shown_place_ids=history_module.get_shown_place_ids(store, sid),
        excluded_place_ids=history_module.get_exclusion_place_ids(store, sid),
        last_recommended_run_id=history_module.get_last_recommended_run_id(store, sid),
        last_intent=state.last_intent,
        pending_clarification=state.pending_clarification,
        user_conditions=state.user_conditions,
        api_context=_build_api_context_view(state),
        condition_version=state.condition_version,
    )


# ================================================================ 6.4

@_wrap_store_errors
def record_recommendation(
    request: RecordRecommendationRequest,
    store: StateStore | None = None,
) -> RecordRecommendationResponse:
    """실제로 노출된 추천 결과를 기록한다. (계약 6.4절)

    Agent Runtime이 추천 응답을 조립한 직후 호출한다.
    노출이 확정된 결과만 이력에 기록해야 재추천이 정확히 동작한다.
    """
    store = store or get_store()

    recorded = history_module.record_recommended(
        store,
        request.session_id,
        request.run_id,
        [(p.place_id, p.rank) for p in request.recommended],
    )
    return RecordRecommendationResponse(recorded=recorded)


# ================================================================ 세션 삭제

@_wrap_store_errors
def delete_session(
    session_id: str,
    store: StateStore | None = None,
) -> DeleteSessionResponse:
    """세션 상태와 추천 이력을 삭제한다.

    세션이 없어도 오류를 내지 않고 deleted=False를 반환한다.
    """
    store = store or get_store()

    existed = store.get_state(session_id) is not None or store.get_history(session_id) is not None
    store.delete_state(session_id)
    store.delete_history(session_id)
    return DeleteSessionResponse(session_id=session_id, deleted=existed)


# ================================================================ 6.5

@_wrap_store_errors
def update_api_context(
    request: UpdateApiContextRequest,
    store: StateStore | None = None,
) -> UpdateApiContextResponse | None:
    """GPS·날씨 데이터를 갱신한다. (계약 6.5절)

    operations와 별도 경로이며 조건 변경으로 취급하지 않는다.
      - condition_version을 증가시키지 않는다
      - updated_at을 갱신하지 않는다 (last_active_at은 갱신)

    세션이 없으면 None을 반환하며 세션을 생성하지 않는다.
    """
    store = store or get_store()

    state = store.get_state(request.session_id)
    if state is None:
        return None

    now = now_kst()
    fields = request.model_fields_set

    if "gps_location" in fields:
        state.api_context.gps_location = request.gps_location
        state.api_context.gps_location_updated_at = (
            request.gps_location_updated_at or now
        )

    if "api_weather" in fields:
        state.api_context.api_weather = request.api_weather
        state.api_context.api_weather_updated_at = (
            request.api_weather_updated_at or now
        )

    session_module.touch(state)
    store.save_state(state)

    return UpdateApiContextResponse(
        session_id=state.session_id,
        api_context=_build_api_context_view(state),
    )


@_wrap_store_errors
def set_pending_clarification(
    request: SetPendingClarificationRequest,
    store: StateStore | None = None,
) -> SetPendingClarificationResponse | None:
    """되묻기 사유를 저장하거나(code) 지운다(None). (api_context 갱신과 같은 성격)

    세션이 없으면 None을 반환하며 세션을 생성하지 않는다.
    """
    store = store or get_store()

    state = store.get_state(request.session_id)
    if state is None:
        return None

    state.pending_clarification = request.code
    session_module.touch(state)
    store.save_state(state)

    return SetPendingClarificationResponse(
        session_id=state.session_id,
        pending_clarification=state.pending_clarification,
    )


# ================================================================ LLMOps Trace

@_wrap_store_errors
def record_trace(
    request: RecordTraceRequest,
    store: StateStore | None = None,
) -> RecordTraceResponse:
    """실행 단계 1건을 기록한다. (llmops-trace-contract-v1.md 4절)

    호출자(A/C/D)가 각 단계(LLM 호출/Tool 호출/Scoring 등)가 끝난 시점에
    호출한다. B는 step 이름이나 버전 값의 의미를 판단하지 않고 그대로 저장한다.
    """
    store = store or get_store()

    trace = trace_module.record(
        store,
        request.session_id,
        request.run_id,
        request.step,
        prompt_version=request.prompt_version,
        scoring_version=request.scoring_version,
        variant_id=request.variant_id,
        latency_ms=request.latency_ms,
        token_usage=request.token_usage,
        error_type=request.error_type,
    )
    return RecordTraceResponse(trace_id=trace.trace_id)