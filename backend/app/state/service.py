"""Package B - 계약 진입점.

계약 문서: docs/package-b/agent-state-contract-v1.md (6절)

Phase 1에서는 동일 프로세스 내 함수 호출로 제공한다.
HTTP 엔드포인트는 AF-05 Agent Runtime의 책임이므로 여기서 정의하지 않는다.
"""

import functools
from datetime import datetime
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field, model_validator

from app.auth.principal import Principal
from app.errors import AppError
from app.state import feedback as feedback_module
from app.state import history as history_module
from app.state import preferences as preferences_module
from app.state import saved_places as saved_places_module
from app.state import session as session_module
from app.state import trace as trace_module
from app.state.errors import SavedPlaceNotRecommendedError, StateStoreError
from app.state.merge import merge_conditions
from app.state.operations import IgnoredOperation, Operation, validate_all
from app.state.schema import (
    MAX_RECENT_TURNS,
    MAX_TURN_ASSISTANT_MESSAGE_CHARS,
    MAX_TURN_USER_INPUT_CHARS,
    ConversationTurn,
    FeedbackReasonCode,
    PendingInfoContext,
    RecommendedItem,
    RecommendedItemInput,
    SavedPlaceItem,
    SituationState,
    UserConditions,
    UserPreference,
    now_kst,
)
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
    # PR #188: 위치 재확인 UX 전용. B는 만료를 판정하지 않고 값만 그대로
    # 실어 보낸다 — 30분 경과 여부는 A가 이 값과 now를 비교해 판단한다.
    gps_location_confirmed_at: datetime | None = None


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
    # COMPARE가 "추천 시 이미 계산된 데이터"(int-04-compare.md §13)를 그대로
    # 쓸 수 있도록 마지막 실행의 전체 항목(거리/남은 운영시간/환경유형 포함)을
    # 함께 반환한다. shown_place_ids와 범위·정렬 기준은 동일(마지막 run_id,
    # rank 순)하다 — COMPARE 데이터 출처 A안, 2026-08-11.
    shown_recommendations: list[RecommendedItem] = Field(default_factory=list)
    excluded_place_ids: list[str] = Field(default_factory=list)
    last_recommended_run_id: str | None = None
    last_intent: str | None = None
    # 직전 턴이 되묻기로 끝났다면 그 사유 코드. A가 이번 턴의 조건 병합 방식을
    # 정할 때 읽는다.
    pending_clarification: str | None = None
    # pending_clarification == "place_ambiguous"일 때 원래 INFO 질문을 그대로
    # 담고 있다. A가 되묻기 버튼 클릭을 결정적으로 재구성할 때 읽는다.
    pending_info_context: PendingInfoContext | None = None
    # "운영 중이 아닌 곳도 볼게요"가 유효한 만료 시각. A가 now와 비교해서
    # 이번 턴에도 폐점 후보를 계속 포함할지 판정한다(state.py는 판단하지 않음).
    ignore_operating_hours_until: datetime | None = None
    # 최근 대화(오래된 것이 앞, 최대 MAX_RECENT_TURNS개). A가 상황 판단과 이어지는
    # 발화 해석에 쓴다. 신뢰할 수 없는 입력이라 프롬프트의 system_instruction에
    # 치환하면 안 된다(ConversationTurn docstring 참고).
    recent_turns: list[ConversationTurn] = Field(default_factory=list)
    # 상황 축이 잡은 현재 상태. 이미 거절당한 제안을 다시 하지 않으려면 A가 이
    # 값의 rejected_actions를 읽어야 한다.
    situation_state: SituationState | None = None
    # 사용자가 명시적으로 담은 장소(담은 순서, SCHEDULE-12). shown_place_ids와
    # 달리 마지막 run으로 좁히지 않는다 — 여러 턴에 걸쳐 담은 것이 전부 들어
    # 있어야 "담은 곳으로 일정 짜줘"가 성립한다. 소비(후보 복귀·배치 보장)는
    # 후속 카드에서 A가 붙인다.
    saved_places: list[SavedPlaceItem] = Field(default_factory=list)
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
    """노출된 장소 1건. (계약 6.4절)

    estimated_arrival~reason은 SCHEDULE 전용 선택 필드(SCHEDULE-06) —
    RECOMMEND/MODIFY 호출은 생략하면 된다. distance_km~environment_type은
    COMPARE 전용 선택 필드(COMPARE 데이터 출처 A안, 2026-08-11) — 추천 시점에
    계산된 Feature 스냅샷을 그대로 넘긴다. SCHEDULE 호출은 생략하면 된다.
    name은 SCHEDULE-09 2단계 전용 선택 필드(2026-08-11) — 부분 재편성에서
    지명 검색 좌표가 매 턴 흔들려도 이전 장소 이름을 안정적으로 재사용하기
    위한 것이다(schema.RecommendedItem 문서 참고). 항상 넘길 수 있으면
    넘기는 게 좋다.
    latitude/longitude는 SCHEDULE-12 전용 선택 필드다 — 보관함에 담긴 장소가
    나중 SCHEDULE 턴의 검색 반경 밖일 때, 후보 간 거리를 계산할 유일한 근거가
    된다. C 응답(AgentContextResponse.places)에서 place_id로 매칭해 채운다.
    """

    place_id: str
    rank: int
    name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    estimated_arrival: str | None = None
    estimated_duration_min: int | None = None
    travel_to_next_min: int | None = None
    reason: str | None = None
    distance_km: float | None = None
    remaining_minutes: int | None = None
    environment_type: str | None = None


