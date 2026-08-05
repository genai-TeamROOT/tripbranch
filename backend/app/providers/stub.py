"""TripBranch fake provider 구현체 모음.

역할: 외부 API 호출 없이 고정/임시 데이터로 각 provider 계약을 만족시킨다.
입력: 각 provider protocol이 요구하는 파라미터.
출력: 각 provider protocol이 요구하는 응답 모델.
호출 시점: PLACE_PROVIDER=fake 등 설정이 fake일 때 provider 팩토리가 주입한다.
TODO: 실제 provider(RealPlaceProvider 등)가 준비되면 팩토리에서 설정값으로 분기한다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain.models import (
    PlaceCategoryFilter,
    PlaceDetails,
    WeatherCondition,
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
from app.schemas import (
    ClarificationPayload,
    CompareCriteria,
    ComparePayload,
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
    RecommendPayload,
    Severity,
    StatedWeather,
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

_KNOWN_PLACE_NAMES = ("경복궁", "창덕궁", "종묘", "인사동", "광화문", "북촌한옥마을")
_HARMFUL_MARKERS = ("바보", "미친", "죽어", "씨발", "개새끼")
_OFF_TOPIC_MARKERS = ("주식", "수학 문제", "코드 짜줘", "파이썬 코드")
_PROMPT_INJECTION_MARKERS = ("시스템 프롬프트", "프롬프트를 보여줘", "무시하고")
_REJECT_ALL_MARKERS = ("다른 곳", "다른 거", "전부 별로", "다 마음에 안", "다른거")
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
_COMPARE_MARKERS = ("가까워", "오래 열어", "어디가 좋아", "뭐가 나아", "비교해")
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


def _find_known_place(user_input: str) -> str | None:
    return next((name for name in _KNOWN_PLACE_NAMES if name in user_input), None)


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
        elif has_previous_recommendation and any(
            marker in user_input for marker in _REJECT_ALL_MARKERS + _MODIFY_CHANGE_MARKERS
        ):
            result = IntentClassificationResult(intent=Intent.MODIFY)
        elif shown_place_count >= 2 and any(
            marker in user_input for marker in _COMPARE_MARKERS
        ):
            result = IntentClassificationResult(intent=Intent.COMPARE)
        elif any(marker in user_input for marker in _GENERAL_MARKERS):
            result = IntentClassificationResult(intent=Intent.GENERAL)
        elif _find_known_place(user_input) and any(
            marker in user_input for marker in _INFO_QUESTION_MARKERS
        ):
            result = IntentClassificationResult(intent=Intent.INFO)
        elif _find_known_place(user_input) and not any(
            marker in user_input for marker in ("근처", "주변", "같은 곳")
        ):
            result = IntentClassificationResult(intent=Intent.INFO)
        else:
            result = IntentClassificationResult(intent=Intent.RECOMMEND)
        return provider_result(result, source=ProviderSource.FAKE_LLM)

    async def extract_recommend_conditions(
        self, user_input: str
    ) -> ProviderResult[LLMOutput]:
        conditions = UserConditions()
        place_name = _find_known_place(user_input)
        if place_name and ("근처" in user_input or "주변" in user_input):
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

        result = LLMOutput(
            intent=Intent.RECOMMEND,
            status=status,
            recommend=RecommendPayload(conditions=conditions),
            clarification=clarification,
        )
        return provider_result(result, source=ProviderSource.FAKE_LLM)

    async def extract_modify_conditions(
        self, user_input: str, current_conditions: UserConditions
    ) -> ProviderResult[LLMOutput]:
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
        if "말고" in user_input and "카페" in user_input:
            changed.place_types = [PlaceType.RESTAURANT]
            changed.place_tags = [t for t in changed.place_tags if t != PlaceTag.CAFE]
            changed_fields.extend(["place_types", "place_tags"])
        new_place = _find_known_place(user_input)
        if new_place and "근처로 바꿔" in user_input:
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

        if "열어" in user_input or "몇 시" in user_input:
            question_type = QuestionType.OPERATING_HOURS
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
        self, user_input: str, *, shown_place_count: int
    ) -> ProviderResult[LLMOutput]:
        if "가까워" in user_input:
            criteria = CompareCriteria.DISTANCE
        elif "오래 열어" in user_input:
            criteria = CompareCriteria.TIME
        else:
            criteria = CompareCriteria.OVERALL

        result = LLMOutput(
            intent=Intent.COMPARE,
            status=OutputStatus.COMPLETE,
            compare=ComparePayload(targets="all", criteria=criteria),
        )
        return provider_result(result, source=ProviderSource.FAKE_LLM)

    async def extract_general_request(
        self, user_input: str
    ) -> ProviderResult[LLMOutput]:
        if "역사" in user_input or "언제 지어졌" in user_input:
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


class FakeWeatherProvider:
    """설정한 공통 날씨 상태를 반환하는 가짜 구현."""

    def __init__(self, condition: WeatherCondition = WeatherCondition.NEUTRAL) -> None:
        self._condition = condition

    async def get_current_condition(
        self, latitude: float, longitude: float
    ) -> ProviderResult[WeatherCondition]:
        return provider_result(self._condition, source=ProviderSource.FAKE_WEATHER)

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
                        condition=self._condition,
                        sky_code=None,
                        precipitation_type=None,
                    )
                    for offset in range(6)
                ),
                provider="fake_weather",
            ),
            source=ProviderSource.FAKE_WEATHER,
        )


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
                category.strip().casefold()
                for category in preferred_categories
                if category.strip()
            }
            accepted_categories = {
                candidate_category
                for category in normalized_categories
                for candidate_category in self._CATEGORY_ALIASES.get(category, ())
            }
            candidates = [
                candidate
                for candidate in candidates
                if candidate.category in accepted_categories
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
                homepage=None,
                telephone=None,
                operating_hours=operating_hours,
                rest_date=rest_date,
                raw_common={},
                raw_intro={},
                provider="fake_place",
                operating_schedule=normalize_operating_schedule(
                    content_type_id=content_type_id,
                    operating_hours=operating_hours,
                    rest_date=rest_date,
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
        candidates = (await self.search_by_keyword(
            normalized_name, region_code, district_code, limit=100
        )).data
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
