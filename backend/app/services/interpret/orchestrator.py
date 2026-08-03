"""사용자 자연어 입력을 Intent + Conditions로 해석하는 서비스.

역할: 2단계 LLM 호출(① Intent 분류 ② Intent별 조건 추출)을 오케스트레이션해서
LLMOutput을 만든다. Fake/Real 여부는 LLMProvider 구현체가 갈라 처리하고, 이 모듈은
어느 쪽이든 동일한 흐름을 탄다 (services/recommendations.py의
get_recommendations()/build_recommendations() 분리와 동일한 패턴).
입력: InterpretRequest (user_input + 이전 추천 이력 컨텍스트).
출력: LLMOutput 모델.
호출 시점: /api/interpret 라우터가 interpret_user_input()을 호출한다.
TODO: B(Agent State) 연동(state_transform.py/session_orchestrator.py)을 이 흐름에
실제로 통합하는 작업은 다음 세션에서 진행한다 — InterpretRequest/응답 계약이 함께 바뀐다.
"""

from __future__ import annotations

from app.providers.protocols import LLMProvider
from app.schemas import (
    ClarificationPayload,
    Intent,
    InterpretRequest,
    LLMOutput,
    OutOfScopePayload,
    OutputStatus,
)
from app.state.schema import now_kst


async def build_interpretation(
    request: InterpretRequest, llm: LLMProvider
) -> LLMOutput:
    """Fake/Real LLMProvider를 인자로 받는 테스트 가능한 본체."""

    classification = (
        await llm.classify_intent(
            request.user_input,
            has_previous_recommendation=request.has_previous_recommendation,
            shown_place_count=request.shown_place_count,
        )
    ).data

    if classification.intent is Intent.OUT_OF_SCOPE:
        return LLMOutput(
            intent=Intent.OUT_OF_SCOPE,
            status=OutputStatus.COMPLETE,
            out_of_scope=OutOfScopePayload(
                category=classification.out_of_scope_category,
                severity=classification.out_of_scope_severity,
            ),
        )

    if classification.intent is Intent.RECOMMEND:
        return (await llm.extract_recommend_conditions(request.user_input)).data

    if classification.intent is Intent.MODIFY:
        if request.current_conditions is None:
            return LLMOutput(
                intent=Intent.MODIFY,
                status=OutputStatus.NEEDS_CLARIFICATION,
                clarification=ClarificationPayload(
                    missing_fields=[
                        {
                            "field": "current_conditions",
                            "reason": "변경할 기존 조건 정보가 없어 어떤 추천을 기준으로 "
                            "바꿔야 할지 확인할 수 없습니다.",
                        }
                    ],
                    message="아직 추천한 결과가 없어요. 어떤 장소를 찾고 계신가요?",
                ),
            )
        return (
            await llm.extract_modify_conditions(
                request.user_input, request.current_conditions
            )
        ).data

    if classification.intent is Intent.INFO:
        return (
            await llm.extract_info_query(
                request.user_input,
                has_previous_recommendation=request.has_previous_recommendation,
                reference_date=now_kst().date(),
            )
        ).data

    if classification.intent is Intent.COMPARE:
        return (
            await llm.extract_compare_request(
                request.user_input, shown_place_count=request.shown_place_count
            )
        ).data

    # 남은 경우는 Intent.GENERAL뿐 (RECOMMEND/MODIFY/INFO/COMPARE/OUT_OF_SCOPE는 위에서 처리).
    return (await llm.extract_general_request(request.user_input)).data


async def interpret_user_input(request: InterpretRequest) -> LLMOutput:
    """라우터가 호출하는 Fake/Real 공통 진입점."""

    from app.providers.factory import get_llm_provider

    return await build_interpretation(request, get_llm_provider())