class RecordRecommendationRequest(BaseModel):
    session_id: str
    run_id: str
    recommended: list[RecommendedPlace] = Field(default_factory=list)


class RecordRecommendationResponse(BaseModel):
    recorded: int


class RecordClosedExclusionsRequest(BaseModel):
    """TP-82: D의 하드 필터가 폐점이라 걸러낸 후보 id 기록 요청.

    RecordRecommendationRequest와 분리한다 — 이 place_id들은 노출되지
    않았으므로 recommended 이력에 섞으면 "노출했다"로 잘못 취급되어
    COMPARE의 "첫 번째"가 실제로 안 보여준 장소를 가리키게 된다.
    """

    session_id: str
    run_id: str
    place_ids: list[str] = Field(default_factory=list)


class RecordClosedExclusionsResponse(BaseModel):
    recorded: int


class SavePlaceRequest(BaseModel):
    """장소 보관함 담기 요청. (SCHEDULE-12)

    session_id는 경로 파라미터로 받으므로 본문에 두지 않는다.
    """

    place_id: str = Field(min_length=1)


class SavedPlacesResponse(BaseModel):
    """보관함 담기/빼기 응답. (SCHEDULE-12)

    담긴 목록 전체를 항상 함께 반환한다 — 프론트가 낙관적으로 갱신한 뒤 이
    값으로 확정하면 되므로 별도 조회가 필요 없다.
    """

    session_id: str
    items: list[SavedPlaceItem] = Field(default_factory=list)
    # 이번 요청으로 실제 변화가 있었는지. 같은 장소를 두 번 담거나 담기지
    # 않은 장소를 빼는 요청은 오류가 아니라 changed=False다(멱등).
    changed: bool


class UpdateApiContextRequest(BaseModel):
    """api_context 갱신 요청. (계약 6.5절)

    전달된 필드만 갱신하며, 생략된 필드는 기존 값을 유지한다.
    """

    session_id: str
    gps_location: str | None = None
    gps_location_updated_at: datetime | None = None
    api_weather: str | None = None
    api_weather_updated_at: datetime | None = None
    # PR #188: gps_location과 독립적으로 채운다 — "현재 위치 다시 가져오기"가
    # 성공했을 때만 A가 gps_location과 함께 이 필드도 넘긴다. "N분 전 위치로
    # 계속"을 선택했을 때는 gps_location만(또는 아무것도) 넘기고 이 필드는
    # 생략해야 값이 갱신되지 않는다.
    gps_location_confirmed_at: datetime | None = None


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


class SetPendingInfoContextRequest(BaseModel):
    """INFO 되묻기(place_ambiguous)가 원래 질문을 저장하는 요청.

    set_pending_clarification과 짝을 이룬다 — code="place_ambiguous"를 저장할
    때 바로 뒤에 이 요청도 보낸다. context=None이면 지운다.
    """

    session_id: str
    context: PendingInfoContext | None = None


class SetPendingInfoContextResponse(BaseModel):
    session_id: str
    pending_info_context: PendingInfoContext | None


class AppendConversationTurnRequest(BaseModel):
    """방금 끝난 대화 한 턴을 세션에 남기는 요청. (대화층 1단계)

    A가 응답을 다 만든 뒤 한 번 호출한다. 자르기(MAX_RECENT_TURNS)와 원문 길이
    상한은 B가 책임진다 — 호출부마다 다르게 자르면 상한이 의미를 잃는다.
    """

    session_id: str
    turn: ConversationTurn


class AppendConversationTurnResponse(BaseModel):
    session_id: str
    recent_turns: list[ConversationTurn]


class SetSituationStateRequest(BaseModel):
    """상황 상태를 저장하거나(state) 지운다(None). (대화층 1단계)"""

    session_id: str
    state: SituationState | None = None


class SetSituationStateResponse(BaseModel):
    session_id: str
    situation_state: SituationState | None


class SetIgnoreOperatingHoursRequest(BaseModel):
    """"운영 중이 아닌 곳도 볼게요" 선택을 일정 시간 기억하는 요청.

    A가 no_data_closed 되묻기의 "운영 중이 아닌 곳도 볼게요"를 해소할 때만
    호출한다. until을 None으로 보내면 즉시 해제한다(수동 초기화용, 현재는
    호출부 없음 — 자연 만료는 조회 시점에 A가 now와 비교해서 판정한다).
    """

    session_id: str
    until: datetime | None = None


class SetIgnoreOperatingHoursResponse(BaseModel):
    session_id: str
    ignore_operating_hours_until: datetime | None


class SetLastIntentRequest(BaseModel):
    """`last_intent` 덮어쓰기 요청 (2026-08-11, D-061).

    apply()는 매 턴 `state.last_intent`를 그 턴의 "원본" intent로 저장한다
    (transform() 호출 시점 값). 그런데 Agent Runtime의 SCHEDULE 재조정 감지
    (3-3절)는 apply() 이후에 "화면상 라벨"만 SCHEDULE로 바꿔치기하므로,
    apply()가 이미 저장한 원본 intent(예: MODIFY)와 실제 처리 결과(SCHEDULE)가
    어긋난다. REJECT_SPECIFIC 부분 재편성이 연속으로 이어질 때(SCHEDULE →
    REJECT_SPECIFIC → REJECT_SPECIFIC) 두 번째 REJECT_SPECIFIC 턴이 직전 턴을
    last_intent="SCHEDULE"로 인식하지 못해 재조정 감지 자체가 실패하는 버그로
    이어졌다(2026-08-11 실사용 재현). apply() 직후 이 함수로 라벨을 다시
    맞춰준다 — condition_version/updated_at 등 다른 필드는 건드리지 않는다.
    """

    session_id: str
    intent: str


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


