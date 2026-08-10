"""D의 RecommendationItem과 LLMOutput을 사용자에게 보여줄 텍스트로 조립한다.

역할: 두 계층을 담당한다(docs/design/agent-response-generation.md 참고).
1) compose_recommendation_message(): 장소 카드 1건에 들어갈 문장. D가 만든
   explanations(근거)/warnings(경고)를 D님과 협의한 순서(근거 먼저, 경고는
   "다만~"으로 마지막)로 이어붙인다. 문장 내용 자체는 재작문하지 않고 D가 만든
   그대로 쓴다.
2) compose_chat_message(): 카드들을 감싸는 챗봇 말풍선 텍스트(AgentResponse.message).
   Intent/status별로 고정 템플릿을 고르거나, GENERAL 답변과 RECOMMEND/MODIFY 추천
   요약에는 LLM을 호출한다. 추천 요약 LLM은 카드의 공개 필드만 보고 짧게 소개한다.
"""

from __future__ import annotations

import logging

from app.errors import AppError
from app.providers.protocols import LLMProvider
from app.schemas import (
    Intent,
    LLMOutput,
    OutputStatus,
    RecommendationItem,
    RecommendationResponse,
    ScheduleResult,
)
from app.services.runtime.context_schemas import Clarification
from app.services.runtime.info_context_schemas import (
    EventInfoResult,
    InfoContextResponse,
    PlaceInfoResult,
)

# C 단계에서 Recommendation으로 못 넘어가는 status. agent_runtime.py의
# _TOOL_TERMINAL_STATUSES와 같은 집합이어야 한다 — 순환 import를 피하려고 별도로
# 둔다. 두 집합이 어긋나면 메시지가 엉뚱한 분기로 새므로 테스트로 일치를 고정한다.
_TOOL_TERMINAL_STATUSES = frozenset(
    {"needs_clarification", "no_data", "unsupported", "unavailable"}
)

_RECOMMEND_WRAPPER_MESSAGE = "이런 곳들을 찾아봤어요:"

# int-03-modify.md §11 "후보 부족 처리" 정책 그대로 재사용 — 시스템이 임의로 조건을
# 완화하지 않고, 사용자에게 선택지를 제시한다.
_NO_DATA_MESSAGE = (
    "조건에 맞는 곳을 찾지 못했어요. 검색 범위를 넓혀볼까요? "
    "다른 종류의 장소도 포함할까요? 운영시간을 확인할 수 없는 장소도 볼까요?"
)

# C 단계 needs_clarification의 code별 템플릿. A 초안 — 팀 공유 후 피드백으로 보완 예정
# (docs/design/agent-response-generation.md §5 결정사항 3).
_CLARIFICATION_TEMPLATES: dict[str, str] = {
    "location_required": "어디 근처에서 찾아드릴까요? 현재 위치나 원하시는 지역을 알려주세요.",
    "location_ambiguous": (
        "말씀하신 장소가 여러 곳으로 해석돼요. 어느 곳을 말씀하시는지 조금 더 알려주시겠어요?"
    ),
    "place_required": "어떤 장소에 대해 알고 싶으신가요?",
    "place_ambiguous": "여러 장소 중 어느 곳을 말씀하시는 건가요?",
}
_CLARIFICATION_FALLBACK_MESSAGE = "조건을 조금 더 자세히 알려주시겠어요?"

_TOOL_UNSUPPORTED_MESSAGE = "죄송하지만 아직 지원하지 않는 요청이에요."

# unsupported는 이유가 여러 가지다. 지원 지역 밖인데 "아직 지원하지 않는 요청"이라고만
# 하면 무엇을 바꿔야 할지 알 수 없다(D-044).
_TOOL_UNSUPPORTED_TEMPLATES: dict[str, str] = {
    "unsupported_region": (
        "현재는 베타 서비스로 종로구의 장소 추천만 가능해요. "
        "종로에서 가고 싶은 위치를 말씀해주세요."
    ),
}


