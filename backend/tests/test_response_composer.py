"""compose_recommendation_message()/compose_chat_message() 단위 테스트."""

from __future__ import annotations

import pytest

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
from app.services.runtime.response_composer import (
    compose_chat_message,
    compose_recommendation_message,
)


class _StubLLM:
    """compose_chat_message()의 GENERAL 분기만 검증하기 위한 최소 테스트 더블."""

    def __init__(self, answer: str = "고정된 배경지식 답변입니다.") -> None:
        self.answer = answer
        self.received: tuple[GeneralTopic, str] | None = None

    async def generate_general_answer(self, topic: GeneralTopic, original_question: str):
        self.received = (topic, original_question)
        return provider_result(self.answer, source=ProviderSource.FAKE_LLM)


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
    async def test_wrapper_message_when_recommendations_present(self, intent: Intent) -> None:
        llm_output = LLMOutput(intent=intent, status=OutputStatus.COMPLETE)
        message = await compose_chat_message(
            llm_output, recommendations=_response(place_ids=["a", "b"]), llm=_StubLLM()
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
