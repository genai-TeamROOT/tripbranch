"""compose_recommendation_message()/compose_chat_message() 단위 테스트."""

from __future__ import annotations

import pytest

from app.agent_context.schemas import ContextError
from app.errors import ProviderUnavailableError
from app.providers.contracts import ProviderSource, provider_result
from app.schemas import (
    ClarificationPayload,
    CompareCriteria,
    ComparisonItem,
    ComparisonResult,
    GeneralPayload,
    GeneralTopic,
    Intent,
    LLMOutput,
    OutOfScopeCategory,
    OutOfScopePayload,
    OutputStatus,
    RecommendationItem,
    RecommendationResponse,
    ScheduleItem,
    ScheduleResult,
    Severity,
)
from app.services.runtime.context_schemas import Clarification
from app.services.runtime.info_context_schemas import (
    ConcentrationInfoResult,
    EventInfoResult,
    EventItem,
    InfoContextResponse,
    PlaceInfoResult,
)
from app.services.runtime.response_composer import (
    compose_chat_message,
    compose_compare_message,
    compose_event_info_message,
    compose_info_concentration_message,
    compose_place_info_message,
    compose_recommendation_message,
    compose_schedule_message,
)


class _StubLLM:
    """compose_chat_message()의 LLM 생성 분기를 검증하기 위한 최소 테스트 더블."""

    def __init__(
        self,
        answer: str = "고정된 배경지식 답변입니다.",
        recommendation_summary: str = "테스트 장소를 중심으로 골라봤어요.",
        fail_recommendation_summary: bool = False,
        compare_summary: str = (
            "첫 번째 비교 문장입니다.\n두 번째 비교 문장입니다.\n세 번째 비교 문장입니다."
        ),
        fail_compare_summary: bool = False,
    ) -> None:
        self.answer = answer
        self.recommendation_summary = recommendation_summary
        self.fail_recommendation_summary = fail_recommendation_summary
        self.compare_summary = compare_summary
        self.fail_compare_summary = fail_compare_summary
        self.received: tuple[GeneralTopic, str] | None = None
        self.summary_received: tuple[Intent, RecommendationResponse] | None = None
        self.compare_received: ComparisonResult | None = None

    async def generate_general_answer(self, topic: GeneralTopic, original_question: str):
        self.received = (topic, original_question)
        return provider_result(self.answer, source=ProviderSource.FAKE_LLM)

    async def generate_recommendation_summary(
        self, intent: Intent, recommendations: RecommendationResponse
    ):
        self.summary_received = (intent, recommendations)
        if self.fail_recommendation_summary:
            raise ProviderUnavailableError("Gemini")
        return provider_result(self.recommendation_summary, source=ProviderSource.FAKE_LLM)

    async def generate_compare_summary(self, comparison: ComparisonResult):
        self.compare_received = comparison
        if self.fail_compare_summary:
            raise ProviderUnavailableError("Gemini")
        return provider_result(self.compare_summary, source=ProviderSource.FAKE_LLM)


def _item(*, explanations: list[str], warnings: list[str]) -> RecommendationItem:
    return RecommendationItem(
        place_id="p1",
        name="테스트 장소",
        category="cafe",
        distance_km=0.3,
        remaining_minutes=60,
        environment_type="indoor",
        recommendation_reason="테스트용",
        explanations=explanations,
        warnings=warnings,
        score=0.5,
        feature_scores={},
        weights_used={},
    )


def test_explanations_only() -> None:
    item = _item(explanations=["지금 날씨 조건에 잘 맞는 장소예요."], warnings=[])
    assert compose_recommendation_message(item) == "지금 날씨 조건에 잘 맞는 장소예요."


def test_explanations_and_warnings() -> None:
    item = _item(
        explanations=["현재 위치에서 가까운 장소예요."],
        warnings=["방문 전에 운영 여부를 확인해주세요."],
    )
    assert compose_recommendation_message(item) == (
        "현재 위치에서 가까운 장소예요. 다만, 방문 전에 운영 여부를 확인해주세요."
    )