class RecordFeedbackRequest(BaseModel):
    """응답 피드백 기록 요청. (roadmap.md 14번)

    rating은 FeedbackRecord가 "like"/"dislike"로 검증한다 — RecordTraceRequest의
    step 등과 달리 B가 값을 검증하는 예외적인 필드다.

    user_input/assistant_message는 2026-08-21 추가된 선택 필드다. 프론트가
    피드백을 남긴 턴의 질문·답변 텍스트를 함께 보내면 그대로 저장한다 —
    FeedbackRecord 스키마 docstring의 원문 저장 범위 설명 참고.

    intent도 같은 날 추가된 선택 필드다. 그 턴의 assistant_text 메시지가
    이미 들고 있는 값을 그대로 전달받아 저장한다.

    comment는 "싫어요" 사유로 사용자가 직접 남긴 자유 텍스트다(develop PR에서
    병합, D-069) — 짧은 사유라는 용도에 맞춰 500자로 길이를 제한한다.
    """

    session_id: str
    run_id: str
    rating: Literal["like", "dislike"]
    user_input: str | None = None
    assistant_message: str | None = None
    intent: str | None = None
    reason_code: FeedbackReasonCode | None = None
    comment: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_reason_details(self) -> "RecordFeedbackRequest":
        """좋아요에는 사유를 남기지 않고, 싫어요에는 표준 사유를 남긴다."""
        if self.rating == "like" and (self.reason_code is not None or self.comment is not None):
            raise ValueError("좋아요에는 reason_code나 comment를 남길 수 없습니다")
        # 기존 클라이언트의 "싫어요" 기록은 reason_code 없이도 읽고 쓸 수 있게
        # 둔다. 새 프론트는 항상 표준 사유를 보낸다.
        return self


class RecordFeedbackResponse(BaseModel):
    recorded_at: datetime


class DislikeFeedbackItem(BaseModel):
    """"싫어요" 1건 + 그 응답을 만든 실행의 버전 정보. (roadmap.md 14번)

    prompt_version/scoring_version은 같은 run_id의 TraceRecord들 중에서
    찾아 채운다 — 기록이 안 남아 있으면(예: record_trace 호출 전 오류) null.
    """

    session_id: str
    run_id: str
    recorded_at: datetime
    intent: str | None = None
    user_input: str | None = None
    assistant_message: str | None = None
    reason_code: FeedbackReasonCode | None = None
    comment: str | None = None
    prompt_version: str | None = None
    scoring_version: str | None = None


class DislikeFeedbackResponse(BaseModel):
    items: list[DislikeFeedbackItem]


class IntentCount(BaseModel):
    """intent 1개의 등장 횟수. (TP-146)"""

    intent: str
    count: int


_FEEDBACK_STATS_UNCLASSIFIED = "unclassified"


class FeedbackStatsResponse(BaseModel):
    """전체 피드백을 rating/reason_code/intent 기준으로 집계한 응답. (TP-146)

    reason_code_counts는 표준 7개 사유 + "unclassified"(구 클라이언트가 사유
    없이 남긴 dislike, RecordFeedbackRequest.validate_reason_details 참고)
    키를 항상 전부 포함한다 — 프론트가 값이 0인 항목까지 그대로 표로 그릴 수
    있게 하기 위해서다. like 행은 이 집계에 들어가지 않는다.

    intent는 자유 텍스트라(스키마 docstring 참고) 값이 무한정 늘어날 수
    있어 상위 top_intents개만 담고, 그 뒤는 other_intent_count로 합친다.
    intent 자체가 없는 행(intent=None)은 missing_intent_count로 따로 센다 —
    "롱테일에 묻힌 것"과 "애초에 안 남은 것"은 다른 상황이라 섞지 않는다.
    """

    since: datetime | None
    until: datetime | None
    total: int
    rating_counts: dict[str, int]
    reason_code_counts: dict[str, int]
    top_intents: list[IntentCount]
    other_intent_count: int
    missing_intent_count: int


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
        gps_location_confirmed_at=state.api_context.gps_location_confirmed_at,
    )


