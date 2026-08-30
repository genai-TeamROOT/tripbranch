"""TripBranch fake provider 구현체 모음.

역할: 외부 API 호출 없이 고정/임시 데이터로 각 provider 계약을 만족시킨다.
입력: 각 provider protocol이 요구하는 파라미터.
출력: 각 provider protocol이 요구하는 응답 모델.
호출 시점: PLACE_PROVIDER=fake 등 설정이 fake일 때 provider 팩토리가 주입한다.
TODO: 실제 provider(RealPlaceProvider 등)가 준비되면 팩토리에서 설정값으로 분기한다.
"""

from __future__ import annotations

import math
from collections.abc import AsyncIterator, Mapping
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from app.domain.models import (
    PlaceCategoryFilter,
    PlaceDetails,
    WeatherForecastResult,
    WeatherForecastSlot,
)
from app.domain.operating_hours import normalize_operating_schedule
from app.errors import AppError
from app.place_search_policy import DEFAULT_PLACE_PROVIDER_RESULT_LIMIT
from app.providers.contracts import (
    ProviderResult,
    ProviderSource,
    ProviderStatus,
    provider_result,
)
from app.providers.tour_intro_keys import (
    BABY_CARRIAGE_KEYS,
    CREDIT_CARD_KEYS,
    PARKING_FEE_KEYS,
    PARKING_KEYS,
    PET_KEYS,
    RESTROOM_KEYS,
    USE_FEE_KEYS,
)
from app.schedule.schemas import (
    ScheduleLLMPlan,
    SchedulePartialFillRequest,
    SchedulePartialLLMPlan,
    SchedulePlanningRequest,
)
from app.schemas import (
    ClarificationPayload,
    CompareCriteria,
    ComparePayload,
    ComparisonItem,
    ComparisonResult,
    ConcentrationIntent,
    Environment,
    GeneralPayload,
    GeneralTopic,
    InfoPayload,
    Intent,
    IntentClassificationResult,
    LLMOutput,
    ModifyPayload,
    ModifyType,
    OutOfScopeCategory,
    OutputStatus,
    PlaceCandidate,
    PlaceContext,
    PlaceTag,
    PlaceType,
    QuestionType,
    RecommendationResponse,
    RecommendPayload,
    ScheduleItem,
    Severity,
    StatedWeather,
    Transport,
    UserConditions,
    WeatherIntent,
)

# NOTE(비활성화, 팀 논의 후 결정 필요): 아래 FakeInterpretProvider는 669cc82(2026-07-22,
# 작성자 mac)에서 도입된 원본 코드다. 2026-07-24 LLM provider 1차 구현(21aad22)에서
# interpret_user_input()의 시그니처가
#   def interpret_user_input(user_input: str) -> InterpretedConditions
# 에서
#   async def interpret_user_input(request: InterpretRequest) -> LLMOutput
# 로 바뀌면서 아래 코드를 그대로 실행하면 깨진다(인자 개수·타입, sync/async 모두 불일치).
# 삭제하지 않고 주석으로만 남겨둔다 — 이 provider를 계속 쓸지, 새 LLMOutput 계약에 맞게
# 고쳐 쓸지는 팀 확인 후 결정한다.
#
# class FakeInterpretProvider:
#     """자연어 입력 해석을 고정 조건으로 대체하는 fake provider."""
#
#     def interpret(self, user_input: str) -> InterpretedConditions:
#         return interpret_user_input(user_input)

_KNOWN_PLACE_NAMES = (
    "경복궁",
    "창덕궁",
    "종묘",
    "인사동",
    "광화문",
    "북촌한옥마을",
    "북촌",
    "종로3가역",
)
_HARMFUL_MARKERS = ("바보", "미친", "죽어", "씨발", "개새끼")
_OFF_TOPIC_MARKERS = ("주식", "수학 문제", "코드 짜줘", "파이썬 코드")
_PROMPT_INJECTION_MARKERS = ("시스템 프롬프트", "프롬프트를 보여줘", "무시하고")
_REJECT_ALL_MARKERS = ("다른 곳", "다른 거", "전부 별로", "다 마음에 안", "다른거")
# _shared/rules/transport.md와 같은 매핑을 미러링한다(RECOMMEND/MODIFY 공유,
# TP-105 — 자동차 경로 네이버 실측이 transport=CAR를 봐야 실제로 호출된다).
# (조사까지 붙인 라벨, ComparisonItem 필드명) — summary_instruction.md의 나열
# 순서(도보·자동차·대중교통)를 Fake에서 미러링한다. "대중교통"은 받침이 있어
# "으로"를 붙여야 하므로("대중교통로"는 어색함) 조사까지 라벨에 미리 넣어둔다.
_TRAVEL_MODE_FIELDS: tuple[tuple[str, str], ...] = (
    ("도보로", "travel_walking_minutes"),
    ("자동차로", "travel_driving_minutes"),
    ("대중교통으로", "travel_transit_minutes"),
)


def _fastest_travel_minutes(item: ComparisonItem) -> int | None:
    candidates = [
        minutes
        for minutes in (
            item.travel_walking_minutes,
            item.travel_driving_minutes,
            item.travel_transit_minutes,
        )
        if minutes is not None
    ]
    return min(candidates) if candidates else None

_TRANSPORT_CAR_MARKERS = ("차로", "운전해서", "차 타고", "차로 가려는데")
_TRANSPORT_WALK_MARKERS = ("걸어서", "도보로", "걸어갈")
_TRANSPORT_PUBLIC_MARKERS = ("대중교통으로", "버스나 지하철", "지하철 타고", "버스 타고")


def _detect_transport(user_input: str) -> Transport | None:
    """RECOMMEND/MODIFY 양쪽이 같은 판정을 쓰도록 공유한다."""

    if any(marker in user_input for marker in _TRANSPORT_CAR_MARKERS):
        return Transport.CAR
    if any(marker in user_input for marker in _TRANSPORT_WALK_MARKERS):
        return Transport.WALK
    if any(marker in user_input for marker in _TRANSPORT_PUBLIC_MARKERS):
        return Transport.PUBLIC
    return None
# SCHEDULE-09: 순번 언급("두 번째는 별로야") → REJECT_SPECIFIC 판별용.
# ComparePayload.targets 파싱과 달리 여기서는 실제로 순번을 파싱해 target_indices를
# 채운다 — REJECT_SPECIFIC 자체가 이번에 신설된 값이라 테스트가 파싱 결과에 의존한다.
_ORDINAL_TO_INDEX = {
    "첫 번째": 1,
    "첫번째": 1,
    "두 번째": 2,
    "두번째": 2,
    "세 번째": 3,
    "세번째": 3,
    "네 번째": 4,
    "네번째": 4,
    "다섯 번째": 5,
    "다섯번째": 5,
}
_REJECT_SPECIFIC_CUE_MARKERS = ("별로", "빼줘", "빼줄래", "빼고", "다른 데로", "다른 곳으로")
# SCHEDULE-09 후속: "두 번째 말고는 다 마음에 안 들어"처럼 남길 자리를 지목하고
# 나머지 전부를 거부하는 표현 — target_indices를 "언급된 순번의 여집합"으로
# 계산해야 한다(직접 지목과 정반대 방향). "말고"는 이미 _MODIFY_CHANGE_MARKERS에
# 있어 classify_intent()의 MODIFY 라우팅은 별도 수정 없이 그대로 통과한다.
_EXCLUSION_MARKERS = ("말고는", "말고")


