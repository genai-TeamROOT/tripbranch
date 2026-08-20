"""D의 RecommendationItem과 LLMOutput을 사용자에게 보여줄 텍스트로 조립한다.

역할: 두 계층을 담당한다(docs/design/agent-response-generation.md 참고).
1) compose_recommendation_message(): 장소 카드 1건에 들어갈 문장. D가 만든
   explanations(근거)/warnings(경고)를 D님과 협의한 순서(근거 먼저, 경고는
   "다만~"으로 마지막)로 이어붙인다. 문장 내용 자체는 재작문하지 않고 D가 만든
   그대로 쓴다.
2) compose_chat_message(): 카드들을 감싸는 챗봇 말풍선 텍스트(AgentResponse.message).
   Intent/status별로 고정 템플릿을 고르거나 GENERAL·INFO·COMPARE처럼 문장 생성 가치가
   큰 응답에만 LLM을 호출한다. RECOMMEND/MODIFY의 카드 소개는 고정 템플릿으로 즉시
   반환해, 이미 완성된 추천 결과를 위해 추가 LLM 대기 시간을 만들지 않는다.
"""

from __future__ import annotations

import logging
import math
from collections.abc import AsyncIterator, Awaitable, Callable

from app.domain.travel_route import TravelRoute
from app.errors import AppError
from app.providers.protocols import LLMProvider
from app.schemas import (
    CompareCriteria,
    ComparisonItem,
    ComparisonResult,
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
    RealtimeCommercialInfoResult,
)
from app.services.runtime.info_display import format_citydata_timestamp, format_parking_for_display

# C 단계에서 Recommendation으로 못 넘어가는 status. agent_runtime.py의
# _TOOL_TERMINAL_STATUSES와 같은 집합이어야 한다 — 순환 import를 피하려고 별도로
# 둔다. 두 집합이 어긋나면 메시지가 엉뚱한 분기로 새므로 테스트로 일치를 고정한다.
_TOOL_TERMINAL_STATUSES = frozenset(
    {"needs_clarification", "no_data", "unsupported", "unavailable"}
)

_RECOMMEND_WRAPPER_MESSAGE = "이런 곳들을 찾아봤어요:"

MessageDeltaCallback = Callable[[str], Awaitable[None]]

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


def tool_clarification_message(code: str | None) -> str:
    """C 단계 되묻기 code를 사용자 문구로 바꾼다.

    agent_runtime이 되묻기에 버튼을 붙일 때(예: location_required) 같은 문구를
    재사용하려고 노출한다 — 이 모듈 안의 compose_chat_message()도 내부적으로
    같은 테이블을 쓴다.
    """
    return _CLARIFICATION_TEMPLATES.get(code or "", _CLARIFICATION_FALLBACK_MESSAGE)


_TOOL_UNSUPPORTED_MESSAGE = "죄송하지만 아직 지원하지 않는 요청이에요."