def _unsupported_message(error_code: str | None) -> str:
    return _TOOL_UNSUPPORTED_TEMPLATES.get(error_code or "", _TOOL_UNSUPPORTED_MESSAGE)
_TOOL_UNAVAILABLE_MESSAGE = "일시적으로 요청을 처리하지 못했어요. 잠시 후 다시 시도해주세요."

_OUT_OF_SCOPE_TEMPLATES: dict[str, str] = {
    "harmful": "죄송하지만 그런 요청은 도와드릴 수 없어요.",
    "unrelated": (
        "저는 국내 여행지 추천을 도와드리는 챗봇이에요. 여행 관련 질문을 해주시면 도와드릴게요!"
    ),
    "role_request": "저는 TripBranch 여행 추천 챗봇으로만 동작해요. 다른 역할은 수행할 수 없어요.",
    "prompt_injection": "죄송하지만 그 요청은 처리할 수 없어요.",
}

# INFO/COMPARE: 답변할 실제 데이터·로직 자체가 아직 없다(별도 트랙, agent-response-
# generation.md §3/§6 3차) — 임시 안내문. question_type=concentration은 예외
# (아래 compose_info_concentration_message).
_NOT_YET_SUPPORTED_MESSAGE = "죄송해요, 이 기능은 아직 준비 중이에요."
_SCHEDULE_NOT_YET_SUPPORTED_MESSAGE = "일정 추천 기능은 아직 준비 중이에요."

# concentration-conditions.md §7 데이터 한계와 응답 원칙.
_CONCENTRATION_NO_DATA_MESSAGE = "이 장소 유형은 혼잡도 데이터가 없어요."

# INFO question_type(concentration 제외 7종) 한글 라벨 — PlaceInfoResult.fields의
# 키와 no_data 문구 조립에 함께 쓴다(backend/docs/package-a/
# info-question-types-handoff.md). C가 fields에 값이 있는 키만 채워 보내므로,
# 이 라벨 맵은 "그 키가 있으면 이렇게 부른다"는 표시 규칙일 뿐이다.
_INFO_FIELD_LABELS: dict[str, str] = {
    "operating_hours": "운영시간",
    "rest_date": "휴무일",
    "fee": "요금",
    "parking": "주차",
    "parking_fee": "주차 요금",
    "baby_carriage": "유모차 대여",
    "pet": "반려동물 동반",
    "credit_card": "카드 결제",
    "restroom": "화장실",
    "address": "주소",
    "general_info": "장소 개요",
    "location_info": "위치",
    "overview": "개요",
    "homepage": "홈페이지",
}
_INFO_QUESTION_TYPE_LABELS: dict[str, str] = {
    "operating_hours": "운영시간",
    "fee": "요금",
    "parking": "주차",
    "facility": "편의시설",
    "location_info": "위치",
    "general_info": "개요",
}
# facility의 하위 필드 4개는 라벨이 고정이라 은/는을 미리 붙여둔다(값의 받침에
# 좌우되지 않게 "라벨+조사"까지 고정하고, 뒤에 값만 이어붙인다).
_FACILITY_FIELD_PHRASES: dict[str, str] = {
    "baby_carriage": "유모차 대여는",
    "pet": "반려동물 동반은",
    "credit_card": "카드 결제는",
    "restroom": "화장실은",
}

logger = logging.getLogger(__name__)


def compose_recommendation_message(item: RecommendationItem) -> str:
    """explanations를 먼저, warnings는 "다만, ~" 형태로 마지막에 붙인다.

    explanations/warnings 둘 다 이미 완결된 문장(마침표 포함)이라 공백으로
    이어붙인다. explanations는 빈 배열일 수 있다(임계값 미달 등) — 그 경우
    warnings만 "다만, ~"으로 반환한다.
    """
    parts: list[str] = []
    if item.explanations:
        parts.append(" ".join(item.explanations))
    if item.warnings:
        parts.append(f"다만, {' '.join(item.warnings)}")
    return " ".join(parts)