def test_warnings_only_when_explanations_empty() -> None:
    item = _item(
        explanations=[],
        warnings=["이 장소는 특별히 강조할 만한 조건은 없지만, 조건에 맞아 추천했어요."],
    )
    assert compose_recommendation_message(item) == (
        "다만, 이 장소는 특별히 강조할 만한 조건은 없지만, 조건에 맞아 추천했어요."
    )


def test_multiple_explanations_joined() -> None:
    item = _item(
        explanations=["지금 날씨 조건에 잘 맞는 장소예요.", "현재 위치에서 가까운 장소예요."],
        warnings=[],
    )
    assert compose_recommendation_message(item) == (
        "지금 날씨 조건에 잘 맞는 장소예요. 현재 위치에서 가까운 장소예요."
    )


def test_both_empty_returns_empty_string() -> None:
    item = _item(explanations=[], warnings=[])
    assert compose_recommendation_message(item) == ""


def _response(*, place_ids: list[str]) -> RecommendationResponse:
    return RecommendationResponse(
        recommendations=[
            _item(explanations=[f"{pid} 근거"], warnings=[]) for pid in place_ids
        ],
        unverified_recommendations=[],
        elapsed_ms=0,
    )


class TestComposeChatMessageClarification:
    @pytest.mark.asyncio
    async def test_llm_stage_needs_clarification_uses_extraction_message(self) -> None:
        llm_output = LLMOutput(
            intent=Intent.RECOMMEND,
            status=OutputStatus.NEEDS_CLARIFICATION,
            clarification=ClarificationPayload(message="눈을 피하고 싶으신가요?"),
        )
        message = await compose_chat_message(llm_output, llm=_StubLLM())
        assert message == "눈을 피하고 싶으신가요?"


class TestComposeChatMessageOutOfScope:
    @pytest.mark.parametrize(
        "category",
        [
            OutOfScopeCategory.HARMFUL,
            OutOfScopeCategory.UNRELATED,
            OutOfScopeCategory.ROLE_REQUEST,
            OutOfScopeCategory.PROMPT_INJECTION,
        ],
    )
    @pytest.mark.asyncio
    async def test_each_category_has_a_template(self, category: OutOfScopeCategory) -> None:
        llm_output = LLMOutput(
            intent=Intent.OUT_OF_SCOPE,
            status=OutputStatus.COMPLETE,
            out_of_scope=OutOfScopePayload(category=category, severity=Severity.LOW),
        )
        message = await compose_chat_message(llm_output, llm=_StubLLM())
        assert message  # 비어있지 않은 고정 문구가 나온다


class TestComposeChatMessageGeneral:
    @pytest.mark.asyncio
    async def test_calls_llm_and_returns_its_answer(self) -> None:
        llm_output = LLMOutput(
            intent=Intent.GENERAL,
            status=OutputStatus.COMPLETE,
            general=GeneralPayload(
                topic=GeneralTopic.PLACE_KNOWLEDGE, original_question="경복궁 역사 알려줘"
            ),
        )
        stub = _StubLLM(answer="경복궁은 조선 왕조의 정궁이에요.")
        message = await compose_chat_message(llm_output, llm=stub)
        assert message == "경복궁은 조선 왕조의 정궁이에요."
        assert stub.received == (GeneralTopic.PLACE_KNOWLEDGE, "경복궁 역사 알려줘")


