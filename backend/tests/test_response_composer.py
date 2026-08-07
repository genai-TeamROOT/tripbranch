"""compose_recommendation_message()/compose_chat_message() 단위 테스트."""

from __future__ import annotations

import pytest

from app.agent_context.schemas import ContextError
from app.errors import ProviderUnavailableError
from app.providers.contracts import ProviderSource, provider_result
from app.schemas import (
    ClarificationPayload,
    GeneralPayload,
    GeneralTopic,
    Intent,
    LLMOutput,
    OutOfScopeCategory,
    OutOfScopePayload,
    OutputStatus,
    RecommendationItem,
    RecommendationResponse,
    Severity,
)
from app.services.runtime.context_schemas import Clarification
from app.services.runtime.info_context_schemas import ConcentrationInfoResult, InfoContextResponse
from app.services.runtime.response_composer import (
    compose_chat_message,
    compose_info_concentration_message,
    compose_recommendation_message,
)


class _StubLLM:
    """compose_chat_message()의 LLM 생성 분기를 검증하기 위한 최소 테스트 더블."""

    def __init__(
        self,
        answer: str = "고정된 배경지식 답변입니다.",
        recommendation_summary: str = "테스트 장소를 중심으로 골라봤어요.",
        fail_recommendation_summary: bool = False,
    ) -> None:
        self.answer = answer
        self.recommendation_summary = recommendation_summary
        self.fail_recommendation_summary = fail_recommendation_summary
        self.received: tuple[GeneralTopic, str] | None = None
        self.summary_received: tuple[Intent, RecommendationResponse] | None = None

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


class TestComposeChatMessageInfoCompare:
    @pytest.mark.parametrize("intent", [Intent.INFO, Intent.COMPARE])
    @pytest.mark.asyncio
    async def test_not_yet_supported_placeholder(self, intent: Intent) -> None:
        llm_output = LLMOutput(intent=intent, status=OutputStatus.COMPLETE)
        message = await compose_chat_message(llm_output, llm=_StubLLM())
        assert "준비 중" in message


@pytest.mark.asyncio
async def test_schedule_uses_dedicated_temporary_message() -> None:
    llm_output = LLMOutput(intent=Intent.SCHEDULE, status=OutputStatus.COMPLETE)

    message = await compose_chat_message(llm_output, llm=_StubLLM())

    assert message == "일정 추천 기능은 아직 준비 중이에요."


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
        message = await compose_chat_message(
            llm_output, info_concentration_response=response, llm=_StubLLM()
        )
        assert "한적함" in message

    @pytest.mark.asyncio
    async def test_info_without_concentration_response_falls_back_to_placeholder(self) -> None:
        llm_output = LLMOutput(intent=Intent.INFO, status=OutputStatus.COMPLETE)
        message = await compose_chat_message(llm_output, llm=_StubLLM())
        assert "준비 중" in message
