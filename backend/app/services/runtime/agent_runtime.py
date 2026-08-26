"""Agent Runtime — A가 B/C/D 호출 순서를 조정하는 상위 오케스트레이션 계층.

역할: 사용자 발화 하나를 받아 LLMOutput 생성 → B(State) 병합 → C(Tool)/D(Recommendation)
호출(부가 흐름에서만) → B(State)에 노출 결과 기록까지 전체 흐름을 조정한다. C/D는 서로
직접 부르지 않고 항상 A(이 모듈)를 거쳐서만 결과를 주고받는다.
입력: AgentRequest(user_input + session_id + device_location).
출력: AgentResponse(LLMOutput + 병합된 State + 추천 결과).
호출 시점: 아직 전용 HTTP 라우트는 없다. A–C 스키마, A–D RecommendationProvider
계약([TECH-02]) 모두 확정되어 run_agent()가 Real Provider를 주입한다.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import timedelta
from typing import TypeVar

from app.agent_context.schemas import PlaceCandidate, RecommendationContext
from app.auth.principal import Principal
from app.config import settings
from app.domain.ranking_origin import resolve_ranking_origin
from app.domain.scoring import SCORING_VERSION
from app.domain.travel_route import (
    GeoCoordinate,
    RouteDestination,
    RouteStatus,
    TravelMode,
    TravelRoute,
)
from app.errors import AppError
from app.geo import haversine_km
from app.observability.api_usage import create_external_client
from app.observability.langfuse_tracing import (
    observe_step,
    record_score,
    trace_attributes,
)
from app.place_search_policy import MAX_PLACE_SEARCH_RADIUS_KM, WALKING_SPEED_KM_PER_MINUTE
from app.prompts.registry import turn_prompt_version
from app.providers.protocols import LLMProvider
from app.schedule.planner import plan_partial_schedule, plan_schedule
from app.schedule.schemas import SchedulePartialFillRequest, SchedulePlanningRequest
from app.schemas import (
    AgentRequest,
    AgentResponse,
    ClarificationOption,
    ClarificationPayload,
    CompareCriteria,
    ComparisonItem,
    ComparisonResult,
    ConcentrationIntent,
    GeneralPayload,
    GeneralTopic,
    Intent,
    InterpretRequest,
    LLMOutput,
    ModifyPayload,
    ModifyType,
    OutputStatus,
    PlaceType,
    QuestionType,
    RecommendationItem,
    RecommendationResponse,
    RecommendPayload,
    ScheduleItem,
    ToolExecutionDebug,
    TravelOrigin,
    UserConditions,
)
from app.service_area import supported_district_label
from app.services.interpret.orchestrator import build_interpretation
from app.services.interpret.session_orchestrator import ensure_current_context
from app.services.interpret.state_transform import to_user_conditions, transform
from app.services.recommendation_pipeline import PreparedRecommendationResult
from app.services.runtime.compare_transform import (
    to_compare_context_request,
    to_comparison_result,
)
from app.services.runtime.context_transform import to_agent_context_request
from app.services.runtime.enrichment_transform import to_candidate_enrichment_request
from app.services.runtime.graph import (
    PipelineDeps,
    concentration_source_rows,
    run_early_return_graph,
    run_recommend_pipeline_graph,
)
from app.services.runtime.info_context_schemas import InfoContextResponse, PlaceInfoResult
from app.services.runtime.info_context_transform import to_info_context_request
from app.services.runtime.info_response_transform import to_info_place_card
from app.services.runtime.llm_execution import (
    consumed_tokens,
    get_llm_execution_metadata,
    reset_llm_execution_metadata,
)
from app.services.runtime.protocols import (
    EnrichmentProvider,
    RecommendationProvider,
    StagedRecommendationProvider,
    ToolProvider,
    TravelRouteToolProvider,
)
from app.services.runtime.recommendation_transform import to_travel_mode
from app.services.runtime.response_composer import (
    compose_chat_message,
    compose_compare_message,
    tool_clarification_message,
)
from app.services.runtime.stream_events import (
    SCHEDULING_HEARTBEAT_INTERVAL_SECONDS,
    SCHEDULING_HEARTBEAT_MESSAGES,
    StreamEventSink,
    await_with_heartbeat,
    begin_streamed_message,
    emit_progress,
    emit_stream_event,
)
from app.services.runtime.tool_debug import (
    build_candidate_enrichment_execution_debug,
    build_compare_execution_debug,
    build_info_concentration_execution_debug,
    build_tool_execution_debug,
)
from app.state.schema import now_kst
from app.state.service import (
    RecommendedPlace,
    RecordClosedExclusionsRequest,
    RecordRecommendationRequest,
    RecordTraceRequest,
    SessionContextResponse,
    SetIgnoreOperatingHoursRequest,
    SetLastIntentRequest,
    SetPendingClarificationRequest,
    StateApplyResponse,
    UpdateApiContextRequest,
    apply,
    record_closed_exclusions,
    record_recommendation,
    record_trace,
    set_ignore_operating_hours_until,
    set_last_intent,
    set_pending_clarification,
    update_api_context,
)
from app.state.session import new_trace_id
from app.state.store import StateStore
from app.tools.travel_route import TravelRouteQuery

logger = logging.getLogger(__name__)

# SSE 발신 헬퍼는 stream_events.py로 옮겼다 — 라우팅 그래프(graph/)도 같은 sink를
# 써야 하는데, 이 모듈이 그래프를 import하므로 반대 방향은 순환이 되기 때문이다.
# 기존 호출부를 그대로 두려고 옮긴 이름을 여기서 비공개 별칭으로 받는다.
_emit_stream_event = emit_stream_event
_emit_progress = emit_progress
_begin_streamed_message = begin_streamed_message
_await_with_heartbeat = await_with_heartbeat
_SCHEDULING_HEARTBEAT_MESSAGES = SCHEDULING_HEARTBEAT_MESSAGES
_SCHEDULING_HEARTBEAT_INTERVAL_SECONDS = SCHEDULING_HEARTBEAT_INTERVAL_SECONDS

T = TypeVar("T")

_INFO_WALKING_TIME_MARKERS = (
    "가는데얼마나걸",
    "걷는데얼마나걸",
    "걸어서얼마나",
    "도보로얼마나",
    "도보시간",
    "도보이동",
)


def _llm_clarification_code(llm_output: LLMOutput) -> str | None:
    """LLM 단계 되묻기를 단일 코드로 정규화한다.

    LLM은 missing_fields/ambiguous_fields 목록으로, C는 location_required 같은 단일
    코드로 되묻는다. B에는 한 가지 표현만 저장하므로 여기서 맞춘다 — 값 자체는
    "무엇을 되물었는지" 기록용이고, 다음 턴의 판단은 "값이 있는지"만 본다.
    """
    clarification = llm_output.clarification
    if clarification is None:
        return "clarification_required"
    # 오케스트레이터가 분류 이전에 선제 차단으로 만든 되묻기(케이스 4/5)는
    # missing_fields/ambiguous_fields가 비어 있어 아래 유도로는 코드를 못 만든다 —
    # 이 값이 있으면 최우선으로 쓴다.
    if clarification.code is not None:
        return clarification.code
    if clarification.missing_fields:
        return f"missing:{clarification.missing_fields[0].field}"
    if clarification.ambiguous_fields:
        return f"ambiguous:{clarification.ambiguous_fields[0].field}"
    return "clarification_required"


def _record_trace_safely(
    *,
    session_id: str,
    run_id: str,
    step: str,
    latency_ms: int,
    error_type: str | None = None,
    prompt_version: str | None = None,
    scoring_version: str | None = None,
    token_usage: int | None = None,
    store: StateStore | None,
) -> None:
    """실행 단계 1건을 B에 기록한다. (llmops-trace-contract-v1.md AF-12, B-07)

    variant_id는 아직 값을 안 줘서 None으로 둔다. 기록 실패가 사용자 응답까지
    막으면 안 되므로 예외를 여기서 흡수한다.

    token_usage는 계약상 LLM 단계에만 해당하는 값이라 호출부가 그 단계에서만
    넘긴다 — 모든 단계에 누적 합계를 넣으면 단계별 토큰인 것처럼 읽힌다.
    """
    try:
        record_trace(
            RecordTraceRequest(
                session_id=session_id,
                run_id=run_id,
                step=step,
                latency_ms=latency_ms,
                error_type=error_type,
                prompt_version=prompt_version,
                scoring_version=scoring_version,
                token_usage=token_usage,
            ),
            store=store,
        )
    except Exception:
        logger.warning(
            "Trace 기록 실패(응답 흐름에는 영향 없음): step=%s session_id=%s run_id=%s",
            step,
            session_id,
            run_id,
            exc_info=True,
        )


def _remember_clarification(session_id: str, code: str | None, store: StateStore | None) -> None:
    """이번 턴이 되묻기로 끝났음을 B에 남긴다(추천까지 갔으면 호출하지 않는다).

    다음 턴의 state_transform이 이 값을 보고 조건 초기화를 건너뛴다.
    """
    set_pending_clarification(
        SetPendingClarificationRequest(session_id=session_id, code=code), store=store
    )


# no_data_closed 되묻기의 "운영 중이 아닌 곳도 볼게요"를 한 번 선택하면 이 시간
# 동안은 매 턴 다시 묻지 않는다(실사용 피드백, 2026-08-13).
_IGNORE_OPERATING_HOURS_TTL = timedelta(hours=1)


def _remember_ignore_operating_hours(session_id: str, store: StateStore | None) -> None:
    """"운영 중이 아닌 곳도 볼게요" 선택을 TTL 동안 B에 남긴다."""
    set_ignore_operating_hours_until(
        SetIgnoreOperatingHoursRequest(
            session_id=session_id, until=now_kst() + _IGNORE_OPERATING_HOURS_TTL
        ),
        store=store,
    )


# SCHEDULE 완료 직후 CHANGE_CONDITION MODIFY가 "일정 재조정"인지 "그냥 추천"인지 글자로는
# 구분 안 되는 경우를 감지한다(docs/design/clarification-options.md 5절). 일정 키워드가
# 전혀 없는데 추천체 어미가 있으면 재조정이라 단정할 근거가 없다.
_SCHEDULE_CONTINUATION_MARKERS = ("일정", "코스", "루트", "편성", "순서", "스케줄")
_RECOMMEND_STYLE_MARKERS = ("추천", "보여줘", "알려줘", "찾아줘", "찾아봐")


def _is_ambiguous_schedule_or_recommend(user_input: str) -> bool:
    return not any(marker in user_input for marker in _SCHEDULE_CONTINUATION_MARKERS) and any(
        marker in user_input for marker in _RECOMMEND_STYLE_MARKERS
    )


# PlaceTag는 값 자체가 한국어라 그대로 쓰면 되지만, PlaceType은 영문 키라 되묻기
# 문구용 한국어 라벨이 따로 필요하다.
_PLACE_TYPE_LABELS: dict[PlaceType, str] = {
    PlaceType.ATTRACTION: "관광지",
    PlaceType.CULTURAL_FACILITY: "문화시설",
    PlaceType.FESTIVAL: "축제",
    PlaceType.LEISURE: "레저",
    PlaceType.SHOPPING: "쇼핑",
    PlaceType.RESTAURANT: "음식점",
}


def _extracted_category_label(modify: ModifyPayload) -> str | None:
    """되묻기 문구/버튼에 넣을 카테고리 라벨. place_tags가 있으면 그대로 쓰고(이미
    한국어 값), 없으면 place_types 라벨, 둘 다 없으면 None(범용 "장소"로 대체)."""
    changes = modify.condition_changes
    if changes is None:
        return None
    if changes.place_tags:
        return changes.place_tags[0].value
    if changes.place_types:
        return _PLACE_TYPE_LABELS.get(changes.place_types[0])
    return None


# 되묻기 버튼 클릭(clarification_choice) 해소 테이블(케이스 1). pending_clarification
# 코드별로 choice_id → 강제할 Intent를 매핑한다. LLM 호출이 없는 순수 dict 매핑이라
# 단위 테스트하기 쉽고, 신규 고정-선택지 코드는 케이스 추가 시 여기에만 등록하면 된다.
_SCHEDULE06_RESOLUTIONS: dict[str, Intent] = {
    "schedule_continue": Intent.SCHEDULE,
    "recommend_only": Intent.RECOMMEND,
}

# location_required 되묻기 버튼(A2). 서비스 지역이 종로구 한정이라(D-044) 대표 스팟을
# 고정 목록으로 제공한다 — docs/design/clarification-options.md 7절.
_LOCATION_REQUIRED_QUICK_PICKS = ("경복궁", "인사동", "광화문", "북촌")

# location_required는 last_intent를 그대로 복원해 재사용한다. RECOMMEND/SCHEDULE는
# 둘 다 llm_output.recommend(RecommendPayload)로 조건을 나르므로 이 지름길로 풀 수
# 있다. MODIFY는 llm_output.modify(ModifyPayload)가 필요해 이 지름길에서 뺐다 — 그런
# 경우는 None을 반환해 평소 경로로 폴백하면, "지명 단독 답변 → MODIFY" 규칙(D-053)이
# 이미 같은 결과를 만들어준다.
_LOCATION_REQUIRED_RESOLVABLE_INTENTS = frozenset({Intent.RECOMMEND.value, Intent.SCHEDULE.value})
# no_data_closed는 SCHEDULE 이전(1차 Scoring 직후)에만 발생하므로 SCHEDULE은 대상이
# 아니다 — RECOMMEND/MODIFY만 재조회 대상이 될 수 있다.
_NO_DATA_CLOSED_RESOLVABLE_INTENTS = frozenset(
    {Intent.RECOMMEND.value, Intent.MODIFY.value, Intent.SCHEDULE.value}
)

# compare_single_shown 되묻기 버튼(PR 3, 케이스 3). "다른 곳도 보여주세요"는 REJECT_ALL로
# 재조회하는 이미 검증된 경로를 그대로 탄다.
_COMPARE_SINGLE_SHOWN_SHOW_MORE = "show_more"
_COMPARE_SINGLE_SHOWN_KEEP_CURRENT = "keep_current"
_COMPARE_SINGLE_SHOWN_KEEP_MESSAGE = "네, 좋은 여행 되세요!"

# 케이스 5(양쪽 변형)의 "새로 시작할게요" 공통 문구. 조건은 비웠지만 Tool을 바로
# 부르지 않는다 — GPS가 있으면 그것만으로 추천이 조용히 나가버려(실사용 재현,
# 2026-08-13), "새로 시작"이라는 사용자 의도(새 조건을 직접 말하고 싶다)와 어긋난다.
_FULL_RESET_TERMINAL_MESSAGE = "새로운 목적지를 입력하거나 원하시는 조건을 알려주세요!"

# no_data_closed 되묻기(실사용 피드백, 2026-08-13: "운영시간 때문이면... 운영중이
# 아닌 곳도 확인하시겠어요?"). D가 결과 0건의 유일한 이유로 폐점 후보 제외를
# 지목했을 때만(RecommendationResponse.excluded_all_closed) 이 문구를 쓴다 —
# 카테고리/거리 등 다른 이유면 기존 _NO_DATA_MESSAGE(response_composer.py)를 그대로 쓴다.
_NO_DATA_CLOSED_MESSAGE = (
    "지금 운영 중인 곳이 없어 검색이 어려워요. 운영 중이 아닌 곳도 확인하시겠어요?"
)
_NO_DATA_CLOSED_SHOW_CLOSED = "show_closed"


async def _respond_no_data_closed(
    llm_output: LLMOutput,
    state_response: StateApplyResponse,
    *,
    store: StateStore | None,
    llm: LLMProvider,
    tool_execution: object,
    tool_executions: object,
) -> AgentResponse:
    """"운영 중이 아닌 곳도 볼게요" 되묻기 응답을 조립한다.

    RECOMMEND/MODIFY 경로와 SCHEDULE 경로 둘 다에서 쓴다 — SCHEDULE도 원인이
    "폐점 후보뿐"이면 "후보가 부족하니 지역/카테고리를 바꿔달라"는 일반 되묻기
    대신 이 되묻기를 먼저 띄워야 한다. 그렇지 않으면 실제 원인(운영시간)과
    무관한 지역/카테고리 변경만 계속 유도하게 되어 무한 되묻기로 이어진다
    (실사용 재현, 2026-08-13 — "경복궁 반나절 코스" 심야 요청).
    """
    clarified = llm_output.model_copy(
        update={
            "status": OutputStatus.NEEDS_CLARIFICATION,
            "clarification": ClarificationPayload(
                code="no_data_closed",
                message=_NO_DATA_CLOSED_MESSAGE,
                options=[
                    ClarificationOption(
                        id=_NO_DATA_CLOSED_SHOW_CLOSED,
                        label="운영 중이 아닌 곳도 볼게요",
                        resolved_intent=llm_output.intent,
                    ),
                ],
            ),
        }
    )
    _remember_clarification(state_response.session_id, "no_data_closed", store)
    message = await compose_chat_message(clarified, llm=llm)
    return AgentResponse(
        llm_output=clarified,
        state=state_response,
        recommendations=None,
        message=message,
        llm_execution=get_llm_execution_metadata(),
        tool_execution=tool_execution,
        tool_executions=tool_executions,
    )


# no_data_empty/no_data_exhausted 되묻기(원인1+3/원인2, 실사용 피드백 후속 조사,
# 2026-08-13). C가 장소 검색 자체에서 0건(status="no_data")을 돌려줄 때, 그 원인이
# "카테고리에 맞는 곳이 없음"(원인1)과 "반경이 좁음"(원인3)은 신호가 동일해
# 구분할 수 없지만(nearby_place_details.py의 `if not selected:`가 raw candidates
# 자체가 없을 때도 NO_DATA를 반환), "이전 노출/거절로 다 소진됨"(원인2)은
# `places.provider_metadata`의 원본 TourAPI 상태로 구분 가능하다 — raw candidates가
# 있었는데 excluded_place_ids로 걸러졌다면 provider_metadata.status는 "success"로
# 남는다(agent_context/mappers.py::map_places_context가 원본 metadata를 그대로 싣는다).
_NO_DATA_RESOLVABLE_INTENTS = _LOCATION_REQUIRED_RESOLVABLE_INTENTS | frozenset(
    {Intent.MODIFY.value}
)

# 두 no_data 되묻기가 공유하는 선택지 id. "widen_radius"/"widen_category"는
# 원인이 뭐든 "후보 풀을 넓힌다"는 같은 처방이라 두 코드에서 동일한 id로 쓴다.
_WIDEN_RADIUS = "widen_radius"
_WIDEN_CATEGORY = "widen_category"
_DIFFERENT_AREA = "different_area"
_IGNORE_WEATHER = "ignore_weather"
_CUSTOM_CONDITIONS = "custom_conditions"

# max_travel_time을 이 값으로 올리면(도보 기준) 검색 반경이 상한(MAX_PLACE_SEARCH_
# RADIUS_KM)까지 커진다(recommendation_transform.to_search_radius_km). 도보가 가장
# 느려 상한에 가장 늦게 닿으므로, 이 값이면 어떤 교통수단이든 상한에 닿는다.
_WIDEN_RADIUS_MAX_TRAVEL_TIME = math.ceil(MAX_PLACE_SEARCH_RADIUS_KM / WALKING_SPEED_KM_PER_MINUTE)

_NO_DATA_EMPTY_MESSAGE = (
    f"말씀하신 조건에 맞는 곳을 {supported_district_label()} 안에서 찾지 못했어요. "
    "검색 범위를 넓혀볼까요, 아니면 다른 종류의 장소도 함께 볼까요?"
)
_NO_DATA_EMPTY_OPTIONS: tuple[tuple[str, str], ...] = (
    (_WIDEN_RADIUS, "검색 범위 넓히기"),
    (_WIDEN_CATEGORY, "다른 종류도 보기"),
)

_NO_DATA_EXHAUSTED_MESSAGE = (
    "지금까지 보여드린 곳 말고는 조건에 맞는 곳을 다 보여드렸어요. 조건을 좀 바꿔볼까요?"
)
_NO_DATA_EXHAUSTED_OPTIONS: tuple[tuple[str, str], ...] = (
    (_WIDEN_CATEGORY, "다른 종류의 장소도 보기"),
    (_WIDEN_RADIUS, "검색 범위 넓혀서 보기"),
    (_DIFFERENT_AREA, "다른 지역에서 찾기"),
    (_IGNORE_WEATHER, "날씨 상관없이 보기"),
    (_CUSTOM_CONDITIONS, "새로운 조건 직접 말할게요"),
)
_NO_DATA_EXHAUSTED_CUSTOM_MESSAGE = "새로운 조건을 알려주세요!"


@dataclass(frozen=True)
class _ClarificationResolution:
    """되묻기 버튼 클릭의 해소 결과.

    llm_output은 항상 채워지며(감사 표시·상태 병합용), terminal_message가 있으면
    Tool/D 호출 없이 이 문구로 바로 응답을 끝낸다 — 조회할 것이 없는 확인성 선택지
    (예: "지금 장소가 마음에 들어요")에 쓴다.
    """

    llm_output: LLMOutput
    terminal_message: str | None = None
    # True면 D 재조회 시 폐점 후보도 제외하지 않는다 — no_data_closed 되묻기의
    # "운영중이 아닌 곳도 볼게요" 선택지에서만 켠다.
    ignore_operating_hours: bool = False
    # True면 조건 병합(MODIFY/CHANGE_CONDITION)이 끝난 뒤 intent 라벨을 SCHEDULE로
    # 바꿔 아래 6)~8) 단계가 일정 편성 분기를 타게 한다 — schedule_no_candidates
    # 되묻기의 "다른 지역/종류로 찾기" 선택지에서만 켠다. 조건을 실제로 지우려면
    # MODIFY/CHANGE_CONDITION 경로(_clear_conditions_llm_output)가 필요한데(RECOMMEND/
    # SCHEDULE 경로는 빈 값을 "언급 안 함"으로 봐서 안 지워진다), SCHEDULE-06의
    # pending_clarification is None 게이트는 되묻기 해소 turn엔 안 맞아 자동으로
    # relabel되지 않는다 — 그래서 여기서 명시적으로 신호를 준다.
    force_schedule: bool = False


# no_data_empty/no_data_exhausted의 "다른 종류도 보기"/"다른 지역에서 찾기"/
# "날씨 상관없이 보기"가 공유하는 값 — 조건을 명시적으로 지울 때 각 필드에 넣을
# "없음"에 해당하는 값이다.
_CLEARED_CONDITION_VALUES: dict[str, object] = {
    "place_types": [],
    "place_tags": [],
    "search_center": None,
    "current_location": None,
    "weather_intent": None,
}

# SCHEDULE 실패(후보 부족) 시 되묻기 버튼 ID 및 텍스트.
_SCHEDULE_RELAX_AREA = "schedule_relax_area"
_SCHEDULE_RELAX_CATEGORY = "schedule_relax_category"
_SCHEDULE_NO_CANDIDATES_MESSAGE = (
    "조건에 맞는 곳을 충분히 찾지 못해 일정을 만들지 못했어요. "
    "다른 지역이나 다른 종류의 장소로 다시 요청해볼까요?"
)
_SCHEDULE_NO_CANDIDATES_OPTIONS = (
    (_SCHEDULE_RELAX_AREA, "다른 지역에서 찾기"),
    (_SCHEDULE_RELAX_CATEGORY, "다른 종류의 장소도 포함해서 찾기"),
)


def _clear_conditions_llm_output(fields: tuple[str, ...]) -> LLMOutput:
    """지정한 필드만 명시적으로 지우는 MODIFY/CHANGE_CONDITION을 만든다.

    RECOMMEND 경로(RecommendPayload)는 값이 없는 필드를 "언급 안 함"으로 보고
    기존 값을 그대로 유지한다(state_transform._full_replace_operations) — 그래서
    필드를 실제로 비우려면 changed_fields로 Remove를 명시하는 MODIFY 경로가
    필요하다(state_transform._changed_field_operations).
    """
    return LLMOutput(
        intent=Intent.MODIFY,
        status=OutputStatus.COMPLETE,
        modify=ModifyPayload(
            modify_type=ModifyType.CHANGE_CONDITION,
            condition_changes=UserConditions(
                **{field: _CLEARED_CONDITION_VALUES[field] for field in fields}
            ),
            changed_fields=list(fields),
        ),
    )


def _resolve_clarification_choice(
    *, choice_id: str, session_context: SessionContextResponse
) -> _ClarificationResolution | None:
    """되묻기 버튼 클릭을 결정적으로 해소한다.

    이미 세션에 병합된 조건(session_context.user_conditions)을 그대로 재사용해
    classify_intent()/extract_*_conditions() 호출을 건너뛴다. pending_clarification
    코드/choice_id가 등록된 조합과 안 맞으면(새로고침 후 오래된 버튼 클릭 등) None을
    반환해 평소 build_interpretation() 경로로 폴백하게 한다 — 절대 죽지 않는다.
    """
    code = session_context.pending_clarification
    if code is None:
        return None
    conditions = to_user_conditions(session_context.user_conditions)

    if code == "schedule06_ambiguous_recommend":
        resolved_intent = _SCHEDULE06_RESOLUTIONS.get(choice_id)
        if resolved_intent is None:
            return None
        return _ClarificationResolution(
            llm_output=LLMOutput(
                intent=resolved_intent,
                status=OutputStatus.COMPLETE,
                recommend=RecommendPayload(conditions=conditions),
            )
        )

    if code == "location_required":
        if choice_id not in _LOCATION_REQUIRED_QUICK_PICKS:
            return None
        if session_context.last_intent not in _LOCATION_REQUIRED_RESOLVABLE_INTENTS:
            return None
        conditions = conditions.model_copy(update={"search_center": choice_id})
        return _ClarificationResolution(
            llm_output=LLMOutput(
                intent=Intent(session_context.last_intent),
                status=OutputStatus.COMPLETE,
                recommend=RecommendPayload(conditions=conditions),
            )
        )

    if code == "location_ambiguous":
        # location_required와 달리 choice_id가 고정 목록이 아니라 Tool이 실제로
        # 찾아낸 후보 이름이다(resolve_location.py) — 값 자체를 검증할 기준이 없어
        # 비어있지만 않으면 그대로 search_center로 쓴다. MODIFY는 location_required와
        # 같은 이유로 이 지름길에서 빠진다.
        if (
            not choice_id
            or session_context.last_intent not in _LOCATION_REQUIRED_RESOLVABLE_INTENTS
        ):
            return None
        conditions = conditions.model_copy(update={"search_center": choice_id})
        return _ClarificationResolution(
            llm_output=LLMOutput(
                intent=Intent(session_context.last_intent),
                status=OutputStatus.COMPLETE,
                recommend=RecommendPayload(conditions=conditions),
            )
        )

    if code == "no_data_closed":
        # 폐점 후보뿐이라 결과가 0건이었던 턴(no_data_closed, D-062류)의 "운영중이
        # 아닌 곳도 볼게요" 선택지. 조건은 그대로 재사용하고 ignore_operating_hours만
        # 켜서 같은 검색을 다시 돌린다 — D가 이번엔 폐점 후보도 채점에 포함한다.
        if (
            choice_id != _NO_DATA_CLOSED_SHOW_CLOSED
            or session_context.last_intent not in _NO_DATA_CLOSED_RESOLVABLE_INTENTS
        ):
            return None
        return _ClarificationResolution(
            llm_output=LLMOutput(
                intent=Intent(session_context.last_intent),
                status=OutputStatus.COMPLETE,
                recommend=RecommendPayload(conditions=conditions),
            ),
            ignore_operating_hours=True,
        )

    if code == "no_data_empty":
        # 원인1+3(TourAPI 자체가 0건). 두 선택지 다 조건을 넓혀 같은 검색을
        # 재조회한다 — 원인을 구분 못 하므로 "후보 풀을 넓힌다"는 같은 처방을 쓴다.
        if session_context.last_intent not in _NO_DATA_RESOLVABLE_INTENTS:
            return None
        if choice_id == _WIDEN_RADIUS:
            updated = conditions.model_copy(
                update={"max_travel_time": _WIDEN_RADIUS_MAX_TRAVEL_TIME}
            )
            return _ClarificationResolution(
                llm_output=LLMOutput(
                    intent=Intent(session_context.last_intent),
                    status=OutputStatus.COMPLETE,
                    recommend=RecommendPayload(conditions=updated),
                )
            )
        if choice_id == _WIDEN_CATEGORY:
            return _ClarificationResolution(
                llm_output=_clear_conditions_llm_output(("place_types", "place_tags"))
            )
        return None

    if code == "no_data_exhausted":
        # 원인2(이전 노출/거절로 소진). "제외 이력을 다시 보여달라"는 선택지는
        # B(세션 상태) 리셋이 필요해 빼고, 조건을 바꿔 재조회하는 선택지들과
        # Tool 호출 없이 자유 입력을 유도하는 선택지만 둔다.
        if session_context.last_intent not in _NO_DATA_RESOLVABLE_INTENTS:
            return None
        if choice_id == _CUSTOM_CONDITIONS:
            return _ClarificationResolution(
                llm_output=LLMOutput(
                    intent=Intent.GENERAL,
                    status=OutputStatus.COMPLETE,
                    general=GeneralPayload(topic=GeneralTopic.TRAVEL_TIP, original_question=""),
                ),
                terminal_message=_NO_DATA_EXHAUSTED_CUSTOM_MESSAGE,
            )
        if choice_id == _WIDEN_CATEGORY:
            return _ClarificationResolution(
                llm_output=_clear_conditions_llm_output(("place_types", "place_tags"))
            )
        if choice_id == _IGNORE_WEATHER:
            return _ClarificationResolution(
                llm_output=_clear_conditions_llm_output(("weather_intent",))
            )
        if choice_id == _DIFFERENT_AREA:
            return _ClarificationResolution(
                llm_output=_clear_conditions_llm_output(("search_center", "current_location"))
            )
        if choice_id == _WIDEN_RADIUS:
            updated = conditions.model_copy(
                update={"max_travel_time": _WIDEN_RADIUS_MAX_TRAVEL_TIME}
            )
            return _ClarificationResolution(
                llm_output=LLMOutput(
                    intent=Intent(session_context.last_intent),
                    status=OutputStatus.COMPLETE,
                    recommend=RecommendPayload(conditions=updated),
                )
            )
        return None

    if code == "schedule_no_candidates":
        # SCHEDULE 실패(후보 부족) 시 조건을 완화해 다시 시도한다.
        if session_context.last_intent not in _NO_DATA_RESOLVABLE_INTENTS:
            return None
        if choice_id == _SCHEDULE_RELAX_AREA:
            return _ClarificationResolution(
                llm_output=_clear_conditions_llm_output(("search_center", "current_location")),
                force_schedule=True,
            )
        if choice_id == _SCHEDULE_RELAX_CATEGORY:
            return _ClarificationResolution(
                llm_output=_clear_conditions_llm_output(("place_types", "place_tags")),
                force_schedule=True,
            )
        return None

    if code == "compare_single_shown":
        if choice_id == _COMPARE_SINGLE_SHOWN_SHOW_MORE:
            return _ClarificationResolution(
                llm_output=LLMOutput(
                    intent=Intent.MODIFY,
                    status=OutputStatus.COMPLETE,
                    modify=ModifyPayload(modify_type=ModifyType.REJECT_ALL),
                )
            )
        if choice_id == _COMPARE_SINGLE_SHOWN_KEEP_CURRENT:
            # Tool/D를 부를 것이 없는 확인성 선택지 — 고정 문구로 바로 끝낸다.
            # GeneralPayload는 감사 표시용으로만 채우고(compose_chat_message는 부르지
            # 않으므로 LLM 호출 없음), topic 값 자체는 의미가 없다.
            return _ClarificationResolution(
                llm_output=LLMOutput(
                    intent=Intent.GENERAL,
                    status=OutputStatus.COMPLETE,
                    general=GeneralPayload(topic=GeneralTopic.TRAVEL_TIP, original_question=""),
                ),
                terminal_message=_COMPARE_SINGLE_SHOWN_KEEP_MESSAGE,
            )
        return None

    if code == "schedule_bare_restart":
        # 케이스 4(PR 4). 두 옵션 다 intent=SCHEDULE로 다시 들어간다 — "restart"는
        # 버튼 label("네, 처음부터 다시 잡을게요")이 _RESET_SCOPE_PHRASES와 일치해
        # state_transform.transform()이 조건을 soft reset으로 비우고, 그 결과
        # search_center가 다시 비어 location_required가 자연스럽게 재발생한다(PR2
        # 종로구 대표 스팟 버튼으로 이어짐). "keep_asking"은 병합된 조건을 그대로
        # 재사용해 같은 location_required를 다시 띄운다 — 새 상태 조작 코드가
        # 필요 없다.
        if choice_id == "restart":
            return _ClarificationResolution(
                llm_output=LLMOutput(
                    intent=Intent.SCHEDULE,
                    status=OutputStatus.COMPLETE,
                    recommend=RecommendPayload(conditions=UserConditions()),
                )
            )
        if choice_id == "keep_asking":
            return _ClarificationResolution(
                llm_output=LLMOutput(
                    intent=Intent.SCHEDULE,
                    status=OutputStatus.COMPLETE,
                    recommend=RecommendPayload(conditions=conditions),
                )
            )
        return None

    if code == "bare_restart_active":
        # 케이스 5(PR 4). "keep_context"는 REJECT_ALL로 조건은 그대로 두고 다시
        # 조회한다(버튼 label에 재시작 문구가 없어 reset이 안 걸린다). "full_reset"은
        # 빈 조건 + label("새로 시작할게요")이 _RESET_SCOPE_PHRASES와 일치해 soft
        # reset으로 조건이 전부 비워진다 — 조회 자체는 터미널 문구로 대신한다(아래
        # _FULL_RESET_TERMINAL_MESSAGE 참고, GPS만으로 조용히 추천이 나가는 걸 막음).
        if choice_id == "keep_context":
            return _ClarificationResolution(
                llm_output=LLMOutput(
                    intent=Intent.MODIFY,
                    status=OutputStatus.COMPLETE,
                    modify=ModifyPayload(modify_type=ModifyType.REJECT_ALL),
                )
            )
        if choice_id == "full_reset":
            return _ClarificationResolution(
                llm_output=LLMOutput(
                    intent=Intent.RECOMMEND,
                    status=OutputStatus.COMPLETE,
                    recommend=RecommendPayload(conditions=UserConditions()),
                ),
                terminal_message=_FULL_RESET_TERMINAL_MESSAGE,
            )
        return None

    if code == "schedule_bare_restart_completed":
        # 케이스 5의 SCHEDULE 버전. "retry_schedule"은 조건을 그대로 두고 SCHEDULE로
        # 재편성한다(REJECT_ALL이 아니다 — SCHEDULE 결과에는 안 맞는 동작이라서다).
        # "full_reset"은 케이스 5와 동일하게 빈 조건 + 터미널 문구로 끝낸다.
        if choice_id == "retry_schedule":
            return _ClarificationResolution(
                llm_output=LLMOutput(
                    intent=Intent.SCHEDULE,
                    status=OutputStatus.COMPLETE,
                    recommend=RecommendPayload(conditions=conditions),
                )
            )
        if choice_id == "full_reset":
            return _ClarificationResolution(
                llm_output=LLMOutput(
                    intent=Intent.RECOMMEND,
                    status=OutputStatus.COMPLETE,
                    recommend=RecommendPayload(conditions=UserConditions()),
                ),
                terminal_message=_FULL_RESET_TERMINAL_MESSAGE,
            )
        return None

    return None


# "OO 기준으로 다시 보기" 비차단형 전환(D-071, TravelOriginToggle)이 결정적으로 재실행할
# 수 있는 Intent. 직전 답변이 RecommendPayload로 조건을 나르는 두 Intent만 대상이다 —
# _resolve_clarification_choice의 location_required와 같은 이유.
_TRAVEL_ORIGIN_OVERRIDE_RESOLVABLE_INTENTS = frozenset(
    {Intent.RECOMMEND.value, Intent.SCHEDULE.value}
)


def _resolve_travel_origin_override(
    *, override: TravelOrigin, session_context: SessionContextResponse
) -> _ClarificationResolution | None:
    """"OO 기준으로 다시 보기" 버튼 클릭을 결정적으로 해소한다.

    되묻기(_resolve_clarification_choice)와 달리 pending_clarification을 요구하지
    않는다 — 이 버튼은 완결된 답변 아래에 조건부로 붙는 비차단형 제안이라(D-071,
    TravelOriginToggle) 직전 턴이 되묻기로 끝났을 필요가 없다. 세션에 이미 병합된
    조건(session_context.user_conditions)을 그대로 재사용해 travel_origin만
    override로 덮어쓴다 — classify_intent()/extract_recommend_conditions() 호출
    없이 즉시 재실행한다.

    직전 턴이 RECOMMEND/SCHEDULE가 아니거나 아직 추천 결과가 없으면(새로고침 뒤
    오래된 버튼 클릭 등) None을 반환해 평소 build_interpretation() 경로로
    폴백한다 — 절대 죽지 않는다.
    """
    if session_context.last_intent not in _TRAVEL_ORIGIN_OVERRIDE_RESOLVABLE_INTENTS:
        return None
    if not session_context.has_recommendation:
        return None
    conditions = to_user_conditions(session_context.user_conditions).model_copy(
        update={"travel_origin": override}
    )
    return _ClarificationResolution(
        llm_output=LLMOutput(
            intent=Intent(session_context.last_intent),
            status=OutputStatus.COMPLETE,
            recommend=RecommendPayload(conditions=conditions),
        )
    )


# C 단계에서 Recommendation으로 못 넘어가는 status. needs_clarification은 조건 재질문(사용자
# 응답 필요), unsupported/unavailable은 그 자체로 안내만 하고 끝나는 상태다(계약 문서 §5.4).
# no_data도 후보가 없어 D에 넘길 것이 없다 — 빈 후보로 Scoring을 돌려도 결과는 같으므로
# 호출하지 않고, 대신 조건을 바꿔볼지 사용자에게 되묻는다(int-03-modify.md §11).
_TOOL_TERMINAL_STATUSES = frozenset(
    {"needs_clarification", "no_data", "unsupported", "unavailable"}
)

# concentration_intent가 AVOID/SEEK일 때만 혼잡도 보강 조회 대상이 되는 값.
_CONCENTRATION_RANK_INTENTS = frozenset({ConcentrationIntent.AVOID, ConcentrationIntent.SEEK})

# 2차 Scoring(재순위)이 실제로 실행됐을 때만 적용하는 최종 노출 개수 — RECOMMEND/MODIFY
# 기본값. (기획 확정, 2026-08-02 — concentration-conditions.md §2.2.3 9단계.
# 재순위가 안 일어나면(D 미구현 등) 1차 결과를 그대로 쓰고 이 상수는 적용하지 않는다 —
# 기능이 실제로 동작하지 않는데 결과 개수만 줄이는 걸 피하기 위함이다.)
#
# (호출부가 final_limit을 항상 명시적으로 넘긴다. 생략했을 때의 기본값은
# settings에서 호출 시점에 읽는다 — 모듈 로드 시점에 굳히면 환경 설정 변경이나
# 테스트의 monkeypatch가 반영되지 않는다.)

# 하드 필터 통과 후보가 목표 개수보다 적을 때 C에 추가 후보를 요청하는 최대 횟수.
# 최초 조회는 포함하지 않으므로 전체 C 호출은 최대 3회다. 무한 반복과 외부 API
# 호출 폭증을 막기 위해 상수로 명시한다.
_MAX_CANDIDATE_REFILL_ATTEMPTS = 2
_CANDIDATE_POOL_TRUNCATED_WARNING = "candidate_pool_truncated"

# 보강 응답 전체가 이 상태면 2차 Scoring을 시도할 실익이 없다(재조회할 데이터가 없음).
_ENRICHMENT_TERMINAL_STATUSES = frozenset({"no_data", "unavailable"})


def _context_place_ids(context: RecommendationContext) -> list[str]:
    places = context.places
    return [place.place_id for place in (places.data or [])] if places is not None else []


def _merge_recommendation_context_places(
    first: RecommendationContext,
    additional: RecommendationContext,
) -> RecommendationContext:
    """후속 혼잡도·일정 계산이 쓸 수 있도록 C 후보 좌표를 ID 기준으로 합친다."""
    first_places = first.places
    additional_places = additional.places
    if first_places is None or additional_places is None:
        return first

    places_by_id = {place.place_id: place for place in (first_places.data or [])}
    for place in additional_places.data or []:
        places_by_id.setdefault(place.place_id, place)

    merged_places = first_places.model_copy(update={"data": list(places_by_id.values())})
    return first.model_copy(update={"places": merged_places})


def _candidate_pool_exhausted(context: RecommendationContext) -> bool:
    """이 반경에서 C가 더 줄 후보가 없는지 판정한다 — 참이면 보충 조회를 멈춘다.

    두 가지 신호를 본다.

    1. `candidate_pool_truncated` 경고 — 제외분이 많아 C가 상한(100행)까지 받고도
       요청한 개수를 못 채웠다는 뜻이다(nearby_place_details.py).
    2. 반환 후보 수가 `recommendation_candidate_limit`보다 적음 — C는
       min(가용 후보, limit)을 반환하므로, limit보다 적게 왔다면 반경 안을 이미
       다 긁은 것이다. 1번 경고는 100행을 넘겨 받았을 때만 서기 때문에, 반경에
       애초에 후보가 몇 개 없는 흔한 경우는 이 조건으로만 걸린다.
    """
    places = context.places
    if places is None:
        return True
    if any(warning.code == _CANDIDATE_POOL_TRUNCATED_WARNING for warning in places.warnings):
        return True
    return len(places.data or []) < settings.recommendation_candidate_limit


def _build_pairwise_distances_km(
    candidates: list[RecommendationItem],
    places: list[PlaceCandidate],
) -> dict[tuple[str, str], float]:
    """SCHEDULE 전용 — 후보 쌍 사이의 직선거리(km)를 계산한다.

    RecommendationItem에는 위경도가 없다(distance_km는 검색 중심 기준 거리라
    후보 간 거리를 못 구한다) — C가 준 PlaceCandidate(위경도 보유)를 place_id로
    매칭해 haversine_km()로 계산한다(docs/design/int-07-schedule.md 6.1절).
    C 응답에 없는 place_id(매칭 실패)는 조용히 건너뛴다 — pairwise_distances_km는
    LLM에 참고 근거로만 쓰이므로 일부 누락되어도 편성 자체가 막히지 않는다.
    """

    coordinates_by_place_id = {place.place_id: place.location for place in places}
    distances: dict[tuple[str, str], float] = {}
    for index, first in enumerate(candidates):
        first_location = coordinates_by_place_id.get(first.place_id)
        if first_location is None:
            continue
        for second in candidates[index + 1 :]:
            second_location = coordinates_by_place_id.get(second.place_id)
            if second_location is None:
                continue
            distances[(first.place_id, second.place_id)] = haversine_km(
                first_location.latitude,
                first_location.longitude,
                second_location.latitude,
                second_location.longitude,
            )
    return distances


def _valid_location(device_location: str | None) -> str | None:
    """'위도,경도' 형식이 아니면 None으로 낮춘다.

    잘못된 GPS 문자열이 파싱 예외로 대화를 중단시키지 않도록 한다.
    (interpret.py의 동일 함수와 중복 — interpret.py가 run_agent()로 교체되면 정리한다.)
    """
    if not device_location:
        return None
    parts = device_location.split(",")
    if len(parts) != 2:
        return None
    try:
        latitude = float(parts[0])
        longitude = float(parts[1])
    except ValueError:
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return device_location


async def _apply_concentration_rerank(
    agent_conditions: UserConditions,
    tool_context: RecommendationContext,
    first_pass: RecommendationResponse,
    *,
    recommendation_provider: RecommendationProvider,
    enrichment_provider: EnrichmentProvider,
    final_limit: int | None = None,
    execution_collector: list[ToolExecutionDebug] | None = None,
) -> RecommendationResponse:
    """concentration_intent가 AVOID/SEEK일 때만 1차 결과를 혼잡도로 보강·재순위한다
    (D-040 확정 — concentration-conditions.md §2.2.3, agent-runtime-contract.md
    §6.5.2). 그 외에는 first_pass를 그대로 반환한다.

    final_limit: 재순위 후 최종 노출 개수. 호출부가 1차 Scoring에 넘긴 limit과
    일치시켜야 한다. RECOMMEND/MODIFY는 recommendation_result_limit,
    SCHEDULE은 recommendation_candidate_limit 설정을 사용한다. None이면
    recommendation_result_limit을 이 시점에 읽는다.

    C 보강 조회(EnrichmentProvider.enrich())와 D의 2차 Scoring
    (rerank_with_concentration())은 모두 실제로 연결·구현 완료됐다(D-040). hasattr
    가드는 이제 "D가 아직 없을 수 있어서"가 아니라, 테스트 더블 등 이 메서드를
    갖추지 않은 구현체가 주입됐을 때도 안전하게 낮아지도록 남겨둔 방어 코드다.

    (2026-08-05, B-06 완료 — PR #78) B의 StateUserConditions에 concentration_intent
    필드가 등록되어, 이제 run_agent_flow() 전체 통합 테스트로도 이 분기가 실제
    트리거된다(test_concentration_intent_persisted_by_b_triggers_rerank 참고).
    run_agent_flow()에서 이 로직을 분리해둔 건 그 갭을 우회하기 위함이었지만,
    agent_conditions(A의 enum 타입 UserConditions)만으로 독립 단위 테스트가
    가능하다는 이점은 여전히 유효해 구조는 그대로 유지한다.
    """

    if agent_conditions.concentration_intent not in _CONCENTRATION_RANK_INTENTS:
        return first_pass

    has_places = tool_context.places and tool_context.places.data
    places = tool_context.places.data if has_places else []
    enrichment_request = to_candidate_enrichment_request(new_trace_id(), first_pass, places)
    if enrichment_request is None:
        return first_pass

    enrichment_started_at = time.monotonic()
    # **혼잡도 보강을 자기 span으로 뺀다.** 이 조회는 `scoring` 노드 안에서 일어나서,
    # 여기서 터져도 화면에는 "scoring이 죽었다"까지만 보였다. 2026-08-25에 SCHEDULE
    # 턴이 `보강 후보는 최대 5개` ValueError로 죽고 있던 걸 그렇게 놓쳤다 — 요청한
    # 후보 수가 span에 있었으면 원인이 바로 읽혔다.
    with observe_step("concentration_enrichment") as enrichment_step:
        enrichment_step.record(
            output={
                "requested": len(enrichment_request.candidates),
                "features": list(enrichment_request.features),
            }
        )
        enrichment_response = await enrichment_provider.enrich(enrichment_request)
        # **Audit용 요약을 span 안에서 만든다.** 밖에서 만들면 span이 이미 닫혀 있어
        # 후보별 출처를 붙일 자리가 없다. 지연은 위에서 재둔 시각으로 계산하므로
        # 자리를 옮겨도 값이 달라지지 않는다.
        enrichment_execution = build_candidate_enrichment_execution_debug(
            enrichment_response,
            latency_ms=int((time.monotonic() - enrichment_started_at) * 1000),
        )
        try:
            enrichment_step.record(
                output={
                    "requested": len(enrichment_request.candidates),
                    "features": list(enrichment_request.features),
                    "status": str(getattr(enrichment_response, "status", None)),
                    "enriched": len(getattr(enrichment_response, "candidates", None) or []),
                    # 성공 건수만으로는 직접 조회한 값과 인근에서 빌려온 값이
                    # 구분되지 않는다 — 후보별 출처를 그대로 남긴다.
                    "candidates": (
                        concentration_source_rows(enrichment_execution)
                        if enrichment_execution is not None
                        else []
                    ),
                },
                status_message=(
                    f"보강 {len(enrichment_request.candidates)}건 요청 · "
                    f"{getattr(enrichment_response, 'status', '?')}"
                ),
            )
        except Exception:
            logger.warning("보강 관측 요약 실패(응답 흐름에는 영향 없음)", exc_info=True)
    if execution_collector is not None and enrichment_execution is not None:
        execution_collector.append(enrichment_execution)
    if enrichment_response.status in _ENRICHMENT_TERMINAL_STATUSES or not hasattr(
        recommendation_provider, "rerank_with_concentration"
    ):
        logger.info(
            "혼잡도 보강 조회는 성공했지만 D의 2차 Scoring이 아직 없어 1차 결과를 "
            "그대로 씀: request_id=%s enrichment_status=%s",
            enrichment_request.request_id,
            enrichment_response.status,
        )
        return first_pass

    reranked = await recommendation_provider.rerank_with_concentration(
        agent_conditions,
        tool_context,
        first_pass,
        enrichment_response,
    )
    shown = [*reranked.recommendations, *reranked.unverified_recommendations]
    resolved_final_limit = (
        final_limit if final_limit is not None else settings.recommendation_result_limit
    )
    return reranked.model_copy(
        update={
            "recommendations": shown[:resolved_final_limit],
            "unverified_recommendations": [],
        }
    )


async def _fetch_travel_routes(
    route_tool: TravelRouteToolProvider | None,
    context: RecommendationContext,
    prepared: PreparedRecommendationResult,
    mode: TravelMode | None,
    conditions: UserConditions | None = None,
) -> tuple[TravelRoute, ...]:
    """하드 필터 통과 후보만 실측 조회하고 D에 넘길 도메인 결과를 반환한다.

    `mode`가 None이면 조회하지 않는다 — 무엇으로 재야 할지 정할 수 없는
    요청이다(to_travel_mode 참고).
    """
    if mode is None or route_tool is None or context.location is None or context.places is None:
        return ()
    resolved_location = context.location.data
    places = context.places.data
    if resolved_location is None or not places:
        return ()

    eligible_ids = {item.candidate.place_id for item in prepared.preparation.eligible_candidates}
    destinations = tuple(
        RouteDestination(
            place_id=place.place_id,
            coordinate=GeoCoordinate(
                latitude=place.location.latitude,
                longitude=place.location.longitude,
            ),
        )
        for place in places
        if place.place_id in eligible_ids
    )
    if not destinations:
        return ()

    # 실측 경로도 거리 계산과 같은 기준점에서 잰다 — 한쪽만 사용자 기준이면
    # 실측이 있는 후보와 없는 후보가 서로 다른 자로 채점된다(TP-112).
    origin = (resolve_ranking_origin(context, conditions) or resolved_location).location
    result = await route_tool.execute(
        TravelRouteQuery(
            origin=GeoCoordinate(
                latitude=origin.latitude,
                longitude=origin.longitude,
            ),
            destinations=destinations,
            mode=mode,
        )
    )
    return result.routes


def _is_info_walking_time_request(llm_output: LLMOutput) -> bool:
    """INFO location_info 중 실제 도보 소요 시간을 물은 경우만 경로를 조회한다."""

    info = llm_output.info
    if info is None or info.question_type is not QuestionType.LOCATION_INFO:
        return False
    normalized_question = (info.specific_question or "").replace(" ", "")
    return any(marker in normalized_question for marker in _INFO_WALKING_TIME_MARKERS)


def _to_geo_coordinate(location: str | None) -> GeoCoordinate | None:
    """B에 저장된 ``위도,경도`` 문자열을 도보 경로 도메인 값으로 변환한다."""

    if location is None:
        return None
    parts = location.split(",")
    if len(parts) != 2:
        return None
    try:
        return GeoCoordinate(latitude=float(parts[0]), longitude=float(parts[1]))
    except (TypeError, ValueError):
        return None


async def _fetch_info_walking_route(
    route_tool: TravelRouteToolProvider | None,
    *,
    origin_location: str | None,
    info_response: InfoContextResponse,
) -> TravelRoute | None:
    """INFO가 해석한 한 장소까지의 실제 도보 경로를 안전하게 조회한다.

    경로 장애가 주소/상세 정보 응답 전체를 실패시키면 안 되므로, 실패·누락은 None으로
    낮춘다. `TravelRouteTool` 내부의 Real→직선거리 추정 fallback은 그대로 사용한다.
    """

    if route_tool is None:
        return None
    result = info_response.result
    if not isinstance(result, PlaceInfoResult):
        return None
    if result.place_id is None or result.destination_coordinates is None:
        return None
    origin = _to_geo_coordinate(origin_location)
    if origin is None:
        return None

    try:
        route_result = await route_tool.execute(
            TravelRouteQuery(
                origin=origin,
                destinations=(
                    RouteDestination(
                        place_id=result.place_id,
                        coordinate=GeoCoordinate(
                            latitude=result.destination_coordinates.latitude,
                            longitude=result.destination_coordinates.longitude,
                        ),
                    ),
                ),
                mode=TravelMode.WALKING,
            )
        )
    except AppError:
        logger.warning("INFO 도보 경로 조회 실패", exc_info=True)
        return None

    return next(
        (
            route
            for route in route_result.routes
            if route.place_id == result.place_id and route.status is RouteStatus.SUCCESS
        ),
        None,
    )


# TravelMode → ComparisonItem의 어느 필드에 채울지. "덜 막힐까" 등 실시간 정체는
# 아직 반영하지 못하므로 이 세 값은 정체 미반영 실측이다(criteria_rules.md에 안내).
_COMPARE_TRAVEL_TIME_FIELDS: dict[TravelMode, str] = {
    TravelMode.WALKING: "travel_walking_minutes",
    TravelMode.DRIVING: "travel_driving_minutes",
    TravelMode.TRANSIT: "travel_transit_minutes",
}
# 대표 거리로 쓸 우선순위 — 자동차 경로가 도로 기준이라 "실제로 얼마나 떨어져
# 있는지"에 가장 가깝다고 보고, 조회 실패 시 도보·대중교통 순으로 대체한다.
_COMPARE_DISTANCE_MODE_PRIORITY = (TravelMode.DRIVING, TravelMode.WALKING, TravelMode.TRANSIT)


async def _fetch_compare_travel_routes(
    route_tool: TravelRouteToolProvider | None,
    *,
    origin_location: str | None,
    comparison: ComparisonResult,
) -> ComparisonResult:
    """COMPARE의 TRAVEL_TIME 기준일 때 도보·자동차·대중교통 세 경로를 모두 실측한다.

    C는 좌표(item.latitude/longitude)만 사실대로 전달했을 뿐 우열을 매기지
    않는다(agent_context/service.py 참고) — 여기서 A가 실측을 붙인다. 대상은
    보통 2~3곳뿐이라 세 수단을 병렬로 조회해도 부담이 적다(_fetch_travel_routes와
    달리 "하드 필터 통과 후보 전체"가 아니라 "이미 비교 대상으로 확정된 소수").

    사용자 조건(transport)으로 한 수단만 고르지 않는다 — "도보/자차/대중교통으로
    얼마나 걸리는지"를 한 번에 보여줘야 사용자가 자기 상황에 맞는 수단을 고를 수
    있다. 수단 하나가 provider 미설정·경로 장애로 실패해도 나머지 수단·item은
    영향받지 않는다(response_composer가 None인 수단은 안내에서 뺀다).
    """

    if comparison.criteria is not CompareCriteria.TRAVEL_TIME or route_tool is None:
        return comparison

    origin = _to_geo_coordinate(origin_location)
    if origin is None:
        return comparison

    destinations = tuple(
        RouteDestination(
            place_id=item.place_id,
            coordinate=GeoCoordinate(latitude=item.latitude, longitude=item.longitude),
        )
        for item in comparison.items
        if item.latitude is not None and item.longitude is not None
    )
    if not destinations:
        return comparison

    async def _fetch_one_mode(mode: TravelMode) -> tuple[TravelMode, tuple[TravelRoute, ...]]:
        try:
            result = await route_tool.execute(
                TravelRouteQuery(origin=origin, destinations=destinations, mode=mode)
            )
        except AppError:
            logger.warning("COMPARE 이동시간 실측 조회 실패: mode=%s", mode.value, exc_info=True)
            return mode, ()
        return mode, result.routes

    mode_results = await asyncio.gather(
        *(_fetch_one_mode(mode) for mode in _COMPARE_TRAVEL_TIME_FIELDS)
    )
    routes_by_mode: dict[TravelMode, dict[str, TravelRoute]] = {
        mode: {route.place_id: route for route in routes if route.status is RouteStatus.SUCCESS}
        for mode, routes in mode_results
    }
    if not any(routes_by_mode.values()):
        return comparison

    def _update_item(item: ComparisonItem) -> ComparisonItem:
        updates: dict[str, object] = {}
        for mode, field in _COMPARE_TRAVEL_TIME_FIELDS.items():
            route = routes_by_mode.get(mode, {}).get(item.place_id)
            if route is not None and route.duration_seconds is not None:
                updates[field] = round(route.duration_seconds / 60)
        for mode in _COMPARE_DISTANCE_MODE_PRIORITY:
            route = routes_by_mode.get(mode, {}).get(item.place_id)
            if route is not None and route.distance_m is not None:
                updates["travel_distance_km"] = round(route.distance_m / 1000, 2)
                break
        return item.model_copy(update=updates) if updates else item

    updated_items = [_update_item(item) for item in comparison.items]
    return comparison.model_copy(update={"items": updated_items})


def _failure_attributes(error: BaseException) -> dict[str, object]:
    """실패한 턴을 `agent_turn` span에 적을 모양으로 편다.

    **`level`·`status_message`는 mask를 타지 않는다.** 오류 코드가 `capture_content`
    스위치에 걸리면 원문 수집을 끈 배포에서 "무엇이 터졌나"를 화면에서 못 읽는데,
    그건 이 관측이 있는 이유 자체다. 그래서 코드는 두 자리 모두에 적는다.

    `AppError`는 우리가 의도해서 만든 오류라 코드·재시도 가능 여부가 계약으로
    정해져 있다(`errors.py`). 그 밖의 예외는 **클래스 이름만** 적는다 — 메시지는
    싣지 않는다. 어디서 터졌느냐에 따라 발화나 좌표가 섞여 들어올 수 있는데
    `status_message`는 스위치와 무관하게 나가는 자리다.
    """

    if isinstance(error, AppError):
        return {
            "level": "ERROR",
            "status_message": f"{error.code} · retryable={error.retryable}",
            "output": {
                "error_code": error.code,
                "retryable": error.retryable,
                "status_code": error.status_code,
                "provider": error.provider,
            },
        }
    name = type(error).__name__
    return {
        "level": "ERROR",
        "status_message": name,
        "output": {"error_code": name, "retryable": False},
    }


def summarize_state_merge(response: StateApplyResponse) -> dict[str, object]:
    """`merge_conditions` span에 실을 값을 고른다 — Audit "B 상태" 탭과 같은 값이다.

    **여기는 span 자체가 없던 자리다.** 조건 병합은 A가 B를 부르는 단계인데 관측을
    안 걸어서, trace만 보면 "이번 턴이 어떤 조건으로 돌았나"를 알 수 없었다.
    `classify_intent`의 출력(= 이번 발화에서 **새로** 추출한 것)은 보여도 **이전
    턴에서 유지된 값까지 합친 최종 조건**은 어디에도 없었다. 2026-08-26에 B와
    협의해 열었다.

    **`user_conditions`에는 좌표가 들어 있다**(`current_location`·`search_center`).
    `api_context.gps_location`도 마찬가지다. `capture_content`가 꺼져 있으면 output
    전체가 `<redacted>`가 되지만 켜면 그대로 나간다 — `tool_fetch` span과 같은
    조건이고, 켜는 것이 명시적 선택이어야 한다.

    조건 목록 전체를 싣는다. B가 돌려주는 값이 곧 이 턴의 입력이라 일부만 고르면
    "왜 이 조건으로 돌았나"에 답이 안 된다 — 그게 이 span을 여는 이유다.
    """

    return {
        "session_created": response.session_created,
        "condition_version": response.condition_version,
        "condition_changed": response.condition_changed,
        "reset_applied": response.reset_applied,
        "user_conditions": response.user_conditions.model_dump(mode="json"),
        "api_context": response.api_context.model_dump(mode="json"),
        "applied_operations": [
            operation.model_dump(mode="json") for operation in response.applied_operations
        ],
        # 무효 처리된 연산이 왜 무시됐는지(reason)가 여기 있다. 적용된 것만 보면
        # "왜 내 말이 반영이 안 됐지"에 답할 수 없다.
        "ignored_operations": [
            operation.model_dump(mode="json") for operation in response.ignored_operations
        ],
        "excluded_place_count": len(response.excluded_place_ids),
    }


def _state_merge_headline(response: StateApplyResponse) -> str:
    """`merge_conditions`의 `status_message`. **mask를 타지 않는 자리다.**

    원문 수집을 꺼도 "이번 턴에 조건이 바뀌었나"는 목록에서 읽혀야 한다. 좌표나
    조건 값은 넣지 않는다 — 여기 넣으면 스위치와 무관하게 나간다.
    """

    parts = [
        f"조건 v{response.condition_version}",
        "변경" if response.condition_changed else "유지",
        f"적용 {len(response.applied_operations)}",
        f"무시 {len(response.ignored_operations)}",
    ]
    if response.reset_applied:
        parts.append(f"reset:{response.reset_applied}")
    return " · ".join(parts)


def summarize_turn(response: AgentResponse) -> dict[str, object]:
    """루트 span(`agent_turn`)에 실을 값을 고른다.

    **여기가 비어 있으면 목록 화면이 안 읽힌다.** 루트는 SPAN이라 토큰·비용·모델이
    원래 없고(그건 자식 GENERATION의 것), 입출력까지 비어 있으면 행에 이름과 지연만
    남는다 — "이 턴이 무슨 요청이었나"를 알려면 눌러서 `classify_intent`의 출력을
    봐야 했다. 턴이 쌓이면 못 쓴다.

    **발화도 답변 원문도 싣지 않는다.** intent와 결과 모양만으로 목록이 읽힌다.
    원문이 필요하면 자식 generation에 이미 있다(`capture_content`가 켜져 있을 때).

    `headline`은 `status_message`로 나간다 — 그 자리는 mask를 타지 않아
    원문 수집을 꺼도 남는다(`langfuse_tracing` 모듈 docstring, 검증 기준 g).
    """
    recommendations = response.recommendations
    shown = list(getattr(recommendations, "recommendations", None) or [])
    unverified = list(getattr(recommendations, "unverified_recommendations", None) or [])
    cards = len(shown) + len(unverified)
    intent = response.llm_output.intent.value
    status = response.llm_output.status.value

    detail = f"카드 {cards}" if cards else None
    if response.schedule is not None:
        detail = "일정"
    elif response.comparison is not None:
        detail = "비교"
    elif response.info_place_card is not None:
        detail = "장소 정보"

    return {
        "intent": intent,
        "status": status,
        "card_count": cards,
        "unverified_count": len(unverified),
        "has_schedule": response.schedule is not None,
        "has_comparison": response.comparison is not None,
        "has_info_card": response.info_place_card is not None,
        # 답변이 나갔는지만 본다. 원문은 자식 generation에 있다.
        "message_length": len(response.message) if response.message else 0,
        "headline": " · ".join(part for part in (intent, status, detail) if part),
    }


async def run_agent_flow(
    request: AgentRequest,
    *,
    llm: LLMProvider,
    tool_provider: ToolProvider,
    recommendation_provider: RecommendationProvider,
    enrichment_provider: EnrichmentProvider,
    travel_route_tool: TravelRouteToolProvider | None = None,
    store: StateStore | None = None,
    principal: Principal | None = None,
    stream_event_sink: StreamEventSink | None = None,
    stream_recommendation_summary: bool = False,
) -> AgentResponse:
    """한 턴 전체를 하나의 관측 trace로 묶고 본체(`_run_agent_flow`)에 넘긴다.

    **루트 span이 있어야 한 턴이 trace 하나가 된다.** 속성만 전파하고
    (`trace_attributes`) 루트를 안 만들면, 부모가 없는 observation이 저마다
    자기가 trace 루트가 되어 한 턴이 여러 조각으로 흩어진다 — 2026-08-25 첫
    실측에서 `classify_intent`와 `extract_recommend_conditions`가 별도 trace로
    올라와 확인했다. 여기서 연 span이 그 부모 자리다.

    이 블록 안에서 생기는 모든 span이 같은 session_id와 태그도 함께 물려받는다.
    LangGraph 노드는 별도 asyncio 태스크에서 돌지만, 태스크 생성 시점에 문맥을
    복사해 가므로 여기서 연 범위가 그 안까지 따라간다(llm_execution.py의
    ContextVar 설명과 같은 이유).

    **첫 턴은 session_id 없이 기록된다.** 세션은 아래 apply()에서 발급되는데
    그때는 이미 LLM 단계가 지나가서, 나중에 붙여도 앞 span에 소급되지 않는다
    (v4에는 trace 속성을 나중에 갱신하는 API가 없다). 두 번째 턴부터는 묶인다.

    관측이 꺼져 있으면(기본값) 이 래퍼는 아무 일도 하지 않는다.
    """

    with (
        trace_attributes(
            session_id=request.session_id,
            user_id=_observed_user_id(principal),
            tags=[f"scoring:{SCORING_VERSION}", f"env:{settings.app_env}"],
        ),
        observe_step("agent_turn") as turn,
    ):
        try:
            response = await _run_agent_flow(
                request,
                llm=llm,
                tool_provider=tool_provider,
                recommendation_provider=recommendation_provider,
                enrichment_provider=enrichment_provider,
                travel_route_tool=travel_route_tool,
                store=store,
                principal=principal,
                stream_event_sink=stream_event_sink,
                stream_recommendation_summary=stream_recommendation_summary,
            )
        except BaseException as error:
            # **오류 코드를 span에 적는다.** 그 전까지 실패한 턴은 `turn_success=0`
            # 하나로만 남아서, 화면에서 "터졌다"까지는 알아도 "무엇이 터졌나"는
            # 서버 로그를 따로 봐야 했다.
            turn.record(**_failure_attributes(error))
            # **실패한 턴에도 점수를 남긴다.** 여기서 안 남기면 실패는 Score 집계에서
            # 통째로 빠져 성공률이 항상 1.0으로 보인다 — 2026-08-07부터 SCHEDULE +
            # 혼잡도 조합이 ValueError로 죽고 있었는데 18일간 아무 지표도 안 움직인
            # 것이 그 모양이다. 예외는 그대로 올린다.
            record_score("turn_success", False)
            raise
        try:
            summary = summarize_turn(response)
            turn.record(
                output=summary,
                # 목록 화면에서 필터를 걸 자리. capture_content가 꺼지면 가려진다.
                metadata={"intent": summary["intent"], "status": summary["status"]},
                # 마스킹을 타지 않는 자리. 원문 수집을 꺼도 목록에서 턴이 읽힌다.
                status_message=summary["headline"],
            )
            record_turn_scores(summary)
        except Exception:
            logger.warning("턴 관측 요약 실패(응답 흐름에는 영향 없음)", exc_info=True)
        return response


def _observed_user_id(principal: Principal | None) -> str | None:
    """관측에 실을 사용자 식별자. 스위치가 꺼져 있으면 `None`.

    켜는 것은 팀 결정이라 기본값이 꺼짐이다(`config.py`). 게스트도 `user_id`를
    갖지만(D-062 2절) 그것 역시 외부로 나가는 식별자라 똑같이 스위치를 탄다.
    """

    if not settings.langfuse_capture_user_id or principal is None:
        return None
    return principal.user_id


def record_turn_scores(summary: Mapping[str, object]) -> None:
    """턴 요약에서 **집계할 값**만 골라 Score로 올린다.

    `turn.record(output=summary)`와 중복이 아니다 — output은 그 턴을 열어봤을 때
    읽는 값이고 Score는 여러 턴에 걸쳐 곡선이 되는 값이다. 그래서 여기 올리는 것은
    "추세가 의미 있는 수치"로 좁힌다. `intent`·`status`는 태그와 metadata로 이미
    필터가 되므로 Score로 또 올리지 않는다.

    `unverified_ratio`는 카드가 있을 때만 올린다 — 0/0을 0.0으로 적으면 "미검증이
    하나도 없는 좋은 턴"과 "카드 자체가 없는 턴"이 같은 값이 되어 평균이 거짓말을 한다.
    """

    record_score("turn_success", True)
    cards = int(summary.get("card_count") or 0)
    record_score("card_count", cards)
    if cards:
        record_score("unverified_ratio", int(summary.get("unverified_count") or 0) / cards)


async def _run_agent_flow(
    request: AgentRequest,
    *,
    llm: LLMProvider,
    tool_provider: ToolProvider,
    recommendation_provider: RecommendationProvider,
    enrichment_provider: EnrichmentProvider,
    travel_route_tool: TravelRouteToolProvider | None = None,
    store: StateStore | None = None,
    principal: Principal | None = None,
    stream_event_sink: StreamEventSink | None = None,
    stream_recommendation_summary: bool = False,
) -> AgentResponse:
    """Provider를 인자로 받는 테스트 가능한 본체.

    호출 순서(A가 전체를 조정, B/C/D는 각자 내부 판단만 담당):
      A→B(세션 컨텍스트) → A(Intent+조건 추출) → A→B(조건 병합) →
      [A→C(Tool) → A→D(Recommendation) → A→B(결과 기록)] → A(최종 응답)
    대괄호 구간은 status가 complete이고 intent가 RECOMMEND/MODIFY일 때만 실행된다.
    이 구간 안에서도 C 응답 status가 needs_clarification/unsupported/unavailable이면
    D를 건너뛴다 — LLM 단계의 needs_clarification과는 별개 레이어다(계약 문서 §5.4).
    """

    # 1) A → B: GPS 세션 컨텍스트 최신화. GPS 형식이 잘못되면 이번 턴만 건너뛴다 —
    #    잘못된 GPS 문자열이 파싱 예외로 대화를 중단시키지 않아야 한다.
    reset_llm_execution_metadata()
    await _emit_progress(
        stream_event_sink,
        "interpreting",
        "요청 의도와 조건을 파악하고 있어요.",
    )
    valid_gps = _valid_location(request.device_location)
    session_context = await ensure_current_context(
        request.session_id, valid_gps, store=store, principal=principal
    )

    # 2) A: LLMOutput 생성 (Intent 분류 + Intent별 조건 추출). B가 준 현재 조건(순수 문자열)을
    #    A 쪽 enum 타입으로 변환해서 넘긴다 — MODIFY 추출이 이 타입을 요구한다.
    # 위치 되묻기 직후에는 아직 추천 결과가 없을 수 있어도, 첫 턴에서 저장된 조건을
    # MODIFY 추출에 제공해야 한다. 그렇지 않으면 "경복궁"이 MODIFY로 올바르게
    # 분류돼도 current_conditions 없음 되묻기로 다시 빠진다.
    # 되묻기 버튼 클릭이면 classify_intent()/extract_*_conditions()를 건너뛰고
    # 결정적으로 해소한다(docs/design/clarification-options.md 3절). code/choice_id가
    # 안 맞으면 None이 와서 아래 평소 경로로 자연스럽게 폴백한다.
    # "OO 기준으로 다시 보기" 버튼(travel_origin_override, D-071)도 같은 이유로
    # 결정적으로 해소한다 — 둘 다 세션에 온 요청이면 클라리피케이션 쪽을 우선한다
    # (두 필드가 같은 턴에 함께 오는 경우는 없다).
    if request.clarification_choice is not None:
        clarification_resolution = _resolve_clarification_choice(
            choice_id=request.clarification_choice,
            session_context=session_context,
        )
    elif request.travel_origin_override is not None:
        clarification_resolution = _resolve_travel_origin_override(
            override=request.travel_origin_override,
            session_context=session_context,
        )
    else:
        clarification_resolution = None
    # 이번 턴에 막 선택했거나(clarification_resolution), 직전에 선택해서 아직
    # TTL 안이거나(session_context), 개발자 채팅의 일회성 디버그 스위치가
    # 켜졌으면 폐점 후보도 계속 포함한다.
    clicked_show_closed = (
        clarification_resolution is not None and clarification_resolution.ignore_operating_hours
    )
    effective_ignore_operating_hours = bool(
        request.debug_ignore_operating_hours
        or clicked_show_closed
        or (
            session_context.ignore_operating_hours_until is not None
            and session_context.ignore_operating_hours_until > now_kst()
        )
    )

    llm_started_at = time.monotonic()
    if clarification_resolution is not None:
        llm_output = clarification_resolution.llm_output
    else:
        location_clarification_pending = session_context.pending_clarification in {
            "location_required",
            "location_ambiguous",
        }
        current_conditions = (
            to_user_conditions(session_context.user_conditions)
            if session_context.has_recommendation or location_clarification_pending
            else None
        )
        interpret_request = InterpretRequest(
            user_input=request.user_input,
            has_previous_recommendation=session_context.has_recommendation,
            shown_place_count=len(session_context.shown_place_ids),
            current_conditions=current_conditions,
            pending_clarification=session_context.pending_clarification,
            last_intent=session_context.last_intent,
            # rank 순으로 채운다 — shown_recommendations는 이미 rank 정렬되어
            # 있으므로(history.get_last_recommended_items) 그대로 옮기면 된다.
            # 이름이 없는 항목(name 저장 이전의 과거 세션 등)은 빈 문자열로 채운다.
            shown_place_names=[item.name or "" for item in session_context.shown_recommendations],
            conversation_place_name=request.conversation_place_name,
        )
        llm_output = await build_interpretation(interpret_request, llm)
    llm_latency_ms = int((time.monotonic() - llm_started_at) * 1000)

    # 3) A → B: 조건 병합. confirmed=False(= status가 complete가 아님)면 B가 State를
    #    바꾸지 않고 현재 상태만 돌려주도록 이미 구현되어 있다(계약 2.6절) — 따로 걸러서
    #    apply()를 건너뛸 필요가 없다. 그래야 needs_clarification 응답에도 병합된(=변화
    #    없는) state가 항상 채워진다.
    await _emit_progress(
        stream_event_sink,
        "merging_conditions",
        "이전 대화 조건을 반영하고 있어요.",
    )
    apply_request = transform(llm_output, session_context, request.user_input)
    with observe_step("merge_conditions") as merge_step:
        state_response = apply(apply_request, store=store, principal=principal)
        try:
            merge_step.record(
                output=summarize_state_merge(state_response),
                status_message=_state_merge_headline(state_response),
            )
        except Exception:
            logger.warning("조건 병합 관측 요약 실패(응답 흐름에는 영향 없음)", exc_info=True)

    if clarification_resolution is not None and clarification_resolution.ignore_operating_hours:
        _remember_ignore_operating_hours(state_response.session_id, store)

    # 2단계(LLM 호출) trace는 여기서 기록한다 — run_id/session_id가 apply() 안에서
    # 발급되므로 2단계 시점엔 아직 없다. latency만 미리 재뒀다가 여기서 기록.
    _record_trace_safely(
        session_id=state_response.session_id,
        run_id=state_response.run_id,
        step="llm_interpret",
        latency_ms=llm_latency_ms,
        # 이번 턴이 실제로 사용한 슬롯의 버전을 남긴다
        # (예: router.classify@2.0.0+info.extract@3.0.0).
        # 예전의 단일 고정 문자열로는 어느 인텐트의 프롬프트가 이 응답을 만들었는지
        # 되짚을 수 없었다.
        prompt_version=turn_prompt_version(llm_output.intent),
        # 계약 2절의 token_usage. 2026-08-25까지 이 값은 항상 None이었다 —
        # 필드는 있었지만 gemini.py가 응답의 usage_metadata를 안 읽었다.
        # 이 시점까지 이 턴이 쓴 총 토큰을 넘긴다(분류 + 조건 추출).
        token_usage=consumed_tokens(),
        store=store,
    )

    # 되묻기 버튼이 "조회할 것 없는 확인성 선택지"로 해소된 경우(예: "지금 장소가
    # 마음에 들어요", "새로 시작할게요") — 조건 병합(soft reset 등)은 이미 위에서
    # 끝났지만 Tool/D 호출 없이 고정 문구로 여기서 바로 끝낸다. intent가
    # RECOMMEND/MODIFY/SCHEDULE이어도(즉 아래 "4) 게이트"를 안 거치는 경우에도)
    # 똑같이 터미널로 끝나야 해서 게이트보다 앞에 둔다 — "새로 시작할게요"가 GPS만
    # 있어도 자동으로 추천을 내버리는 걸 막는다(실사용 재현, 2026-08-13:
    # 사용자가 새 목적지를 직접 말하길 기다려야 하는데 조건이 비어있다는 이유로
    # 현재 위치 기준 추천이 조용히 나가버렸다).
    if clarification_resolution is not None and clarification_resolution.terminal_message:
        _remember_clarification(state_response.session_id, None, store)
        return AgentResponse(
            llm_output=llm_output,
            state=state_response,
            recommendations=None,
            message=clarification_resolution.terminal_message,
            llm_execution=get_llm_execution_metadata(),
        )

    # 3-1) 최초 턴이면 방금 생성된 세션에 GPS를 심는다. ensure_current_context()(1번)는
    #      세션이 이미 있을 때만 GPS를 갱신한다(B 계약상 read-only, 세션은 apply()만
    #      생성) — 그래서 세션이 방금 생긴 최초 턴에는 1번에서 GPS를 심을 수 없다.
    #      update_api_context()는 동기 함수라 await를 붙이지 않는다.
    if state_response.session_created and valid_gps:
        update_api_context(
            UpdateApiContextRequest(
                session_id=state_response.session_id,
                gps_location=valid_gps,
                gps_location_updated_at=now_kst(),
            ),
            store=store,
        )

    # 3-2) 되묻기 플래그 소비. 조건을 건드리는 턴(RECOMMEND/MODIFY/SCHEDULE)만 지운다 —
    #      transform()이 이미 session_context의 값을 읽어 병합 방식을 정했으므로,
    #      여기서 지워도 이번 턴 판단에는 영향이 없다. 이번 턴이 또 되묻기로 끝나면
    #      아래 4)/5-1)에서 새 값을 다시 심는다. INFO/GENERAL 같은 곁가지 대화는
    #      조건을 바꾸지 않으므로 이전 되묻기를 그대로 살려둔다. SCHEDULE도 RECOMMEND와
    #      동일하게 조건을 건드리는 턴이라 목록에 포함한다(D-059) — 빠뜨리면 SCHEDULE
    #      되묻기가 옳게 이어져도 플래그가 계속 남아 다음 턴 판단에 잘못 영향을 준다.
    if session_context.pending_clarification is not None and llm_output.intent in (
        Intent.RECOMMEND,
        Intent.MODIFY,
        Intent.SCHEDULE,
    ):
        _remember_clarification(state_response.session_id, None, store)

    # 3-3) SCHEDULE 재조정 감지(SCHEDULE-06). 직전 턴이 SCHEDULE로 완료됐는데
    #      (last_intent="SCHEDULE", 되묻기 없이 끝남 — pending_clarification=None)
    #      이번 턴이 조건을 바꾸는 MODIFY로 분류됐다면 "일정 재조정" 요청으로
    #      본다. session_context는 이번 턴 처리 전에 조회한 값이라 직전 턴
    #      정보를 그대로 담고 있다(1번 참고). 조건 병합(3번)은 이미 원래
    #      MODIFY 페이로드(llm_output.modify)로 정상적으로 끝났으므로 그 결과는
    #      손대지 않고, intent 라벨만 SCHEDULE로 바꿔 아래 6)~8) 단계가 기존
    #      SCHEDULE 분기(D 10개 호출·편성 모듈 호출)를 그대로 타게 한다.
    #      classify_intent 프롬프트나 extract_modify_conditions는 건드리지
    #      않는다 — last_intent는 B가 이미 매 턴 저장해온 값을 여기서 처음
    #      읽는 것뿐이다(docs/design/int-07-schedule.md 3절 참고, A 공유 완료).
    if (
        llm_output.intent is Intent.MODIFY
        and llm_output.status is OutputStatus.COMPLETE
        and session_context.last_intent == Intent.SCHEDULE.value
        and session_context.pending_clarification is None
    ):
        modify = llm_output.modify
        if (
            modify is not None
            and modify.modify_type is ModifyType.CHANGE_CONDITION
            and _is_ambiguous_schedule_or_recommend(request.user_input)
        ):
            # "카페 추천해줘"류는 "일정 재조정"인지 "그냥 추천"인지 글자로 구분이 안
            # 되는 진짜 모호 케이스다 — 추측 대신 되묻는다(버튼 2개,
            # docs/design/clarification-options.md 5절). 조건 병합은 이미 원래 MODIFY
            # 페이로드로 끝났으므로 손대지 않고 라벨만 되묻기로 바꾼다. 이번 턴에서
            # 추출된 카테고리(예: "카페")가 있으면 "장소" 대신 그 카테고리명을 그대로
            # 문구/버튼에 넣는다 — 범용 문구보다 사용자가 방금 말한 걸 그대로
            # 되비춰주는 쪽이 더 명확하다.
            category_label = _extracted_category_label(modify)
            recommend_label = (
                f"{category_label}만 추천받기" if category_label else "장소만 추천받기"
            )
            clarification_message = (
                f"이어서 일정을 다시 짜드릴까요, 아니면 {category_label}만 추천해드릴까요?"
                if category_label
                else "이어서 일정을 다시 짜드릴까요, 아니면 장소만 추천해드릴까요?"
            )
            clarification_llm_output = llm_output.model_copy(
                update={
                    "status": OutputStatus.NEEDS_CLARIFICATION,
                    "clarification": ClarificationPayload(
                        message=clarification_message,
                        options=[
                            ClarificationOption(
                                id="schedule_continue",
                                label="일정 다시 짜기",
                                resolved_intent=Intent.SCHEDULE,
                            ),
                            ClarificationOption(
                                id="recommend_only",
                                label=recommend_label,
                                resolved_intent=Intent.RECOMMEND,
                            ),
                        ],
                    ),
                }
            )
            _remember_clarification(
                state_response.session_id, "schedule06_ambiguous_recommend", store
            )
            message = await compose_chat_message(clarification_llm_output, llm=llm)
            return AgentResponse(
                llm_output=clarification_llm_output,
                state=state_response,
                recommendations=None,
                message=message,
                llm_execution=get_llm_execution_metadata(),
            )
        llm_output = llm_output.model_copy(update={"intent": Intent.SCHEDULE})
        # apply()(3번)는 이미 이 턴의 원본 intent(MODIFY)로 last_intent를 저장했다
        # — 그 호출 시점엔 아직 이 relabel이 일어나기 전이었기 때문이다. 그대로
        # 두면 다음 턴이 이번 턴을 last_intent="MODIFY"로 보게 되어, SCHEDULE →
        # REJECT_SPECIFIC → REJECT_SPECIFIC처럼 재조정이 연속될 때 두 번째부터
        # 이 감지 자체가 실패한다(2026-08-11 실사용 재현, D-061). 화면상 라벨과
        # 저장된 last_intent를 다시 맞춘다.
        set_last_intent(
            SetLastIntentRequest(
                session_id=state_response.session_id, intent=Intent.SCHEDULE.value
            ),
            store=store,
        )

    # 3-4) schedule_no_candidates 되묻기 해소(force_schedule). 되묻기 해소 turn은
    #      session_context.pending_clarification이 "schedule_no_candidates"라서
    #      바로 위 3-3)의 게이트(pending_clarification is None)를 못 타 자동
    #      relabel이 안 된다 — 여기서 명시적으로 같은 relabel을 반복한다.
    if (
        clarification_resolution is not None
        and clarification_resolution.force_schedule
        and llm_output.intent is not Intent.SCHEDULE
    ):
        llm_output = llm_output.model_copy(update={"intent": Intent.SCHEDULE})
        set_last_intent(
            SetLastIntentRequest(
                session_id=state_response.session_id, intent=Intent.SCHEDULE.value
            ),
            store=store,
        )

    # 4-0) INFO는 question_type 8종 모두 RECOMMEND/MODIFY와 별개로 C를 거친다
    #      (D-054/D-055, backend/docs/package-a/info-question-types-handoff.md)
    #      COMPARE/GENERAL은 그대로 4)의 일반 게이트로 빠진다 — Tool을 직접 호출하지
    #      않는다는 기존 원칙(ToolProvider Protocol)을 그대로 따른다.
    #      hasattr 체크: Fake 등 fetch_info_context()를 구현하지 않은 ToolProvider에도
    #      AttributeError로 요청 전체가 죽지 않고 기존 "준비 중" 문구로 안전하게
    #      낮아지게 한다.
    if (
        llm_output.status is OutputStatus.COMPLETE
        and llm_output.intent is Intent.INFO
        and llm_output.info is not None
        and hasattr(tool_provider, "fetch_info_context")
    ):
        info_request = to_info_context_request(new_trace_id(), llm_output.info)
        await _emit_progress(
            stream_event_sink,
            "fetching_context",
            "장소 상세 정보를 찾고 있어요.",
        )
        info_started_at = time.monotonic()
        info_response = await tool_provider.fetch_info_context(info_request)
        info_execution = build_info_concentration_execution_debug(
            info_response,
            latency_ms=int((time.monotonic() - info_started_at) * 1000),
        )
        requests_walking_time = _is_info_walking_time_request(llm_output)
        info_origin_location = valid_gps
        if info_origin_location is None and not state_response.api_context.gps_expired:
            info_origin_location = state_response.api_context.gps_location
        info_walking_route = None
        if requests_walking_time:
            await _emit_progress(
                stream_event_sink,
                "fetching_context",
                "현재 위치에서 도보 이동 시간을 확인하고 있어요.",
            )
            info_walking_route = await _fetch_info_walking_route(
                travel_route_tool,
                origin_location=info_origin_location,
                info_response=info_response,
            )
        stream_info_message = (
            stream_recommendation_summary
            and isinstance(info_response.result, PlaceInfoResult)
            and info_response.result.status == "success"
            and bool(info_response.result.fields)
            and not requests_walking_time
        )
        if stream_info_message:
            await _begin_streamed_message(
                stream_event_sink,
                intent=Intent.INFO,
                progress_message="정보를 정리하고 있어요.",
            )

        async def emit_info_message_delta(text: str) -> None:
            await _emit_stream_event(stream_event_sink, "message_delta", {"text": text})

        message = await compose_chat_message(
            llm_output,
            info_response=info_response,
            llm=llm,
            info_walking_route=info_walking_route,
            info_walking_origin_available=info_origin_location is not None,
            on_message_delta=(emit_info_message_delta if stream_info_message else None),
        )
        return AgentResponse(
            llm_output=llm_output,
            state=state_response,
            recommendations=None,
            info_place_card=to_info_place_card(info_response),
            message=message,
            llm_execution=get_llm_execution_metadata(),
            tool_execution=info_execution,
            tool_executions=[info_execution] if info_execution is not None else [],
        )

    # 4-1) COMPARE는 마지막 추천 이력의 Feature 스냅샷을 A가 targets로 해석해
    #      C에 넘기고, C가 place_id를 장소명으로 보강한 사실만 LLM 요약에 사용한다.
    #      새 추천 후보 검색·D 재점수화는 하지 않는다(D-050, int-04-compare.md §13).
    if (
        llm_output.status is OutputStatus.COMPLETE
        and llm_output.intent is Intent.COMPARE
        and llm_output.compare is not None
    ):
        if len(session_context.shown_place_ids) <= 1:
            # COMPARE 전제조건(노출 2개 이상)을 구조적으로 위반한다 — LLM이 그렇게
            # 분류했어도 비교 대상 자체가 성립하지 않는다(2026-08-11 68건 테스트에서
            # thinking 예산에 따라 COMPARE/RECOMMEND가 갈리는 걸로 확인, 케이스 3).
            # to_compare_context_request()의 기존 "비교할 장소가 더 필요해요" 안내
            # 대신 다음 행동을 바로 고를 수 있는 되묻기 버튼을 준다.
            clarification_llm_output = llm_output.model_copy(
                update={
                    "status": OutputStatus.NEEDS_CLARIFICATION,
                    "clarification": ClarificationPayload(
                        message="지금 보여드린 곳이 마음에 드시나요, 다른 곳도 보여드릴까요?",
                        options=[
                            ClarificationOption(
                                id=_COMPARE_SINGLE_SHOWN_KEEP_CURRENT,
                                label="지금 장소가 마음에 들어요",
                                resolved_intent=Intent.GENERAL,
                            ),
                            ClarificationOption(
                                id=_COMPARE_SINGLE_SHOWN_SHOW_MORE,
                                label="다른 곳도 보여주세요",
                                resolved_intent=Intent.MODIFY,
                            ),
                        ],
                    ),
                }
            )
            _remember_clarification(state_response.session_id, "compare_single_shown", store)
            message = await compose_chat_message(clarification_llm_output, llm=llm)
            return AgentResponse(
                llm_output=clarification_llm_output,
                state=state_response,
                recommendations=None,
                message=message,
                llm_execution=get_llm_execution_metadata(),
            )
        resolution = to_compare_context_request(
            new_trace_id(), llm_output.compare, session_context.shown_recommendations
        )
        if resolution.request is None:
            return AgentResponse(
                llm_output=llm_output,
                state=state_response,
                recommendations=None,
                message=resolution.message or "비교할 장소를 확인할 수 없어요.",
                llm_execution=get_llm_execution_metadata(),
            )

        compare_started_at = time.monotonic()
        await _emit_progress(
            stream_event_sink,
            "fetching_context",
            "비교할 장소 정보를 확인하고 있어요.",
        )
        compare_response = await tool_provider.fetch_compare_context(resolution.request)
        compare_latency_ms = int((time.monotonic() - compare_started_at) * 1000)
        compare_execution = build_compare_execution_debug(
            compare_response, latency_ms=compare_latency_ms
        )
        _record_trace_safely(
            session_id=state_response.session_id,
            run_id=state_response.run_id,
            step="tool_fetch",
            latency_ms=compare_latency_ms,
            error_type=(
                compare_response.status
                if compare_response.status in {"no_data", "unavailable"}
                else None
            ),
            store=store,
        )
        comparison: ComparisonResult | None = to_comparison_result(compare_response)
        if comparison is None:
            message = (
                "비교에 필요한 장소 정보가 부족해요. 다른 추천을 볼까요?"
                if compare_response.status == "no_data"
                else "일시적으로 비교 정보를 확인하지 못했어요. 잠시 후 다시 시도해주세요."
            )
            return AgentResponse(
                llm_output=llm_output,
                state=state_response,
                recommendations=None,
                message=message,
                llm_execution=get_llm_execution_metadata(),
                tool_execution=compare_execution,
                tool_executions=[compare_execution] if compare_execution is not None else [],
            )

        if comparison.criteria is CompareCriteria.TRAVEL_TIME:
            await _emit_progress(
                stream_event_sink,
                "fetching_context",
                "실제 이동시간을 확인하고 있어요.",
            )
            compare_origin_location = valid_gps or state_response.api_context.gps_location
            comparison = await _fetch_compare_travel_routes(
                travel_route_tool,
                origin_location=compare_origin_location,
                comparison=comparison,
            )

        await _emit_progress(
            stream_event_sink,
            "composing_message",
            "비교 결과를 정리하고 있어요.",
        )
        message = await compose_compare_message(comparison, llm)
        return AgentResponse(
            llm_output=llm_output,
            state=state_response,
            recommendations=None,
            comparison=comparison,
            message=message,
            llm_execution=get_llm_execution_metadata(),
            tool_execution=compare_execution,
            tool_executions=[compare_execution] if compare_execution is not None else [],
        )

    # 4) 확인이 더 필요하거나(needs_clarification), RECOMMEND/MODIFY/SCHEDULE이 아니면
    #    (INFO/COMPARE/GENERAL/OUT_OF_SCOPE) 여기서 끝난다 — Tool/Recommendation은
    #    부가 흐름이라 스킵한다. SCHEDULE도 D 호출까지 이어져야 하므로 포함한다
    #    (docs/design/int-07-schedule.md 4절).
    if llm_output.status is not OutputStatus.COMPLETE or llm_output.intent not in (
        Intent.RECOMMEND,
        Intent.MODIFY,
        Intent.SCHEDULE,
    ):
        # LLM이 되물은 경우만 기록한다. INFO/GENERAL 같은 다른 Intent는 조건을 건드리지
        # 않으므로, 이전 되묻기가 있었다면 그대로 살려둔다(곁가지 대화로 취급).
        if llm_output.status is not OutputStatus.COMPLETE:
            _remember_clarification(
                state_response.session_id, _llm_clarification_code(llm_output), store
            )
        # terminal_message가 있는 경우는 위(3단계 직후)에서 이미 처리하고
        # 반환했으므로 여기서는 다시 안 본다.
        is_streaming_general = stream_recommendation_summary and llm_output.intent is Intent.GENERAL
        if settings.use_langgraph_early_return:
            # 2단계: 조기 반환 경로(Tool/Scoring 없이 끝나는 턴) 전체를 라우팅
            # 그래프가 맡는다(langgraph-adoption.md §6.1). RECOMMEND/MODIFY/
            # SCHEDULE은 아래로 내려가 기존 경로 그대로다 — 병행 운영이라 문제가
            # 보이면 USE_LANGGRAPH_EARLY_RETURN=false 하나로 즉시 되돌아간다.
            message = await run_early_return_graph(
                llm_output,
                llm=llm,
                stream_event_sink=stream_event_sink,
                stream_general=is_streaming_general,
            )
        else:
            if is_streaming_general:
                await _begin_streamed_message(
                    stream_event_sink,
                    intent=Intent.GENERAL,
                    progress_message="답변을 정리하고 있어요.",
                )

            async def emit_general_message_delta(text: str) -> None:
                await _emit_stream_event(stream_event_sink, "message_delta", {"text": text})

            message = await compose_chat_message(
                llm_output,
                llm=llm,
                on_message_delta=emit_general_message_delta if is_streaming_general else None,
            )
        return AgentResponse(
            llm_output=llm_output,
            state=state_response,
            recommendations=None,
            message=message,
            llm_execution=get_llm_execution_metadata(),
        )

    if settings.use_langgraph_pipeline:
        # 3단계: Tool 조회부터 응답 조립까지를 라우팅 그래프가 맡는다
        # (langgraph-adoption.md §6.1). 노드는 아래에서 떼어낸 단계 함수를 호출만
        # 하므로 동작은 아래 기존 경로와 같다 — 문제가 보이면
        # USE_LANGGRAPH_PIPELINE=false 하나로 되돌아간다.
        return await run_recommend_pipeline_graph(
            {
                "request": request,
                "llm_output": llm_output,
                "state_response": state_response,
                "valid_gps": valid_gps,
                "effective_ignore_operating_hours": effective_ignore_operating_hours,
                "stream_recommendation_summary": stream_recommendation_summary,
                "session_context": session_context,
                "tool_executions": [],
                "response": None,
            },
            deps=PipelineDeps(
                llm=llm,
                tool_provider=tool_provider,
                recommendation_provider=recommendation_provider,
                enrichment_provider=enrichment_provider,
                travel_route_tool=travel_route_tool,
                store=store,
                principal=principal,
            ),
            stream_event_sink=stream_event_sink,
        )

    tool_outcome = await _fetch_tool_context(
        request,
        llm_output,
        state_response,
        valid_gps=valid_gps,
        effective_ignore_operating_hours=effective_ignore_operating_hours,
        llm=llm,
        tool_provider=tool_provider,
        travel_route_tool=travel_route_tool,
        store=store,
        stream_event_sink=stream_event_sink,
    )
    if tool_outcome.terminal is not None:
        return tool_outcome.terminal
    assert tool_outcome.tool_context is not None
    assert tool_outcome.agent_conditions is not None
    tool_context = tool_outcome.tool_context
    agent_conditions = tool_outcome.agent_conditions
    context_gps = tool_outcome.context_gps
    tool_execution = tool_outcome.tool_execution
    tool_executions = tool_outcome.tool_executions

    is_schedule = llm_output.intent is Intent.SCHEDULE

    recommendations = await _score_recommendations(
        state_response,
        tool_context=tool_context,
        agent_conditions=agent_conditions,
        context_gps=context_gps,
        is_schedule=is_schedule,
        tool_provider=tool_provider,
        recommendation_provider=recommendation_provider,
        enrichment_provider=enrichment_provider,
        travel_route_tool=travel_route_tool,
        store=store,
        principal=principal,
        tool_executions=tool_executions,
        effective_ignore_operating_hours=effective_ignore_operating_hours,
        stream_event_sink=stream_event_sink,
    )

    if is_schedule:
        return await _run_schedule_branch(
            llm_output,
            state_response,
            recommendations,
            tool_context=tool_context,
            agent_conditions=agent_conditions,
            session_context=session_context,
            llm=llm,
            store=store,
            principal=principal,
            tool_execution=tool_execution,
            tool_executions=tool_executions,
            effective_ignore_operating_hours=effective_ignore_operating_hours,
            stream_event_sink=stream_event_sink,
        )

    return await _finalize_recommendation_response(
        llm_output,
        state_response,
        recommendations,
        llm=llm,
        store=store,
        principal=principal,
        tool_execution=tool_execution,
        tool_executions=tool_executions,
        effective_ignore_operating_hours=effective_ignore_operating_hours,
        stream_recommendation_summary=stream_recommendation_summary,
        stream_event_sink=stream_event_sink,
    )


@dataclass(frozen=True)
class _ToolFetchOutcome:
    """Tool 조회 결과. 여기서 끝날 수도, 다음 단계로 넘어갈 수도 있다.

    ``terminal``이 채워져 있으면 그 응답으로 이번 턴을 끝낸다(C가 되묻기·no_data·
    unsupported를 돌려준 경우). 비어 있으면 나머지 칸이 다음 단계 입력이 된다.
    """

    terminal: AgentResponse | None = None
    tool_context: RecommendationContext | None = None
    agent_conditions: UserConditions | None = None
    context_gps: str | None = None
    tool_execution: ToolExecutionDebug | None = None
    tool_executions: list[ToolExecutionDebug] = dataclass_field(default_factory=list)


async def _fetch_tool_context(
    request: AgentRequest,
    llm_output: LLMOutput,
    state_response: StateApplyResponse,
    *,
    valid_gps: str | None,
    effective_ignore_operating_hours: bool,
    llm: LLMProvider,
    tool_provider: ToolProvider,
    travel_route_tool: TravelRouteToolProvider | None,
    store: StateStore | None,
    stream_event_sink: StreamEventSink | None,
) -> _ToolFetchOutcome:
    """A → C Tool 조회와 종료 상태 판정(5단계).

    `run_agent_flow()`의 5단계 블록을 그대로 옮긴 것이다 — 라우팅 그래프가 이 단계를
    노드로 감쌀 수 있게 먼저 함수로 떼어냈다(langgraph-adoption.md §6.1 3단계).
    **본문은 한 줄도 바꾸지 않았고**, 중간 반환만 `_ToolFetchOutcome`으로 포장했다.
    """

    # 5) A → C: Tool 결과 확보 (Protocol을 통해서만 — C의 구체 클래스는 여기서 모른다).
    #    B가 준 조건(순수 문자열)을 A의 enum 타입으로 바꾼 뒤 C 계약 형태로 변환한다.
    #    conditions.weather(5단계 rain/snow/hot/cold/good)만 넘기고, api_context.api_weather
    #    (3단계 good/neutral/bad, Provider 정규화 값)는 여기 관여하지 않는다. GPS는
    #    사용자 조건과 별도 인자로 전달되어 Coordinates로 변환된다(계약 §5.2).
    agent_conditions = to_user_conditions(state_response.user_conditions)
    # 이번 요청의 유효한 GPS를 우선하고, 없으면 B에 저장된 신선한 GPS를 재사용한다.
    # 문자열은 A→C 변환 경계에서 Coordinates로 바뀌며 C는 원본 문자열을 알지 않는다.
    context_gps = valid_gps
    if context_gps is None and not state_response.api_context.gps_expired:
        context_gps = state_response.api_context.gps_location
    context_request = to_agent_context_request(
        request_id=new_trace_id(),
        conditions=agent_conditions,
        gps_location=context_gps,
        # D에 넘기는 것과 같은 소진분을 C에도 넘긴다. C는 이걸로 판정하지 않고
        # 수집 범위를 그만큼 넓히는 데만 쓴다 — 안 넘기면 "다른 곳 보여줘"에
        # 같은 후보가 다시 와서 D가 전부 걸러내고 0건이 된다.
        excluded_place_ids=state_response.excluded_place_ids,
    )
    await _emit_progress(
        stream_event_sink,
        "fetching_context",
        "장소·운영시간·날씨 정보를 찾고 있어요.",
    )
    tool_started_at = time.monotonic()
    tool_response = await tool_provider.fetch_context(context_request)
    tool_latency_ms = int((time.monotonic() - tool_started_at) * 1000)
    # 개발자용 Audit 표시 정보. 아래 어느 경로로 응답이 끝나든 C를 호출한 사실은
    # 남아야 하므로 여기서 한 번만 만들어 모든 return에 함께 싣는다.
    tool_execution = build_tool_execution_debug(
        tool_response, latency_ms=tool_latency_ms, conditions=agent_conditions
    )
    tool_executions = [tool_execution] if tool_execution is not None else []
    _record_trace_safely(
        session_id=state_response.session_id,
        run_id=state_response.run_id,
        step="tool_fetch",
        latency_ms=tool_latency_ms,
        error_type=(
            tool_response.status if tool_response.status in _TOOL_TERMINAL_STATUSES else None
        ),
        store=store,
    )

    # 5-1) C 단계 자체의 needs_clarification/unsupported/unavailable — LLM 단계
    #      needs_clarification(4번)과 같은 방식으로 여기서 바로 응답을 끝낸다.
    if tool_response.status in _TOOL_TERMINAL_STATUSES:
        if tool_response.status == "needs_clarification" and tool_response.error is not None:
            # 계약(§5.5)상 needs_clarification이면 error는 항상 null이어야 한다. 위반이면
            # 흐름을 막지 않고 로그만 남긴다 — A가 사용자에게 재질문하는 데는 지장이 없다.
            logger.warning(
                "C 응답이 needs_clarification인데 error도 채워짐(계약 위반 의심): "
                "request_id=%s clarification=%s error=%s",
                tool_response.request_id,
                tool_response.clarification,
                tool_response.error,
            )
        if tool_response.status == "needs_clarification":
            code = (
                tool_response.clarification.code
                if tool_response.clarification is not None
                else "clarification_required"
            )
            _remember_clarification(state_response.session_id, code, store)
            if code == "location_required":
                # 서비스 지역이 종로구 한정이라(D-044) 대표 스팟 고정 버튼을 제공한다
                # (docs/design/clarification-options.md 7절, A2). resolved_intent는
                # 이번 턴의 intent를 그대로 표시용으로 담는다 — 실제 해소는 다음 턴에
                # last_intent로 복원한다(_resolve_clarification_choice).
                llm_output = llm_output.model_copy(
                    update={
                        "status": OutputStatus.NEEDS_CLARIFICATION,
                        "clarification": ClarificationPayload(
                            message=tool_clarification_message(code),
                            options=[
                                ClarificationOption(
                                    id=name,
                                    label=f"{name} 근처",
                                    resolved_intent=llm_output.intent,
                                )
                                for name in _LOCATION_REQUIRED_QUICK_PICKS
                            ],
                        ),
                    }
                )
            elif code == "location_ambiguous" and tool_response.clarification is not None:
                # 동명이인 장소 후보(Tool이 실제로 찾아낸 지하철역·명소 이름)를
                # 버튼으로 준다. resolve_location.py가 이미 식당·상점류는 걸러내고
                # 넘긴다 — 여기서 candidates가 비어 있으면(전부 식당·상점뿐이었거나
                # 지오코딩 경로라 이름 자체를 모르면) 식당을 보여주는 대신 A2와 같은
                # 종로구 대표 스팟 고정 버튼으로 대신한다(실사용 피드백, 2026-08-13:
                # "그냥 지하철역으로만 가자").
                found_candidates = tool_response.clarification.candidates
                if found_candidates:
                    message = tool_clarification_message(code)
                    options = [
                        ClarificationOption(id=name, label=name, resolved_intent=llm_output.intent)
                        for name in found_candidates
                    ]
                else:
                    message = (
                        "말씀하신 목적지 범위가 여러곳으로 해석돼요. "
                        f"{supported_district_label()} 안에서 이런 곳들은 어떠세요? "
                        "아니면, 좀 더 자세히 말씀해주시겠어요?"
                    )
                    options = [
                        ClarificationOption(
                            id=name, label=f"{name} 근처", resolved_intent=llm_output.intent
                        )
                        for name in _LOCATION_REQUIRED_QUICK_PICKS
                    ]
                llm_output = llm_output.model_copy(
                    update={
                        "status": OutputStatus.NEEDS_CLARIFICATION,
                        "clarification": ClarificationPayload(
                            message=message,
                            options=options,
                        ),
                    }
                )
        elif tool_response.status == "no_data":
            # 원인2(이전 노출/거절로 소진)와 원인1+3(TourAPI 자체가 0건)을
            # provider_metadata의 원본 상태로 구분한다 — 위 상수 블록 주석 참고.
            places_value = (
                tool_response.context.places if tool_response.context is not None else None
            )
            provider_statuses = {
                item.status for item in (places_value.provider_metadata if places_value else [])
            }
            if "success" in provider_statuses:
                no_data_code = "no_data_exhausted"
                no_data_message = _NO_DATA_EXHAUSTED_MESSAGE
                no_data_options = _NO_DATA_EXHAUSTED_OPTIONS
            else:
                no_data_code = "no_data_empty"
                no_data_message = _NO_DATA_EMPTY_MESSAGE
                no_data_options = _NO_DATA_EMPTY_OPTIONS
            # "검색 범위를 넓혀볼까요?"에 대한 답변은 새 요청이 아니라 이번 요청을
            # 이어가는 발화다. 표시해두지 않으면 다음 턴이 RECOMMEND로 분류되면서
            # soft reset이 걸려 앞 턴 조건(장소·태그)이 사라진다(D-039와 같은 이유).
            _remember_clarification(state_response.session_id, no_data_code, store)
            llm_output = llm_output.model_copy(
                update={
                    "status": OutputStatus.NEEDS_CLARIFICATION,
                    "clarification": ClarificationPayload(
                        code=no_data_code,
                        message=no_data_message,
                        options=[
                            ClarificationOption(
                                id=option_id, label=label, resolved_intent=llm_output.intent
                            )
                            for option_id, label in no_data_options
                        ],
                    ),
                }
            )
        message = await compose_chat_message(
            llm_output,
            tool_status=tool_response.status,
            tool_clarification=tool_response.clarification,
            tool_error_code=tool_response.error.code if tool_response.error else None,
            llm=llm,
        )
        return _ToolFetchOutcome(
            terminal=AgentResponse(
                llm_output=llm_output,
                state=state_response,
                recommendations=None,
                message=message,
                llm_execution=get_llm_execution_metadata(),
                tool_execution=tool_execution,
                tool_executions=tool_executions,
            )
        )

    # success/partial은 Recommendation 단계로 진행한다(경고가 있어도 가능한 데이터로
    # 계속 — 계약 문서 §5.4). 위에서 종료 상태를 걸렀으므로 context는 항상 있다.
    # AgentContextResponse.warnings(최상위)만 지금은 보고 넘어간다.
    # TODO(자연어 응답 생성 단계): RecommendationContext의 항목별 ContextValue.warnings
    # (예: weather.warnings)까지 합쳐서 사용자에게 보여줄지 다시 검토한다.
    tool_context = tool_response.context
    if tool_context is None:
        # success/partial은 Schema가 Context를 강제하지만 no_data는 아직 None을 허용한다.
        # 잘못되거나 불완전한 C 응답을 D에 전달하지 않고 이번 실행을 안전하게 끝낸다.
        logger.warning(
            "C 응답에 RecommendationContext가 없음: request_id=%s status=%s",
            tool_response.request_id,
            tool_response.status,
        )
        message = await compose_chat_message(llm_output, tool_status=tool_response.status, llm=llm)
        return _ToolFetchOutcome(
            terminal=AgentResponse(
                llm_output=llm_output,
                state=state_response,
                recommendations=None,
                message=message,
                llm_execution=get_llm_execution_metadata(),
                tool_execution=tool_execution,
                tool_executions=tool_executions,
            )
        )

    return _ToolFetchOutcome(
        tool_context=tool_context,
        agent_conditions=agent_conditions,
        context_gps=context_gps,
        tool_execution=tool_execution,
        tool_executions=tool_executions,
    )


async def _score_recommendations(
    state_response: StateApplyResponse,
    *,
    tool_context: RecommendationContext,
    agent_conditions: UserConditions,
    context_gps: str | None,
    is_schedule: bool,
    tool_provider: ToolProvider,
    recommendation_provider: RecommendationProvider,
    enrichment_provider: EnrichmentProvider,
    travel_route_tool: TravelRouteToolProvider | None,
    store: StateStore | None,
    principal: Principal | None,
    tool_executions: list[ToolExecutionDebug],
    effective_ignore_operating_hours: bool,
    stream_event_sink: StreamEventSink | None,
) -> RecommendationResponse:
    """1차 Scoring과 후보 보충·혼잡도 재정렬까지 끝난 추천 결과를 돌려준다(6단계).

    `run_agent_flow()`의 6단계 블록을 그대로 옮긴 것이다 — 라우팅 그래프가 이 단계를
    노드로 감쌀 수 있게 먼저 함수로 떼어냈다(langgraph-adoption.md §6.1 3단계).
    **본문은 한 줄도 바꾸지 않았다.** 이 구간에는 중간 반환이 없어 결과 하나만
    돌려주면 되는, 경계가 가장 깨끗한 단계다.
    """

    # 6) A → D: 1차 Scoring (Protocol을 통해서만 — D의 구체 클래스는 여기서 모른다).
    #    최종 반환은 RECOMMEND/MODIFY가 recommendation_result_limit, SCHEDULE이
    #    recommendation_candidate_limit을 쓴다(docs/design/int-07-schedule.md 2절/5절).
    #
    #    보충 조회 목표(candidate_target)는 recommendation_candidate_limit이다 —
    #    하드 필터를 통과한 후보를 설정된 후보 상한만큼 모아두고 그 안에서 고른다.
    #    (읽는 사람이 다시 파지 않도록 짚어둔다: C가 한 번에 반환하는 최대 후보 수도
    #    같은 설정값이라, 첫 조회에서 한 곳이라도 걸러지면 이 목표에는 도달할 수 없다.
    #    그래서 실제 동작은 "목표를 채운다"가 아니라 "_MAX_CANDIDATE_REFILL_ATTEMPTS
    #    회까지 더 긁어 모은다"에 가깝고, 후보가 넉넉한 지역에서는 C 호출이 최대 3회로
    #    늘어난다. 반경에 후보가 적으면 _candidate_pool_exhausted()가 첫 조회에서
    #    잡아내 보충하지 않는다.)
    candidate_target = settings.recommendation_candidate_limit
    recommendation_limit = (
        settings.recommendation_candidate_limit
        if is_schedule
        else settings.recommendation_result_limit
    )
    await _emit_progress(
        stream_event_sink,
        "scoring",
        "조건에 맞게 장소 순위를 계산하고 있어요.",
    )
    scoring_started_at = time.monotonic()
    if isinstance(recommendation_provider, StagedRecommendationProvider):
        # 같은 실행의 모든 prepare가 동일한 운영시간 기준을 사용해야 한다. B 세션에는
        # 저장하지 않고 이 실행 동안만 고정한다.
        visit_at = now_kst()
        prepared_batches = [
            await recommendation_provider.prepare(
                agent_conditions,
                tool_context,
                state_response.excluded_place_ids,
                visit_at=visit_at,
                ignore_operating_hours=effective_ignore_operating_hours,
            )
        ]
        run_seen_ids = _context_place_ids(tool_context)
        run_seen_id_set = set(run_seen_ids)
        candidate_pool_exhausted = _candidate_pool_exhausted(tool_context)

        for refill_attempt in range(1, _MAX_CANDIDATE_REFILL_ATTEMPTS + 1):
            merged_prepared = recommendation_provider.merge_prepared(prepared_batches)
            if (
                merged_prepared.preparation.eligible_count >= candidate_target
                or candidate_pool_exhausted
            ):
                break

            refill_request = to_agent_context_request(
                request_id=new_trace_id(),
                conditions=agent_conditions,
                gps_location=context_gps,
                excluded_place_ids=[
                    *state_response.excluded_place_ids,
                    *(
                        place_id
                        for place_id in run_seen_ids
                        if place_id not in state_response.excluded_place_ids
                    ),
                ],
            )
            # stage는 "scoring"을 유지한다 — 프론트가 stage로 진행 순서를 그리므로
            # 여기서 fetching_context로 되돌리면 진행 표시가 뒤로 간다. 문구만 바꾼다
            # (AgentProgressMessage.tsx가 detail을 서버 message로 덮어쓴다).
            await _emit_progress(
                stream_event_sink,
                "scoring",
                "조건에 맞는 장소를 조금 더 찾고 있어요.",
            )
            refill_started_at = time.monotonic()
            refill_response = await tool_provider.fetch_context(refill_request)
            refill_latency_ms = int((time.monotonic() - refill_started_at) * 1000)
            refill_execution = build_tool_execution_debug(
                refill_response,
                latency_ms=refill_latency_ms,
                conditions=agent_conditions,
            )
            if refill_execution is not None:
                tool_executions.append(refill_execution)
            _record_trace_safely(
                session_id=state_response.session_id,
                run_id=state_response.run_id,
                step=f"tool_refill_{refill_attempt}",
                latency_ms=refill_latency_ms,
                error_type=(
                    refill_response.status
                    if refill_response.status in _TOOL_TERMINAL_STATUSES
                    else None
                ),
                store=store,
            )

            # 최초 조회에서 이미 사용할 후보가 있으므로, 보충 조회 실패는 전체 요청을
            # 실패시키지 않고 확보된 후보로 진행한다.
            if refill_response.status in _TOOL_TERMINAL_STATUSES:
                break
            refill_context = refill_response.context
            if refill_context is None:
                break

            refill_place_ids = _context_place_ids(refill_context)
            new_place_ids = [
                place_id for place_id in refill_place_ids if place_id not in run_seen_id_set
            ]
            if not new_place_ids:
                break
            run_seen_ids.extend(new_place_ids)
            run_seen_id_set.update(new_place_ids)

            try:
                refill_prepared = await recommendation_provider.prepare(
                    agent_conditions,
                    refill_context,
                    state_response.excluded_place_ids,
                    visit_at=visit_at,
                    ignore_operating_hours=effective_ignore_operating_hours,
                )
            except AppError:
                # 보충 Context가 장소는 실었지만 location이 없거나 places가
                # unavailable인 경우다. 위와 같은 이유로 확보분으로 진행한다.
                break

            # 보충 조회가 날씨를 다시 조회해 값이 달라져도 여기서 배치를 버리지
            # 않는다 — merge_prepared()가 첫 배치의 판정 기준을 그대로 재사용한다.
            # 모든 prepare에 같은 visit_at/ignore_operating_hours를 넘기는 것만
            # 지키면 된다(그 둘이 어긋나면 merge_prepared()가 ValueError를 던진다).
            prepared_batches.append(refill_prepared)
            tool_context = _merge_recommendation_context_places(
                tool_context,
                refill_context,
            )
            candidate_pool_exhausted = _candidate_pool_exhausted(refill_context)

        merged_prepared = recommendation_provider.merge_prepared(prepared_batches)
        travel_routes = await _fetch_travel_routes(
            travel_route_tool,
            tool_context,
            merged_prepared,
            to_travel_mode(agent_conditions),
            agent_conditions,
        )
        recommendations = await recommendation_provider.score_prepared(
            agent_conditions,
            merged_prepared,
            travel_routes=travel_routes,
            limit=recommendation_limit,
        )
    else:
        recommendations = await recommendation_provider.recommend(
            agent_conditions,
            tool_context,
            state_response.excluded_place_ids,
            limit=recommendation_limit,
            ignore_operating_hours=effective_ignore_operating_hours,
        )
    _record_trace_safely(
        session_id=state_response.session_id,
        run_id=state_response.run_id,
        step="scoring",
        latency_ms=int((time.monotonic() - scoring_started_at) * 1000),
        scoring_version=SCORING_VERSION,
        store=store,
    )

    # 6-1) concentration_intent가 AVOID/SEEK일 때만: 1차 상위 후보의 혼잡도를 C에
    #      보강 조회하고, D의 2차 Scoring(재순위)으로 그 결과를 교체한다(D-040 확정 —
    #      concentration-conditions.md §2.2.3, agent-runtime-contract.md §6.5.2).
    #      분기 로직은 _apply_concentration_rerank()로 분리했다 — B의
    #      concentration_intent 필드 등록 완료(2026-08-05, B-06, PR #78) 이후로는
    #      run_agent_flow() 전체 통합 테스트로도 exercise되지만(§7 참고), agent_
    #      conditions만으로 독립 단위 테스트할 수 있는 이점이 있어 구조는 유지한다.
    #      final_limit을 recommendation_limit과 맞춰야 SCHEDULE의 10개가 재순위 후
    #      5개로 조용히 잘리지 않는다.
    recommendations = await _apply_concentration_rerank(
        agent_conditions,
        tool_context,
        recommendations,
        recommendation_provider=recommendation_provider,
        enrichment_provider=enrichment_provider,
        final_limit=recommendation_limit,
        execution_collector=tool_executions,
    )

    # 6-1) A → B: D의 하드 필터(_is_closed)가 폐점이라 걸러낸 후보 id를 기록한다
    #      (TP-82). 이 후보들은 recommendations/unverified_recommendations
    #      어디에도 담기지 않아 아래 record_recommendation()의 노출 이력 경로를
    #      탈 수 없다 — 그래서 기록하지 않으면 다음 회차 후보 수집에서 매번
    #      다시 뽑혀, 밤 시간대처럼 폐점 비율이 높을 때 "다른 곳 보여줘"를
    #      반복하면 카드 수가 점점 줄어드는 문제로 이어진다. SCHEDULE/RECOMMEND/
    #      MODIFY 어느 경로든 D 응답은 여기서 이미 확정됐으므로, 분기 전에 한
    #      번만 기록해 두 경로에 중복하지 않는다.
    if recommendations.excluded_closed_place_ids:
        record_closed_exclusions(
            RecordClosedExclusionsRequest(
                session_id=state_response.session_id,
                run_id=state_response.run_id,
                place_ids=recommendations.excluded_closed_place_ids,
            ),
            store=store,
            principal=principal,
        )
    return recommendations


async def _run_schedule_branch(
    llm_output: LLMOutput,
    state_response: StateApplyResponse,
    recommendations: RecommendationResponse,
    *,
    tool_context: RecommendationContext,
    agent_conditions: UserConditions,
    session_context: SessionContextResponse,
    llm: LLMProvider,
    store: StateStore | None,
    principal: Principal | None,
    tool_execution: ToolExecutionDebug | None,
    tool_executions: list[ToolExecutionDebug],
    effective_ignore_operating_hours: bool,
    stream_event_sink: StreamEventSink | None,
) -> AgentResponse:
    """SCHEDULE 편성 분기(6-2단계)를 처리한다.

    `run_agent_flow()`의 `if is_schedule:` 블록을 그대로 옮긴 것이다 — 라우팅 그래프가
    이 단계를 노드로 감쌀 수 있게 먼저 함수로 떼어냈다(langgraph-adoption.md §6.1
    3단계). **본문은 한 줄도 바꾸지 않았다**(들여쓰기만 한 단계 내어썼다).
    """

    # 6-2) A: C의 AgentContextResponse.places(위경도)를 place_id로 매칭해
    #      pairwise_distances_km 계산 → 일정 편성 모듈 호출(docs/design/
    #      int-07-schedule.md 4절/6절). 상태 저장소 비접근 — D를 부르는 것과
    #      동일한 방식.
    schedule_candidates = [
        *recommendations.recommendations,
        *recommendations.unverified_recommendations,
    ]
    # 후보가 전부 폐점 때문에 제외됐으면(D가 excluded_all_closed로 표시) 일정을
    # 못 짠 진짜 원인이 "지역/카테고리 부족"이 아니라 "운영시간"이다 — 그런데도
    # 아래 schedule_no_candidates로 넘어가면 지역/카테고리를 아무리 바꿔도 같은
    # 이유로 계속 실패해 무한 되묻기가 된다(실사용 재현, 2026-08-13). RECOMMEND/
    # MODIFY 경로와 동일하게 "운영 중이 아닌 곳도 볼게요"를 먼저 제안한다.
    if (
        not schedule_candidates
        and recommendations.excluded_all_closed
        and not effective_ignore_operating_hours
    ):
        return await _respond_no_data_closed(
            llm_output,
            state_response,
            store=store,
            llm=llm,
            tool_execution=tool_execution,
            tool_executions=tool_executions,
        )
    places = tool_context.places.data if tool_context.places and tool_context.places.data else []

    # 6-2-1) SCHEDULE-09 2단계: REJECT_SPECIFIC으로 재라우팅된 턴이면 통째로
    #        새로 짜지 않고, target_indices가 가리키는 자리만 새로 채운다.
    #        session_context는 이번 턴 처리 전에 조회한 값이라 직전 SCHEDULE
    #        턴의 shown_recommendations(순서·도착시각 등 포함)를 그대로 담고
    #        있다(3-3절과 동일한 전제). pinned 대상의 place_name은 이번 턴
    #        C 응답에서 다시 매칭하지 않고 B에 저장된 값을 그대로 쓴다 —
    #        원래는 재매칭하도록 짰다가, "경복궁"류 지명 검색이 호출마다
    #        다른 좌표로 resolve돼 이번 턴 주변 후보가 매번 통째로 달라지는
    #        사례가 실사용 테스트에서 확인됐다(2026-08-11). 그러면 이전
    #        place_id가 이번 후보에 전혀 안 잡혀 pinned 유지가 매번 실패하고
    #        REJECT_ALL처럼 조용히 전체 재편성으로 폴백됐다. B가 추천 시점에
    #        이름도 함께 저장해두면(schema.RecommendedItem.name, SCHEDULE-09
    #        2단계 예외) 이 재검색에 의존하지 않아 안정적이다.
    pinned_items: list[ScheduleItem] = []
    if (
        llm_output.modify is not None
        and llm_output.modify.modify_type is ModifyType.REJECT_SPECIFIC
    ):
        target_orders = set(llm_output.modify.target_indices)
        for prev in session_context.shown_recommendations:
            if prev.rank in target_orders:
                continue
            if (
                prev.name is None
                or prev.estimated_arrival is None
                or prev.estimated_duration_min is None
            ):
                # 방어적 폴백 — SCHEDULE-09 2단계 도입 이전에 기록된 세션처럼
                # 이 필드들이 없는 과거 데이터일 때만 해당하며, 이 항목만 새
                # 후보로 채워지고 나머지는 정상적으로 유지된다. 4개 필드
                # (estimated_arrival~reason)는 SCHEDULE-06에서 한꺼번에
                # 추가돼 따로 없을 일은 거의 없지만, name/estimated_arrival만
                # 체크하고 estimated_duration_min은 빠져 있으면 아래에서
                # `or 0`으로 조용히 체류시간 0분짜리 pinned 항목이 만들어질
                # 수 있었다 — 가드를 맞춰 방지한다(실사용 리뷰로 발견,
                # 2026-08-13). travel_to_next_min은 원래 마지막 항목이면
                # None이 정상이라 이 가드에 넣지 않는다.
                continue
            pinned_items.append(
                ScheduleItem(
                    order=prev.rank,
                    place_id=prev.place_id,
                    place_name=prev.name,
                    estimated_arrival=prev.estimated_arrival,
                    estimated_duration_min=prev.estimated_duration_min,
                    travel_to_next_min=prev.travel_to_next_min,
                    reason=prev.reason or "",
                )
            )

    if pinned_items and llm_output.modify is not None:
        partial_request = SchedulePartialFillRequest(
            pinned_items=pinned_items,
            target_orders=sorted(set(llm_output.modify.target_indices)),
            candidates=schedule_candidates,
            conditions=agent_conditions,
            visit_datetime=None,
            pairwise_distances_km=_build_pairwise_distances_km(schedule_candidates, places),
        )
        await _emit_progress(
            stream_event_sink,
            "scheduling",
            "기존 일정은 유지하고 바꿀 장소를 다시 편성하고 있어요.",
        )
        schedule_result = await _await_with_heartbeat(
            plan_partial_schedule(partial_request, llm),
            sink=stream_event_sink,
            stage="scheduling",
        )
    else:
        schedule_request = SchedulePlanningRequest(
            candidates=schedule_candidates,
            conditions=agent_conditions,
            visit_datetime=None,
            pairwise_distances_km=_build_pairwise_distances_km(schedule_candidates, places),
        )
        await _emit_progress(
            stream_event_sink,
            "scheduling",
            "장소 순서와 머무는 시간을 구성하고 있어요.",
        )
        schedule_result = await _await_with_heartbeat(
            plan_schedule(schedule_request, llm),
            sink=stream_event_sink,
            stage="scheduling",
        )

    await _emit_progress(
        stream_event_sink,
        "composing_message",
        "일정 결과를 정리하고 있어요.",
    )

    # 7) A → B: 일정에 실제로 포함된 장소만 기록한다(6.3절) — LLM이 제외한
    #    후보는 기록하지 않아 이후 RECOMMEND 요청에서 재노출될 수 있다.
    if schedule_result.items:
        record_recommendation(
            RecordRecommendationRequest(
                session_id=state_response.session_id,
                run_id=state_response.run_id,
                recommended=[
                    RecommendedPlace(
                        place_id=item.place_id,
                        rank=item.order,
                        name=item.place_name,
                        estimated_arrival=item.estimated_arrival,
                        estimated_duration_min=item.estimated_duration_min,
                        travel_to_next_min=item.travel_to_next_min,
                        reason=item.reason,
                    )
                    for item in schedule_result.items
                ],
            ),
            store=store,
            principal=principal,
        )
    else:
        # 후보가 부족해서 일정을 못 짠 경우, route_summary 메시지만 반환하지 말고
        # 명시적 되묻기로 사용자에게 선택지를 준다(실사용 피드백, 2026-08-13).
        # 버튼 클릭이 SCHEDULE intent로 올바르게 라우팅되어야 다시 SCHEDULE을 시도하지,
        # 프론트가 텍스트 파싱으로 버튼을 만들면 LLM 분류가 틀린다.
        llm_output = llm_output.model_copy(
            update={
                "status": OutputStatus.NEEDS_CLARIFICATION,
                "clarification": ClarificationPayload(
                    code="schedule_no_candidates",
                    message=_SCHEDULE_NO_CANDIDATES_MESSAGE,
                    options=[
                        ClarificationOption(
                            id=option_id,
                            label=label,
                            resolved_intent=Intent.SCHEDULE,
                        )
                        for option_id, label in _SCHEDULE_NO_CANDIDATES_OPTIONS
                    ],
                ),
            }
        )
        _remember_clarification(state_response.session_id, "schedule_no_candidates", store)
        message = await compose_chat_message(llm_output, llm=llm)
        return AgentResponse(
            llm_output=llm_output,
            state=state_response,
            recommendations=None,
            schedule=None,
            message=message,
            llm_execution=get_llm_execution_metadata(),
            tool_execution=tool_execution,
            tool_executions=tool_executions,
        )

    # 8) A: 최종 응답 조립. recommendations는 채우지 않는다(AgentResponse
    #    docstring — schedule과 동시에 채워지지 않음).
    message = await compose_chat_message(
        llm_output,
        schedule=schedule_result,
        schedule_time_available_min=agent_conditions.time_available,
        llm=llm,
    )
    return AgentResponse(
        llm_output=llm_output,
        state=state_response,
        recommendations=None,
        schedule=schedule_result,
        message=message,
        llm_execution=get_llm_execution_metadata(),
        tool_execution=tool_execution,
        tool_executions=tool_executions,
    )


async def _finalize_recommendation_response(
    llm_output: LLMOutput,
    state_response: StateApplyResponse,
    recommendations: RecommendationResponse,
    *,
    llm: LLMProvider,
    store: StateStore | None,
    principal: Principal | None,
    tool_execution: ToolExecutionDebug | None,
    tool_executions: list[ToolExecutionDebug],
    effective_ignore_operating_hours: bool,
    stream_recommendation_summary: bool,
    stream_event_sink: StreamEventSink | None,
) -> AgentResponse:
    """RECOMMEND/MODIFY 결과를 이력에 남기고 카드·요약을 방출한다(7·8단계).

    `run_agent_flow()`의 꼬리를 그대로 옮긴 것이다 — 라우팅 그래프가 이 단계를 노드로
    감쌀 수 있게 먼저 함수로 떼어냈다(docs/design/langgraph-adoption.md §6.1 3단계).
    **본문은 한 줄도 바꾸지 않았다**: 이관은 출력이 같아야 하는 작업이라, 옮기는 것과
    고치는 것을 같은 커밋에 섞지 않는다.
    """

    # 7) A → B: 실제로 화면에 노출된 결과만 기록한다. recommendations와
    #    unverified_recommendations 둘 다 프론트에 렌더링되므로(운영시간 미검증 섹션으로
    #    구분되어 보일 뿐 노출 자체는 됨) 함께 기록한다 — 계산만 하고 안 보여준 건 넣지
    #    않아야 "다른 곳 보여줘"의 제외 목록이 정확해진다.
    #    distance_km/remaining_minutes/environment_type도 함께 기록한다 —
    #    COMPARE가 "추천 시 이미 계산된 데이터"를 그대로 쓸 수 있게 하는
    #    Feature 스냅샷이다(COMPARE 데이터 출처 A안, 2026-08-11).
    shown = [*recommendations.recommendations, *recommendations.unverified_recommendations]
    # 결과 0건이 전부 폐점 후보 제외 때문이면(D가 excluded_all_closed로 표시)
    # 일반 _NO_DATA_MESSAGE 대신 "운영중이 아닌 곳도 볼래요" 되묻기를 띄운다.
    # 이미 그 선택지로 재조회했거나 TTL 안이라 계속 무시 중인데도 여전히
    # 0건이면(ignore_operating_hours=True인데 excluded_all_closed) 무한
    # 되묻기를 피하려고 다시 띄우지 않고 그대로 진행한다.
    if not shown and recommendations.excluded_all_closed and not effective_ignore_operating_hours:
        return await _respond_no_data_closed(
            llm_output,
            state_response,
            store=store,
            llm=llm,
            tool_execution=tool_execution,
            tool_executions=tool_executions,
        )
    if shown:
        record_recommendation(
            RecordRecommendationRequest(
                session_id=state_response.session_id,
                run_id=state_response.run_id,
                recommended=[
                    RecommendedPlace(
                        place_id=item.place_id,
                        rank=index + 1,
                        name=item.name,
                        distance_km=item.distance_km,
                        remaining_minutes=item.remaining_minutes,
                        environment_type=item.environment_type,
                    )
                    for index, item in enumerate(shown)
                ],
            ),
            store=store,
            principal=principal,
        )

    # 8) A: 추천 카드와 LLM 요약을 같은 시점부터 화면에 보인다. 이전에는 카드(result)를
    #    먼저 내보내고 한참 뒤 요약을 시작해, 화면상 카드가 "답변 생성 중" 말풍선보다
    #    먼저 나타났다. 스트리밍일 때는 첫 텍스트 조각을 보낸 직후 result를 내보내므로
    #    답변이 실제로 시작되는 순간 카드도 함께 노출된다.
    result_payload = {
        "llm_output": llm_output.model_dump(mode="json"),
        "state": state_response.model_dump(mode="json"),
        "recommendations": recommendations.model_dump(mode="json"),
    }
    result_emitted = False

    async def emit_recommendation_result() -> None:
        nonlocal result_emitted
        if result_emitted:
            return
        await _emit_stream_event(stream_event_sink, "result", result_payload)
        result_emitted = True

    if stream_recommendation_summary:
        await _begin_streamed_message(
            stream_event_sink,
            intent=llm_output.intent,
            progress_message="추천 결과를 안내하고 있어요.",
        )
    else:
        # 스트리밍을 사용하지 않는 호출자는 기존처럼 결과를 즉시 관측한다.
        await emit_recommendation_result()

    async def emit_message_delta(text: str) -> None:
        await _emit_stream_event(stream_event_sink, "message_delta", {"text": text})
        # 프론트는 message_delta를 먼저 처리해 답변 말풍선을 연 뒤 result를 처리한다.
        # 따라서 카드가 말풍선보다 앞서 보이지 않는다.
        await emit_recommendation_result()

    message = await compose_chat_message(
        llm_output,
        recommendations=recommendations,
        llm=llm,
        on_message_delta=(emit_message_delta if stream_recommendation_summary else None),
    )
    # Provider가 빈 스트림을 반환하는 예외적 경우에도 카드가 영구히 보이지 않지 않도록
    # 마지막에 한 번 보장한다. 정상 스트림에서는 첫 delta에서 이미 전송됐다.
    await emit_recommendation_result()
    return AgentResponse(
        llm_output=llm_output,
        state=state_response,
        recommendations=recommendations,
        message=message,
        llm_execution=get_llm_execution_metadata(),
        tool_execution=tool_execution,
        tool_executions=tool_executions,
    )


async def run_agent(
    request: AgentRequest,
    *,
    principal: Principal | None = None,
    stream_event_sink: StreamEventSink | None = None,
    stream_recommendation_summary: bool = False,
) -> AgentResponse:
    """호출자가 쓰는 Fake/Real 공통 진입점.

    A는 조건 기반 ContextProvider 계약만 알고, C 내부 Tool·Provider 조립은
    app.agent_context.factory에 위임한다. D 계약이 확정되어([TECH-02])
    RealRecommendationProvider를 기본으로 주입한다.
    """

    from app.agent_context.factory import get_candidate_enrichment_service, get_context_provider
    from app.providers.factory import (
        get_llm_provider,
        get_place_evidence_provider,
        get_travel_route_tool,
    )
    from app.services.runtime.real_recommendation_provider import RealRecommendationProvider

    async with create_external_client() as client:
        return await run_agent_flow(
            request,
            llm=get_llm_provider(),
            tool_provider=get_context_provider(client),
            recommendation_provider=RealRecommendationProvider(get_place_evidence_provider(client)),
            enrichment_provider=get_candidate_enrichment_service(client),
            travel_route_tool=get_travel_route_tool(client),
            principal=principal,
            stream_event_sink=stream_event_sink,
            stream_recommendation_summary=stream_recommendation_summary,
        )


__all__ = ["StreamEventSink", "run_agent", "run_agent_flow", "summarize_turn"]