def _wrap_store_errors(fn):
    """저장소 호출 중 예상 못한 예외를 B 공통 오류(StateStoreError)로 감싼다.

    이미 AppError인 경우(SupabaseStateStore가 HTTP 실패 시 이미 StateStoreError로
    직접 던지는 경우 등)는 의미가 있으므로 그대로 전달한다. "세션 없음"은 예외가
    아니라 정상 반환값이므로 영향받지 않는다 (계약 5.2/6.7절).
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
    principal: Principal | None = None,
) -> StateApplyResponse:
    """조건 변경을 적용하고 현재 상태를 반환한다. (계약 6.1 / 6.2절)"""
    store = store or get_store()

    # 1) 세션 확보
    state, session_created = session_module.get_or_create_session(
        store, request.session_id
    )

    # 1-0) 소유권 대조 (D-063 결정 2 후속, D-073) — 신원 연결(1-1)보다 먼저
    #      실행한다. 방금 생성된 세션(session_created=True)은 principal이
    #      있으면 곧 1-1에서 그 신원이 채워질 값이라 항상 통과한다.
    session_module.verify_ownership(state, principal)

    # 1-1) 신원 연결 (TP-101 3단계, D-063) — 세션 확보 직후, 두 저장 경로
    #      (아래 3번 confirmed=false 조기 반환 / 9번 본 경로) 모두보다 먼저
    #      실행해야 어느 쪽으로 빠지든 user_id가 함께 저장된다.
    session_module.attach_user_id(state, principal)

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
            principal=principal,
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
    principal: Principal | None = None,
) -> SessionContextResponse:
    """인텐트 분류에 필요한 정보를 조회한다. (계약 6.3절)

    State를 변경하지 않는다. run_id를 발급하지 않으며
    last_active_at도 갱신하지 않는다.

    세션이 없거나 만료된 경우에도 오류를 반환하지 않고
    session_exists: false로 응답하며, 세션을 새로 만들지 않는다.

    principal이 주어지면 소유권을 대조한다(D-063 결정 2 후속, D-073) — 이
    함수는 조건·이력·GPS까지 포함한 세션 전체를 노출하는 읽기 경로라, 쓰기
    경로인 apply()와 별도로 여기서도 대조해야 한다.
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

    session_module.verify_ownership(state, principal)

    sid = state.session_id
    return SessionContextResponse(
        session_id=sid,
        session_exists=True,
        has_recommendation=history_module.has_recommendation(store, sid),
        recommended_count=history_module.count_recommended(store, sid),
        shown_place_ids=history_module.get_shown_place_ids(store, sid),
        shown_recommendations=history_module.get_last_recommended_items(store, sid),
        excluded_place_ids=history_module.get_exclusion_place_ids(store, sid),
        last_recommended_run_id=history_module.get_last_recommended_run_id(store, sid),
        last_intent=state.last_intent,
        pending_clarification=state.pending_clarification,
        pending_info_context=state.pending_info_context,
        ignore_operating_hours_until=state.ignore_operating_hours_until,
        recent_turns=state.recent_turns,
        situation_state=state.situation_state,
        saved_places=saved_places_module.get_items(store, sid),
        user_conditions=state.user_conditions,
        api_context=_build_api_context_view(state),
        condition_version=state.condition_version,
    )


# ================================================================ 6.4

@_wrap_store_errors
def record_recommendation(
    request: RecordRecommendationRequest,
    store: StateStore | None = None,
    principal: Principal | None = None,
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
        [
            RecommendedItemInput(
                place_id=p.place_id,
                rank=p.rank,
                name=p.name,
                latitude=p.latitude,
                longitude=p.longitude,
                estimated_arrival=p.estimated_arrival,
                estimated_duration_min=p.estimated_duration_min,
                travel_to_next_min=p.travel_to_next_min,
                reason=p.reason,
                distance_km=p.distance_km,
                remaining_minutes=p.remaining_minutes,
                environment_type=p.environment_type,
            )
            for p in request.recommended
        ],
        principal=principal,
    )
    return RecordRecommendationResponse(recorded=recorded)


# ================================================================ TP-82

@_wrap_store_errors
def record_closed_exclusions(
    request: RecordClosedExclusionsRequest,
    store: StateStore | None = None,
    principal: Principal | None = None,
) -> RecordClosedExclusionsResponse:
    """D의 하드 필터가 폐점이라 걸러낸 후보 id를 기록한다. (TP-82)

    Agent Runtime이 D 응답(`RecommendationResponse.excluded_closed_place_ids`)을
    받은 직후 호출한다. 여기 기록된 id는 get_exclusion_place_ids()가 다음
    회차 후보 수집 시 제외 목록에 포함시켜, 노출 이력이 없어 반복
    수집되던 폐점 후보를 걸러낸다.
    """
    store = store or get_store()

    recorded = history_module.record_closed_excluded(
        store,
        request.session_id,
        request.run_id,
        request.place_ids,
        principal=principal,
    )
    return RecordClosedExclusionsResponse(recorded=recorded)


# ================================================================ SCHEDULE-12

@_wrap_store_errors
def save_place(
    session_id: str,
    request: SavePlaceRequest,
    store: StateStore | None = None,
    principal: Principal | None = None,
) -> SavedPlacesResponse:
    """장소를 보관함에 담는다. (SCHEDULE-12)

    담을 수 있는 것은 그 세션에서 노출된 적이 있는 장소뿐이다 — 임의 place_id
    주입을 막고, 이름을 추천 시점 스냅샷에서 그대로 가져오기 위해서다. 세션이
    없거나 노출 이력에 없으면 SavedPlaceNotRecommendedError(400)를 던진다.

    principal이 주어지면 소유권을 대조한다(D-063 결정 2 후속, D-073) — 세션에
    쓰기를 하는 경로이므로 apply()·delete_session()과 같은 기준으로 막는다.
    """
    store = store or get_store()

    state = session_module.peek_session(store, session_id)
    if state is not None:
        session_module.verify_ownership(state, principal)

    recommended = history_module.find_recommended_item(
        store, session_id, request.place_id
    )
    if recommended is None:
        raise SavedPlaceNotRecommendedError(request.place_id)

    changed = saved_places_module.add(
        store,
        session_id,
        SavedPlaceItem(
            place_id=recommended.place_id,
            # 추천 시점 스냅샷을 그대로 쓴다. name이 없던 과거 데이터는
            # place_id로 대체한다 — 화면에 빈 칸이 뜨는 것보다 낫고,
            # 담기 자체를 막을 이유는 아니다.
            name=recommended.name or recommended.place_id,
            saved_from_run_id=recommended.run_id,
            # 추천 시점 좌표를 그대로 옮긴다(SCHEDULE-12). 담긴 장소가 나중
            # SCHEDULE 턴의 검색 반경 밖이면 C 응답에 없어, 여기 남은 값이
            # 후보 간 거리를 계산할 유일한 근거가 된다.
            latitude=recommended.latitude,
            longitude=recommended.longitude,
        ),
        principal=principal,
    )
    return SavedPlacesResponse(
        session_id=session_id,
        items=saved_places_module.get_items(store, session_id),
        changed=changed,
    )