class TestComposeChatMessageRecommendAndModify:
    @pytest.mark.parametrize("intent", [Intent.RECOMMEND, Intent.MODIFY])
    @pytest.mark.asyncio
    async def test_generates_summary_when_recommendations_present(self, intent: Intent) -> None:
        llm_output = LLMOutput(intent=intent, status=OutputStatus.COMPLETE)
        stub = _StubLLM(recommendation_summary="테스트 장소를 중심으로 골라봤어요.")
        message = await compose_chat_message(
            llm_output, recommendations=_response(place_ids=["a", "b"]), llm=stub
        )
        assert message == "테스트 장소를 중심으로 골라봤어요."
        assert stub.summary_received is not None
        assert stub.summary_received[0] is intent

    @pytest.mark.asyncio
    async def test_recommendation_summary_failure_falls_back_to_template(self) -> None:
        llm_output = LLMOutput(intent=Intent.RECOMMEND, status=OutputStatus.COMPLETE)
        message = await compose_chat_message(
            llm_output,
            recommendations=_response(place_ids=["a", "b"]),
            llm=_StubLLM(fail_recommendation_summary=True),
        )
        assert message == "이런 곳들을 찾아봤어요:"

    @pytest.mark.asyncio
    async def test_no_data_message_when_recommendations_is_none(self) -> None:
        llm_output = LLMOutput(intent=Intent.RECOMMEND, status=OutputStatus.COMPLETE)
        message = await compose_chat_message(llm_output, recommendations=None, llm=_StubLLM())
        assert "찾지 못했어요" in message

    @pytest.mark.asyncio
    async def test_no_data_message_when_recommendations_are_empty(self) -> None:
        llm_output = LLMOutput(intent=Intent.RECOMMEND, status=OutputStatus.COMPLETE)
        message = await compose_chat_message(
            llm_output, recommendations=_response(place_ids=[]), llm=_StubLLM()
        )
        assert "찾지 못했어요" in message

    @pytest.mark.asyncio
    async def test_tool_stage_needs_clarification_known_code(self) -> None:
        llm_output = LLMOutput(intent=Intent.RECOMMEND, status=OutputStatus.COMPLETE)
        clarification = Clarification(code="location_required", missing_fields=[], candidates=[])
        message = await compose_chat_message(
            llm_output,
            tool_status="needs_clarification",
            tool_clarification=clarification,
            llm=_StubLLM(),
        )
        assert message == "어디 근처에서 찾아드릴까요? 현재 위치나 원하시는 지역을 알려주세요."

    @pytest.mark.asyncio
    async def test_tool_stage_needs_clarification_missing_clarification_falls_back(self) -> None:
        llm_output = LLMOutput(intent=Intent.RECOMMEND, status=OutputStatus.COMPLETE)
        message = await compose_chat_message(
            llm_output, tool_status="needs_clarification", tool_clarification=None, llm=_StubLLM()
        )
        assert message == "조건을 조금 더 자세히 알려주시겠어요?"

    @pytest.mark.asyncio
    async def test_tool_stage_unsupported(self) -> None:
        llm_output = LLMOutput(intent=Intent.MODIFY, status=OutputStatus.COMPLETE)
        message = await compose_chat_message(
            llm_output, tool_status="unsupported", llm=_StubLLM()
        )
        assert message == "죄송하지만 아직 지원하지 않는 요청이에요."

    @pytest.mark.asyncio
    async def test_tool_stage_unsupported_region_names_the_service_area(self) -> None:
        """지원 지역 밖은 무엇이 문제인지 알려야 한다(D-044).

        "아직 지원하지 않는 요청"이라고만 하면 조건을 바꿔 다시 시도하게 된다.
        """
        llm_output = LLMOutput(intent=Intent.RECOMMEND, status=OutputStatus.COMPLETE)
        message = await compose_chat_message(
            llm_output,
            tool_status="unsupported",
            tool_error_code="unsupported_region",
            llm=_StubLLM(),
        )
        assert message == (
            "현재는 베타 서비스로 종로구의 장소 추천만 가능해요. "
            "종로에서 가고 싶은 위치를 말씀해주세요."
        )

    @pytest.mark.asyncio
    async def test_tool_stage_unavailable(self) -> None:
        llm_output = LLMOutput(intent=Intent.RECOMMEND, status=OutputStatus.COMPLETE)
        message = await compose_chat_message(
            llm_output, tool_status="unavailable", llm=_StubLLM()
        )
        assert "잠시 후 다시 시도" in message


