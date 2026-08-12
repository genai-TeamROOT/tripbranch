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

import logging
import time

from app.agent_context.schemas import PlaceCandidate, RecommendationContext
from app.domain.scoring import SCORING_VERSION
from app.geo import haversine_km
from app.observability.api_usage import create_external_client
from app.providers.gemini_prompts import PROMPT_VERSION
from app.providers.protocols import LLMProvider
from app.schedule.planner import plan_partial_schedule, plan_schedule
from app.schedule.schemas import SchedulePartialFillRequest, SchedulePlanningRequest
from app.schemas import (
    AgentRequest,
    AgentResponse,
    ComparisonResult,
    ConcentrationIntent,
    Intent,
    InterpretRequest,
    LLMOutput,
    ModifyType,
    OutputStatus,
    RecommendationItem,
    RecommendationResponse,
    ScheduleItem,
    ToolExecutionDebug,
    UserConditions,
)
from app.services.interpret.orchestrator import build_interpretation
from app.services.interpret.session_orchestrator import ensure_current_context
from app.services.interpret.state_transform import to_user_conditions, transform
from app.services.runtime.compare_transform import (
    to_compare_context_request,
    to_comparison_result,
)
from app.services.runtime.context_transform import to_agent_context_request
from app.services.runtime.enrichment_transform import to_candidate_enrichment_request
from app.services.runtime.info_context_transform import to_info_context_request
from app.services.runtime.info_response_transform import to_info_place_card
from app.services.runtime.llm_execution import (
    get_llm_execution_metadata,
    reset_llm_execution_metadata,
)
from app.services.runtime.protocols import EnrichmentProvider, RecommendationProvider, ToolProvider
from app.services.runtime.response_composer import compose_chat_message, compose_compare_message
from app.services.runtime.tool_debug import (
    build_candidate_enrichment_execution_debug,
    build_compare_execution_debug,
    build_info_concentration_execution_debug,
    build_tool_execution_debug,
)
from app.state.schema import now_kst
from app.state.service import (
    RecommendedPlace,
    RecordRecommendationRequest,
    RecordTraceRequest,
    SetLastIntentRequest,
    SetPendingClarificationRequest,
    UpdateApiContextRequest,
    apply,
    record_recommendation,
    record_trace,
    set_last_intent,
    set_pending_clarification,
    update_api_context,
)
from app.state.session import new_trace_id
from app.state.store import StateStore

logger = logging.getLogger(__name__)


def _llm_clarification_code(llm_output: LLMOutput) -> str | None:
    """LLM 단계 되묻기를 단일 코드로 정규화한다.

    LLM은 missing_fields/ambiguous_fields 목록으로, C는 location_required 같은 단일
    코드로 되묻는다. B에는 한 가지 표현만 저장하므로 여기서 맞춘다 — 값 자체는
    "무엇을 되물었는지" 기록용이고, 다음 턴의 판단은 "값이 있는지"만 본다.
    """
    clarification = llm_output.clarification
    if clarification is None:
        return "clarification_required"
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
    store: StateStore | None,
) -> None:
    """실행 단계 1건을 B에 기록한다. (llmops-trace-contract-v1.md AF-12, B-07)

    variant_id는 아직 값을 안 줘서 None으로 둔다. 기록 실패가 사용자 응답까지
    막으면 안 되므로 예외를 여기서 흡수한다.
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
# SCHEDULE은 이 값을 쓰지 않는다 — _SCHEDULE_RECOMMENDATION_LIMIT(10)을 대신 넘긴다.
# (주의) 예전엔 1차 Scoring이 항상 5개까지만 넘겨서 이 슬라이싱이 사실상 no-op이라고
# 적혀 있었는데, SCHEDULE 도입으로 1차가 10개를 넘길 수 있게 되면서 더 이상 no-op이
# 아니다 — _apply_concentration_rerank() 호출부가 반드시 알맞은 limit을 넘겨야 한다.
_CONCENTRATION_FINAL_LIMIT = 5

# SCHEDULE의 1차 Scoring/2차 재순위 최종 노출 개수(D 협의 완료 — docs/design/
# int-07-schedule.md 2절/4절). RECOMMEND/MODIFY의 5개보다 많이 받아 LLM이 그중
# 3~5개를 골라 일정을 편성한다.
_SCHEDULE_RECOMMENDATION_LIMIT = 10

# 보강 응답 전체가 이 상태면 2차 Scoring을 시도할 실익이 없다(재조회할 데이터가 없음).
_ENRICHMENT_TERMINAL_STATUSES = frozenset({"no_data", "unavailable"})


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
    final_limit: int = _CONCENTRATION_FINAL_LIMIT,
    execution_collector: list[ToolExecutionDebug] | None = None,
) -> RecommendationResponse:
    """concentration_intent가 AVOID/SEEK일 때만 1차 결과를 혼잡도로 보강·재순위한다
    (D-040 확정 — concentration-conditions.md §2.2.3, agent-runtime-contract.md
    §6.5.2). 그 외에는 first_pass를 그대로 반환한다.

    final_limit: 재순위 후 최종 노출 개수. 호출부가 1차 Scoring에 넘긴 limit과
    일치시켜야 한다 — RECOMMEND/MODIFY는 기본값 5, SCHEDULE은 10
    (_SCHEDULE_RECOMMENDATION_LIMIT, docs/design/int-07-schedule.md 4절).

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
    enrichment_response = await enrichment_provider.enrich(enrichment_request)
    enrichment_execution = build_candidate_enrichment_execution_debug(
        enrichment_response,
        latency_ms=int((time.monotonic() - enrichment_started_at) * 1000),
    )
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
    return reranked.model_copy(
        update={
            "recommendations": shown[:final_limit],
            "unverified_recommendations": [],
        }
    )


