"""compose_recommendation_message()/compose_chat_message() 단위 테스트."""

from __future__ import annotations

import pytest

from app.agent_context.schemas import ContextError
from app.errors import ProviderTimeoutError, ProviderUnavailableError
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
    SituationKind,
)
from app.services.runtime.context_schemas import Clarification
from app.services.runtime.info_context_schemas import (
    ConcentrationInfoResult,
    EventInfoResult,
    EventItem,
    InfoContextResponse,
    PlaceInfoResult,
    RealtimeCityInfoResult,
    RealtimeCommercialInfoResult,
    RealtimePopulationInfoResult,
)
from app.services.runtime.response_composer import (
    compose_chat_message,
    compose_compare_message,
    compose_event_info_message,
    compose_info_concentration_message,
    compose_place_info_message,
    compose_realtime_city_info_message,
    compose_realtime_commercial_message,
    compose_realtime_population_message,
    compose_recommendation_message,
    compose_schedule_message,
    unsupported_region_footnote,
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
        self.offer_content_received: str | None = None
        self.recommendation_summary = recommendation_summary
        self.fail_recommendation_summary = fail_recommendation_summary
        self.compare_summary = compare_summary
        self.fail_compare_summary = fail_compare_summary
        self.received: tuple[GeneralTopic, str] | None = None
        self.summary_received: tuple[Intent, RecommendationResponse] | None = None
        self.compare_received: ComparisonResult | None = None
        self.info_received: dict[str, str] | None = None
        self.conditions_received = None
        self.history_received = None

    async def generate_general_answer(
        self,
        topic: GeneralTopic,
        original_question: str,
        *,
        offer_content: str | None = None,
        history=None,
    ):
        self.received = (topic, original_question)
        self.offer_content_received = offer_content
        self.history_received = history
        return provider_result(self.answer, source=ProviderSource.FAKE_LLM)

    async def generate_recommendation_summary(
        self,
        intent: Intent,
        recommendations: RecommendationResponse,
        *,
        conditions=None,
        history=None,
    ):
        self.summary_received = (intent, recommendations)
        self.conditions_received = conditions
        self.history_received = history
        if self.fail_recommendation_summary:
            raise ProviderUnavailableError("Gemini")
        return provider_result(self.recommendation_summary, source=ProviderSource.FAKE_LLM)

    async def stream_recommendation_summary(
        self,
        intent: Intent,
        recommendations: RecommendationResponse,
        *,
        conditions=None,
        history=None,
    ):
        """SSE 경로 검증용: 같은 요약 문장을 두 조각으로 나눈다."""

        result = await self.generate_recommendation_summary(
            intent, recommendations, conditions=conditions, history=history
        )
        midpoint = max(1, len(result.data) // 2)
        yield result.data[:midpoint]
        yield result.data[midpoint:]

    async def stream_general_answer(
        self,
        topic: GeneralTopic,
        original_question: str,
        *,
        offer_content: str | None = None,
        history=None,
    ):
        result = await self.generate_general_answer(
            topic, original_question, offer_content=offer_content, history=history
        )
        midpoint = max(1, len(result.data) // 2)
        yield result.data[:midpoint]
        yield result.data[midpoint:]

    async def stream_info_answer(
        self,
        *,
        place_name: str,
        question_type: str,
        specific_question: str | None,
        fields: dict[str, str],
        history=None,
    ):
        del place_name, question_type, specific_question, history
        self.info_received = fields
        text = "카드 기반 INFO 스트리밍 답변입니다."
        midpoint = max(1, len(text) // 2)
        yield text[:midpoint]
        yield text[midpoint:]

    async def generate_compare_summary(self, comparison: ComparisonResult, *, history=None):
        self.compare_received = comparison
        self.history_received = history
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
        recommendations=[_item(explanations=[f"{pid} 근거"], warnings=[]) for pid in place_ids],
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

    @pytest.mark.asyncio
    async def test_streams_general_answer_chunks_when_callback_is_provided(self) -> None:
        llm_output = LLMOutput(
            intent=Intent.GENERAL,
            status=OutputStatus.COMPLETE,
            general=GeneralPayload(
                topic=GeneralTopic.PLACE_KNOWLEDGE, original_question="경복궁 역사"
            ),
        )
        received: list[str] = []

        async def on_delta(text: str) -> None:
            received.append(text)

        message = await compose_chat_message(llm_output, llm=_StubLLM(), on_message_delta=on_delta)

        assert len(received) == 2
        assert message == "".join(received)

    @pytest.mark.asyncio
    async def test_passes_offer_content_when_situation_has_an_actionable_offer(self) -> None:
        """대화층 3단계 — situational_offers가 상황에 맞는 도움을 찾으면 그 content를
        답변 LLM 호출에 실어, 답변이 그 도움을 자연스러운 질문으로 제안하게 한다."""
        llm_output = LLMOutput(
            intent=Intent.GENERAL,
            status=OutputStatus.COMPLETE,
            general=GeneralPayload(
                topic=GeneralTopic.TRAVEL_TIP,
                original_question="너무 지친다",
                situation=SituationKind.FATIGUE,
            ),
        )
        stub = _StubLLM()

        await compose_chat_message(llm_output, llm=stub)

        assert stub.offer_content_received == "이동이 짧고 쉬기 편한 곳"

    @pytest.mark.asyncio
    async def test_omits_offer_content_for_vague_situation(self) -> None:
        """실행 가능한 제안이 없는 상황(vague)은 offer_content를 만들지 않는다."""
        llm_output = LLMOutput(
            intent=Intent.GENERAL,
            status=OutputStatus.COMPLETE,
            general=GeneralPayload(
                topic=GeneralTopic.TRAVEL_TIP,
                original_question="오늘 진짜 되는 일이 없네",
                situation=SituationKind.VAGUE,
            ),
        )
        stub = _StubLLM()

        await compose_chat_message(llm_output, llm=stub)

        assert stub.offer_content_received is None

    @pytest.mark.asyncio
    async def test_omits_offer_content_for_already_rejected_action(self) -> None:
        """이미 거절당한 제안은 같은 세션에서 답변 문구에도 다시 나오지 않는다."""
        llm_output = LLMOutput(
            intent=Intent.GENERAL,
            status=OutputStatus.COMPLETE,
            general=GeneralPayload(
                topic=GeneralTopic.TRAVEL_TIP,
                original_question="너무 지친다",
                situation=SituationKind.FATIGUE,
            ),
        )
        stub = _StubLLM()

        await compose_chat_message(
            llm_output, llm=stub, rejected_offer_actions=["recommend_nearby_rest_place"]
        )

        assert stub.offer_content_received is None


class TestComposeChatMessageRecommendAndModify:
    @pytest.mark.parametrize("intent", [Intent.RECOMMEND, Intent.MODIFY])
    @pytest.mark.asyncio
    async def test_uses_llm_summary_when_recommendations_present(
        self, intent: Intent
    ) -> None:
        llm_output = LLMOutput(intent=intent, status=OutputStatus.COMPLETE)
        stub = _StubLLM(recommendation_summary="테스트 장소를 중심으로 골라봤어요.")
        recommendations = _response(place_ids=["a", "b"])
        message = await compose_chat_message(
            llm_output, recommendations=recommendations, llm=stub
        )
        assert message == "테스트 장소를 중심으로 골라봤어요."
        assert stub.summary_received == (intent, recommendations)

    @pytest.mark.asyncio
    async def test_falls_back_to_template_when_recommendation_summary_llm_fails(self) -> None:
        llm_output = LLMOutput(intent=Intent.RECOMMEND, status=OutputStatus.COMPLETE)
        stub = _StubLLM(fail_recommendation_summary=True)
        message = await compose_chat_message(
            llm_output,
            recommendations=_response(place_ids=["a", "b"]),
            llm=stub,
        )
        assert message == "이런 곳들을 찾아봤어요:"
        assert stub.summary_received is not None

    @pytest.mark.asyncio
    async def test_streams_llm_summary_when_callback_is_provided(self) -> None:
        """SSE 경로에서는 추천 소개 문장이 청크 단위로 먼저 전달된다."""

        llm_output = LLMOutput(intent=Intent.RECOMMEND, status=OutputStatus.COMPLETE)
        received: list[str] = []

        async def on_delta(text: str) -> None:
            received.append(text)

        stub = _StubLLM(recommendation_summary="테스트 장소를 중심으로 골라봤어요.")
        message = await compose_chat_message(
            llm_output,
            recommendations=_response(place_ids=["a", "b"]),
            llm=stub,
            on_message_delta=on_delta,
        )

        assert len(received) == 2
        assert message == "".join(received)
        assert message == "테스트 장소를 중심으로 골라봤어요."
        assert stub.summary_received is not None

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
        message = await compose_chat_message(llm_output, tool_status="unsupported", llm=_StubLLM())
        assert message == "죄송하지만 아직 지원하지 않는 요청이에요."

    @pytest.mark.asyncio
    async def test_tool_stage_unsupported_region_names_the_service_area(self) -> None:
        """지원 지역 밖은 무엇이 문제인지 알려야 한다(D-044).

        "아직 지원하지 않는 요청"이라고만 하면 조건을 바꿔 다시 시도하게 된다. 다만
        구 목록 자체는 message 본문이 아니라 message_footnote가 담당한다(D-085) —
        본문에 그대로 이어붙이면 구가 늘 때마다 문장이 길어져서다. 여기서는 본문이
        짧게 고정됐는지만 보고, 목록은 unsupported_region_footnote()로 따로 검증한다.
        """
        llm_output = LLMOutput(intent=Intent.RECOMMEND, status=OutputStatus.COMPLETE)
        message = await compose_chat_message(
            llm_output,
            tool_status="unsupported",
            tool_error_code="unsupported_region",
            llm=_StubLLM(),
        )
        assert message == "이 위치는 지금 서비스 지역이 아니에요. 다른 위치를 말씀해 주세요."
        footnote = unsupported_region_footnote("unsupported_region")
        assert footnote is not None
        assert "종로구" in footnote and "성동구" in footnote

    def test_unsupported_region_footnote_is_none_for_other_codes(self) -> None:
        """다른 사유의 unsupported까지 구 목록을 붙이지 않는다."""
        assert unsupported_region_footnote(None) is None
        assert unsupported_region_footnote("some_other_error") is None

    @pytest.mark.asyncio
    async def test_tool_stage_unavailable(self) -> None:
        llm_output = LLMOutput(intent=Intent.RECOMMEND, status=OutputStatus.COMPLETE)
        message = await compose_chat_message(llm_output, tool_status="unavailable", llm=_StubLLM())
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
        message = await compose_compare_message(_comparison(), _StubLLM(fail_compare_summary=True))

        lines = message.splitlines()
        assert 3 <= len(lines) <= 6
        assert "국립현대미술관 서울" in message
        assert "도보 약 5분" in message
        assert "약 3시간 남음" in message
        assert "0.3km" not in message
        assert "180분" not in message
        assert "점수" not in message

    @pytest.mark.asyncio
    async def test_llm_failure_travel_time_fallback_prefers_measured_duration(self) -> None:
        """LLM 장애 시 fallback도 실측(travel_walking_minutes 등)을 우선 쓰고,
        같은 항목의 직선거리(distance_km)는 언급하지 않는다."""
        comparison = ComparisonResult(
            criteria=CompareCriteria.TRAVEL_TIME,
            items=[
                ComparisonItem(
                    place_id="p1",
                    place_name="국립현대미술관 서울",
                    rank=1,
                    distance_km=0.3,
                    travel_distance_km=2.1,
                    travel_walking_minutes=9,
                    travel_driving_minutes=4,
                ),
                ComparisonItem(
                    place_id="p2",
                    place_name="창덕궁",
                    rank=2,
                    distance_km=0.8,
                    travel_distance_km=4.5,
                    travel_walking_minutes=18,
                    travel_driving_minutes=10,
                ),
            ],
        )

        message = await compose_compare_message(comparison, _StubLLM(fail_compare_summary=True))

        assert "국립현대미술관 서울" in message
        assert "도보로 약 9분" in message
        assert "자동차로 약 4분" in message
        assert "0.3km" not in message
        assert "0.3" not in message


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
        elapsed_ms=100.0,
    )

    message = await compose_chat_message(llm_output, schedule=schedule, llm=_StubLLM())

    assert message == compose_schedule_message(schedule)
    assert "1시간 30분" in message
    assert "연남동 카페 A에서 시작해요." in message


@pytest.mark.asyncio
async def test_schedule_with_time_available_passes_through_to_message() -> None:
    """agent_runtime.py가 schedule_time_available_min을 넘기면 compose_schedule_message에
    그대로 전달돼 요청 시간 기준 문구가 나온다(오차 15분 이내인 케이스)."""
    llm_output = LLMOutput(intent=Intent.SCHEDULE, status=OutputStatus.COMPLETE)
    schedule = ScheduleResult(
        items=[_schedule_item()],
        total_duration_min=112,
        route_summary="경복궁 근처 코스예요.",
        basis_note="기준 시각 안내",
        elapsed_ms=100.0,
    )

    message = await compose_chat_message(
        llm_output,
        schedule=schedule,
        schedule_time_available_min=120,
        llm=_StubLLM(),
    )

    assert message == "2시간 코스를 짜봤어요. 경복궁 근처 코스예요."


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
            elapsed_ms=100.0,
        )

        message = compose_schedule_message(schedule)

        assert message == "2시간 5분 코스를 짜봤어요. 동선 요약입니다."

    def test_formats_minutes_only_when_under_an_hour(self) -> None:
        schedule = ScheduleResult(
            items=[_schedule_item()],
            total_duration_min=45,
            route_summary="짧은 코스예요.",
            basis_note="기준 시각 안내",
            elapsed_ms=100.0,
        )

        message = compose_schedule_message(schedule)

        assert message == "45분 코스를 짜봤어요. 짧은 코스예요."

    def test_uses_requested_time_when_close_to_actual(self) -> None:
        """실제 편성 시간(112분)이 요청 시간(120분)과 30분 이내로 가까우면
        어색한 "1시간 52분" 대신 요청한 "2시간"을 그대로 보여준다."""
        schedule = ScheduleResult(
            items=[_schedule_item()],
            total_duration_min=112,
            route_summary="동선 요약입니다.",
            basis_note="기준 시각 안내",
            elapsed_ms=100.0,
        )

        message = compose_schedule_message(schedule, time_available_min=120)

        assert message == "2시간 코스를 짜봤어요. 동선 요약입니다."

    def test_boundary_exactly_at_tolerance_uses_requested_time(self) -> None:
        schedule = ScheduleResult(
            items=[_schedule_item()],
            total_duration_min=90,
            route_summary="동선 요약입니다.",
            basis_note="기준 시각 안내",
            elapsed_ms=100.0,
        )

        message = compose_schedule_message(schedule, time_available_min=120)

        assert message == "2시간 코스를 짜봤어요. 동선 요약입니다."

    def test_uses_actual_duration_when_far_from_requested_time(self) -> None:
        """후보 부족 등으로 실제 편성이 요청과 크게 어긋나면(30분 초과 차이)
        요청 시간을 그대로 보여주지 않고 실제 계산값을 정직하게 보여준다."""
        schedule = ScheduleResult(
            items=[_schedule_item()],
            total_duration_min=60,
            route_summary="동선 요약입니다.",
            basis_note="기준 시각 안내",
            elapsed_ms=100.0,
        )

        message = compose_schedule_message(schedule, time_available_min=300)

        assert message == "1시간 코스를 짜봤어요. 동선 요약입니다."

    def test_no_time_available_falls_back_to_actual_duration(self) -> None:
        """time_available_min을 안 넘기면(사용자가 시간을 명시하지 않은 요청)
        기존과 동일하게 실제 계산값을 보여준다."""
        schedule = ScheduleResult(
            items=[_schedule_item()],
            total_duration_min=125,
            route_summary="동선 요약입니다.",
            basis_note="기준 시각 안내",
            elapsed_ms=100.0,
        )

        message = compose_schedule_message(schedule)

        assert message == "2시간 5분 코스를 짜봤어요. 동선 요약입니다."

    def test_empty_items_returns_route_summary_without_duration_prefix(self) -> None:
        """items가 비면(후보 부족 등) planner.py가 route_summary를 안내 문구로
        정규화해서 넘긴다 — 여기서는 "0분 코스를 짜봤어요" 같은 어색한 접두사 없이
        그 문구를 그대로 반환하기만 한다(SCHEDULE-06 후속 수정)."""
        schedule = ScheduleResult(
            items=[],
            total_duration_min=0,
            route_summary="조건에 맞는 곳을 충분히 찾지 못해 일정을 만들지 못했어요.",
            basis_note="기준 시각 안내",
            elapsed_ms=100.0,
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
        """ "혼잡도 데이터가 없다"고 하면 다른 날 다시 물어보게 된다(D-044).

        구 목록은 message 본문이 아니라 message_footnote가 담당한다(D-085) —
        unsupported_region_footnote()로 따로 검증한다.
        """
        response = InfoContextResponse(
            request_id="r5",
            status="unsupported",
            error=ContextError(
                code="unsupported_region",
                message="현재는 서울특별시 종로구·중구·용산구·성동구 안에서만 찾아드릴 수 있어요.",
                retryable=False,
            ),
        )
        message = compose_info_concentration_message(response)
        assert message == "이 위치는 지금 서비스 지역이 아니에요. 다른 위치를 말씀해 주세요."
        footnote = unsupported_region_footnote(response.error.code if response.error else None)
        assert footnote is not None
        assert "종로구" in footnote and "성동구" in footnote

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


class TestComposeRealtimePopulationMessage:
    def test_discloses_nearby_area_and_current_basis(self) -> None:
        response = InfoContextResponse(
            request_id="population-message",
            status="success",
            result=RealtimePopulationInfoResult(
                status="success",
                requested_place_name="경복궁",
                area_name="광화문·덕수궁",
                proxy_distance_km=0.4,
                current_congestion_level="보통",
                observed_at="2026-08-20 14:00",
            ),
        )

        message = compose_realtime_population_message(response)

        assert "경복궁 자체의 실시간 인구 데이터는 아니지만" in message
        assert "광화문·덕수궁" in message
        assert "현재 보통 수준" in message
        assert "12시간" in message

    def test_omits_self_referential_disclosure_when_area_equals_requested_place(self) -> None:
        """121곳 목록에 요청 장소 자체가 있으면(예: 경복궁) 대체가 아니다.

        "경복궁 자체의 데이터는 아니지만, 경복궁 기준으로는"처럼 스스로를 대체값
        이라 말하는 문장이 나오면 안 된다(TP-141/D-084 후속 발견).
        """

        response = InfoContextResponse(
            request_id="population-message-exact",
            status="success",
            result=RealtimePopulationInfoResult(
                status="success",
                requested_place_name="경복궁",
                resolved_place_name="경복궁",
                area_name="경복궁",
                proxy_distance_km=0.1,
                current_congestion_level="보통",
                observed_at="2026-08-20 14:00",
            ),
        )

        message = compose_realtime_population_message(response)

        assert "자체" not in message
        assert "아니지만" not in message
        assert "경복궁 기준으로는 현재 보통 수준" in message

    def test_treats_same_place_with_different_spacing_as_self_reference(self) -> None:
        """지오코딩 표기("여의도 한강공원")와 목록 표기("여의도한강공원")는 같은
        장소인데 공백만 다르다 — 실측으로 발견됨(TP-141/D-084 후속).
        """

        response = InfoContextResponse(
            request_id="population-message-spacing",
            status="success",
            result=RealtimePopulationInfoResult(
                status="success",
                requested_place_name="여의도 한강공원",
                resolved_place_name="여의도 한강공원",
                area_name="여의도한강공원",
                proxy_distance_km=0.7,
                current_congestion_level="보통",
                observed_at="2026-08-26 11:40",
            ),
        )

        message = compose_realtime_population_message(response)

        assert "자체" not in message
        assert "아니지만" not in message
        assert "여의도한강공원 기준으로는 현재 보통 수준" in message


class TestComposePlaceInfoMessage:
    """D-054 A 배선 — concentration/event를 제외한 6종 question_type."""

    @pytest.mark.asyncio
    async def test_streams_success_place_info_answer_when_callback_is_provided(self) -> None:
        response = InfoContextResponse(
            request_id="r8-stream",
            status="success",
            result=PlaceInfoResult(
                status="success",
                question_type="parking",
                requested_place_name="경복궁",
                resolved_place_name="경복궁",
                fields={"parking": "가능 (승용차 240대 / 버스 50대)"},
            ),
        )
        received: list[str] = []

        async def on_delta(text: str) -> None:
            received.append(text)

        stub = _StubLLM()
        message = await compose_chat_message(
            LLMOutput(intent=Intent.INFO, status=OutputStatus.COMPLETE),
            info_response=response,
            llm=stub,
            on_message_delta=on_delta,
        )

        assert len(received) == 2
        assert message == "".join(received)
        assert stub.info_received == {"parking": "가능 (승용차 240대)"}

    @pytest.mark.asyncio
    async def test_stream_timeout_falls_back_to_the_fixed_message_instead_of_dying(self) -> None:
        """답변 스트림이 타임아웃해도 C가 가져온 장소 정보를 버리지 않는다.

        여기까지 왔다는 것은 C 조회가 이미 성공했다는 뜻이다. 말풍선 문장 하나 때문에
        턴 전체를 실패시키면 그 정보가 통째로 사라지고 사용자는 오류만 본다 —
        2026-08-27에 실제로 그렇게 됐다. 타임아웃이 `AppError` 계열
        (`ProviderTimeoutError`)로 올라와야 이 폴백이 걸린다.
        """

        class _TimingOutLLM(_StubLLM):
            async def stream_info_answer(self, **kwargs: object):
                raise ProviderTimeoutError("Gemini")
                yield ""  # pragma: no cover - 제너레이터로 만들기 위한 선언

        response = InfoContextResponse(
            request_id="r8-timeout",
            status="success",
            result=PlaceInfoResult(
                status="success",
                question_type="parking",
                requested_place_name="경복궁",
                resolved_place_name="경복궁",
                fields={"parking": "가능 (승용차 240대)"},
            ),
        )
        received: list[str] = []

        async def on_delta(text: str) -> None:
            received.append(text)

        message = await compose_chat_message(
            LLMOutput(intent=Intent.INFO, status=OutputStatus.COMPLETE),
            info_response=response,
            llm=_TimingOutLLM(),
            on_message_delta=on_delta,
        )

        # 예외가 새지 않고, C가 확인한 사실(경복궁에 주차 가능)이 문장으로 남는다.
        # 상세 수치는 이 폴백에서 카드 쪽으로 넘긴다 — 그래서 "240대"는 없다.
        assert message == "경복궁 주차는 가능해요. 아래 주차 상세 내용을 확인해보세요."
        assert received == [message]

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
            "경복궁 운영시간을 확인했어요. 아래에서 월별 운영시간과 휴무일을 확인하세요."
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
            "경복궁 운영시간을 확인했어요. 아래에서 월별 운영시간과 휴무일을 확인하세요."
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
            "경복궁 입장료는 성인 기준 3,000원이에요. 아래에서 상세 요금 정보를 확인해보세요!"
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


class TestComposeRealtimeCommercialMessage:
    def _response(self, *, status: str = "success") -> InfoContextResponse:
        return InfoContextResponse(
            request_id="commercial",
            status=status,  # type: ignore[arg-type]
            result=(
                RealtimeCommercialInfoResult(
                    status=status,  # type: ignore[arg-type]
                    requested_place_name="테스트 카페",
                    resolved_place_name="테스트 카페",
                    area_name="용리단길",
                    proxy_distance_km=0.2,
                    category_label="음식·음료 · 커피·음료",
                    commercial_level="바쁜 시간대",
                    observed_at="2026-08-20 14:00",
                )
                if status != "unavailable"
                else None
            ),
        )

    def test_discloses_area_category_proxy_and_activity_basis(self) -> None:
        message = compose_realtime_commercial_message(self._response())

        assert "개별 매장 혼잡도는 확인할 수 없지만" in message
        assert "약 0.2km 떨어진 용리단길" in message
        assert "커피·음료" in message
        assert "바쁜 시간대" in message
        assert "카드 소비 활동" in message
        assert "8월 20일 14:00 기준" in message

    def test_unsupported_region_has_citydata_specific_message(self) -> None:
        response = InfoContextResponse(
            request_id="commercial-outside",
            status="unsupported",
            error=ContextError(
                code="realtime_commercial_unsupported_region",
                message="제공 지역 밖",
                retryable=False,
            ),
        )

        assert "서울시 주요 82개 지역" in compose_realtime_commercial_message(response)

    def test_area_overall_fallback_discloses_missing_cafe_category(self) -> None:
        response = self._response()
        assert isinstance(response.result, RealtimeCommercialInfoResult)
        response.result.category_label = None
        response.result.commercial_level = "한산한"
        response.result.commercial_scope = "area_overall"

        message = compose_realtime_commercial_message(response)

        assert "요청 업종 세부값도 현재 제공되지 않았어요" in message
        assert "용리단길 전체 상권은 현재 한산한" in message

    @pytest.mark.asyncio
    async def test_chat_composer_dispatches_realtime_commercial(self) -> None:
        message = await compose_chat_message(
            LLMOutput(intent=Intent.INFO, status=OutputStatus.COMPLETE),
            info_response=self._response(),
            llm=_StubLLM(),
        )

        assert "개별 매장 혼잡도" in message


class TestComposeRealtimeCityInfoMessage:
    def _traffic_response(
        self, *, fields: dict[str, str] | None = None, status: str = "success"
    ) -> InfoContextResponse:
        return InfoContextResponse(
            request_id="traffic",
            status=status,  # type: ignore[arg-type]
            result=RealtimeCityInfoResult(
                status=status,  # type: ignore[arg-type]
                question_type="realtime_traffic",
                requested_place_name="이촌한강공원",
                resolved_place_name="이촌한강공원",
                fields=fields
                if fields is not None
                else {"도로소통 단계": "원활", "평균 주행속도": "32km/h"},
            ),
        )

    def test_traffic_message_embeds_level_and_speed_directly(self) -> None:
        message = compose_realtime_city_info_message(self._traffic_response())

        assert message == "이촌한강공원 주변 도로는 지금 원활 수준이에요. 평균 주행속도 32km/h예요."

    def test_traffic_message_omits_speed_sentence_when_missing(self) -> None:
        message = compose_realtime_city_info_message(
            self._traffic_response(fields={"도로소통 단계": "정체"})
        )

        assert message == "이촌한강공원 주변 도로는 지금 정체 수준이에요."

    def test_traffic_message_reports_no_data(self) -> None:
        message = compose_realtime_city_info_message(
            self._traffic_response(fields={}, status="no_data")
        )

        assert "현재 확인할 수 없어요" in message

    def test_parking_message_stays_generic_card_pointer(self) -> None:
        response = InfoContextResponse(
            request_id="parking",
            status="success",
            result=RealtimeCityInfoResult(
                status="success",
                question_type="realtime_parking",
                requested_place_name="경복궁",
                resolved_place_name="경복궁",
                fields={"[공영] 테스트 주차장": "총 50면 · 현재 20대 주차 · 유료"},
            ),
        )

        message = compose_realtime_city_info_message(response)

        assert "실시간 주차장 정보를 찾았어요" in message


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