def _is_reject_specific_utterance(user_input: str) -> bool:
    """ "두 번째는 별로야"처럼 순번 언급과 거절 신호가 함께 있으면 True.

    classify_intent()(1단계, MODIFY로 라우팅 여부)와 extract_modify_conditions()
    (2단계, REJECT_SPECIFIC 판별)가 같은 기준을 쓰도록 공유한다 — 기준이
    갈리면 1단계는 MODIFY로 안 보내는데 2단계는 REJECT_SPECIFIC을 반환하려는
    (또는 그 반대) 모순이 생길 수 있다.
    """
    has_ordinal = any(marker in user_input for marker in _ORDINAL_TO_INDEX)
    has_cue = any(marker in user_input for marker in _REJECT_SPECIFIC_CUE_MARKERS)
    return has_ordinal and has_cue


def _mentions_shown_place_by_name(user_input: str, shown_place_names: list[str] | None) -> bool:
    """SCHEDULE-09 후속(이름 지목): 노출된 항목 이름이 발화에 그대로 들어있으면 True.

    빈 문자열(이름 미저장 과거 세션)은 건너뛴다.
    """
    return any(name and name in user_input for name in (shown_place_names or []))


_MODIFY_CHANGE_MARKERS = (
    "말고",
    "빼고",
    "무료",
    "가격 상관없",
    "예산 상관없",
    "가까운",
    "먼 곳",
    "실내로",
    "야외도",
    "주차",
    "근처로 바꿔",
)

# Fake도 Real Gemini 프롬프트의 MODIFY 장소 유형 교체/병합 규칙을 재현한다. 테스트
# 환경에서 "공원도 추천"이 카페+공원 누적으로 오인되면 Real 경로와 다른 C 분류 충돌을
# 놓칠 수 있으므로, 대표적인 교차 유형 태그를 명시한다.
_MODIFY_CATEGORY_TAGS = (
    ("카페", PlaceTag.CAFE, PlaceType.RESTAURANT),
    ("공원", PlaceTag.PARK, PlaceType.ATTRACTION),
)
_EXPLICIT_CATEGORY_ADD_MARKERS = ("포함", "함께 넣", "같이 넣")
_COMPARE_MARKERS = ("가까워", "오래 열어", "어디가 좋아", "뭐가 나아", "비교해")
_SCHEDULE_MARKERS = (
    "일정 짜",
    "일정 만들어",
    "일정 만들",
    "코스 짜",
    "코스 만들어",
    "코스 만들",
    "루트 만들어",
    "루트 만들",
    "순서 알려",
    "어디부터 갈",
)
# state_transform._RESET_SCOPE_PHRASES와 같은 문구를 미러링한다(D-059) — SCHEDULE
# 되묻기를 이어가는 도중에도 사용자가 명시적으로 재시작을 말하면 이어가기로 강제하지
# 않는다. Fake는 프로덕션 상태 모듈에 의존하지 않는 레이어 분리를 유지하므로 별도 상수로
# 둔다(문구 4개뿐이라 중복 비용이 적다).
_EXPLICIT_RESTART_MARKERS = (
    "처음부터 다시",
    "조건 다시 정할게",
    "조건 다시 정하고 싶어",
    "새로 시작",
)
_INFO_QUESTION_MARKERS = (
    "열어",
    "몇 시",
    "입장료",
    "얼마",
    "주차",
    "화장실",
    "휠체어",
    "전시",
    "행사",
    "어디에 있",
    "주소",
    "사람 많",
    "붐빌",
    "혼잡",
    "개요",
    "가는데 얼마나 걸",
)
_GENERAL_MARKERS = (
    "역사",
    "지어졌",
    "여행 팁",
    "언제 피어",
    "동네",
    "에티켓",
    "막차",
    "동선",
)
_SERVICE_IDENTITY_MARKERS = (
    "넌 누구",
    "너 누구",
    "이름이 뭐",
    "뭘 할 수",
    "뭐 할 수",
    "트리비",
    "TripBranch",
    "tripbranch",
)
_LOCATION_ONLY_REMAINDERS = frozenset(
    {
        "근처",
        "근처는",
        "근처에서",
        "근처로",
        "근처어때",
        "주변",
        "주변은",
        "주변에서",
        "주변으로",
        "주변어때",
        "에서",
        "으로",
        "로",
        "은",
        "는",
        "어때",
    }
)
_LOCATION_ANSWER_REMAINDERS = frozenset({"", "요", "이요", "입니다", "이에요"})
_LOCATION_CLARIFICATION_CODES = frozenset({"location_required", "location_ambiguous"})


def _find_known_place(user_input: str) -> str | None:
    return next((name for name in _KNOWN_PLACE_NAMES if name in user_input), None)


def _is_location_only_change(user_input: str) -> bool:
    """이전 추천 이력 뒤 검색 중심점만 바꾸는 짧은 발화인지 판정한다.

    지명 단독("광화문")은 제외한다 — 추천을 받은 뒤 지명만 던지는 건 검색 위치 변경이
    아니라 그 장소를 지목한 정보 질문이라, INFO 경계 사례로 남긴다(intent-definition.md §5).
    """

    place_name = _find_known_place(user_input)
    if place_name is None:
        return False

    remainder = user_input.replace(place_name, "", 1).strip()
    if not remainder:
        return False
    for prefix in ("그럼", "그러면", "아니"):
        if remainder.startswith(prefix):
            remainder = remainder[len(prefix) :].strip()
            break
    normalized = remainder.replace(" ", "").rstrip("?!.")
    return normalized in _LOCATION_ONLY_REMAINDERS


def _is_simple_location_answer(user_input: str) -> bool:
    """위치 되묻기에 답한 지명 단독/짧은 존댓말 답변인지 판정한다."""

    place_name = _find_known_place(user_input)
    if place_name is None:
        return False
    remainder = user_input.replace(place_name, "", 1).strip().replace(" ", "").rstrip("?!.")
    return remainder in _LOCATION_ANSWER_REMAINDERS


def _is_location_scoped_change(user_input: str) -> bool:
    """이전 추천 이력 뒤 "지명 + 근처/주변"으로 검색 범위를 옮기는 발화인지 판정한다.

    `_is_location_only_change()`가 잔여 조건이 전혀 없는 발화만 받는 데 비해, 이쪽은
    "경복궁 근처 카페 추천해줘"처럼 위치와 함께 다른 조건(카테고리 등)이 붙은 발화까지
    받는다 — 실 Gemini(프롬프트 1.0.2)가 이런 발화를 MODIFY로 분류하는 것과 맞추기
    위해서다(D-053). 지명 단독은 여기서도 제외되고(뒤에 근처/주변이 없다), 정보/일반
    질문 어휘가 섞이면 INFO·GENERAL 판정을 가리지 않도록 빠진다.
    """

    place_name = _find_known_place(user_input)
    if place_name is None:
        return False

    tail = user_input[user_input.find(place_name) + len(place_name) :]
    if not tail.strip().replace(" ", "").startswith(("근처", "주변")):
        return False
    return not any(marker in user_input for marker in _INFO_QUESTION_MARKERS + _GENERAL_MARKERS)


def _stub_visit_time(user_input: str, reference_date: date) -> str:
    """concentration-conditions.md §3.2 파싱 규칙의 최소 스텁 버전.

    "오늘"/"내일"/"이번 주말" 정도만 구분하고, 그 외(명시적 날짜 등)는 기준일로
    둔다 — 실제 자연어 날짜 파싱은 Real Gemini provider의 책임이다.
    """
    if "내일" in user_input:
        return (reference_date + timedelta(days=1)).isoformat()
    if "주말" in user_input:
        days_until_saturday = (5 - reference_date.weekday()) % 7
        days_ahead = days_until_saturday or 7
        return (reference_date + timedelta(days=days_ahead)).isoformat()
    return reference_date.isoformat()