def compose_info_concentration_message(response: InfoContextResponse) -> str:
    """INFO(question_type=concentration) 응답 문구를 조립한다.

    concentration-conditions.md §3.3/§7의 고지 규칙을 고정 로직으로 강제한다 —
    LLM 스타일링이 아니라 정확성이 걸린 문제라서다. is_proxy=True면 반드시
    "근처 [관광지] 기준" 문구를 넣고, 요청한 장소 자체의 값처럼 말하지 않는다.
    """

    if response.status == "needs_clarification":
        code = response.clarification.code if response.clarification is not None else None
        return _CLARIFICATION_TEMPLATES.get(code, _CLARIFICATION_FALLBACK_MESSAGE)
    if response.status == "unsupported":
        return _unsupported_message(response.error.code if response.error else None)
    if response.status == "unavailable" or response.result is None:
        return _TOOL_UNAVAILABLE_MESSAGE

    result = response.result
    if result.status == "unavailable":
        return _TOOL_UNAVAILABLE_MESSAGE
    if result.status == "no_data":
        return _CONCENTRATION_NO_DATA_MESSAGE

    label = result.concentration_label or "알 수 없음"
    date_label = result.forecast_date or "해당 날짜"
    if result.is_proxy:
        return (
            f"{result.requested_place_name} 자체의 혼잡도 데이터는 없지만, "
            f"가장 가까운 관광지인 {result.resolved_place_name} 기준으로는 "
            f"{date_label} {label}인 편이에요. 비슷한 수준일 가능성이 있어요."
        )
    return f"{result.resolved_place_name}은(는) {date_label} 기준 {label} 것으로 예측돼요."


def compose_place_info_message(response: InfoContextResponse) -> str:
    """INFO(question_type=concentration/event 제외 6종) 응답 문구를 조립한다.

    C가 fields에 값이 있는 키만 채워 보내므로(info-question-types-handoff.md),
    여기서 없는 값을 지어내지 않고 fields를 그대로 나열한다. general_info의
    overview는 원문 그대로 싣는다 — LLM 요약 없이 고정 템플릿으로 두는 쪽이
    concentration과 같은 "정확성이 걸린 문제는 스타일링하지 않는다" 원칙과
    일관된다.
    """

    if response.status == "needs_clarification":
        code = response.clarification.code if response.clarification is not None else None
        return _CLARIFICATION_TEMPLATES.get(code, _CLARIFICATION_FALLBACK_MESSAGE)
    if response.status == "unsupported":
        return _unsupported_message(response.error.code if response.error else None)
    if response.status == "unavailable" or response.result is None:
        return _TOOL_UNAVAILABLE_MESSAGE

    result = response.result
    assert isinstance(result, PlaceInfoResult)
    if result.status == "unavailable":
        return _TOOL_UNAVAILABLE_MESSAGE

    place_label = result.resolved_place_name or result.requested_place_name or "그 장소"
    if result.status == "no_data":
        type_label = _INFO_QUESTION_TYPE_LABELS.get(result.question_type, "그 질문")
        return f"{place_label}의 {type_label} 정보는 확인할 수 없어요."

    return _compose_place_info_sentence(place_label, result.question_type, result.fields)


