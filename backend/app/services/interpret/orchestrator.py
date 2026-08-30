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
    ClarificationOption,
    ClarificationPayload,
    GeneralPayload,
    GeneralTopic,
    Intent,
    IntentClassificationResult,
    InteractionMode,
    InterpretRequest,
    LLMOutput,
    OutOfScopeCategory,
    OutOfScopePayload,
    OutputStatus,
    PlaceContext,
    StatedWeather,
    UserConditions,
    WeatherIntent,
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


# 목적어 없는 재시작("처음부터 다시")과 목적어 있는 재시작("처음부터 다시 추천해줘")을
# 구분한다 — 후자는 D-053/기존 MODIFY 규칙이 이미 잘 처리하므로 여기서 손대지 않는다
# (docs/design/clarification-options.md 케이스 4/5).
_BARE_RESTART_MARKERS = ("처음부터 다시", "다시 처음부터")


def _resolve_info_conversation_reference(
    output: LLMOutput,
    conversation_place_name: str | None,
) -> LLMOutput:
    """INFO 추출기가 남긴 대화 지시어를 직전 INFO 카드 장소명으로 해소한다.

    LLM 프롬프트에도 같은 컨텍스트를 전달하지만, 모델이 from_conversation만 채우고
    place_name을 비워도 C가 불필요한 ``place_required`` 되묻기를 하지 않도록 A에서
    결정적으로 보정한다. 사용자가 이번 발화에서 명시한 장소(place_name이 이미 있음)는
    절대 덮어쓰지 않는다.
    """

    info = output.info
    if (
        info is None
        or info.place_context is not PlaceContext.FROM_CONVERSATION
        or info.place_name is not None
        or not conversation_place_name
    ):
        return output
    return output.model_copy(
        update={"info": info.model_copy(update={"place_name": conversation_place_name})}
    )


def _is_bare_restart_phrase(user_input: str) -> bool:
    stripped = user_input.strip().rstrip("!?.~ ")
    return any(
        stripped == marker or stripped == f"{marker}요" for marker in _BARE_RESTART_MARKERS
    )


_WEATHER_AVOID_LABELS: dict[StatedWeather, str] = {
    StatedWeather.RAIN: "비를 피할 장소",
    StatedWeather.SNOW: "눈을 피할 장소",
    StatedWeather.HOT: "더위를 피할 장소",
    StatedWeather.COLD: "추위를 피할 장소",
}


def _compose_condition_phrase(conditions: UserConditions) -> str | None:
    """되묻기 문구/버튼에 넣을 짧은 조건 구절. 채워진 신호만 우선순위(장소 → 날씨 →
    카테고리) 순으로 최대 2개까지 이어붙인다 — 다 붙이면 문장이 길고 부자연스러워
    진다(docs/design/clarification-options.md 6절)."""
    parts: list[str] = []
    if conditions.search_center:
        parts.append(f"{conditions.search_center} 근처")
    if len(parts) < 2:
        if (
            conditions.weather_intent == WeatherIntent.AVOID
            and conditions.weather in _WEATHER_AVOID_LABELS
        ):
            parts.append(_WEATHER_AVOID_LABELS[conditions.weather])
        elif conditions.place_tags:
            parts.append(conditions.place_tags[0].value)
    return " ".join(parts) if parts else None


def _bare_restart_during_schedule_location_ask(request: InterpretRequest) -> LLMOutput | None:
    """케이스 4: SCHEDULE 위치 되묻기 중 목적어 없는 "처음부터 다시".

    되묻기가 이미 진행 중이라(pending_clarification="location_required",
    last_intent="SCHEDULE") 이 발화가 새 일정 재조정인지 전체 초기화인지 글자로는
    구분이 안 된다 — 추측 대신 되묻는다.
    """
    if (
        request.last_intent != Intent.SCHEDULE.value
        or request.pending_clarification != "location_required"
        or not _is_bare_restart_phrase(request.user_input)
    ):
        return None
    return LLMOutput(
        intent=Intent.SCHEDULE,
        status=OutputStatus.NEEDS_CLARIFICATION,
        clarification=ClarificationPayload(
            code="schedule_bare_restart",
            message="일정을 처음부터 다시 잡아드릴까요, 아니면 계속 위치만 여쭤볼까요?",
            options=[
                ClarificationOption(
                    id="restart",
                    label="네, 처음부터 다시 잡을게요",
                    resolved_intent=Intent.SCHEDULE,
                ),
                ClarificationOption(
                    id="keep_asking",
                    label="아니요, 위치만 알려드릴게요",
                    resolved_intent=Intent.SCHEDULE,
                ),
            ],
        ),
    )