@_wrap_store_errors
def remove_saved_place(
    session_id: str,
    place_id: str,
    store: StateStore | None = None,
    principal: Principal | None = None,
) -> SavedPlacesResponse:
    """장소를 보관함에서 뺀다. (SCHEDULE-12)

    담기와 달리 추천 이력을 확인하지 않는다 — 빼는 대상은 이미 보관함에 있는
    것이고, 없는 place_id를 빼달라는 요청은 멱등하게 changed=False로 답한다.
    """
    store = store or get_store()

    state = session_module.peek_session(store, session_id)
    if state is not None:
        session_module.verify_ownership(state, principal)

    changed = saved_places_module.remove(
        store, session_id, place_id, principal=principal
    )
    return SavedPlacesResponse(
        session_id=session_id,
        items=saved_places_module.get_items(store, session_id),
        changed=changed,
    )


@_wrap_store_errors
def get_saved_places(
    session_id: str,
    store: StateStore | None = None,
    principal: Principal | None = None,
) -> SavedPlacesResponse:
    """보관함을 조회한다. (SCHEDULE-12)

    get_session_context()의 saved_places와 같은 값이다 — 프론트가 세션 전체를
    다시 받지 않고 보관함만 새로 고칠 수 있게 하는 경로다. changed는 항상
    False다(조회는 아무것도 바꾸지 않는다).
    """
    store = store or get_store()

    state = session_module.peek_session(store, session_id)
    if state is not None:
        session_module.verify_ownership(state, principal)

    return SavedPlacesResponse(
        session_id=session_id,
        items=saved_places_module.get_items(store, session_id),
        changed=False,
    )


# ================================================================ 세션 삭제