def _compose_place_info_sentence(
    place_label: str, question_type: str, fields: dict[str, str]
) -> str:
    """question_type별로 자연스러운 한국어 문장을 만든다.

    fields의 값(C가 TourAPI 원문에서 뽑은 자유 텍스트)은 절대 파싱·재구성하지
    않는다 — 값을 감싸는 문장 커넥터만 question_type에 맞춰 고른다. 값을 안
    건드리므로 라벨:값 나열보다 자연스러우면서도 사실을 지어낼 위험은 없다.
    """

    if question_type == "operating_hours" and "operating_hours" in fields:
        sentence = f"{place_label} 운영시간은 {fields['operating_hours']}예요."
        if "rest_date" in fields:
            sentence += f" 휴무일은 {fields['rest_date']}예요."
        return sentence

    if question_type == "fee" and "fee" in fields:
        return f"{place_label} 입장료는 {fields['fee']}예요."

    if question_type == "parking" and "parking" in fields:
        sentence = f"{place_label} 주차는 {fields['parking']}이에요."
        if "parking_fee" in fields:
            sentence += f" 주차 요금은 {fields['parking_fee']}예요."
        return sentence

    if question_type == "facility":
        # 라벨 4개가 고정이라 은/는을 직접 붙인다(받침 유무로 자동 판정하지 않음).
        parts = [
            f"{_FACILITY_FIELD_PHRASES[key]} {fields[key]}"
            for key in ("baby_carriage", "pet", "credit_card", "restroom")
            if key in fields
        ]
        if parts:
            return f"{place_label}의 편의시설이에요. " + ", ".join(parts) + "예요."

    if question_type == "location_info" and "address" in fields:
        return f"{place_label} 주소는 {fields['address']}예요."

    if question_type == "general_info" and "overview" in fields:
        sentence = f"{place_label} 소개예요. {fields['overview']}"
        if "homepage" in fields:
            sentence += f" 홈페이지는 {fields['homepage']}예요."
        return sentence

    # 8종 외 새 question_type이 생기거나 예상 밖 필드 조합이면 라벨:값 나열로
    # 안전하게 낮아진다 — 크래시 대신 최소한의 정보는 전달한다.
    homepage = fields.get("homepage")
    parts = [
        f"{_INFO_FIELD_LABELS.get(key, key)}: {value}"
        for key, value in fields.items()
        if key != "homepage"
    ]
    sentence = f"{place_label} — " + ", ".join(parts) if parts else f"{place_label} 정보예요."
    if homepage:
        sentence += f" 홈페이지: {homepage}"
    return sentence


def compose_event_info_message(response: InfoContextResponse) -> str:
    """INFO(question_type=event) 응답 문구를 조립한다.

    D-055/info-question-types-handoff.md의 필수 규칙: is_direct_match=False인
    행사를 그 장소의 행사처럼 말하지 않는다 — TourAPI에 장소별 행사 조회가
    없어 지역 단위로 받아 좌표 거리로 근접 매칭하기 때문이다. 직접 매칭 행사와
    근처 행사를 문장에서 분리해 고지한다.
    """

    if response.status == "needs_clarification":
        code = response.clarification.code if response.clarification is not None else None
        return _CLARIFICATION_TEMPLATES.get(code, _CLARIFICATION_FALLBACK_MESSAGE)
    if response.status == "unsupported":
        return _unsupported_message(response.error.code if response.error else None)
    if response.status == "unavailable" or response.result is None:
        return _TOOL_UNAVAILABLE_MESSAGE

    result = response.result
    assert isinstance(result, EventInfoResult)
    if result.status == "unavailable":
        return _TOOL_UNAVAILABLE_MESSAGE

    place_label = result.resolved_place_name or result.requested_place_name or "그 장소"
    if result.status == "no_data" or not result.events:
        return f"{place_label} 근처에 지금 진행 중인 행사가 없어요."

    direct = [event for event in result.events if event.is_direct_match]
    nearby = [event for event in result.events if not event.is_direct_match]

    sentences: list[str] = []
    if direct:
        titles = ", ".join(event.title for event in direct)
        sentences.append(f"{place_label}에서 진행 중인 행사예요. {titles}.")
    if nearby:
        items = ", ".join(
            f"{event.title}({event.distance_km:.2f}km)"
            if event.distance_km is not None
            else event.title
            for event in nearby
        )
        sentences.append(f"{place_label} 근처에서 진행 중인 행사예요. {items}.")
    return " ".join(sentences)


def compose_schedule_message(schedule: ScheduleResult) -> str:
    """SCHEDULE 응답 말풍선 텍스트를 조립한다.

    장소별 도착 시각·이유 같은 상세는 여기서 다시 풀어쓰지 않는다 —
    AgentResponse.schedule이 이미 그 정보를 갖고 있다(문서 docstring 원칙과
    동일하게 message는 요약만 맡는다).
    """

    hours, minutes = divmod(schedule.total_duration_min, 60)
    duration_label = f"{hours}시간 {minutes}분" if hours else f"{minutes}분"
    return f"{duration_label} 코스를 짜봤어요. {schedule.route_summary}"