def _comparison() -> ComparisonResult:
    return ComparisonResult(
        criteria=CompareCriteria.OVERALL,
        items=[
            ComparisonItem(
                place_id="p1",
                place_name="국립현대미술관 서울",
                rank=1,
                distance_km=0.3,
                remaining_minutes=180,
                environment_type="indoor",
            ),
            ComparisonItem(
                place_id="p2",
                place_name="창덕궁",
                rank=2,
                distance_km=0.8,
                remaining_minutes=90,
                environment_type="outdoor",
            ),
        ],
    )


class TestComposeCompareMessage:
    @pytest.mark.asyncio
    async def test_calls_llm_with_only_comparison_facts(self) -> None:
        comparison = _comparison()
        stub = _StubLLM(compare_summary="첫째 줄\n둘째 줄\n셋째 줄")

        message = await compose_compare_message(comparison, stub)

        assert message == "첫째 줄\n둘째 줄\n셋째 줄"
        assert stub.compare_received == comparison

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_fact_only_template(self) -> None:
        message = await compose_compare_message(
            _comparison(), _StubLLM(fail_compare_summary=True)
        )

        lines = message.splitlines()
        assert 3 <= len(lines) <= 6
        assert "국립현대미술관 서울" in message
        assert "거리 0.3km" in message
        assert "점수" not in message


class TestComposeChatMessageInfoCompare:
    @pytest.mark.parametrize("intent", [Intent.INFO, Intent.COMPARE])
    @pytest.mark.asyncio
    async def test_not_yet_supported_placeholder(self, intent: Intent) -> None:
        llm_output = LLMOutput(intent=intent, status=OutputStatus.COMPLETE)
        message = await compose_chat_message(llm_output, llm=_StubLLM())
        assert "준비 중" in message


@pytest.mark.asyncio
async def test_schedule_without_result_falls_back_to_placeholder() -> None:
    """schedule을 안 넘기면(배선 전 방어적 호출 등) 안내 문구로 안전하게 낮아진다."""
    llm_output = LLMOutput(intent=Intent.SCHEDULE, status=OutputStatus.COMPLETE)

    message = await compose_chat_message(llm_output, llm=_StubLLM())

    assert message == "일정 추천 기능은 아직 준비 중이에요."


@pytest.mark.asyncio
async def test_schedule_with_result_uses_schedule_summary() -> None:
    llm_output = LLMOutput(intent=Intent.SCHEDULE, status=OutputStatus.COMPLETE)
    schedule = ScheduleResult(
        items=[
            ScheduleItem(
                order=1,
                place_id="p1",
                place_name="연남동 카페 A",
                estimated_arrival="15:00",
                estimated_duration_min=60,
                travel_to_next_min=15,
                reason="도보 이동 시작점에 가까워요.",
            )
        ],
        total_duration_min=90,
        route_summary="연남동 카페 A에서 시작해요.",
        basis_note="이 정보는 15:00 기준으로 계산됐어요.",
    )

    message = await compose_chat_message(llm_output, schedule=schedule, llm=_StubLLM())

    assert message == compose_schedule_message(schedule)
    assert "1시간 30분" in message
    assert "연남동 카페 A에서 시작해요." in message


def _schedule_item(place_id: str = "p1") -> ScheduleItem:
    return ScheduleItem(
        order=1,
        place_id=place_id,
        place_name=f"장소 {place_id}",
        estimated_arrival="15:00",
        estimated_duration_min=60,
        travel_to_next_min=None,
        reason="테스트 이유",
    )