class FakeLLMProvider:
    """실제 Gemini 호출 없이 키워드 매칭으로 LLMOutput을 흉내 내는 fake provider.

    FakeGeocodingProvider가 substring 매칭으로 소수 지명만 처리하는 것과 같은 결이다.
    test-cases.md TC-01~04(RECOMMEND), TC-07~09(MODIFY), TC-11(GENERAL),
    TC-12/13(OUT_OF_SCOPE)와 llm-output-schema.md §7의 needs_clarification 예시를
    재현할 수 있는 수준까지만 다룬다 — 실제 자연어 이해가 아니라 고정 회귀 테스트용.
    """

    async def classify_intent(
        self,
        user_input: str,
        *,
        has_previous_recommendation: bool,
        shown_place_count: int,
        pending_clarification: str | None = None,
        last_intent: str | None = None,
        shown_place_names: list[str] | None = None,
        conversation_place_name: str | None = None,
    ) -> ProviderResult[IntentClassificationResult]:
        if any(marker in user_input for marker in _PROMPT_INJECTION_MARKERS):
            result = IntentClassificationResult(
                intent=Intent.OUT_OF_SCOPE,
                out_of_scope_category=OutOfScopeCategory.PROMPT_INJECTION,
                out_of_scope_severity=Severity.HIGH,
            )
        elif any(marker in user_input for marker in _HARMFUL_MARKERS):
            result = IntentClassificationResult(
                intent=Intent.OUT_OF_SCOPE,
                out_of_scope_category=OutOfScopeCategory.HARMFUL,
                out_of_scope_severity=Severity.HIGH,
            )
        elif any(marker in user_input for marker in _OFF_TOPIC_MARKERS):
            result = IntentClassificationResult(
                intent=Intent.OUT_OF_SCOPE,
                out_of_scope_category=OutOfScopeCategory.UNRELATED,
                out_of_scope_severity=Severity.LOW,
            )
        elif any(marker in user_input for marker in _SCHEDULE_MARKERS):
            result = IntentClassificationResult(intent=Intent.SCHEDULE)
        elif (
            last_intent == Intent.SCHEDULE.value
            and pending_clarification is not None
            and not any(phrase in user_input for phrase in _EXPLICIT_RESTART_MARKERS)
        ):
            # D-059: 직전 턴이 SCHEDULE 되묻기로 끝났으면, 지명만 던지거나 조건만
            # 보충하는 짧은 답변도 새 MODIFY 요청이 아니라 그 SCHEDULE을 이어가는
            # 중이다. MODIFY 분기(바로 아래)보다 먼저 검사해 우선순위를 준다.
            result = IntentClassificationResult(intent=Intent.SCHEDULE)
        elif (
            last_intent in (Intent.RECOMMEND.value, Intent.MODIFY.value)
            and pending_clarification in _LOCATION_CLARIFICATION_CODES
            and _is_simple_location_answer(user_input)
        ):
            # 위치를 물어본 직후의 단순 지명은 INFO가 아니라, 기존 조건에 검색 중심을
            # 보충하는 MODIFY다. "경복궁 오늘 열어?"처럼 질문이 붙으면 이 조건을
            # 통과하지 않아 아래 INFO 규칙으로 간다.
            result = IntentClassificationResult(intent=Intent.MODIFY)
        elif has_previous_recommendation and (
            any(marker in user_input for marker in _REJECT_ALL_MARKERS + _MODIFY_CHANGE_MARKERS)
            or _is_location_only_change(user_input)
            or _is_location_scoped_change(user_input)
            or _is_reject_specific_utterance(user_input)
            or (
                _mentions_shown_place_by_name(user_input, shown_place_names)
                and any(
                    marker in user_input
                    for marker in _REJECT_SPECIFIC_CUE_MARKERS + _EXCLUSION_MARKERS
                )
            )
        ):
            result = IntentClassificationResult(intent=Intent.MODIFY)
        elif shown_place_count >= 2 and any(marker in user_input for marker in _COMPARE_MARKERS):
            result = IntentClassificationResult(intent=Intent.COMPARE)
        elif any(marker in user_input for marker in _GENERAL_MARKERS + _SERVICE_IDENTITY_MARKERS):
            result = IntentClassificationResult(intent=Intent.GENERAL)
        elif (
            conversation_place_name is not None
            and any(reference in user_input for reference in ("여기", "이곳", "거기", "이리로"))
            and any(marker in user_input for marker in _INFO_QUESTION_MARKERS)
        ):
            result = IntentClassificationResult(intent=Intent.INFO)
        elif _find_known_place(user_input) and any(
            marker in user_input for marker in _INFO_QUESTION_MARKERS
        ):
            result = IntentClassificationResult(intent=Intent.INFO)
        elif _is_simple_location_answer(user_input):
            result = IntentClassificationResult(
                intent=Intent.MODIFY if has_previous_recommendation else Intent.RECOMMEND
            )
        else:
            result = IntentClassificationResult(intent=Intent.RECOMMEND)
        return provider_result(result, source=ProviderSource.FAKE_LLM)

    async def extract_recommend_conditions(self, user_input: str) -> ProviderResult[LLMOutput]:
        conditions = UserConditions()
        place_name = _find_known_place(user_input)
        if place_name and (
            "근처" in user_input or "주변" in user_input or _is_simple_location_answer(user_input)
        ):
            conditions.search_center = place_name
        if "나 지금" in user_input and place_name:
            conditions.current_location = place_name
            conditions.search_center = None

        if "카페" in user_input:
            conditions.place_types.append(PlaceType.RESTAURANT)
            conditions.place_tags.append(PlaceTag.CAFE)
        if "맛집" in user_input or "음식" in user_input:
            if PlaceType.RESTAURANT not in conditions.place_types:
                conditions.place_types.append(PlaceType.RESTAURANT)
        if "박물관" in user_input:
            conditions.place_types.append(PlaceType.CULTURAL_FACILITY)
            conditions.place_tags.append(PlaceTag.MUSEUM)

        # 날씨를 언급하지 않았으면 기본값은 NO_MENTION이다.
        conditions.weather_intent = WeatherIntent.NO_MENTION

        status = OutputStatus.COMPLETE
        clarification = None
        if "눈" in user_input and not any(
            marker in user_input for marker in ("피해", "피하고", "실내", "즐기고", "보고 싶")
        ):
            conditions.weather = StatedWeather.SNOW
            conditions.weather_intent = None
            status = OutputStatus.NEEDS_CLARIFICATION
            clarification = ClarificationPayload(
                ambiguous_fields=[
                    {
                        "field": "weather_intent",
                        "user_input": user_input,
                        "candidates": ["AVOID", "ENJOY"],
                        "reason": (
                            "눈을 피해 실내를 원하시는지, 눈 오는 풍경을 즐기고 싶으신지 "
                            "확인이 필요합니다"
                        ),
                    }
                ],
                message="눈 오는 풍경을 즐기고 싶으신가요, 아니면 실내 장소를 찾으시나요?",
            )
        elif "비" in user_input:
            conditions.weather = StatedWeather.RAIN
            conditions.weather_intent = WeatherIntent.AVOID
            conditions.environment = Environment.INDOOR
        elif any(marker in user_input for marker in ("날씨 상관없", "날씨는 상관없", "아무 날씨")):
            conditions.weather_intent = WeatherIntent.IGNORE

        if any(marker in user_input for marker in ("조용", "한적", "사람 없")):
            conditions.concentration_intent = ConcentrationIntent.AVOID
        elif any(marker in user_input for marker in ("핫한", "인기", "북적")):
            conditions.concentration_intent = ConcentrationIntent.SEEK

        conditions.transport = _detect_transport(user_input)

        result = LLMOutput(
            intent=Intent.RECOMMEND,
            status=status,
            recommend=RecommendPayload(conditions=conditions),
            clarification=clarification,
        )
        return provider_result(result, source=ProviderSource.FAKE_LLM)

    async def extract_modify_conditions(
        self,
        user_input: str,
        current_conditions: UserConditions,
        *,
        pending_clarification: str | None = None,
        shown_place_count: int = 0,
        shown_place_names: list[str] | None = None,
    ) -> ProviderResult[LLMOutput]:
        ordinal_indices = {
            index for marker, index in _ORDINAL_TO_INDEX.items() if marker in user_input
        }
        # SCHEDULE-09 후속(이름 지목): "두가헌 레스토랑은 빼줘"처럼 순번 대신
        # 노출된 항목 이름을 그대로 언급해도 같은 순번으로 매칭한다. 1-indexed —
        # shown_place_names[0]이 1번이다. 빈 문자열(이름 미저장 과거 세션)은
        # 건너뛴다 — 빈 문자열이 user_input에 항상 포함되어 오매칭나는 것을 막는다.
        name_indices = {
            rank
            for rank, name in enumerate(shown_place_names or [], start=1)
            if name and name in user_input
        }
        mentioned_indices = sorted(ordinal_indices | name_indices)

        if mentioned_indices and any(marker in user_input for marker in _EXCLUSION_MARKERS):
            # "두 번째 말고는 다 마음에 안 들어" — 언급된 순번은 남기고 나머지
            # 전부를 거부한다. 아래 직접 지목 분기와 target_indices의 의미가
            # 정반대이므로(여집합) 먼저 검사한다 — 순서를 바꾸면 이 분기가
            # 죽는다.
            out_of_range = [i for i in mentioned_indices if i > shown_place_count]
            if out_of_range:
                result = LLMOutput(
                    intent=Intent.MODIFY,
                    status=OutputStatus.NEEDS_CLARIFICATION,
                    clarification=ClarificationPayload(
                        message=f"일정에는 {shown_place_count}개 항목만 있어요. "
                        "몇 번째를 남겨드릴까요?",
                    ),
                )
                return provider_result(result, source=ProviderSource.FAKE_LLM)

            target_indices = [
                i for i in range(1, shown_place_count + 1) if i not in mentioned_indices
            ]
            result = LLMOutput(
                intent=Intent.MODIFY,
                status=OutputStatus.COMPLETE,
                modify=ModifyPayload(
                    modify_type=ModifyType.REJECT_SPECIFIC,
                    target_indices=target_indices,
                ),
            )
            return provider_result(result, source=ProviderSource.FAKE_LLM)

        if mentioned_indices and any(
            marker in user_input for marker in _REJECT_SPECIFIC_CUE_MARKERS
        ):
            out_of_range = [i for i in mentioned_indices if i > shown_place_count]
            if out_of_range:
                result = LLMOutput(
                    intent=Intent.MODIFY,
                    status=OutputStatus.NEEDS_CLARIFICATION,
                    clarification=ClarificationPayload(
                        message=f"일정에는 {shown_place_count}개 항목만 있어요. "
                        "몇 번째를 바꿔드릴까요?",
                    ),
                )
                return provider_result(result, source=ProviderSource.FAKE_LLM)

            result = LLMOutput(
                intent=Intent.MODIFY,
                status=OutputStatus.COMPLETE,
                modify=ModifyPayload(
                    modify_type=ModifyType.REJECT_SPECIFIC,
                    target_indices=mentioned_indices,
                ),
            )
            return provider_result(result, source=ProviderSource.FAKE_LLM)

        if any(marker in user_input for marker in _REJECT_ALL_MARKERS):
            result = LLMOutput(
                intent=Intent.MODIFY,
                status=OutputStatus.COMPLETE,
                modify=ModifyPayload(modify_type=ModifyType.REJECT_ALL),
            )
            return provider_result(result, source=ProviderSource.FAKE_LLM)

        changed = current_conditions.model_copy(deep=True)
        changed_fields: list[str] = []
        if "무료" in user_input or "가격 상관없" in user_input or "예산 상관없" in user_input:
            changed.budget = "free" if "무료" in user_input else None
            changed_fields.append("budget")
        if "가까운" in user_input:
            base = changed.max_travel_time or 30
            changed.max_travel_time = max(5, base // 2)
            changed_fields.append("max_travel_time")
        if "먼 곳" in user_input:
            base = changed.max_travel_time or 15
            changed.max_travel_time = min(60, base + 15)
            changed_fields.append("max_travel_time")
        if "실내로" in user_input:
            changed.environment = Environment.INDOOR
            changed_fields.append("environment")
        if "야외도" in user_input:
            changed.environment = Environment.ANY
            changed_fields.append("environment")
        if "주차" in user_input:
            changed.special_requirements = [*changed.special_requirements, "주차"]
            changed_fields.append("special_requirements")
        mentioned_categories = [
            category for category in _MODIFY_CATEGORY_TAGS if category[0] in user_input
        ]
        replacement_categories = [
            category
            for category in mentioned_categories
            if "말고" in user_input and user_input.index(category[0]) > user_input.index("말고")
        ]
        if replacement_categories:
            changed.place_tags = [tag for _, tag, _ in replacement_categories]
            changed.place_types = [place_type for _, _, place_type in replacement_categories]
            changed_fields.extend(["place_types", "place_tags"])
        elif "말고" in user_input and "카페" in user_input:
            changed.place_types = [PlaceType.RESTAURANT]
            changed.place_tags = [t for t in changed.place_tags if t != PlaceTag.CAFE]
            changed_fields.extend(["place_types", "place_tags"])
        elif mentioned_categories:
            # "공원도 추천"의 '도'는 선택지를 늘린다는 뜻이 아니라 자연스러운 강조로
            # 취급한다. '포함'처럼 명시적인 추가일 때만 기존 목록과 합친다.
            if any(marker in user_input for marker in _EXPLICIT_CATEGORY_ADD_MARKERS):
                changed.place_tags = list(
                    dict.fromkeys(
                        [*changed.place_tags, *(tag for _, tag, _ in mentioned_categories)]
                    )
                )
                changed.place_types = list(
                    dict.fromkeys(
                        [
                            *changed.place_types,
                            *(place_type for _, _, place_type in mentioned_categories),
                        ]
                    )
                )
            else:
                # "카페와 공원 같이", "카페나 공원"처럼 발화에 둘 이상을 나열한 경우는
                # 둘 다 유지하고, 한 유형만 말하면 그 유형으로 교체한다.
                changed.place_tags = [tag for _, tag, _ in mentioned_categories]
                changed.place_types = [place_type for _, _, place_type in mentioned_categories]
            changed_fields.extend(["place_types", "place_tags"])
        # 날씨는 RECOMMEND 추출과 같은 결로 맞춘다(stub.py의 extract_recommend_conditions):
        # "비"는 피하고 싶은 날씨로 보고 실내로 좁힌다. MODIFY 경로에도 날씨가 필요한 건
        # "비 오는데 ~ 근처 카페" 같은 발화가 이제 MODIFY로 분류되기 때문이다(D-053).
        if "비" in user_input:
            changed.weather = StatedWeather.RAIN
            changed.weather_intent = WeatherIntent.AVOID
            changed.environment = Environment.INDOOR
            changed_fields.extend(["weather", "weather_intent", "environment"])

        # MODIFY도 RECOMMEND와 같은 혼잡도 의도 규칙을 적용한다. 이전 조건을 복사한
        # changed 객체를 쓰므로, 이 발화에서 혼잡도를 언급하지 않으면 changed_fields에
        # 넣지 않아 기존 concentration_intent가 그대로 유지된다.
        if any(marker in user_input for marker in ("조용", "한적", "사람 없")):
            changed.concentration_intent = ConcentrationIntent.AVOID
            changed_fields.append("concentration_intent")
        elif any(marker in user_input for marker in ("핫한", "인기", "북적")):
            changed.concentration_intent = ConcentrationIntent.SEEK
            changed_fields.append("concentration_intent")

        detected_transport = _detect_transport(user_input)
        if detected_transport is not None:
            changed.transport = detected_transport
            changed_fields.append("transport")

        new_place = _find_known_place(user_input)
        if new_place and (
            "근처로 바꿔" in user_input
            or _is_location_only_change(user_input)
            or _is_location_scoped_change(user_input)
            or _is_simple_location_answer(user_input)
            or (
                pending_clarification in _LOCATION_CLARIFICATION_CODES
                and _is_simple_location_answer(user_input)
            )
        ):
            changed.search_center = new_place
            changed_fields.append("search_center")

        result = LLMOutput(
            intent=Intent.MODIFY,
            status=OutputStatus.COMPLETE,
            modify=ModifyPayload(
                modify_type=ModifyType.CHANGE_CONDITION,
                condition_changes=changed,
                changed_fields=changed_fields,
            ),
        )
        return provider_result(result, source=ProviderSource.FAKE_LLM)

    async def extract_info_query(
        self,
        user_input: str,
        *,
        has_previous_recommendation: bool,
        reference_date: date,
        conversation_place_name: str | None = None,
    ) -> ProviderResult[LLMOutput]:
        place_name = _find_known_place(user_input)
        if place_name:
            place_context = PlaceContext.EXPLICIT
        elif has_previous_recommendation and (
            "첫 번째" in user_input or "두 번째" in user_input or "거기" in user_input
        ):
            place_context = PlaceContext.FROM_RECOMMENDATION
        else:
            place_context = PlaceContext.FROM_CONVERSATION

        if place_context is PlaceContext.FROM_CONVERSATION and conversation_place_name:
            place_name = conversation_place_name

        if any(marker in user_input for marker in ("지하철", "전철")) and any(
            marker in user_input for marker in ("언제", "도착", "몇 분", "몇분")
        ):
            question_type = QuestionType.REALTIME_SUBWAY
        elif "버스" in user_input and any(
            marker in user_input for marker in ("정류장", "어디", "언제", "도착")
        ):
            question_type = QuestionType.REALTIME_BUS
        elif "주차" in user_input and any(marker in user_input for marker in ("공영", "시영")):
            question_type = QuestionType.REALTIME_PUBLIC_PARKING
        elif "주차" in user_input and (
            any(marker in user_input for marker in ("지금", "현재", "실시간", "자리", "빈자리"))
            or any(marker in user_input for marker in ("근처", "주변", "어디"))
        ):
            question_type = QuestionType.REALTIME_PARKING
        elif ("행사" in user_input or "축제" in user_input) and any(
            marker in user_input for marker in ("지금", "현재", "오늘", "실시간")
        ):
            question_type = QuestionType.REALTIME_EVENT
        elif "열어" in user_input or "몇 시" in user_input:
            question_type = QuestionType.OPERATING_HOURS
        elif "가는데 얼마나 걸" in user_input:
            # "얼마"가 있어도 입장료가 아니라 이동시간 질문이다.
            question_type = QuestionType.LOCATION_INFO
        elif "입장료" in user_input or "얼마" in user_input:
            question_type = QuestionType.FEE
        elif "주차" in user_input:
            question_type = QuestionType.PARKING
        elif "화장실" in user_input or "휠체어" in user_input:
            question_type = QuestionType.FACILITY
        elif "전시" in user_input or "행사" in user_input:
            question_type = QuestionType.EVENT
        elif "어디에 있" in user_input or "주소" in user_input:
            question_type = QuestionType.LOCATION_INFO
        elif any(marker in user_input for marker in ("카페", "커피", "상권")) and any(
            marker in user_input for marker in ("지금", "사람 많", "붐빌", "혼잡")
        ):
            question_type = QuestionType.REALTIME_COMMERCIAL
        elif any(marker in user_input for marker in ("사람 많", "붐빌", "혼잡")):
            question_type = QuestionType.CONCENTRATION
        else:
            question_type = QuestionType.GENERAL_INFO

        visit_time = (
            _stub_visit_time(user_input, reference_date)
            if question_type is QuestionType.CONCENTRATION
            else None
        )

        result = LLMOutput(
            intent=Intent.INFO,
            status=OutputStatus.COMPLETE,
            info=InfoPayload(
                place_name=place_name,
                place_context=place_context,
                question_type=question_type,
                specific_question=user_input,
                visit_time=visit_time,
            ),
        )
        return provider_result(result, source=ProviderSource.FAKE_LLM)

    async def extract_compare_request(
        self,
        user_input: str,
        *,
        shown_place_count: int,
        shown_place_names: list[str] | None = None,
    ) -> ProviderResult[LLMOutput]:
        if "오래 열어" in user_input:
            criteria = CompareCriteria.TIME
        elif any(
            marker in user_input
            for marker in (
                "가까워",
                "거리 차이",
                "빨리 갈",
                "얼마나 걸려",
                "이동 시간",
                "덜 막혀",
                "덜 막힐",
            )
        ):
            criteria = CompareCriteria.TRAVEL_TIME
        else:
            criteria = CompareCriteria.OVERALL

        # 순번이든 이름이든 지목이 있으면 그 대상만 비교한다. MODIFY의
        # target_indices와 같은 매칭 규칙을 쓴다 — 1-indexed이고, 빈 이름(과거
        # 세션)은 건너뛴다(빈 문자열은 어떤 발화에도 포함돼 오매칭난다).
        ordinal_indices = {
            index for marker, index in _ORDINAL_TO_INDEX.items() if marker in user_input
        }
        name_indices = {
            rank
            for rank, name in enumerate(shown_place_names or [], start=1)
            if name and name in user_input
        }
        mentioned_indices = sorted(ordinal_indices | name_indices)

        targets: list[int] | Literal["all"] = "all"
        if mentioned_indices:
            out_of_range = [index for index in mentioned_indices if index > shown_place_count]
            if out_of_range:
                result = LLMOutput(
                    intent=Intent.COMPARE,
                    status=OutputStatus.NEEDS_CLARIFICATION,
                    clarification=ClarificationPayload(
                        missing_fields=[],
                        message=f"추천 결과는 {shown_place_count}개까지 있어요. "
                        "몇 번을 비교할까요?",
                    ),
                )
                return provider_result(result, source=ProviderSource.FAKE_LLM)
            targets = mentioned_indices

        result = LLMOutput(
            intent=Intent.COMPARE,
            status=OutputStatus.COMPLETE,
            compare=ComparePayload(targets=targets, criteria=criteria),
        )
        return provider_result(result, source=ProviderSource.FAKE_LLM)

    async def extract_general_request(self, user_input: str) -> ProviderResult[LLMOutput]:
        if any(marker in user_input for marker in _SERVICE_IDENTITY_MARKERS):
            topic = GeneralTopic.SERVICE_IDENTITY
        elif "역사" in user_input or "언제 지어졌" in user_input:
            topic = GeneralTopic.PLACE_KNOWLEDGE
        elif "언제 피어" in user_input:
            topic = GeneralTopic.SEASON_INFO
        elif "동네" in user_input:
            topic = GeneralTopic.AREA_INFO
        elif "에티켓" in user_input or "음식" in user_input:
            topic = GeneralTopic.FOOD_CULTURE
        elif "막차" in user_input or "지하철" in user_input:
            topic = GeneralTopic.TRANSPORT_INFO
        elif "여행 팁" in user_input:
            topic = GeneralTopic.TRAVEL_TIP
        else:
            topic = GeneralTopic.PLANNING_TIP

        result = LLMOutput(
            intent=Intent.GENERAL,
            status=OutputStatus.COMPLETE,
            general=GeneralPayload(topic=topic, original_question=user_input),
        )
        return provider_result(result, source=ProviderSource.FAKE_LLM)

    async def generate_general_answer(
        self, topic: GeneralTopic, original_question: str, *, offer_content: str | None = None
    ) -> ProviderResult[str]:
        if topic is GeneralTopic.SERVICE_IDENTITY:
            answer = (
                "저는 TripBranch의 국내 여행 챗봇 트리비예요. "
                "원하는 지역이나 현재 위치를 기준으로 날씨, 운영시간, 거리, "
                "혼잡도 선호를 함께 보고 갈 만한 곳을 추천해드릴 수 있어요."
            )
        else:
            answer = "국내 여행에 참고할 만한 정보를 간단히 알려드릴게요."
        if offer_content:
            # 실 프롬프트의 질문형 제안 문구를 그대로 흉내내지 않고, 테스트가
            # offer_content 전달 여부만 확인할 수 있게 문자열로 남긴다.
            answer = f"{answer} {offer_content}을(를) 찾아드릴까요?"
        return provider_result(answer, source=ProviderSource.FAKE_LLM)

    async def generate_recommendation_summary(
        self, intent: Intent, recommendations: RecommendationResponse
    ) -> ProviderResult[str]:
        shown = [*recommendations.recommendations, *recommendations.unverified_recommendations]
        if not shown:
            return provider_result(
                "조건에 맞는 곳을 찾지 못했어요.", source=ProviderSource.FAKE_LLM
            )
        first = shown[0]
        return provider_result(
            f"{first.name}을(를) 중심으로 지금 가볼 만한 곳을 골라봤어요.",
            source=ProviderSource.FAKE_LLM,
        )

    async def generate_follow_up_suggestions(
        self,
        *,
        user_input: str,
        intent: Intent,
        assistant_message: str,
        place_names: list[str],
        search_place: str | None,
        transport: str | None,
        max_suggestions: int,
        max_label_length: int,
    ) -> ProviderResult[list[str]]:
        """후속 질문 제안의 테스트용 결정적 대체 구현.

        **호출부가 실제로 읽는 것을 채운다.** 빈 목록을 돌려주면 소비 측
        (`follow_up_suggester.py`)의 정제·상한 로직이 한 줄도 안 돌면서 테스트는
        통과한다. 그래서 여기서는 이번 턴에 나간 장소 이름을 실제로 써서 문구를
        만들고, 상한을 넘는 개수를 일부러 반환한다 — 호출부가 자르는지 확인된다.
        """

        del assistant_message, max_label_length
        # 혼잡도 문구에는 장소명을 반드시 넣는다 — 소비 측이 그 유무로 걸러낸다.
        subject = place_names[0] if place_names else search_place
        if subject and "혼잡" in user_input:
            return provider_result(
                [f"주말에 {subject} 많이 혼잡해?"], source=ProviderSource.FAKE_LLM
            )
        # 이동수단이 차면 주차 질문을 섞는다 — 소비 측이 실제로 읽는 조건이다.
        if transport == "car" and place_names:
            return provider_result(
                [f"{place_names[0]} 근처에 주차할 데 있는지 알려줘"],
                source=ProviderSource.FAKE_LLM,
            )
        if intent in (Intent.OUT_OF_SCOPE, Intent.GENERAL) and not place_names:
            return provider_result(
                ["서울에서 갈 만한 곳 추천해줘"], source=ProviderSource.FAKE_LLM
            )
        suggestions = [f"{name} 운영시간 알려줘" for name in place_names[:max_suggestions]]
        suggestions.append("다른 곳도 보여줘")
        suggestions.append("이 장소들로 일정 짜줘")
        return provider_result(suggestions, source=ProviderSource.FAKE_LLM)

    async def stream_recommendation_summary(
        self, intent: Intent, recommendations: RecommendationResponse
    ) -> AsyncIterator[str]:
        """SSE 테스트용: 결정적 요약을 두 조각으로 나눈다."""

        summary = await self.generate_recommendation_summary(intent, recommendations)
        text = summary.data
        midpoint = max(1, len(text) // 2)
        yield text[:midpoint]
        yield text[midpoint:]

    async def stream_general_answer(
        self, topic: GeneralTopic, original_question: str, *, offer_content: str | None = None
    ) -> AsyncIterator[str]:
        """SSE 테스트용 GENERAL 답변을 결정적으로 두 조각으로 나눈다."""

        answer = await self.generate_general_answer(
            topic, original_question, offer_content=offer_content
        )
        text = answer.data
        midpoint = max(1, len(text) // 2)
        yield text[:midpoint]
        yield text[midpoint:]

    async def stream_info_answer(
        self,
        *,
        place_name: str,
        question_type: str,
        specific_question: str | None,
        fields: dict[str, str],
    ) -> AsyncIterator[str]:
        """SSE 테스트용 INFO 답변. 전달된 C fields 밖의 사실은 만들지 않는다."""

        del specific_question
        value = next(iter(fields.values()), "정보")
        text = (
            f"{place_name}의 {question_type} 정보를 확인했어요. "
            f"{value} 자세한 내용은 아래 상세 카드에서 확인해보세요."
        )
        midpoint = max(1, len(text) // 2)
        yield text[:midpoint]
        yield text[midpoint:]

    async def generate_compare_summary(self, comparison: ComparisonResult) -> ProviderResult[str]:
        """COMPARE LLM 요약의 테스트용 결정적 대체 구현.

        실제 Gemini와 달리 문체 다양화는 하지 않되, 3줄 이상이라는 출력 계약과
        전달된 사실만 쓴다는 원칙을 회귀 테스트에서 확인할 수 있게 한다.
        """

        items = comparison.items
        if comparison.criteria is CompareCriteria.TIME:
            candidates = [item for item in items if item.remaining_minutes is not None]
            recommended = (
                max(candidates, key=lambda item: item.remaining_minutes or 0)
                if candidates
                else items[0]
            )
        elif comparison.criteria is CompareCriteria.TRAVEL_TIME:
            candidates = [item for item in items if _fastest_travel_minutes(item) is not None]
            recommended = (
                min(candidates, key=lambda item: _fastest_travel_minutes(item) or 0)
                if candidates
                else items[0]
            )
        else:
            recommended = items[0]
        lines = [f"{recommended.place_name}{_object_particle(recommended.place_name)} 추천드려요."]
        for item in items[:3]:
            details: list[str] = []
            mode_parts = [
                f"{label} 약 {minutes}분"
                for label, field in _TRAVEL_MODE_FIELDS
                if (minutes := getattr(item, field)) is not None
            ]
            if mode_parts:
                if item.travel_distance_km is not None:
                    details.append(f"약 {item.travel_distance_km}km")
                details.extend(mode_parts)
            elif item.distance_km is not None:
                minutes = max(1, math.ceil(item.distance_km * 60 / 3.6))
                details.append(f"도보 약 {minutes}분")
            if item.remaining_minutes is not None:
                hours = max(1, math.floor(item.remaining_minutes / 60 + 0.5))
                details.append(f"약 {hours}시간 남음")
            if item.environment_type is not None:
                details.append(f"{item.environment_type} 환경")
            value = ", ".join(details) if details else "비교 정보 확인 필요"
            lines.append(f"{item.rank}번 {item.place_name}은 {value}이에요.")
        while len(lines) < 3:
            lines.append("제공된 비교 정보를 바탕으로 선택해보세요.")
        return provider_result("\n".join(lines[:6]), source=ProviderSource.FAKE_LLM)

    async def generate_schedule_plan(
        self, request: SchedulePlanningRequest
    ) -> ProviderResult[ScheduleLLMPlan]:
        """실제 Gemini 호출 없이 candidates 앞쪽 최대 3개를 순서대로 배치한
        고정 일정을 반환한다 — 회귀 테스트용, 실제 편성 판단이 아니다."""
        selected = request.candidates[:3]
        items = [
            ScheduleItem(
                order=index + 1,
                place_id=candidate.place_id,
                place_name=candidate.name,
                estimated_arrival=f"{14 + index}:00",
                estimated_duration_min=60,
                travel_to_next_min=15 if index < len(selected) - 1 else None,
                reason="Agent Runtime 골격 검증용 고정 일정입니다.",
            )
            for index, candidate in enumerate(selected)
        ]
        total_duration = 60 * len(items) + 15 * max(len(items) - 1, 0)
        result = ScheduleLLMPlan(
            items=items,
            total_duration_min=total_duration,
            route_summary="고정 스텁 동선입니다.",
        )
        return provider_result(result, source=ProviderSource.FAKE_LLM)

    async def generate_schedule_fill(
        self, request: SchedulePartialFillRequest
    ) -> ProviderResult[SchedulePartialLLMPlan]:
        """실제 Gemini 호출 없이 candidates 앞쪽에서 필요한 개수만큼 순서대로
        target_orders에 배정한다 — SCHEDULE-09 2단계 회귀 테스트용, 실제
        편성 판단이 아니다.

        candidates가 target_orders보다 적으면(strict=False) new_items 개수가
        모자란 채로 반환된다 — 의도적이다. planner.py의 사후 검증(order 집합
        일치 확인)이 이 불일치를 잡아내는 경로를 테스트할 수 있게 한다.
        """
        orders = sorted(request.target_orders)
        selected = request.candidates[: len(orders)]
        new_items = [
            ScheduleItem(
                order=order,
                place_id=candidate.place_id,
                place_name=candidate.name,
                estimated_arrival=f"{15 + index}:00",
                estimated_duration_min=60,
                travel_to_next_min=15,
                reason="Agent Runtime 골격 검증용 고정 대체 항목입니다.",
            )
            for index, (order, candidate) in enumerate(zip(orders, selected, strict=False))
        ]
        result = SchedulePartialLLMPlan(new_items=new_items)
        return provider_result(result, source=ProviderSource.FAKE_LLM)


def _object_particle(value: str) -> str:
    """Fake 응답도 실제 화면처럼 자연스러운 목적격 조사를 쓴다."""

    last = value[-1] if value else ""
    is_hangul = "가" <= last <= "힣"
    return "을" if is_hangul and (ord(last) - ord("가")) % 28 else "를"


# SKY(하늘상태) 4 흐림, PTY(강수형태) 0 강수 없음 — 판정을 어느 쪽으로도 밀지 않는
# 중립 조합이다. fake도 실제 provider와 같은 "사실"을 내려줘야 한다: D는 사실
# 3종(precipitation/sky/temperature)으로 판정하므로(D-051) 코드를 비워두면 D
# 입력이 전부 None이 되어 어떤 날씨 시나리오도 재현되지 않는다.
_FAKE_DEFAULT_SKY_CODE = "4"
_FAKE_DEFAULT_PRECIPITATION_TYPE = "0"

# 폭염(33°C)·한파(-12°C) 경계에서 먼 값을 기본으로 둔다 — 기본 기온이 판정을
# 흔들면 sky·pty 인자의 의미가 흐려진다. 폭염·한파 시나리오는 생성자에
# temperature_celsius를 직접 넘겨서 만든다.
_FAKE_DEFAULT_TEMPERATURE_CELSIUS = 22.0


class FakeWeatherProvider:
    """설정한 공통 날씨 사실을 반환하는 가짜 구현.

    D-051 이후 Provider는 판정을 하지 않으므로 fake도 사실만 받는다. 기상청 코드를
    그대로 받는 이유는 실제 provider와 같은 모양이어야 D 판정 경로가 실제로
    실행되기 때문이다 — 맑음은 `("1", "0")`, 비는 `("4", "1")`.
    """

    def __init__(
        self,
        sky_code: str | None = _FAKE_DEFAULT_SKY_CODE,
        precipitation_type: str | None = _FAKE_DEFAULT_PRECIPITATION_TYPE,
        temperature_celsius: float | None = _FAKE_DEFAULT_TEMPERATURE_CELSIUS,
    ) -> None:
        self._sky_code = sky_code
        self._precipitation_type = precipitation_type
        self._temperature_celsius = temperature_celsius

    async def get_forecast_slots(
        self, latitude: float, longitude: float
    ) -> ProviderResult[WeatherForecastResult]:
        now = datetime.now(ZoneInfo("Asia/Seoul")).replace(
            minute=0,
            second=0,
            microsecond=0,
        )
        return provider_result(
            WeatherForecastResult(
                latitude=latitude,
                longitude=longitude,
                grid_x=60,
                grid_y=127,
                slots=tuple(
                    WeatherForecastSlot(
                        forecast_for=now + timedelta(hours=offset),
                        sky_code=self._sky_code,
                        precipitation_type=self._precipitation_type,
                        temperature_celsius=self._temperature_celsius,
                    )
                    for offset in range(6)
                ),
                provider="fake_weather",
            ),
            source=ProviderSource.FAKE_WEATHER,
        )


def _first_intro_text(intro: Mapping[str, object], keys: tuple[str, ...]) -> str | None:
    """실 provider의 _first_text와 같은 규칙으로 첫 값을 고른다."""
    for key in keys:
        value = intro.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _fake_intro(content_type_id: str) -> dict[str, object]:
    """detailIntro2 응답을 유형별 필드명까지 흉내 낸다.

    이 값을 비워두면 INFO 상세 질의(요금·주차·편의시설)의 필드 추출이 한 줄도
    실행되지 않은 채 테스트가 통과한다 — "값이 없다"와 "로직이 안 돌았다"를 구분할
    수 없어진다. 소비 측은 이제 raw_intro가 아니라 정규화 필드를 읽지만(D-060),
    get_details()가 그 필드를 여기서 뽑아 채우므로 이 dict가 비면 결과는 같다.

    **실 Provider와 같은 키 이름을 쓰는 것이 핵심이다**(문화시설 14는 usefee/
    parkingculture, 음식점 39는 parkingfood). 키 선택도 tour_intro_keys의 같은
    목록으로 하므로 fake가 실 응답과 어긋나면 테스트에서 드러난다.
    """

    if content_type_id == "39":
        return {
            "parkingfood": "가능(10대)",
            "chkcreditcardfood": "가능",
            "opentimefood": "08:00-22:00",
        }
    return {
        "usefee": "어른 3,000원 / 어린이 1,500원",
        "parkingculture": "주차 가능(무료)",
        "chkbabycarriageculture": "가능",
        "chkpetculture": "불가",
        "chkcreditcardculture": "가능",
    }


class FakePlaceProvider:
    """장소 검색 결과를 고정 후보 목록으로 대체하는 fake provider."""

    # 후보 category는 실 Provider와 같은 PlaceType 어휘를 쓴다. Fake로 검증한 동작이
    # 실 경로에서 달라지지 않게 하려는 것이다. 호출자는 place_types(영문 PlaceType)와
    # place_tags(한글)를 함께 넘기므로 양쪽을 모두 받는다.
    _CATEGORY_ALIASES = {
        "cultural_facility": frozenset({"cultural_facility"}),
        "restaurant": frozenset({"restaurant"}),
        "박물관": frozenset({"cultural_facility"}),
        "카페": frozenset({"restaurant"}),
    }

    async def search_places(
        self,
        latitude: float,
        longitude: float,
        preferred_categories: list[str],
        search_radius_km: float,
        region_code: str | None = None,
        district_code: str | None = None,
        category_filter: PlaceCategoryFilter | None = None,
        limit: int = DEFAULT_PLACE_PROVIDER_RESULT_LIMIT,
    ) -> ProviderResult[list[PlaceCandidate]]:
        candidates = [
            PlaceCandidate(
                place_id="fake-museum-1",
                content_type_id="14",
                lcls_systm1="VE",
                lcls_systm2="VE07",
                lcls_systm3="VE070100",
                name="테스트 박물관",
                category="cultural_facility",
                latitude=latitude,
                longitude=longitude,
                address="서울 종로구 어딘가",
                operating_hours="09:00-18:00",
                raw_source="fake_place",
            ),
            PlaceCandidate(
                place_id="fake-cafe-1",
                content_type_id="39",
                lcls_systm1="FD",
                lcls_systm2="FD05",
                lcls_systm3="FD050100",
                name="테스트 카페",
                category="restaurant",
                latitude=latitude + 0.001,
                longitude=longitude + 0.001,
                address="서울 종로구 어딘가",
                operating_hours="08:00-22:00",
                raw_source="fake_place",
            ),
        ]
        if category_filter and category_filter.content_type_id:
            candidates = [
                candidate
                for candidate in candidates
                if candidate.content_type_id == category_filter.content_type_id
            ]
        elif preferred_categories:
            # 명시적인 TourAPI 분류 필터가 없을 때만 레거시 선호 카테고리를 적용한다.
            normalized_categories = {
                category.strip().casefold() for category in preferred_categories if category.strip()
            }
            accepted_categories = {
                candidate_category
                for category in normalized_categories
                for candidate_category in self._CATEGORY_ALIASES.get(category, ())
            }
            candidates = [
                candidate for candidate in candidates if candidate.category in accepted_categories
            ]
        selected = candidates[: max(1, min(limit, 100))]
        return provider_result(
            selected,
            source=ProviderSource.FAKE_PLACE,
            status=ProviderStatus.SUCCESS if selected else ProviderStatus.NO_DATA,
        )

    async def search_by_keyword(
        self,
        keyword: str,
        region_code: str | None = None,
        district_code: str | None = None,
        limit: int = DEFAULT_PLACE_PROVIDER_RESULT_LIMIT,
    ) -> ProviderResult[list[PlaceCandidate]]:
        candidates = (await self.search_places(37.5796, 126.9770, [], 1.0)).data
        normalized = keyword.strip().lower()
        selected = [candidate for candidate in candidates if normalized in candidate.name.lower()][
            :limit
        ]
        return provider_result(
            selected,
            source=ProviderSource.FAKE_PLACE,
            status=ProviderStatus.SUCCESS if selected else ProviderStatus.NO_DATA,
        )

    async def get_details(
        self, content_id: str, content_type_id: str
    ) -> ProviderResult[PlaceDetails]:
        candidates = (await self.search_places(37.5796, 126.9770, [], 1.0)).data
        candidate = next((item for item in candidates if item.place_id == content_id), None)
        intro = _fake_intro(content_type_id) if candidate else {}
        operating_hours = candidate.operating_hours if candidate else None
        rest_date = (
            "매주 월요일"
            if candidate and candidate.category == "cultural_facility"
            else "연중무휴"
            if candidate
            else None
        )
        return provider_result(
            PlaceDetails(
                content_id=content_id,
                content_type_id=content_type_id,
                title=candidate.name if candidate else None,
                address=candidate.address if candidate else None,
                overview="Fake Provider의 장소 상세정보입니다.",
                homepage="https://example.test/fake-place",
                telephone="02-000-0000",
                operating_hours=operating_hours,
                rest_date=rest_date,
                raw_common={},
                raw_intro=intro,
                provider="fake_place",
                operating_schedule=normalize_operating_schedule(
                    content_type_id=content_type_id,
                    operating_hours=operating_hours,
                    rest_date=rest_date,
                ),
                # 정규화 필드도 실 provider와 같은 키 목록으로 뽑는다. 손으로 값을
                # 적어 넣으면 fake가 raw_intro와 어긋나도 아무도 모른다.
                parking=_first_intro_text(intro, PARKING_KEYS),
                parking_fee=_first_intro_text(intro, PARKING_FEE_KEYS),
                fee=_first_intro_text(intro, USE_FEE_KEYS),
                baby_carriage=_first_intro_text(intro, BABY_CARRIAGE_KEYS),
                pet=_first_intro_text(intro, PET_KEYS),
                credit_card=_first_intro_text(intro, CREDIT_CARD_KEYS),
                restroom=_first_intro_text(intro, RESTROOM_KEYS),
                # 무장애 정보(D-077)도 채운다. 비워 두면 INFO facility 배선이
                # 끊어져도 fake로 도는 테스트는 전부 통과하고, 실제 운영에서만
                # 값이 비는 상태가 된다.
                approach_route_raw="출입구까지 턱이 없어 휠체어 접근 가능함",
                entrance_access_raw="주출입구는 경사로가 있어 휠체어 접근 가능함",
                elevator_raw="엘리베이터 있음",
                accessible_restroom_raw="장애인 화장실 있음",
                accessible_parking_raw="장애인 주차장 있음(2대)",
                braille_block_raw="점자블록 있음",
                braille_promotion_raw="점자 안내물 있음",
                audio_guide_raw="음성 안내 있음",
                guide_dog_raw="동반가능",
                # 이름과 달리 출입이 아니라 대여다 — fake도 그 뜻으로 채운다.
                wheelchair_rental_raw="대여가능(2대, 안내데스크)",
                stroller_rental_raw="대여가능",
                nursing_room_raw="수유실 있음",
                infant_family_etc_raw="기저귀교환대 있음",
                public_transport_raw="저상버스 운행",
                disability_etc_raw="장애인 안내 도우미 있음",
                thumbnail_url=(
                    f"https://example.test/{content_id}-thumb.jpg" if candidate else None
                ),
            ),
            source=ProviderSource.FAKE_PLACE,
        )

    async def find_details_by_name(
        self,
        name: str,
        region_code: str | None = None,
        district_code: str | None = None,
    ) -> ProviderResult[PlaceDetails]:
        normalized_name = name.strip()
        candidates = (
            await self.search_by_keyword(normalized_name, region_code, district_code, limit=100)
        ).data
        exact = next(
            (
                candidate
                for candidate in candidates
                if candidate.name.strip().casefold() == normalized_name.casefold()
            ),
            None,
        )
        if exact is None or not exact.content_type_id:
            raise AppError(
                code="place_not_found",
                message=f"'{normalized_name}' 장소를 정확히 찾을 수 없어요.",
                status_code=404,
            )
        return await self.get_details(exact.place_id, exact.content_type_id)
