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

import httpx

from app.providers.protocols import LLMProvider, WeatherProvider
from app.schemas import (
    AgentRequest,
    AgentResponse,
    Intent,
    InterpretRequest,
    OutputStatus,
    QuestionType,
)
from app.services.interpret.orchestrator import build_interpretation
from app.services.interpret.session_orchestrator import ensure_current_context
from app.services.interpret.state_transform import to_user_conditions, transform
from app.services.runtime.context_transform import to_agent_context_request
from app.services.runtime.info_context_transform import to_info_context_request
from app.services.runtime.protocols import RecommendationProvider, ToolProvider
from app.services.runtime.response_composer import compose_chat_message
from app.state.schema import now_kst
from app.state.service import (
    RecommendedPlace,
    RecordRecommendationRequest,
    UpdateApiContextRequest,
    apply,
    record_recommendation,
    update_api_context,
)
from app.state.session import new_trace_id
from app.state.store import StateStore

logger = logging.getLogger(__name__)

# C 단계에서 Recommendation으로 못 넘어가는 status. needs_clarification은 조건 재질문(사용자
# 응답 필요), unsupported/unavailable은 그 자체로 안내만 하고 끝나는 상태다(계약 문서 §5.4).
_TOOL_TERMINAL_STATUSES = frozenset({"needs_clarification", "unsupported", "unavailable"})


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
        float(parts[0])
        float(parts[1])
    except ValueError:
        return None
    return device_location