@_wrap_store_errors
def delete_session(
    session_id: str,
    store: StateStore | None = None,
    principal: Principal | None = None,
) -> DeleteSessionResponse:
    """세션 상태와 추천 이력을 삭제한다.

    세션이 없어도 오류를 내지 않고 deleted=False를 반환한다.

    principal이 주어지면 삭제 전에 소유권을 대조한다(D-063 결정 2 후속,
    D-073) — 조회보다 되돌릴 수 없는 파괴적 동작이라 반드시 같은 기준으로
    막는다.
    """
    store = store or get_store()

    existing_state = store.get_state(session_id)
    if existing_state is not None:
        session_module.verify_ownership(existing_state, principal)

    existed = existing_state is not None or store.get_history(session_id) is not None
    store.delete_state(session_id)
    store.delete_history(session_id)
    # 보관함도 세션 수명에 묶여 있다(SCHEDULE-12) — 남겨두면 같은 session_id가
    # 재사용될 때 이전 사용자가 담아둔 장소가 되살아난다. existed 판정에는
    # 넣지 않는다: 보관함만 있고 상태·이력이 없는 조합은 만들어질 수 없다
    # (담기가 추천 이력을 전제로 하므로).
    store.delete_saved_places(session_id)
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

    # PR #188: gps_location 블록과 독립된 분기다 — 매 GPS 갱신마다 자동으로
    # 따라오면 안 되고, A가 "재확인 성공"을 명시적으로 알릴 때만 값이 바뀐다.
    if "gps_location_confirmed_at" in fields:
        state.api_context.gps_location_confirmed_at = (
            request.gps_location_confirmed_at or now
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
    # pending_info_context는 place_ambiguous일 때만 의미가 있다. 다른 코드로
    # 바뀌거나(다른 되묻기) 지워지면(정상 완료) 여기서 같이 지운다 — 그러면
    # set_pending_info_context()는 place_ambiguous를 저장하는 호출부 한 곳만
    # 신경 쓰면 되고, 기존 set_pending_clarification 호출부 전부가 자동으로
    # 안전하게 정리된다.
    if request.code != "place_ambiguous":
        state.pending_info_context = None
    session_module.touch(state)
    store.save_state(state)

    return SetPendingClarificationResponse(
        session_id=state.session_id,
        pending_clarification=state.pending_clarification,
    )


@_wrap_store_errors
def set_pending_info_context(
    request: SetPendingInfoContextRequest,
    store: StateStore | None = None,
) -> SetPendingInfoContextResponse | None:
    """INFO 되묻기(place_ambiguous)가 원래 질문을 저장하거나(context) 지운다(None).

    set_pending_clarification(code="place_ambiguous") 직후에 호출한다. 세션이
    없으면 None을 반환하며 세션을 생성하지 않는다(다른 pending_* 갱신 함수들과
    같은 방어 패턴).
    """
    store = store or get_store()

    state = store.get_state(request.session_id)
    if state is None:
        return None

    state.pending_info_context = request.context
    session_module.touch(state)
    store.save_state(state)

    return SetPendingInfoContextResponse(
        session_id=state.session_id,
        pending_info_context=state.pending_info_context,
    )


@_wrap_store_errors
def append_conversation_turn(
    request: AppendConversationTurnRequest,
    store: StateStore | None = None,
) -> AppendConversationTurnResponse | None:
    """대화 한 턴을 남기고, 오래된 턴을 상한까지 버린다. (대화층 1단계)

    자르는 책임을 여기 한 곳에만 둔다 — 호출부가 각자 자르면 상한이 곧 어긋난다.
    세션이 없으면 None을 반환하며 세션을 생성하지 않는다(다른 갱신 함수들과 같은
    방어 패턴).
    """
    store = store or get_store()

    state = store.get_state(request.session_id)
    if state is None:
        return None

    turn = request.turn
    # 자르는 것은 길이 상한을 지키기 위해서지 요약이 아니다 — 뒷부분이 사라진다는
    # 사실을 감추지 않으려고 말줄임표를 붙이지 않는다. 사용자 원문과 어시스턴트
    # 답변을 같은 자리에서 함께 자른다(상한 관리를 한 곳에 두는 위 원칙).
    truncations: dict[str, str] = {}
    if len(turn.user_input) > MAX_TURN_USER_INPUT_CHARS:
        truncations["user_input"] = turn.user_input[:MAX_TURN_USER_INPUT_CHARS]
    if (
        turn.assistant_message is not None
        and len(turn.assistant_message) > MAX_TURN_ASSISTANT_MESSAGE_CHARS
    ):
        truncations["assistant_message"] = turn.assistant_message[
            :MAX_TURN_ASSISTANT_MESSAGE_CHARS
        ]
    if truncations:
        turn = turn.model_copy(update=truncations)

    state.recent_turns = [*state.recent_turns, turn][-MAX_RECENT_TURNS:]
    session_module.touch(state)
    store.save_state(state)

    return AppendConversationTurnResponse(
        session_id=state.session_id,
        recent_turns=state.recent_turns,
    )


@_wrap_store_errors
def set_situation_state(
    request: SetSituationStateRequest,
    store: StateStore | None = None,
) -> SetSituationStateResponse | None:
    """상황 상태를 저장하거나(state) 지운다(None). (대화층 1단계)

    세션이 없으면 None을 반환하며 세션을 생성하지 않는다.
    """
    store = store or get_store()

    state = store.get_state(request.session_id)
    if state is None:
        return None

    state.situation_state = request.state
    session_module.touch(state)
    store.save_state(state)

    return SetSituationStateResponse(
        session_id=state.session_id,
        situation_state=state.situation_state,
    )


@_wrap_store_errors
def set_ignore_operating_hours_until(
    request: SetIgnoreOperatingHoursRequest,
    store: StateStore | None = None,
) -> SetIgnoreOperatingHoursResponse | None:
    """"운영 중이 아닌 곳도 볼게요" 만료 시각을 저장하거나(until) 지운다(None).

    세션이 없으면 None을 반환하며 세션을 생성하지 않는다(api_context/
    pending_clarification 갱신 함수들과 같은 방어 패턴).
    """
    store = store or get_store()

    state = store.get_state(request.session_id)
    if state is None:
        return None

    state.ignore_operating_hours_until = request.until
    session_module.touch(state)
    store.save_state(state)

    return SetIgnoreOperatingHoursResponse(
        session_id=state.session_id,
        ignore_operating_hours_until=state.ignore_operating_hours_until,
    )


@_wrap_store_errors
def set_last_intent(
    request: SetLastIntentRequest,
    store: StateStore | None = None,
) -> None:
    """`last_intent`를 덮어쓴다 (SetLastIntentRequest 문서 참고).

    세션이 없으면 조용히 아무것도 하지 않는다 — apply()가 방금 만든 세션이
    사라졌을 리 없지만, api_context/pending_clarification 갱신 함수들과
    같은 방어 패턴을 따른다.
    """
    store = store or get_store()

    state = store.get_state(request.session_id)
    if state is None:
        return

    state.last_intent = request.intent
    store.save_state(state)


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


# ================================================================ 응답 피드백

@_wrap_store_errors
def record_feedback(
    request: RecordFeedbackRequest,
    store: StateStore | None = None,
) -> RecordFeedbackResponse:
    """응답 1건에 대한 사용자 반응(좋아요/싫어요)을 기록한다. (roadmap.md 14번)

    프론트가 피드백 버튼 클릭 직후 호출한다. run_id로 trace_records와 조인하면
    이 반응이 어떤 prompt_version/scoring_version에서 나온 응답인지 추적할 수
    있다 — 그 조인 조회는 실제로 쓰는 곳이 생기면 그때 추가한다(llmops-trace-
    contract-v1.md 4절과 동일한 YAGNI 판단. get_feedback()/trace_module.
    get_traces()가 이미 세션 단위로 존재해 필요하면 호출부에서 run_id로
    걸러 쓸 수 있다).
    """
    store = store or get_store()

    feedback = feedback_module.record(
        store,
        request.session_id,
        request.run_id,
        request.rating,
        user_input=request.user_input,
        assistant_message=request.assistant_message,
        intent=request.intent,
        reason_code=request.reason_code,
        comment=request.comment,
    )
    return RecordFeedbackResponse(recorded_at=feedback.recorded_at)


_DEFAULT_DISLIKE_LIMIT = 50


@_wrap_store_errors
def get_dislike_feedback(
    limit: int = _DEFAULT_DISLIKE_LIMIT,
    store: StateStore | None = None,
) -> DislikeFeedbackResponse:
    """최근 "싫어요"를 버전 정보와 함께 모아 반환한다. (roadmap.md 14번)

    dislike 목록을 먼저 모으고, 각 항목의 run_id로 같은 세션의 trace 기록을
    다시 불러와 prompt_version/scoring_version을 채운다 — trace_records는
    세션 단위로만 조회 가능하므로(get_traces(run_id) 자체가 없음, llmops-
    trace-contract-v1.md 4절) session_id를 먼저 알아야 하는데, FeedbackRecord가
    이미 session_id를 들고 있어 별도 조회 없이 바로 이어 쓸 수 있다.

    dislike 자체가 흔치 않을 것으로 가정해 세션별로 트레이스를 다시 불러오는
    비용은 감수한다 — 세션마다 캐싱하는 최적화는 실제로 느릴 때 추가한다.
    """
    store = store or get_store()

    dislikes = feedback_module.list_dislikes(store, limit)

    items: list[DislikeFeedbackItem] = []
    traces_by_session: dict[str, list] = {}
    for feedback in dislikes:
        if feedback.session_id not in traces_by_session:
            traces_by_session[feedback.session_id] = trace_module.get_traces(
                store, feedback.session_id
            )
        run_traces = [
            t for t in traces_by_session[feedback.session_id] if t.run_id == feedback.run_id
        ]
        prompt_version = next(
            (t.prompt_version for t in run_traces if t.prompt_version), None
        )
        scoring_version = next(
            (t.scoring_version for t in run_traces if t.scoring_version), None
        )
        items.append(
            DislikeFeedbackItem(
                session_id=feedback.session_id,
                run_id=feedback.run_id,
                recorded_at=feedback.recorded_at,
                intent=feedback.intent,
                user_input=feedback.user_input,
                assistant_message=feedback.assistant_message,
                reason_code=feedback.reason_code,
                comment=feedback.comment,
                prompt_version=prompt_version,
                scoring_version=scoring_version,
            )
        )

    return DislikeFeedbackResponse(items=items)


_DEFAULT_TOP_INTENTS = 20


@_wrap_store_errors
def get_feedback_stats(
    since: datetime | None = None,
    until: datetime | None = None,
    top_intents: int = _DEFAULT_TOP_INTENTS,
    store: StateStore | None = None,
) -> FeedbackStatsResponse:
    """전체 피드백을 집계해 dev-ops 패널에서 볼 수 있는 요약을 만든다. (TP-146)

    집계 자체는 SQL group-by가 아니라 여기(Python)에서 한다 — 다른 조회
    메서드(list_dislikes 등)도 전부 원본 행을 FeedbackRecord로 그대로
    돌려주는 방식을 따르고 있어 그 패턴을 유지했고, PostgREST의 count()
    집계는 이 프로젝트 설정에서 기본 활성화가 보장되지 않는다. 데이터
    규모가 커지면(수만 건 이상) 그때 DB 쪽 집계로 옮기는 게 맞다 — 지금은
    "이미 쌓인 데이터를 처음으로 꺼내 쓴다"는 이번 카드의 목적에 비해
    과한 최적화다.
    """
    store = store or get_store()
    records = feedback_module.list_for_stats(store, since=since, until=until)

    rating_counts: dict[str, int] = {"like": 0, "dislike": 0}
    reason_code_counts: dict[str, int] = dict.fromkeys(get_args(FeedbackReasonCode), 0)
    reason_code_counts[_FEEDBACK_STATS_UNCLASSIFIED] = 0
    intent_counts: dict[str, int] = {}
    missing_intent_count = 0

    for record in records:
        rating_counts[record.rating] = rating_counts.get(record.rating, 0) + 1
        if record.rating == "dislike":
            key = record.reason_code or _FEEDBACK_STATS_UNCLASSIFIED
            reason_code_counts[key] = reason_code_counts.get(key, 0) + 1
        if record.intent:
            intent_counts[record.intent] = intent_counts.get(record.intent, 0) + 1
        else:
            missing_intent_count += 1

    sorted_intents = sorted(intent_counts.items(), key=lambda kv: kv[1], reverse=True)
    top = sorted_intents[:top_intents]
    other_intent_count = sum(count for _, count in sorted_intents[top_intents:])

    return FeedbackStatsResponse(
        since=since,
        until=until,
        total=len(records),
        rating_counts=rating_counts,
        reason_code_counts=reason_code_counts,
        top_intents=[IntentCount(intent=intent, count=count) for intent, count in top],
        other_intent_count=other_intent_count,
        missing_intent_count=missing_intent_count,
    )


# ================================================================ 실행 기록(Trace) 통계


class TraceStepStat(BaseModel):
    """step 하나의 집계. (TP-157)"""

    step: str
    count: int
    avg_latency_ms: float | None
    max_latency_ms: int | None
    error_count: int


class TraceRecentError(BaseModel):
    """최근 에러 발생 실행 1건. (TP-157)"""

    session_id: str
    run_id: str
    step: str
    error_type: str
    recorded_at: datetime


class TraceStatsResponse(BaseModel):
    """전체 trace를 step 기준으로 집계한 응답. (TP-157)

    step_stats는 등장한 step만 담는다(reason_code_counts처럼 고정된 값
    집합이 없다 — step은 trace.py docstring대로 A/C/D가 자유롭게 붙이는
    문자열이라 B가 미리 알 수 없다). avg_latency_ms/max_latency_ms는
    latency_ms가 기록된 행만으로 계산하고, 한 건도 없으면 null이다.
    recent_errors는 error_type이 있는 행만 최근순으로 상위
    recent_errors_limit개.
    """

    since: datetime | None
    until: datetime | None
    total: int
    step_stats: list[TraceStepStat]
    recent_errors: list[TraceRecentError]


_DEFAULT_RECENT_ERRORS_LIMIT = 20


@_wrap_store_errors
def get_trace_stats(
    since: datetime | None = None,
    until: datetime | None = None,
    recent_errors_limit: int = _DEFAULT_RECENT_ERRORS_LIMIT,
    store: StateStore | None = None,
) -> TraceStatsResponse:
    """전체 trace를 집계해 dev-ops 패널에서 볼 수 있는 요약을 만든다. (TP-157)

    집계는 get_feedback_stats와 동일한 이유로 SQL group-by가 아니라
    여기(Python)에서 한다.
    """
    store = store or get_store()
    records = trace_module.list_for_stats(store, since=since, until=until)

    counts: dict[str, int] = {}
    latency_sums: dict[str, int] = {}
    latency_counts: dict[str, int] = {}
    max_latency: dict[str, int] = {}
    error_counts: dict[str, int] = {}
    step_order: list[str] = []

    for record in records:
        if record.step not in counts:
            step_order.append(record.step)
        counts[record.step] = counts.get(record.step, 0) + 1
        if record.latency_ms is not None:
            latency_sums[record.step] = latency_sums.get(record.step, 0) + record.latency_ms
            latency_counts[record.step] = latency_counts.get(record.step, 0) + 1
            max_latency[record.step] = max(
                max_latency.get(record.step, record.latency_ms), record.latency_ms
            )
        if record.error_type is not None:
            error_counts[record.step] = error_counts.get(record.step, 0) + 1

    step_stats = [
        TraceStepStat(
            step=step,
            count=counts[step],
            avg_latency_ms=(
                latency_sums[step] / latency_counts[step] if step in latency_counts else None
            ),
            max_latency_ms=max_latency.get(step),
            error_count=error_counts.get(step, 0),
        )
        for step in step_order
    ]

    error_records = [r for r in records if r.error_type is not None]
    error_records.sort(key=lambda r: r.recorded_at, reverse=True)
    recent_errors = [
        TraceRecentError(
            session_id=r.session_id,
            run_id=r.run_id,
            step=r.step,
            error_type=r.error_type,  # type: ignore[arg-type]  # filtered not-None above
            recorded_at=r.recorded_at,
        )
        for r in error_records[:recent_errors_limit]
    ]

    return TraceStatsResponse(
        since=since,
        until=until,
        total=len(records),
        step_stats=step_stats,
        recent_errors=recent_errors,
    )


# ================================================================ 취향 (계정 단위)


class UserPreferencesResponse(BaseModel):
    """계정 단위 취향 조회·저장 응답. (TP-222 후속)

    session_id를 담지 않는다 — 이 값은 세션에 속하지 않는다. 다른 상태 응답과
    모양이 다른 것은 의도된 것이고, 그래서 라우트도 /state/{session_id} 아래가
    아니라 /preferences로 따로 나 있다.
    """

    items: list[UserPreference] = Field(default_factory=list)
    updated_at: datetime | None = None


@_wrap_store_errors
def get_user_preferences(
    user_id: str,
    store: StateStore | None = None,
) -> UserPreferencesResponse:
    """계정의 취향을 조회한다.

    아직 고른 적이 없으면 빈 목록에 updated_at=None으로 답한다. 404가 아닌
    이유는 "취향을 안 고른 계정"이 정상 상태이기 때문이다 — 화면은 어느 쪽이든
    빈 선택으로 그리면 된다.
    """
    store = store or get_store()

    stored = store.get_preferences(user_id)
    if stored is None:
        return UserPreferencesResponse()
    return UserPreferencesResponse(items=list(stored.items), updated_at=stored.updated_at)


@_wrap_store_errors
def replace_user_preferences(
    user_id: str,
    items: list[UserPreference],
    store: StateStore | None = None,
) -> UserPreferencesResponse:
    """계정의 취향을 통째로 바꾼다.

    빈 목록도 정상적인 저장이다(전부 해제한 경우). 소유권 검증이 따로 없는
    이유는 키가 곧 신원이기 때문이다 — 라우트가 RequiredPrincipal로 받은
    user_id만 여기 들어오므로 남의 취향에 닿을 경로가 없다. session_id를
    받아 state.user_id와 대조해야 하는 세션 API들과 다른 점이다.
    """
    store = store or get_store()

    stored = preferences_module.replace(store, user_id, items)
    return UserPreferencesResponse(items=list(stored.items), updated_at=stored.updated_at)