class TestComposeScheduleMessage:
    def test_formats_hours_and_minutes(self) -> None:
        schedule = ScheduleResult(
            items=[_schedule_item()],
            total_duration_min=125,
            route_summary="동선 요약입니다.",
            basis_note="기준 시각 안내",
        )

        message = compose_schedule_message(schedule)

        assert message == "2시간 5분 코스를 짜봤어요. 동선 요약입니다."

    def test_formats_minutes_only_when_under_an_hour(self) -> None:
        schedule = ScheduleResult(
            items=[_schedule_item()],
            total_duration_min=45,
            route_summary="짧은 코스예요.",
            basis_note="기준 시각 안내",
        )

        message = compose_schedule_message(schedule)

        assert message == "45분 코스를 짜봤어요. 짧은 코스예요."

    def test_empty_items_returns_route_summary_without_duration_prefix(self) -> None:
        """items가 비면(후보 부족 등) planner.py가 route_summary를 안내 문구로
        정규화해서 넘긴다 — 여기서는 "0분 코스를 짜봤어요" 같은 어색한 접두사 없이
        그 문구를 그대로 반환하기만 한다(SCHEDULE-06 후속 수정)."""
        schedule = ScheduleResult(
            items=[],
            total_duration_min=0,
            route_summary="조건에 맞는 곳을 충분히 찾지 못해 일정을 만들지 못했어요.",
            basis_note="기준 시각 안내",
        )

        message = compose_schedule_message(schedule)

        assert message == "조건에 맞는 곳을 충분히 찾지 못해 일정을 만들지 못했어요."


class TestComposeInfoConcentrationMessage:
    """concentration-conditions.md §3.3/§7의 고지 규칙 — is_proxy=True일 때만
    "근처 [관광지] 기준" 문구가 나와야 하고, 절대 요청 장소 자체의 값처럼
    말하지 않아야 한다."""

    def test_direct_hit_uses_predictive_phrasing(self) -> None:
        response = InfoContextResponse(
            request_id="r1",
            status="success",
            result=ConcentrationInfoResult(
                status="success",
                is_proxy=False,
                requested_place_name="경복궁",
                resolved_place_name="경복궁",
                forecast_date="2026-08-01",
                concentration_rate=42.0,
                concentration_level="normal",
                concentration_label="보통",
            ),
        )
        message = compose_info_concentration_message(response)
        assert "경복궁" in message
        assert "보통" in message
        assert "것으로 예측돼요" in message
        assert "지금" not in message  # 실시간 단정 표현 금지 (§7)

    def test_proxy_discloses_nearest_attraction(self) -> None:
        response = InfoContextResponse(
            request_id="r2",
            status="success",
            result=ConcentrationInfoResult(
                status="success",
                is_proxy=True,
                requested_place_name="인사동카페",
                resolved_place_name="경복궁",
                forecast_date="2026-08-01",
                concentration_rate=58.0,
                concentration_level="slightly_crowded",
                concentration_label="다소 혼잡",
            ),
        )
        message = compose_info_concentration_message(response)
        assert "인사동카페 자체" in message
        assert "가장 가까운 관광지인 경복궁" in message
        assert "다소 혼잡" in message

    def test_no_data_result_returns_fixed_message(self) -> None:
        response = InfoContextResponse(
            request_id="r3",
            status="success",
            result=ConcentrationInfoResult(status="no_data", requested_place_name="용리단길카페"),
        )
        message = compose_info_concentration_message(response)
        assert message == "이 장소 유형은 혼잡도 데이터가 없어요."

    def test_unsupported_region_names_the_service_area(self) -> None:
        """"혼잡도 데이터가 없다"고 하면 다른 날 다시 물어보게 된다(D-044)."""
        response = InfoContextResponse(
            request_id="r5",
            status="unsupported",
            error=ContextError(
                code="unsupported_region",
                message="현재는 서울특별시 종로구 내 장소만 지원합니다.",
                retryable=False,
            ),
        )
        message = compose_info_concentration_message(response)
        assert message == (
            "현재는 베타 서비스로 종로구의 장소 추천만 가능해요. "
            "종로에서 가고 싶은 위치를 말씀해주세요."
        )

    def test_unavailable_result_returns_generic_error(self) -> None:
        response = InfoContextResponse(
            request_id="r4",
            status="success",
            result=ConcentrationInfoResult(status="unavailable"),
        )
        assert "잠시 후 다시" in compose_info_concentration_message(response)

    def test_envelope_unavailable_without_result(self) -> None:
        response = InfoContextResponse(request_id="r5", status="unavailable")
        assert "잠시 후 다시" in compose_info_concentration_message(response)

    def test_needs_clarification_uses_place_required_template(self) -> None:
        response = InfoContextResponse(
            request_id="r6",
            status="needs_clarification",
            clarification=Clarification(code="place_required", missing_fields=["place_name"]),
        )
        assert compose_info_concentration_message(response) == "어떤 장소에 대해 알고 싶으신가요?"

    @pytest.mark.asyncio
    async def test_compose_chat_message_dispatches_to_concentration_composer(self) -> None:
        llm_output = LLMOutput(intent=Intent.INFO, status=OutputStatus.COMPLETE)
        response = InfoContextResponse(
            request_id="r7",
            status="success",
            result=ConcentrationInfoResult(
                status="success",
                is_proxy=False,
                requested_place_name="창덕궁",
                resolved_place_name="창덕궁",
                forecast_date="2026-08-01",
                concentration_rate=20.0,
                concentration_level="quiet",
                concentration_label="한적함",
            ),
        )
        message = await compose_chat_message(llm_output, info_response=response, llm=_StubLLM())
        assert "한적함" in message

    @pytest.mark.asyncio
    async def test_info_without_concentration_response_falls_back_to_placeholder(self) -> None:
        llm_output = LLMOutput(intent=Intent.INFO, status=OutputStatus.COMPLETE)
        message = await compose_chat_message(llm_output, llm=_StubLLM())
        assert "준비 중" in message