async def run_agent_flow(
    request: AgentRequest,
    *,
    llm: LLMProvider,
    weather_provider: WeatherProvider,
    tool_provider: ToolProvider,
    recommendation_provider: RecommendationProvider,
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

    # 1) A → B: GPS·날씨 세션 컨텍스트 최신화. GPS 형식이 잘못되면 이번 턴만 건너뛴다 —
    #    잘못된 GPS 문자열이 파싱 예외로 대화를 중단시키지 않아야 한다.
    valid_gps = _valid_location(request.device_location)
    session_context = await ensure_current_context(
        request.session_id, valid_gps, weather_provider, store=store
    )

    # 2) A: LLMOutput 생성 (Intent 분류 + Intent별 조건 추출). B가 준 현재 조건(순수 문자열)을
    #    A 쪽 enum 타입으로 변환해서 넘긴다 — MODIFY 추출이 이 타입을 요구한다.
    current_conditions = (
        to_user_conditions(session_context.user_conditions)
        if session_context.has_recommendation
        else None
    )
    interpret_request = InterpretRequest(
        user_input=request.user_input,
        has_previous_recommendation=session_context.has_recommendation,
        shown_place_count=len(session_context.shown_place_ids),
        current_conditions=current_conditions,
    )
    llm_output = await build_interpretation(interpret_request, llm)

    # 3) A → B: 조건 병합. confirmed=False(= status가 complete가 아님)면 B가 State를
    #    바꾸지 않고 현재 상태만 돌려주도록 이미 구현되어 있다(계약 2.6절) — 따로 걸러서
    #    apply()를 건너뛸 필요가 없다. 그래야 needs_clarification 응답에도 병합된(=변화
    #    없는) state가 항상 채워진다.
    apply_request = transform(llm_output, session_context, request.user_input)
    state_response = apply(apply_request, store=store)

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

    # 4-0) INFO의 혼잡도 질의(question_type=concentration)는 RECOMMEND/MODIFY와 별개로
    #      C를 거친다(concentration-conditions.md §2.4/§3.3). 그 외 INFO question_type과
    #      COMPARE/GENERAL은 그대로 4)의 일반 게이트로 빠진다 — Tool을 직접 호출하지
    #      않는다는 기존 원칙(ToolProvider Protocol)을 그대로 따른다.
    if (
        llm_output.status is OutputStatus.COMPLETE
        and llm_output.intent is Intent.INFO
        and llm_output.info is not None
        and llm_output.info.question_type is QuestionType.CONCENTRATION
    ):
        info_request = to_info_context_request(new_trace_id(), llm_output.info)
        info_response = await tool_provider.fetch_info_context(info_request)
        message = await compose_chat_message(
            llm_output, info_concentration_response=info_response, llm=llm
        )
        return AgentResponse(
            llm_output=llm_output, state=state_response, recommendations=None, message=message
        )

    # 4) 확인이 더 필요하거나(needs_clarification), RECOMMEND/MODIFY가 아니면(INFO/COMPARE/
    #    GENERAL/OUT_OF_SCOPE) 여기서 끝난다 — Tool/Recommendation은 부가 흐름이라 스킵한다.
    if llm_output.status is not OutputStatus.COMPLETE or llm_output.intent not in (
        Intent.RECOMMEND,
        Intent.MODIFY,
    ):
        message = await compose_chat_message(llm_output, llm=llm)
        return AgentResponse(
            llm_output=llm_output, state=state_response, recommendations=None, message=message
        )

    # 5) A → C: Tool 결과 확보 (Protocol을 통해서만 — C의 구체 클래스는 여기서 모른다).
    #    B가 준 조건(순수 문자열)을 A의 enum 타입으로 바꾼 뒤 C 계약 형태로 변환한다.
    #    conditions.weather(5단계 rain/snow/hot/cold/good)만 넘기고, api_context.api_weather
    #    (3단계 good/neutral/bad, Provider 정규화 값)는 여기 관여하지 않는다 — to_agent_
    #    context_request()가 UserConditions만 받는 구조라 애초에 섞일 수 없다(계약 §5.2).
    agent_conditions = to_user_conditions(state_response.user_conditions)
    context_request = to_agent_context_request(
        request_id=new_trace_id(), conditions=agent_conditions
    )
    tool_response = await tool_provider.fetch_context(context_request)

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
        message = await compose_chat_message(
            llm_output,
            tool_status=tool_response.status,
            tool_clarification=tool_response.clarification,
            llm=llm,
        )
        return AgentResponse(
            llm_output=llm_output, state=state_response, recommendations=None, message=message
        )

    # success/partial/no_data는 Recommendation 단계로 진행한다(경고가 있어도 가능한
    # 데이터로 계속 — 계약 문서 §5.4). 위에서 세 종료 상태를 걸렀으므로 context는 항상 있다.
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
        )

    # 6) A → D: 추천 결과 확보 (Protocol을 통해서만 — D의 구체 클래스는 여기서 모른다)
    recommendations = await recommendation_provider.recommend(
        agent_conditions,
        tool_context,
        state_response.excluded_place_ids,
    )

    # 7) A → B: 실제로 화면에 노출된 결과만 기록한다. recommendations와
    #    unverified_recommendations 둘 다 프론트에 렌더링되므로(운영시간 미검증 섹션으로
    #    구분되어 보일 뿐 노출 자체는 됨) 함께 기록한다 — 계산만 하고 안 보여준 건 넣지
    #    않아야 "다른 곳 보여줘"의 제외 목록이 정확해진다.
    shown = [*recommendations.recommendations, *recommendations.unverified_recommendations]
    if shown:
        record_recommendation(
            RecordRecommendationRequest(
                session_id=state_response.session_id,
                run_id=state_response.run_id,
                recommended=[
                    RecommendedPlace(place_id=item.place_id, rank=index + 1)
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
    )


async def run_agent(request: AgentRequest) -> AgentResponse:
    """호출자가 쓰는 Fake/Real 공통 진입점.

    A는 조건 기반 ContextProvider 계약만 알고, C 내부 Tool·Provider 조립은
    app.agent_context.factory에 위임한다. D 계약이 확정되어([TECH-02])
    RealRecommendationProvider를 기본으로 주입한다.
    """

    from app.agent_context.factory import get_context_provider
    from app.providers.factory import get_llm_provider, get_weather_provider
    from app.services.runtime.real_recommendation_provider import RealRecommendationProvider

    async with httpx.AsyncClient() as client:
        weather_provider = get_weather_provider(client)
        return await run_agent_flow(
            request,
            llm=get_llm_provider(),
            weather_provider=weather_provider,
            tool_provider=get_context_provider(client),
            recommendation_provider=RealRecommendationProvider(),
        )


__all__ = ["run_agent", "run_agent_flow"]