async def compose_chat_message(
    llm_output: LLMOutput,
    *,
    recommendations: RecommendationResponse | None = None,
    schedule: ScheduleResult | None = None,
    tool_status: str | None = None,
    tool_clarification: Clarification | None = None,
    tool_error_code: str | None = None,
    info_response: InfoContextResponse | None = None,
    llm: LLMProvider,
) -> str:
    """AgentResponse.message(챗봇 말풍선 텍스트)를 조립한다.

    docs/design/agent-response-generation.md의 결정을 구현한다. GENERAL은 답변
    본문을, RECOMMEND/MODIFY 성공 경로는 추천 카드 wrapper를 LLM으로 생성한다.
    추천 카드의 상세 내용은 여기서 길게 다시 풀어쓰지 않는다.
    """

    if llm_output.status is OutputStatus.NEEDS_CLARIFICATION:
        # LLM 단계 needs_clarification은 추출 단계에서 이미 자연어 메시지가 나온다.
        assert llm_output.clarification is not None
        return llm_output.clarification.message

    if llm_output.intent is Intent.OUT_OF_SCOPE:
        assert llm_output.out_of_scope is not None
        return _OUT_OF_SCOPE_TEMPLATES[llm_output.out_of_scope.category.value]

    if llm_output.intent is Intent.GENERAL:
        assert llm_output.general is not None
        result = await llm.generate_general_answer(
            llm_output.general.topic, llm_output.general.original_question
        )
        return result.data

    if llm_output.intent is Intent.INFO and info_response is not None:
        if isinstance(info_response.result, EventInfoResult):
            return compose_event_info_message(info_response)
        if isinstance(info_response.result, PlaceInfoResult):
            return compose_place_info_message(info_response)
        return compose_info_concentration_message(info_response)

    if llm_output.intent in (Intent.RECOMMEND, Intent.MODIFY, Intent.SCHEDULE):
        if tool_status in _TOOL_TERMINAL_STATUSES:
            if tool_status == "needs_clarification":
                code = tool_clarification.code if tool_clarification is not None else None
                return _CLARIFICATION_TEMPLATES.get(code, _CLARIFICATION_FALLBACK_MESSAGE)
            if tool_status == "unsupported":
                return _unsupported_message(tool_error_code)
            # no_data는 장애가 아니라 "조건에 맞는 후보가 없음"이다. 명시하지 않으면
            # 아래 unavailable 문구로 새어 사용자에게 오류처럼 보인다.
            if tool_status == "no_data":
                return _NO_DATA_MESSAGE
            return _TOOL_UNAVAILABLE_MESSAGE

        if llm_output.intent is Intent.SCHEDULE:
            # schedule이 아직 None이면(예: 이번 호출부가 배선 전이거나 방어적 호출)
            # 안내 문구로 안전하게 낮춘다 — 정상 경로는 agent_runtime.py가 항상
            # schedule을 채워서 넘긴다.
            if schedule is None:
                return _SCHEDULE_NOT_YET_SUPPORTED_MESSAGE
            return compose_schedule_message(schedule)

        shown = (
            [*recommendations.recommendations, *recommendations.unverified_recommendations]
            if recommendations is not None
            else []
        )
        if not shown:
            return _NO_DATA_MESSAGE
        try:
            result = await llm.generate_recommendation_summary(llm_output.intent, recommendations)
        except AppError:
            logger.warning(
                "추천 요약 LLM 생성 실패, 기본 템플릿으로 fallback: intent=%s",
                llm_output.intent.value,
                exc_info=True,
            )
            return _RECOMMEND_WRAPPER_MESSAGE
        return result.data

    # INFO/COMPARE — 별도 트랙(agent-response-generation.md §3/§6 3차), 지금은 안내만.
    return _NOT_YET_SUPPORTED_MESSAGE


__all__ = [
    "compose_recommendation_message",
    "compose_chat_message",
    "compose_info_concentration_message",
    "compose_place_info_message",
    "compose_event_info_message",
    "compose_schedule_message",
]