def _bare_restart_during_active_search(request: InterpretRequest) -> LLMOutput | None:
    """케이스 5: RECOMMEND/MODIFY 진행 중(되묻기 아님) 목적어 없는 "처음부터 다시".

    되묻기 중이 아니므로 이번 조건 자체를 새로 초기화하려는 건지, 지금 조건을 유지한
    채 다시 찾아달라는 건지 글자로는 구분이 안 된다.
    """
    if (
        request.pending_clarification is not None
        or request.last_intent not in (Intent.RECOMMEND.value, Intent.MODIFY.value)
        or not _is_bare_restart_phrase(request.user_input)
    ):
        return None
    phrase = (
        _compose_condition_phrase(request.current_conditions)
        if request.current_conditions is not None
        else None
    )
    keep_label = f"{phrase}로 다시 찾아주세요" if phrase else "이대로 다시 찾아주세요"
    message = (
        f"{phrase}로 다시 알아볼까요, 아니면 새로운 목적지로 찾아볼까요?"
        if phrase
        else "다시 알아볼까요, 아니면 새로운 목적지로 찾아볼까요?"
    )
    return LLMOutput(
        intent=Intent(request.last_intent),
        status=OutputStatus.NEEDS_CLARIFICATION,
        clarification=ClarificationPayload(
            code="bare_restart_active",
            message=message,
            options=[
                ClarificationOption(
                    id="keep_context", label=keep_label, resolved_intent=Intent.MODIFY
                ),
                ClarificationOption(
                    id="full_reset", label="새로 시작할게요", resolved_intent=Intent.RECOMMEND
                ),
            ],
        ),
    )


def _bare_restart_after_schedule_completed(request: InterpretRequest) -> LLMOutput | None:
    """SCHEDULE이 되묻기 없이 완료된 뒤(케이스 5와 대칭, SCHEDULE 전용) 목적어 없는
    "처음부터 다시".

    케이스 5는 last_intent가 RECOMMEND/MODIFY일 때만 다루고 SCHEDULE은 일부러
    뺐다 — REJECT_ALL(MODIFY)이 SCHEDULE 결과에는 안 맞는 동작이라서다. 그런데
    아무 규칙도 없이 흘려보내면 SCHEDULE-06(agent_runtime.py)이 "처음부터 다시"를
    무조건 MODIFY→SCHEDULE 재라우팅 대상으로 삼아 같은 조건으로 재편성을 시도하고,
    후보가 부족하면 "일정을 만들지 못했어요" 실패 문구로 새어버린다(실사용 재현,
    2026-08-13). 케이스 5와 같은 선택지를 SCHEDULE에 맞게 준다 — "이 조건으로 다시
    짜기"(SCHEDULE 유지)/"새로 시작"(RECOMMEND로 전환, 조건 초기화).
    """
    if (
        request.pending_clarification is not None
        or request.last_intent != Intent.SCHEDULE.value
        or not _is_bare_restart_phrase(request.user_input)
    ):
        return None
    phrase = (
        _compose_condition_phrase(request.current_conditions)
        if request.current_conditions is not None
        else None
    )
    retry_label = f"{phrase}로 다시 짜주세요" if phrase else "이 조건으로 다시 짜주세요"
    message = (
        f"{phrase}로 다시 짜드릴까요, 아니면 새로운 목적지로 찾아볼까요?"
        if phrase
        else "다시 짜드릴까요, 아니면 새로운 목적지로 찾아볼까요?"
    )
    return LLMOutput(
        intent=Intent.SCHEDULE,
        status=OutputStatus.NEEDS_CLARIFICATION,
        clarification=ClarificationPayload(
            code="schedule_bare_restart_completed",
            message=message,
            options=[
                ClarificationOption(
                    id="retry_schedule", label=retry_label, resolved_intent=Intent.SCHEDULE
                ),
                ClarificationOption(
                    id="full_reset", label="새로 시작할게요", resolved_intent=Intent.RECOMMEND
                ),
            ],
        ),
    )


async def _general_output(user_input: str, llm: LLMProvider) -> LLMOutput:
    """GENERAL 추출 결과를 반드시 GENERAL로 못 박아 돌려준다.

    extract_general_request()는 LLMOutput 전체를 모델이 채우게 두므로 intent도
    모델이 정한다. 그래서 **분류기가 GENERAL이라고 판정한 뒤에도 추출기가 그 결정을
    뒤집을 수 있다** — 실측(2026-08-30)에서 "너무 지친다"는 분류기가 GENERAL로 잘
    보냈는데 추출기가 OUT_OF_SCOPE를 돌려줘 결국 거절 문구가 나갔다. 인텐트를 정하는
    것은 분류 단계의 책임이므로 여기서 되돌린다(SCHEDULE 분기가
    extract_recommend_conditions() 결과의 intent를 바꿔치기하는 것과 같은 처리다).

    payload가 비어 있으면 답변 생성 단계가 쓸 수 없으므로 원문을 담아 채워 준다.
    """

    output = (await llm.extract_general_request(user_input)).data
    if output.intent is Intent.GENERAL and output.general is not None:
        return output
    return output.model_copy(
        update={
            "intent": Intent.GENERAL,
            "status": OutputStatus.COMPLETE,
            "out_of_scope": None,
            "general": output.general
            or GeneralPayload(
                topic=GeneralTopic.TRAVEL_TIP,
                original_question=user_input,
            ),
        }
    )