class TestComposePlaceInfoMessage:
    """D-054 A 배선 — concentration/event를 제외한 6종 question_type."""

    def test_success_renders_fields_with_labels(self) -> None:
        response = InfoContextResponse(
            request_id="r8",
            status="success",
            result=PlaceInfoResult(
                status="success",
                question_type="operating_hours",
                requested_place_name="경복궁",
                resolved_place_name="경복궁",
                fields={"operating_hours": "09:00~18:00", "rest_date": "매주 화요일"},
            ),
        )
        message = compose_place_info_message(response)
        assert message == (
            "경복궁 운영시간을 확인했어요. "
            "아래에서 월별 운영시간과 휴무일을 확인하세요."
        )

    def test_operating_hours_is_a_natural_sentence_not_label_value(self) -> None:
        response = InfoContextResponse(
            request_id="r8b",
            status="success",
            result=PlaceInfoResult(
                status="success",
                question_type="operating_hours",
                requested_place_name="경복궁",
                resolved_place_name="경복궁",
                fields={"operating_hours": "09:00~18:00", "rest_date": "매주 화요일"},
            ),
        )
        message = compose_place_info_message(response)
        assert message == (
            "경복궁 운영시간을 확인했어요. "
            "아래에서 월별 운영시간과 휴무일을 확인하세요."
        )
        assert "09:00~18:00" not in message

    def test_fee_is_a_natural_sentence(self) -> None:
        response = InfoContextResponse(
            request_id="r8c",
            status="success",
            result=PlaceInfoResult(
                status="success",
                question_type="fee",
                requested_place_name="경복궁",
                resolved_place_name="경복궁",
                fields={"fee": "성인 3,000원"},
            ),
        )
        message = compose_place_info_message(response)
        assert message == (
            "경복궁 입장료는 성인 기준 3,000원이에요. "
            "아래에서 상세 요금 정보를 확인해보세요!"
        )

    def test_rest_date_keeps_notice_on_a_separate_line(self) -> None:
        response = InfoContextResponse(
            request_id="r8c-rest",
            status="success",
            result=PlaceInfoResult(
                status="success",
                question_type="operating_hours",
                requested_place_name="경복궁",
                resolved_place_name="경복궁",
                fields={
                    "operating_hours": "09:00~18:00",
                    "rest_date": "매주 화요일 ※ 공휴일이면 개방",
                },
            ),
        )

        message = compose_place_info_message(response, specific_question="경복궁 휴무일 언제야?")

        assert message == (
            "경복궁 휴무일은 매주 화요일입니다.\n※ 공휴일이면 개방\n\n"
            "아래에서 자세한 운영시간을 확인하세요."
        )

    def test_parking_shows_only_car_capacity(self) -> None:
        """일반 사용자용 메시지에서는 버스 수용 대수를 숨긴다."""
        response = InfoContextResponse(
            request_id="r8d",
            status="success",
            result=PlaceInfoResult(
                status="success",
                question_type="parking",
                requested_place_name="경복궁",
                resolved_place_name="경복궁",
                fields={
                    "parking": "가능 (승용차 240대 / 버스 50대)",
                    "parking_fee": "무료",
                },
            ),
        )
        message = compose_place_info_message(response)
        assert message == "경복궁 주차는 가능해요. 아래 주차 상세 내용을 확인해보세요."

    def test_facility_joins_present_fields_into_one_sentence(self) -> None:
        response = InfoContextResponse(
            request_id="r8e",
            status="success",
            result=PlaceInfoResult(
                status="success",
                question_type="facility",
                requested_place_name="경복궁",
                resolved_place_name="경복궁",
                fields={"baby_carriage": "가능", "restroom": "있음"},
            ),
        )
        message = compose_place_info_message(response)
        assert message == "경복궁의 편의시설이에요. 유모차 대여는 가능, 화장실은 있음예요."

    def test_location_info_is_a_natural_sentence(self) -> None:
        response = InfoContextResponse(
            request_id="r8f",
            status="success",
            result=PlaceInfoResult(
                status="success",
                question_type="location_info",
                requested_place_name="종묘",
                resolved_place_name="종묘",
                fields={"address": "서울특별시 종로구 종로 157"},
            ),
        )
        message = compose_place_info_message(response)
        assert message == "종묘 주소는 서울특별시 종로구 종로 157예요."

    def test_general_info_shows_overview_raw_without_summarizing(self) -> None:
        """사용자 결정: overview는 LLM 요약 없이 원문 그대로 노출한다."""
        overview = "조선 왕조의 법궁으로 1395년에 창건된 궁궐이다." * 3
        response = InfoContextResponse(
            request_id="r9",
            status="success",
            result=PlaceInfoResult(
                status="success",
                question_type="general_info",
                requested_place_name="경복궁",
                resolved_place_name="경복궁",
                fields={"overview": overview, "homepage": "http://www.royalpalace.go.kr"},
            ),
        )
        message = compose_place_info_message(response)
        assert overview in message
        assert "http://www.royalpalace.go.kr" in message
        assert message.startswith("경복궁 소개예요. ")
        assert message.endswith("홈페이지는 http://www.royalpalace.go.kr예요.")

    def test_no_data_names_the_question_type_not_generic_unavailable(self) -> None:
        response = InfoContextResponse(
            request_id="r10",
            status="success",
            result=PlaceInfoResult(
                status="no_data",
                question_type="parking",
                requested_place_name="경복궁",
                resolved_place_name="경복궁",
                fields={},
            ),
        )
        message = compose_place_info_message(response)
        assert "경복궁" in message
        assert "주차" in message

    def test_unavailable_uses_shared_unavailable_message(self) -> None:
        response = InfoContextResponse(request_id="r11", status="unavailable")
        message = compose_place_info_message(response)
        assert "잠시 후 다시" in message

    def test_needs_clarification_reuses_place_required_template(self) -> None:
        response = InfoContextResponse(
            request_id="r12",
            status="needs_clarification",
            clarification=Clarification(code="place_required", missing_fields=["place_name"]),
        )
        assert compose_place_info_message(response) == "어떤 장소에 대해 알고 싶으신가요?"

    @pytest.mark.asyncio
    async def test_compose_chat_message_dispatches_to_place_composer(self) -> None:
        llm_output = LLMOutput(intent=Intent.INFO, status=OutputStatus.COMPLETE)
        response = InfoContextResponse(
            request_id="r13",
            status="success",
            result=PlaceInfoResult(
                status="success",
                question_type="fee",
                requested_place_name="경복궁",
                resolved_place_name="경복궁",
                fields={"fee": "성인 3,000원"},
            ),
        )
        message = await compose_chat_message(llm_output, info_response=response, llm=_StubLLM())
        assert "성인 기준 3,000원" in message


