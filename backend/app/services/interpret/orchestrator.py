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
    GeneralPayload,
    GeneralTopic,
    Intent,
    InterpretRequest,
    LLMOutput,
    OutOfScopePayload,
    OutputStatus,
)
from app.state.schema import now_kst

_SERVICE_IDENTITY_MARKERS = (
    "넌 누구",
    "너 누구",
    "너는 누구",
    "이름이 뭐",
    "이름 뭐",
    "뭘 할 수",
    "뭐 할 수",
    "무엇을 할 수",
    "트리비",
    "TripBranch",
    "tripbranch",
)


def _is_service_identity_question(user_input: str) -> bool:
    """챗봇/서비스 정체성 질문은 LLM 1차 분류 전에 GENERAL로 고정한다.

    Gemini가 "넌 누구야?"를 role_request/OUT_OF_SCOPE로 밀 수 있어 생기는
    회귀를 막는다. int-06-outofscope.md §12도 서비스 소개 요청은 GENERAL로 둔다.
    """

    return any(marker in user_input for marker in _SERVICE_IDENTITY_MARKERS)


async def build_interpretation(
    request: InterpretRequest, llm: LLMProvider
) -> LLMOutput:
    """Fake/Real LLMProvider를 인자로 받는 테스트 가능한 본체."""

    if _is_service_identity_question(request.user_input):
        return LLMOutput(
            intent=Intent.GENERAL,
            status=OutputStatus.COMPLETE,
            general=GeneralPayload(
                topic=GeneralTopic.SERVICE_IDENTITY,
                original_question=request.user_input,
            ),
        )

    classification = (
        await llm.classify_intent(
            request.user_input,
            has_previous_recommendation=request.has_previous_recommendation,
            shown_place_count=request.shown_place_count,
            pending_clarification=request.pending_clarification,
            last_intent=request.last_intent,
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

    # SCHEDULE도 RECOMMEND와 같은 15개 조건(time_available, place_tags 등)을 쓴다
    # (docs/design/int-07-schedule.md 6.1절) — 별도 추출 메서드를 새로 만들지 않고
    # extract_recommend_conditions()를 그대로 재사용한 뒤 intent만 SCHEDULE로
    # 바꿔치기한다. status(complete/needs_clarification)와 clarification은 그대로
    # 유지된다 — RECOMMEND와 동일한 되묻기 흐름을 탄다.
    if classification.intent is Intent.SCHEDULE:
        result = (await llm.extract_recommend_conditions(request.user_input)).data
        return result.model_copy(update={"intent": Intent.SCHEDULE})

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