async def _extract_for_intent(
    classification: IntentClassificationResult,
    request: InterpretRequest,
    llm: LLMProvider,
) -> LLMOutput:
    """분류된 Intent에 맞는 추출기를 골라 LLMOutput을 만든다.

    build_interpretation()에서 떼어낸 이유는 상황 축(interaction_mode) 때문이다.
    반환 경로가 8개인데 각 경로에서 축을 채우면 하나는 반드시 빠진다 — 여기서는
    인텐트별 결과만 만들고, 축은 호출부가 한 번에 덧붙인다.
    """

    if classification.intent is Intent.OUT_OF_SCOPE:
        # 상황 발화는 거절하지 않는다. 분류기는 "너무 지친다"를 GENERAL로 잘
        # 보내지만(2026-08-30 실측), 우선순위 1번이 다른 무엇보다 먼저 걸리는
        # 캐스케이드라 비슷한 발화가 OUT_OF_SCOPE로 새는 일이 남는다. 같은
        # 실측에서 interaction_mode 축은 8/8 정확했으므로 축을 근거로 뒤집는다 —
        # _is_service_identity_question()이 Gemini의 알려진 오분류를 막는 것과
        # 같은 성격의 가드다.
        #
        # **유해 발언·프롬프트 인젝션은 뒤집지 않는다.** "너 진짜 바보야?"가
        # situational로 분류되는 것을 실측에서 확인했다 — 축만 보고 구제하면
        # 욕설이 GENERAL 답변을 받는다. 차단이 먼저다.
        rescuable = classification.out_of_scope_category not in {
            OutOfScopeCategory.HARMFUL,
            OutOfScopeCategory.PROMPT_INJECTION,
        }
        if classification.interaction_mode is InteractionMode.SITUATIONAL and rescuable:
            return await _general_output(request.user_input, llm)
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
                request.user_input,
                request.current_conditions,
                pending_clarification=request.pending_clarification,
                shown_place_count=request.shown_place_count,
                shown_place_names=request.shown_place_names,
            )
        ).data

    if classification.intent is Intent.INFO:
        output = (
            await llm.extract_info_query(
                request.user_input,
                has_previous_recommendation=request.has_previous_recommendation,
                reference_date=now_kst().date(),
                conversation_place_name=request.conversation_place_name,
            )
        ).data
        return _resolve_info_conversation_reference(output, request.conversation_place_name)

    if classification.intent is Intent.COMPARE:
        return (
            await llm.extract_compare_request(
                request.user_input,
                shown_place_count=request.shown_place_count,
                shown_place_names=request.shown_place_names,
            )
        ).data

    # 남은 경우는 Intent.GENERAL뿐 (RECOMMEND/MODIFY/INFO/COMPARE/OUT_OF_SCOPE는 위에서 처리).
    return await _general_output(request.user_input, llm)


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

    # 케이스 4/5(PR 4, docs/design/clarification-options.md): 목적어 없는 "처음부터
    # 다시"는 classify_intent() 호출 전에 결정적으로 되묻는다 — 글자만으로는 SCHEDULE
    # 재진입인지, 조건 유지 재조회인지, 전체 초기화인지 LLM마다 판정이 갈린다.
    bare_restart = (
        _bare_restart_during_schedule_location_ask(request)
        or _bare_restart_during_active_search(request)
        or _bare_restart_after_schedule_completed(request)
    )
    if bare_restart is not None:
        return bare_restart

    classification = (
        await llm.classify_intent(
            request.user_input,
            has_previous_recommendation=request.has_previous_recommendation,
            shown_place_count=request.shown_place_count,
            pending_clarification=request.pending_clarification,
            last_intent=request.last_intent,
            shown_place_names=request.shown_place_names,
            conversation_place_name=request.conversation_place_name,
        )
    ).data

    output = await _extract_for_intent(classification, request, llm)
    # 상황 축은 인텐트별 추출기가 모르는 값이라, 분류 결과에서 여기 한 곳에서만
    # 옮겨 담는다 — 반환 경로가 8개라 각 경로에서 채우면 반드시 하나를 빠뜨린다.
    return output.model_copy(
        update={"interaction_mode": classification.interaction_mode}
    )


async def interpret_user_input(request: InterpretRequest) -> LLMOutput:
    """라우터가 호출하는 Fake/Real 공통 진입점."""

    from app.providers.factory import get_llm_provider

    return await build_interpretation(request, get_llm_provider())