class TestComposeEventInfoMessage:
    """D-055 A 배선 — is_direct_match=False인 행사를 그 장소의 행사로 말하지 않는다."""

    def test_direct_match_and_nearby_are_worded_differently(self) -> None:
        response = InfoContextResponse(
            request_id="r14",
            status="success",
            result=EventInfoResult(
                status="success",
                requested_place_name="경복궁",
                resolved_place_name="경복궁",
                reference_date="2026-08-10",
                events=[
                    EventItem(
                        title="경복궁 별빛야행",
                        start_date="2026-08-01",
                        end_date="2026-08-31",
                        distance_km=0.0,
                        is_direct_match=True,
                    ),
                    EventItem(
                        title="종로구 전통문화행사",
                        start_date="2026-08-01",
                        end_date="2026-08-10",
                        distance_km=0.21,
                        is_direct_match=False,
                    ),
                ],
                has_direct_match=True,
            ),
        )
        message = compose_event_info_message(response)
        assert "경복궁에서 진행 중인 행사예요. 경복궁 별빛야행" in message
        assert "경복궁 근처에서 진행 중인 행사예요. 종로구 전통문화행사(0.21km)" in message
        # 근처 행사를 그 장소의 행사처럼 말하지 않는다(D-055 필수 규칙).
        assert "경복궁에서 진행 중인 행사예요. 종로구 전통문화행사" not in message

    def test_only_nearby_events_never_claims_direct(self) -> None:
        response = InfoContextResponse(
            request_id="r15",
            status="success",
            result=EventInfoResult(
                status="success",
                requested_place_name="경복궁",
                resolved_place_name="경복궁",
                events=[
                    EventItem(
                        title="종로구 전통문화행사",
                        start_date="2026-08-01",
                        end_date="2026-08-10",
                        distance_km=0.21,
                        is_direct_match=False,
                    ),
                ],
                has_direct_match=False,
            ),
        )
        message = compose_event_info_message(response)
        assert "근처에서 진행 중인 행사예요" in message
        assert "경복궁에서 진행 중인 행사예요" not in message

    def test_no_events_says_none_in_progress(self) -> None:
        response = InfoContextResponse(
            request_id="r16",
            status="success",
            result=EventInfoResult(
                status="no_data",
                requested_place_name="경복궁",
                resolved_place_name="경복궁",
                events=[],
            ),
        )
        message = compose_event_info_message(response)
        assert "행사가 없어요" in message

    def test_unavailable_uses_shared_unavailable_message(self) -> None:
        response = InfoContextResponse(request_id="r17", status="unavailable")
        message = compose_event_info_message(response)
        assert "잠시 후 다시" in message

    @pytest.mark.asyncio
    async def test_compose_chat_message_dispatches_to_event_composer(self) -> None:
        llm_output = LLMOutput(intent=Intent.INFO, status=OutputStatus.COMPLETE)
        response = InfoContextResponse(
            request_id="r18",
            status="success",
            result=EventInfoResult(
                status="success",
                requested_place_name="경복궁",
                resolved_place_name="경복궁",
                events=[
                    EventItem(
                        title="경복궁 별빛야행",
                        start_date="2026-08-01",
                        end_date="2026-08-31",
                        distance_km=0.0,
                        is_direct_match=True,
                    ),
                ],
                has_direct_match=True,
            ),
        )
        message = await compose_chat_message(llm_output, info_response=response, llm=_StubLLM())
        assert "경복궁 별빛야행" in message
