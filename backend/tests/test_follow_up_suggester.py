"""후속 질문 제안(`services/runtime/follow_up_suggester.py`) 단위 테스트.

버튼 문구는 누르는 순간 그대로 사용자 발화가 된다. 그래서 여기서 잠그는 것은 "LLM을
불렀다"가 아니라 **LLM이 준 것을 그대로 화면에 올리지 않는다**는 쪽이다 — 개수·길이
상한, 중복 제거, 실패 시 침묵이 전부 그 이야기다.
"""

from __future__ import annotations

import pytest

from app.errors import ProviderUnavailableError
from app.providers.contracts import ProviderSource, provider_result
from app.schemas import (
    AgentRequest,
    AgentResponse,
    ClarificationPayload,
    Intent,
    LLMOutput,
    OutOfScopeCategory,
    OutOfScopePayload,
    OutputStatus,
    RecommendationItem,
    RecommendationResponse,
    Severity,
)
from app.services.runtime.follow_up_suggester import (
    MAX_LABEL_LENGTH,
    MAX_SUGGESTIONS,
    suggest_follow_ups,
)
from app.state.schema import UserConditions as StateUserConditions
from app.state.service import ApiContextView, StateApplyResponse


class _RecordingLLM:
    """전달받은 인자를 그대로 보관하는 최소 LLM 대역."""

    def __init__(self, suggestions: list[str] | None = None) -> None:
        self.suggestions = suggestions if suggestions is not None else ["다른 곳도 보여줘"]
        self.calls: list[dict[str, object]] = []

    async def generate_follow_up_suggestions(self, **kwargs: object):
        self.calls.append(kwargs)
        return provider_result(self.suggestions, source=ProviderSource.FAKE_LLM)


class _FailingLLM:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def generate_follow_up_suggestions(self, **kwargs: object):
        raise self.error


def _item(place_id: str, name: str) -> RecommendationItem:
    return RecommendationItem(
        place_id=place_id,
        name=name,
        category="cafe",
        distance_km=0.3,
        remaining_minutes=120,
        environment_type="indoor",
        recommendation_reason="가까워요.",
        explanations=[],
        warnings=[],
        score=0.8,
        feature_scores={},
        weights_used={},
    )


def _response(
    *,
    intent: Intent = Intent.RECOMMEND,
    status: OutputStatus = OutputStatus.COMPLETE,
    message: str = "이런 곳들을 찾아봤어요:",
    recommendations: RecommendationResponse | None = None,
    llm_output: LLMOutput | None = None,
) -> AgentResponse:
    return AgentResponse(
        llm_output=llm_output or LLMOutput(intent=intent, status=status),
        state=StateApplyResponse(
            session_id="sess_follow_up",
            run_id="run_follow_up",
            session_created=True,
            user_conditions=StateUserConditions(),
            api_context=ApiContextView(),
            condition_version=1,
            condition_changed=False,
        ),
        recommendations=recommendations,
        message=message,
    )


def _request(user_input: str = "경복궁 근처 카페 추천해줘") -> AgentRequest:
    return AgentRequest(user_input=user_input, session_id="sess_follow_up")


@pytest.mark.asyncio
async def test_suggestions_pass_through_when_they_are_already_clean() -> None:
    llm = _RecordingLLM(["여기 주차되나요?", "이 근처 카페도 알려줘"])

    suggestions = await suggest_follow_ups(_request(), _response(), llm=llm)  # type: ignore[arg-type]

    assert suggestions == ["여기 주차되나요?", "이 근처 카페도 알려줘"]


@pytest.mark.asyncio
async def test_more_suggestions_than_the_cap_are_cut_instead_of_failing_the_turn() -> None:
    """상한 초과는 오류가 아니다 — 답변은 이미 확정됐으니 잘라 쓴다."""
    llm = _RecordingLLM([f"제안 {index}" for index in range(MAX_SUGGESTIONS + 3)])

    suggestions = await suggest_follow_ups(_request(), _response(), llm=llm)  # type: ignore[arg-type]

    assert len(suggestions) == MAX_SUGGESTIONS


@pytest.mark.asyncio
async def test_labels_longer_than_a_button_are_dropped() -> None:
    """버튼 한 칸에 안 들어가는 문구는 화면에서 두 줄로 접힌다."""
    too_long = "가" * (MAX_LABEL_LENGTH + 1)
    llm = _RecordingLLM([too_long, "짧은 제안"])

    suggestions = await suggest_follow_ups(_request(), _response(), llm=llm)  # type: ignore[arg-type]

    assert suggestions == ["짧은 제안"]