async def run_agent_flow(
    request: AgentRequest,
    *,
    llm: LLMProvider,
    tool_provider: ToolProvider,
    recommendation_provider: RecommendationProvider,
    enrichment_provider: EnrichmentProvider,
    store: StateStore | None = None,
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
    valid_gps = _valid_location(request.device_location)
    session_context = await ensure_current_context(
        request.session_id, valid_gps, store=store
    )

    # 2) A: LLMOutput 생성 (Intent 분류 + Intent별 조건 추출). B가 준 현재 조건(순수 문자열)을
    #    A 쪽 enum 타입으로 변환해서 넘긴다 — MODIFY 추출이 이 타입을 요구한다.
    # 위치 되묻기 직후에는 아직 추천 결과가 없을 수 있어도, 첫 턴에서 저장된 조건을
    # MODIFY 추출에 제공해야 한다. 그렇지 않으면 "경복궁"이 MODIFY로 올바르게
    # 분류돼도 current_conditions 없음 되묻기로 다시 빠진다.
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
    )
    llm_started_at = time.monotonic()
    llm_output = await build_interpretation(interpret_request, llm)
    llm_latency_ms = int((time.monotonic() - llm_started_at) * 1000)

    # 3) A → B: 조건 병합. confirmed=False(= status가 complete가 아님)면 B가 State를
    #    바꾸지 않고 현재 상태만 돌려주도록 이미 구현되어 있다(계약 2.6절) — 따로 걸러서
    #    apply()를 건너뛸 필요가 없다. 그래야 needs_clarification 응답에도 병합된(=변화
    #    없는) state가 항상 채워진다.
    apply_request = transform(llm_output, session_context, request.user_input)
    state_response = apply(apply_request, store=store)

    # 2단계(LLM 호출) trace는 여기서 기록한다 — run_id/session_id가 apply() 안에서
    # 발급되므로 2단계 시점엔 아직 없다. latency만 미리 재뒀다가 여기서 기록.
    _record_trace_safely(
        session_id=state_response.session_id,
        run_id=state_response.run_id,
        step="llm_interpret",
        latency_ms=llm_latency_ms,
        prompt_version=PROMPT_VERSION,
        store=store,
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
    if (
        session_context.pending_clarification is not None
        and llm_output.intent in (Intent.RECOMMEND, Intent.MODIFY, Intent.SCHEDULE)
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
        info_started_at = time.monotonic()
        info_response = await tool_provider.fetch_info_context(info_request)
        info_execution = build_info_concentration_execution_debug(
            info_response,
            latency_ms=int((time.monotonic() - info_started_at) * 1000),
        )
        message = await compose_chat_message(
            llm_output, info_response=info_response, llm=llm
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
        message = await compose_chat_message(llm_output, llm=llm)
        return AgentResponse(
            llm_output=llm_output,
            state=state_response,
            recommendations=None,
            message=message,
            llm_execution=get_llm_execution_metadata(),
        )

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
    tool_started_at = time.monotonic()
    tool_response = await tool_provider.fetch_context(context_request)
    tool_latency_ms = int((time.monotonic() - tool_started_at) * 1000)
    # 개발자용 Audit 표시 정보. 아래 어느 경로로 응답이 끝나든 C를 호출한 사실은
    # 남아야 하므로 여기서 한 번만 만들어 모든 return에 함께 싣는다.
    tool_execution = build_tool_execution_debug(tool_response, latency_ms=tool_latency_ms)
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
        elif tool_response.status == "no_data":
            # "검색 범위를 넓혀볼까요?"에 대한 답변은 새 요청이 아니라 이번 요청을
            # 이어가는 발화다. 표시해두지 않으면 다음 턴이 RECOMMEND로 분류되면서
            # soft reset이 걸려 앞 턴 조건(장소·태그)이 사라진다(D-039와 같은 이유).
            _remember_clarification(state_response.session_id, "no_candidate", store)
        message = await compose_chat_message(
            llm_output,
            tool_status=tool_response.status,
            tool_clarification=tool_response.clarification,
            tool_error_code=tool_response.error.code if tool_response.error else None,
            llm=llm,
        )
        return AgentResponse(
            llm_output=llm_output,
            state=state_response,
            recommendations=None,
            message=message,
            llm_execution=get_llm_execution_metadata(),
            tool_execution=tool_execution,
            tool_executions=tool_executions,
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
        message = await compose_chat_message(
            llm_output, tool_status=tool_response.status, llm=llm
        )
        return AgentResponse(
            llm_output=llm_output,
            state=state_response,
            recommendations=None,
            message=message,
            llm_execution=get_llm_execution_metadata(),
            tool_execution=tool_execution,
            tool_executions=tool_executions,
        )

    is_schedule = llm_output.intent is Intent.SCHEDULE

    # 6) A → D: 1차 Scoring (Protocol을 통해서만 — D의 구체 클래스는 여기서 모른다).
    #    concentration_intent 유무와 무관하게 항상 이 호출 하나만 한다 — 기존과 동일.
    #    SCHEDULE은 10개, RECOMMEND/MODIFY는 기존과 동일하게 5개를 받는다
    #    (docs/design/int-07-schedule.md 2절/5절, D 협의 완료).
    recommendation_limit = _SCHEDULE_RECOMMENDATION_LIMIT if is_schedule else 5
    scoring_started_at = time.monotonic()
    recommendations = await recommendation_provider.recommend(
        agent_conditions,
        tool_context,
        state_response.excluded_place_ids,
        limit=recommendation_limit,
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

    if is_schedule:
        # 6-2) A: C의 AgentContextResponse.places(위경도)를 place_id로 매칭해
        #      pairwise_distances_km 계산 → 일정 편성 모듈 호출(docs/design/
        #      int-07-schedule.md 4절/6절). 상태 저장소 비접근 — D를 부르는 것과
        #      동일한 방식.
        schedule_candidates = [
            *recommendations.recommendations,
            *recommendations.unverified_recommendations,
        ]
        places = (
            tool_context.places.data
            if tool_context.places and tool_context.places.data
            else []
        )

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
                if prev.name is None or prev.estimated_arrival is None:
                    # 방어적 폴백 — SCHEDULE-09 2단계 도입 이전에 기록된 세션처럼
                    # name이 없는 과거 데이터일 때만 해당하며, 이 항목만 새 후보로
                    # 채워지고 나머지는 정상적으로 유지된다.
                    continue
                pinned_items.append(
                    ScheduleItem(
                        order=prev.rank,
                        place_id=prev.place_id,
                        place_name=prev.name,
                        estimated_arrival=prev.estimated_arrival,
                        estimated_duration_min=prev.estimated_duration_min or 0,
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
            schedule_result = await plan_partial_schedule(partial_request, llm)
        else:
            schedule_request = SchedulePlanningRequest(
                candidates=schedule_candidates,
                conditions=agent_conditions,
                visit_datetime=None,
                pairwise_distances_km=_build_pairwise_distances_km(schedule_candidates, places),
            )
            schedule_result = await plan_schedule(schedule_request, llm)

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
            )

        # 8) A: 최종 응답 조립. recommendations는 채우지 않는다(AgentResponse
        #    docstring — schedule과 동시에 채워지지 않음).
        message = await compose_chat_message(llm_output, schedule=schedule_result, llm=llm)
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

    # 7) A → B: 실제로 화면에 노출된 결과만 기록한다. recommendations와
    #    unverified_recommendations 둘 다 프론트에 렌더링되므로(운영시간 미검증 섹션으로
    #    구분되어 보일 뿐 노출 자체는 됨) 함께 기록한다 — 계산만 하고 안 보여준 건 넣지
    #    않아야 "다른 곳 보여줘"의 제외 목록이 정확해진다.
    #    distance_km/remaining_minutes/environment_type도 함께 기록한다 —
    #    COMPARE가 "추천 시 이미 계산된 데이터"를 그대로 쓸 수 있게 하는
    #    Feature 스냅샷이다(COMPARE 데이터 출처 A안, 2026-08-11).
    shown = [*recommendations.recommendations, *recommendations.unverified_recommendations]
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
        )

    # 8) A: 최종 응답 조립
    message = await compose_chat_message(llm_output, recommendations=recommendations, llm=llm)
    return AgentResponse(
        llm_output=llm_output,
        state=state_response,
        recommendations=recommendations,
        message=message,
        llm_execution=get_llm_execution_metadata(),
        tool_execution=tool_execution,
        tool_executions=tool_executions,
    )


async def run_agent(request: AgentRequest) -> AgentResponse:
    """호출자가 쓰는 Fake/Real 공통 진입점.

    A는 조건 기반 ContextProvider 계약만 알고, C 내부 Tool·Provider 조립은
    app.agent_context.factory에 위임한다. D 계약이 확정되어([TECH-02])
    RealRecommendationProvider를 기본으로 주입한다.
    """

    from app.agent_context.factory import get_candidate_enrichment_service, get_context_provider
    from app.providers.factory import get_llm_provider
    from app.services.runtime.real_recommendation_provider import RealRecommendationProvider

    async with create_external_client() as client:
        return await run_agent_flow(
            request,
            llm=get_llm_provider(),
            tool_provider=get_context_provider(client),
            recommendation_provider=RealRecommendationProvider(),
            enrichment_provider=get_candidate_enrichment_service(client),
        )


__all__ = ["run_agent", "run_agent_flow"]