# unsupported는 이유가 여러 가지다. 지원 지역 밖인데 "아직 지원하지 않는 요청"이라고만
# 하면 무엇을 바꿔야 할지 알 수 없다(D-044).
_TOOL_UNSUPPORTED_TEMPLATES: dict[str, str] = {
    "unsupported_region": (
        "현재는 베타 서비스로 종로구의 장소 추천만 가능해요. "
        "종로에서 가고 싶은 위치를 말씀해주세요."
    ),
    "realtime_commercial_unsupported_region": (
        "해당 장소 주변은 서울시 실시간 상권 데이터 제공 지역이 아니에요. "
        "현재는 서울시 주요 82개 지역의 카페 상권 현황만 확인할 수 있어요."
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


async def _collect_message_stream(
    stream: AsyncIterator[str], on_message_delta: MessageDeltaCallback
) -> str:
    """LLM 텍스트 스트림을 말풍선 이벤트로 전달하면서 최종 문장도 조립한다."""

    chunks: list[str] = []
    async for delta in stream:
        if not delta:
            continue
        chunks.append(delta)
        await on_message_delta(delta)
    return "".join(chunks).strip()


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


def compose_realtime_commercial_message(response: InfoContextResponse) -> str:
    """특정 카페를 최근접 서울시 상권의 카페 소비 활동으로 안내한다."""

    if response.status == "needs_clarification":
        code = response.clarification.code if response.clarification is not None else None
        return _CLARIFICATION_TEMPLATES.get(code, _CLARIFICATION_FALLBACK_MESSAGE)
    if response.status == "unsupported":
        return _unsupported_message(response.error.code if response.error else None)
    if response.status == "unavailable" or response.result is None:
        return _TOOL_UNAVAILABLE_MESSAGE

    result = response.result
    assert isinstance(result, RealtimeCommercialInfoResult)
    if result.status == "unavailable":
        return _TOOL_UNAVAILABLE_MESSAGE
    if result.status == "no_data":
        area = result.area_name or "가까운 제공 지역"
        return f"{area}의 카페 상권 실시간 데이터는 현재 확인할 수 없어요."

    place = result.resolved_place_name or result.requested_place_name or "해당 카페"
    area = result.area_name or "가까운 상권"
    category = result.category_label or "카페 업종"
    level = result.commercial_level or "확인할 수 없음"
    distance = (
        f"약 {result.proxy_distance_km:.1f}km 떨어진 "
        if result.proxy_distance_km is not None and result.proxy_distance_km >= 0.05
        else ""
    )
    observed_at = format_citydata_timestamp(result.observed_at)
    observed = f" {observed_at} 기준이에요." if observed_at else ""
    if result.commercial_scope == "area_overall":
        return (
            f"{place} 개별 매장 혼잡도는 확인할 수 없고, {distance}{area}의 카페 업종 "
            f"세부값도 현재 제공되지 않았어요. 대신 {area} 전체 상권은 현재 {level} 수준이에요. "
            f"이 값은 지역 전체 카드 소비 활동 기준이에요.{observed}"
        )
    return (
        f"{place} 개별 매장 혼잡도는 확인할 수 없지만, {distance}{area}의 "
        f"{category} 상권은 현재 {level} 수준이에요. 이 값은 지역·업종별 카드 소비 활동 기준이에요."
        f"{observed}"
    )


def compose_place_info_message(
    response: InfoContextResponse,
    *,
    specific_question: str | None = None,
    walking_route: TravelRoute | None = None,
    walking_origin_available: bool = False,
) -> str:
    """INFO(question_type=concentration/event 제외 6종) 응답 문구를 조립한다.

    C가 fields에 값이 있는 키만 채워 보내므로(info-question-types-handoff.md),
    여기서 없는 값을 지어내지 않는다. 긴 원문(운영시간·요금·개요)은 말풍선에
    다시 싣지 않고 아래 장소 카드에서 보여준다. 사실값을 재서술하는 LLM 호출은
    추가하지 않고 질문 유형별 고정 템플릿으로 짧게 안내한다.
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
    if result.question_type == "location_info" and _asks_walking_time(specific_question):
        return _compose_info_walking_time_message(
            place_label,
            result.fields.get("address"),
            walking_route=walking_route,
            origin_available=walking_origin_available,
        )
    if result.status == "no_data":
        type_label = _INFO_QUESTION_TYPE_LABELS.get(result.question_type, "그 질문")
        return f"{place_label}의 {type_label} 정보는 확인할 수 없어요."

    return _compose_place_info_sentence(
        place_label,
        result.question_type,
        result.fields,
        specific_question=specific_question,
    )


def _asks_walking_time(specific_question: str | None) -> bool:
    normalized = (specific_question or "").replace(" ", "")
    markers = (
        "가는데얼마나걸",
        "걷는데얼마나걸",
        "걸어서얼마나",
        "도보로얼마나",
        "도보시간",
        "도보이동",
    )
    return any(marker in normalized for marker in markers)


def _compose_info_walking_time_message(
    place_label: str,
    address: str | None,
    *,
    walking_route: TravelRoute | None,
    origin_available: bool,
) -> str:
    """INFO 도보 시간은 LLM 추측 대신 카카오 경로 결과만으로 안내한다."""

    if walking_route is not None:
        seconds = walking_route.duration_seconds or 0
        distance_m = walking_route.distance_m or 0
        if seconds == 0:
            return f"현재 위치에서 {place_label}까지 바로 도착할 수 있어요."
        minutes = max(1, math.ceil(seconds / 60))
        return (
            f"현재 위치에서 {place_label}까지 도보 약 {minutes}분 걸려요. "
            f"이동 거리는 약 {distance_m:,}m예요."
        )
    if not origin_available:
        message = f"현재 위치 정보가 없어 {place_label}까지 도보 이동 시간을 확인할 수 없어요."
        return f"{message} {place_label} 주소는 {address}예요." if address else message
    message = f"현재 위치에서 {place_label}까지의 도보 경로를 확인하지 못했어요."
    return f"{message} {place_label} 주소는 {address}예요." if address else message


def _compose_place_info_sentence(
    place_label: str,
    question_type: str,
    fields: dict[str, str],
    *,
    specific_question: str | None,
) -> str:
    """질문 유형별 짧은 말풍선 안내를 만든다.

    세부 사실은 같은 응답의 ``info_place_card``가 담당한다. 단, 휴무일과 성인
    입장료처럼 사용자가 즉시 알고 싶어 하는 1차 결론만 원문에서 안전하게 꺼낸다.
    """

    if question_type == "operating_hours" and "operating_hours" in fields:
        rest_date = fields.get("rest_date")
        if rest_date and _asks_rest_date(specific_question):
            main, notices = _split_notices(rest_date)
            sentence = f"{place_label} 휴무일은 {main}입니다."
            if notices:
                sentence += "\n" + "\n".join(notices)
            return sentence + "\n\n아래에서 자세한 운영시간을 확인하세요."
        return f"{place_label} 운영시간을 확인했어요. 아래에서 월별 운영시간과 휴무일을 확인하세요."

    if question_type == "fee" and "fee" in fields:
        summary = _fee_summary(fields["fee"])
        if summary:
            return (
                f"{place_label} 입장료는 {summary}이에요. 아래에서 상세 요금 정보를 확인해보세요!"
            )
        return f"{place_label} 입장료 정보를 찾았어요. 아래에서 상세 요금 정보를 확인해보세요!"

    if question_type == "parking" and "parking" in fields:
        return (
            f"{place_label} 주차는 {_parking_status(fields['parking'])}해요. "
            "아래 주차 상세 내용을 확인해보세요."
        )

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


def _asks_rest_date(question: str | None) -> bool:
    """운영시간 유형 안에서 휴무일을 직접 물은 경우만 구분한다."""

    normalized = (question or "").replace(" ", "")
    return any(token in normalized for token in ("휴무", "쉬는날", "휴관"))


def _split_notices(value: str) -> tuple[str, list[str]]:
    """``※`` 뒤 안내를 별도 줄로 분리한다."""

    parts = [part.strip() for part in value.split("※")]
    main = parts[0]
    notices = [f"※ {part}" for part in parts[1:] if part]
    return main, notices


def _fee_summary(value: str) -> str | None:
    """요금 원문 첫 항목에서 성인 기준의 짧은 결론만 뽑는다."""

    before_notice = value.split("※", maxsplit=1)[0]
    items = [item.strip() for item in before_notice.split("-") if item.strip()]
    if not items:
        return None
    first = items[0]
    if first.startswith("성인 "):
        return "성인 기준 " + first.removeprefix("성인 ")
    return first


def _parking_status(value: str) -> str:
    """수용 대수보다 먼저 읽히는 주차 가능 여부만 말풍선에 쓴다."""

    status = value.split("(", maxsplit=1)[0].strip()
    return {"가능": "가능", "불가": "불가능"}.get(status, status or "확인 가능")


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


async def compose_compare_message(comparison: ComparisonResult, llm: LLMProvider) -> str:
    """COMPARE 사실 데이터를 3~6줄 LLM 설명으로 바꾼다.

    C가 반환할 ComparisonResult는 이미 추천 시점 Feature 스냅샷을 기준으로 한
    검증된 데이터다. LLM은 문장을 다듬는 역할만 하며, 호출이 실패해도 비교 요청
    전체를 실패시키지 않고 고정 템플릿으로 안전하게 낮춘다.
    """

    try:
        return (await llm.generate_compare_summary(comparison)).data
    except AppError:
        logger.warning(
            "COMPARE 요약 LLM 생성 실패, 기본 템플릿으로 fallback: criteria=%s",
            comparison.criteria.value,
            exc_info=True,
        )
        return _compose_compare_fallback(comparison)


def _compose_compare_fallback(comparison: ComparisonResult) -> str:
    """LLM 장애 시 C의 사실 데이터만으로 만드는 사용자 표시용 비교 문구."""

    criterion_label = {
        CompareCriteria.DISTANCE: "거리",
        CompareCriteria.TIME: "운영시간",
        CompareCriteria.OVERALL: "거리·운영시간·환경",
    }[comparison.criteria]
    recommended = _select_compare_recommendation(comparison)
    lines = [
        f"요청하신 {criterion_label} 기준으로 보면, "
        f"{recommended.place_name}{_object_particle(recommended.place_name)} 추천드려요."
    ]
    for item in comparison.items[:4]:
        details: list[str] = []
        if item.distance_km is not None:
            details.append(_format_compare_walking_time(item.distance_km))
        if item.remaining_minutes is not None:
            details.append(_format_compare_remaining_time(item.remaining_minutes))
        if item.environment_type is not None:
            details.append(f"{item.environment_type} 환경")
        value = ", ".join(details) if details else "비교 정보 확인 필요"
        lines.append(f"{item.rank}번 {item.place_name}은 {value}이에요.")
    while len(lines) < 3:
        lines.append("확인된 정보를 바탕으로 방문 목적에 맞는 곳을 선택해보세요.")
    return "\n".join(lines[:6])


def _select_compare_recommendation(comparison: ComparisonResult) -> ComparisonItem:
    """LLM fallback에서도 질문 기준과 맞는 한 곳을 분명히 고른다."""

    if comparison.criteria is CompareCriteria.DISTANCE:
        with_distance = [item for item in comparison.items if item.distance_km is not None]
        if with_distance:
            return min(with_distance, key=lambda item: item.distance_km or 0)
    elif comparison.criteria is CompareCriteria.TIME:
        with_time = [item for item in comparison.items if item.remaining_minutes is not None]
        if with_time:
            return max(with_time, key=lambda item: item.remaining_minutes or 0)
    # overall은 D가 직전에 정렬해 노출한 1번을 기준으로, 추가 점수 계산 없이 고른다.
    return comparison.items[0]


def _object_particle(value: str) -> str:
    """한글 장소명 뒤에 자연스러운 목적격 조사(을/를)를 붙인다."""

    last = value[-1] if value else ""
    is_hangul = "가" <= last <= "힣"
    return "을" if is_hangul and (ord(last) - ord("가")) % 28 else "를"


def _format_compare_walking_time(distance_km: float) -> str:
    """추천 카드와 같은 보수적 보행 속도로 거리 스냅샷을 표시한다."""

    minutes = max(1, math.ceil(distance_km * 60 / 3.6))
    return f"도보 약 {minutes}분"


def _format_compare_remaining_time(remaining_minutes: int) -> str:
    """분 단위 스냅샷을 카드와 같은 시간 단위 표시로 바꾼다."""

    # JavaScript 카드의 Math.round()와 동일하게 .5는 올림 처리한다.
    hours = max(1, math.floor(remaining_minutes / 60 + 0.5))
    return f"약 {hours}시간 남음"


# 요청 시간과 실제 편성 시간의 차이가 이 값(분) 이내면 문구에 실제 계산값 대신
# 사용자가 요청한 시간을 그대로 보여준다 — "2시간 짜줘"에 "1시간 52분 코스를
# 짜봤어요"처럼 어색하게 어긋나 보이는 걸 막는다. 차이가 크면(후보 부족 등으로
# 실제 편성이 요청과 크게 벌어진 경우) 사용자를 오도하지 않도록 실제 계산값을
# 그대로 보여준다. 15분이었을 때 "3시간 짜줘"(180분)에 실제 163분(오차 17분)이
# 편성되는 경계 사례가 실제 계산값을 그대로 노출해 어색했다 — 되도록 요청값을
# 그대로 보여주는 쪽을 우선하기로 하고 30분으로 넓힘(실사용 피드백, 2026-08-14).
_DURATION_MATCH_TOLERANCE_MIN = 30


def _format_duration_label(total_minutes: int) -> str:
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}시간 {minutes}분"
    if hours:
        return f"{hours}시간"
    return f"{minutes}분"


def compose_schedule_message(
    schedule: ScheduleResult, *, time_available_min: int | None = None
) -> str:
    """SCHEDULE 응답 말풍선 텍스트를 조립한다.

    장소별 도착 시각·이유 같은 상세는 여기서 다시 풀어쓰지 않는다 —
    AgentResponse.schedule이 이미 그 정보를 갖고 있다(문서 docstring 원칙과
    동일하게 message는 요약만 맡는다).

    items가 비어있으면(후보 부족 등으로 일정을 못 짠 경우, app/schedule/
    planner.py가 route_summary를 안내 문구로 정규화해서 넘겨준다) "0분 코스를
    짜봤어요" 같은 어색한 접두사 없이 route_summary만 그대로 반환한다.

    time_available_min(사용자가 요청한 시간, 분)이 주어지고 실제
    total_duration_min과의 차이가 _DURATION_MATCH_TOLERANCE_MIN 이내면 요청
    시간을 그대로 보여준다("2시간 짜줘" → "2시간 코스를 짜봤어요"). 차이가 크면
    실제 편성 결과가 요청과 동떨어졌다는 뜻이므로 실제 계산값을 보여준다.
    """

    if not schedule.items:
        return schedule.route_summary

    if (
        time_available_min is not None
        and abs(time_available_min - schedule.total_duration_min) <= _DURATION_MATCH_TOLERANCE_MIN
    ):
        duration_label = _format_duration_label(time_available_min)
    else:
        duration_label = _format_duration_label(schedule.total_duration_min)
    return f"{duration_label} 코스를 짜봤어요. {schedule.route_summary}"


async def compose_chat_message(
    llm_output: LLMOutput,
    *,
    recommendations: RecommendationResponse | None = None,
    schedule: ScheduleResult | None = None,
    schedule_time_available_min: int | None = None,
    tool_status: str | None = None,
    tool_clarification: Clarification | None = None,
    tool_error_code: str | None = None,
    info_response: InfoContextResponse | None = None,
    info_walking_route: TravelRoute | None = None,
    info_walking_origin_available: bool = False,
    llm: LLMProvider,
    on_message_delta: MessageDeltaCallback | None = None,
) -> str:
    """AgentResponse.message(챗봇 말풍선 텍스트)를 조립한다.

    docs/design/agent-response-generation.md의 결정을 구현한다. GENERAL·INFO·COMPARE는
    필요할 때 LLM으로 답변 본문을 생성하고, RECOMMEND/MODIFY 성공 경로는 추천 카드
    wrapper를 LLM으로 생성한다. 추천 카드의 상세 내용은 여기서 길게 다시 풀어쓰지 않는다.

    schedule_time_available_min은 SCHEDULE 경로에서만 쓰인다(사용자가 요청한
    활동 가능 시간, 분) — compose_schedule_message에 그대로 전달해 "요청한
    시간대로" 문구를 만드는 데 쓴다.
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
        if on_message_delta is not None:
            try:
                message = await _collect_message_stream(
                    llm.stream_general_answer(
                        llm_output.general.topic, llm_output.general.original_question
                    ),
                    on_message_delta,
                )
                if message:
                    return message
            except AppError:
                logger.warning("GENERAL 답변 스트리밍 실패, 단발 호출로 fallback", exc_info=True)
        result = await llm.generate_general_answer(
            llm_output.general.topic, llm_output.general.original_question
        )
        if on_message_delta is not None:
            await on_message_delta(result.data)
        return result.data

    if llm_output.intent is Intent.INFO and info_response is not None:
        if isinstance(info_response.result, RealtimeCommercialInfoResult):
            return compose_realtime_commercial_message(info_response)
        if isinstance(info_response.result, EventInfoResult):
            return compose_event_info_message(info_response)
        if isinstance(info_response.result, PlaceInfoResult):
            fallback_message = compose_place_info_message(
                info_response,
                specific_question=(
                    llm_output.info.specific_question if llm_output.info is not None else None
                ),
                walking_route=info_walking_route,
                walking_origin_available=info_walking_origin_available,
            )
            result = info_response.result
            if on_message_delta is not None and result.status == "success" and bool(result.fields):
                place_name = result.resolved_place_name or result.requested_place_name or "그 장소"
                # 말풍선도 카드의 질문 답변과 같은 정제 규칙을 따른다. 예를 들어
                # 주차 원문에는 버스 수용 대수가 있어도 일반 사용자용 화면은 승용차
                # 정보만 노출한다.
                display_fields = {
                    key: format_parking_for_display(value) if key == "parking" else value
                    for key, value in result.fields.items()
                }
                try:
                    message = await _collect_message_stream(
                        llm.stream_info_answer(
                            place_name=place_name,
                            question_type=result.question_type,
                            specific_question=(
                                llm_output.info.specific_question
                                if llm_output.info is not None
                                else None
                            ),
                            fields=display_fields,
                        ),
                        on_message_delta,
                    )
                    if message:
                        return message
                except AppError:
                    logger.warning(
                        "INFO 답변 스트리밍 실패, 고정 안내문으로 fallback", exc_info=True
                    )
                await on_message_delta(fallback_message)
            return fallback_message
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
            return compose_schedule_message(
                schedule, time_available_min=schedule_time_available_min
            )

        shown = (
            [*recommendations.recommendations, *recommendations.unverified_recommendations]
            if recommendations is not None
            else []
        )
        if not shown:
            return _NO_DATA_MESSAGE
        if on_message_delta is not None:
            await on_message_delta(_RECOMMEND_WRAPPER_MESSAGE)
        return _RECOMMEND_WRAPPER_MESSAGE

    # INFO/COMPARE — 별도 트랙(agent-response-generation.md §3/§6 3차), 지금은 안내만.
    return _NOT_YET_SUPPORTED_MESSAGE


__all__ = [
    "compose_recommendation_message",
    "compose_chat_message",
    "compose_info_concentration_message",
    "compose_realtime_commercial_message",
    "compose_place_info_message",
    "compose_event_info_message",
    "compose_compare_message",
    "compose_schedule_message",
]