@pytest.mark.asyncio
async def test_duplicates_and_the_question_just_asked_are_removed() -> None:
    llm = _RecordingLLM(["다른 곳도 보여줘", "다른 곳도 보여줘", "경복궁 근처 카페 추천해줘"])

    suggestions = await suggest_follow_ups(_request(), _response(), llm=llm)  # type: ignore[arg-type]

    assert suggestions == ["다른 곳도 보여줘"]


@pytest.mark.asyncio
async def test_clarification_turn_gets_no_suggestions() -> None:
    """되묻기 턴에는 이미 그 턴의 선택지 버튼이 붙는다(clarification-options.md)."""
    llm = _RecordingLLM()
    response = _response(
        llm_output=LLMOutput(
            intent=Intent.RECOMMEND,
            status=OutputStatus.NEEDS_CLARIFICATION,
            clarification=ClarificationPayload(message="어디 근처에서 찾을까요?"),
        ),
        message="어디 근처에서 찾을까요?",
    )

    suggestions = await suggest_follow_ups(_request(), response, llm=llm)  # type: ignore[arg-type]

    assert suggestions == []
    assert llm.calls == []


@pytest.mark.asyncio
async def test_out_of_scope_turn_gets_no_suggestions() -> None:
    llm = _RecordingLLM()
    response = _response(
        llm_output=LLMOutput(
            intent=Intent.OUT_OF_SCOPE,
            status=OutputStatus.COMPLETE,
            out_of_scope=OutOfScopePayload(
                category=OutOfScopeCategory.UNRELATED, severity=Severity.LOW
            ),
        ),
        message="여행 관련 질문만 도와드릴 수 있어요.",
    )

    suggestions = await suggest_follow_ups(_request(), response, llm=llm)  # type: ignore[arg-type]

    assert suggestions == []
    assert llm.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [ProviderUnavailableError("Gemini"), RuntimeError("예상 못 한 오류")]
)
async def test_provider_failure_is_silent(error: Exception) -> None:
    """버튼을 못 만든 것 때문에 이미 완성된 답변을 실패시키지 않는다."""

    suggestions = await suggest_follow_ups(
        _request(), _response(), llm=_FailingLLM(error)  # type: ignore[arg-type]
    )

    assert suggestions == []


@pytest.mark.asyncio
async def test_shown_place_names_reach_the_model() -> None:
    """**LLM이 실제로 읽는 값을 채우는지 본다.**

    RECOMMEND 성공 경로의 말풍선은 카드 위 고정 문구라 장소 이름이 한 글자도 없다.
    이름을 안 넘기면 호출은 성공하는데 나오는 제안은 "다른 곳 보여줘" 수준으로만
    남는다 — 통과하지만 아무것도 검증하지 못하는 상태가 된다.
    """
    llm = _RecordingLLM()
    response = _response(
        recommendations=RecommendationResponse(
            recommendations=[_item("place-1", "블루보틀 삼청"), _item("place-2", "커피한약방")],
            unverified_recommendations=[_item("place-3", "테라로사 광화문")],
            elapsed_ms=10,
        )
    )

    await suggest_follow_ups(_request(), response, llm=llm)  # type: ignore[arg-type]

    assert llm.calls[0]["place_names"] == ["블루보틀 삼청", "커피한약방", "테라로사 광화문"]
    assert llm.calls[0]["intent"] is Intent.RECOMMEND
    assert llm.calls[0]["user_input"] == "경복궁 근처 카페 추천해줘"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("이 근처 카페도 추천해줘?", "이 근처 카페도 추천해줘"),
        ("이 장소들로 일정 짜줘?", "이 장소들로 일정 짜줘"),
        ("운영시간 알려줘 ?", "운영시간 알려줘"),
        # 진짜 의문문은 그대로 둔다 — 물음표가 있어야 맞는 문장이다.
        ("여기 주차되나요?", "여기 주차되나요?"),
        ("거기까지 얼마나 걸려?", "거기까지 얼마나 걸려?"),
    ],
)
async def test_question_mark_is_dropped_only_from_commands(given: str, expected: str) -> None:
    """후속 '질문'이라고 전부 의문문은 아니다.

    "-줘"는 시키는 말이라 물음표가 붙으면 어색하다. 반대로 "주차되나요?"에서 물음표를
    떼면 그쪽이 틀린 문장이 되므로, 어미로 가를 수 있는 경우에만 손댄다.
    """
    llm = _RecordingLLM([given])

    suggestions = await suggest_follow_ups(_request(), _response(), llm=llm)  # type: ignore[arg-type]

    assert suggestions == [expected]
