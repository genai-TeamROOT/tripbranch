"""Agent Runtime(run_agent_flow)의 A→B→A→C→A→D→A→B 흐름 통합 테스트.

FakeLLMProvider/FakeWeatherProvider/FakeToolProvider/FakeRecommendationProvider와 B의
실제 apply()/get_session_context()를 조합해서 검증한다(팩토리는 거치지 않음 —
test_state_integration.py와 같은 스타일).
FakeToolProvider는 A-C Context Contract v0(docs/design/a-c-context-contract-draft.md)를
그대로 흉내 낸다 — C 단계 자체의 needs_clarification은 LLM 단계 needs_clarification과
별개 레이어라 따로 테스트한다.
"""

from __future__ import annotations

import pytest

from app.agent_context.schemas import AgentContextRequest, AgentContextResponse
from app.providers.stub import FakeLLMProvider, FakeWeatherProvider
from app.schemas import AgentRequest, OutputStatus
from app.services.runtime.agent_runtime import run_agent_flow
from app.services.runtime.stubs import FakeRecommendationProvider, FakeToolProvider
from app.state.service import get_session_context
from app.state.store import InMemoryStateStore

DEVICE_LOCATION = "37.5788,126.9770"


class _CountingToolProvider:
    """실제 FakeToolProvider를 감싸서 호출 횟수를 세고, 마지막 요청을 검사용으로 보관한다."""

    def __init__(self) -> None:
        self.call_count = 0
        self.last_request: AgentContextRequest | None = None
        self._inner = FakeToolProvider()

    async def fetch_context(self, request: AgentContextRequest) -> AgentContextResponse:
        self.call_count += 1
        self.last_request = request
        return await self._inner.fetch_context(request)


class _CountingRecommendationProvider:
    def __init__(self) -> None:
        self.call_count = 0
        self._inner = FakeRecommendationProvider()

    async def recommend(self, conditions, context, excluded_place_ids):
        self.call_count += 1
        return await self._inner.recommend(conditions, context, excluded_place_ids)


def _providers():
    return {
        "llm": FakeLLMProvider(),
        "weather_provider": FakeWeatherProvider(),
        "tool_provider": _CountingToolProvider(),
        "recommendation_provider": _CountingRecommendationProvider(),
    }


@pytest.mark.asyncio
async def test_recommend_flow_reaches_recommendations() -> None:
    store = InMemoryStateStore()
    providers = _providers()

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert response.llm_output.intent == "RECOMMEND"
    assert response.llm_output.status is OutputStatus.COMPLETE
    assert response.state.user_conditions.search_center == "경복궁"
    assert response.recommendations is not None
    assert len(response.recommendations.recommendations) > 0
    assert providers["tool_provider"].call_count == 1
    assert providers["recommendation_provider"].call_count == 1


@pytest.mark.asyncio
async def test_keep_flow_conditions_persist_and_reject_all_excludes_shown() -> None:
    """1턴 RECOMMEND → 2턴 REJECT_ALL: 조건은 KEEP, 1턴에서 노출된 장소는 제외된다."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘", session_id=None, device_location=DEVICE_LOCATION
        ),
        store=store,
        **providers,
    )
    session_id = first.state.session_id
    first_shown = {item.place_id for item in first.recommendations.recommendations}
    assert first_shown  # FakeRecommendationProvider가 뭔가는 반환했어야 한다

    second = await run_agent_flow(
        AgentRequest(
            user_input="다른 곳 보여줘", session_id=session_id, device_location=DEVICE_LOCATION
        ),
        store=store,
        **providers,
    )

    assert second.llm_output.intent == "MODIFY"
    assert second.llm_output.modify.modify_type == "REJECT_ALL"
    # KEEP: 조건은 1턴 값이 그대로 유지된다.
    assert second.state.user_conditions.search_center == "경복궁"
    # 1턴에서 노출된 장소가 제외 목록에 들어갔다.
    assert first_shown.issubset(set(second.state.excluded_place_ids))
    # FakeRecommendationProvider가 excluded_place_ids를 반영해 후보에서 뺐으므로
    # (C는 더 이상 필터링하지 않는다 — 계약 §2) 2턴 추천은 비어 있다.
    assert second.recommendations is not None
    second_shown = {item.place_id for item in second.recommendations.recommendations}
    assert not (second_shown & first_shown)


@pytest.mark.asyncio
async def test_modify_change_condition_flow_reaches_recommendations() -> None:
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘", session_id=None, device_location=DEVICE_LOCATION
        ),
        store=store,
        **providers,
    )
    session_id = first.state.session_id

    second = await run_agent_flow(
        AgentRequest(
            user_input="무료인 곳으로", session_id=session_id, device_location=DEVICE_LOCATION
        ),
        store=store,
        **providers,
    )

    assert second.llm_output.intent == "MODIFY"
    assert second.llm_output.modify.modify_type == "CHANGE_CONDITION"
    assert second.state.user_conditions.budget == "free"
    assert second.recommendations is not None


@pytest.mark.asyncio
async def test_needs_clarification_skips_tool_and_recommendation() -> None:
    """LLM 단계 needs_clarification(눈/weather_intent 모호) — C 호출 자체를 안 한다."""
    store = InMemoryStateStore()
    providers = _providers()

    response = await run_agent_flow(
        AgentRequest(
            user_input="눈 오는데 카페 추천해줘", session_id=None, device_location=DEVICE_LOCATION
        ),
        store=store,
        **providers,
    )

    assert response.llm_output.status is OutputStatus.NEEDS_CLARIFICATION
    assert response.recommendations is None
    assert providers["tool_provider"].call_count == 0
    assert providers["recommendation_provider"].call_count == 0
    # needs_clarification이어도 state는 채워진다(변화 없는 현재 상태).
    assert response.state.session_id


@pytest.mark.asyncio
async def test_tool_needs_clarification_skips_recommendation() -> None:
    """C 단계 자체의 needs_clarification(위치 정보 전무) — LLM 단계와 별개 레이어.

    "카페 추천해줘"는 장소명이 전혀 없어 LLM 단계는 COMPLETE로 끝나지만(current_location/
    search_center 둘 다 None), device_location(GPS)은 UserConditions.current_location이
    아니므로 C 계약상 needs_clarification 대상이다 — Tool은 호출되지만 Recommendation은
    호출되지 않아야 한다.
    """
    store = InMemoryStateStore()
    providers = _providers()

    response = await run_agent_flow(
        AgentRequest(user_input="카페 추천해줘", session_id=None, device_location=DEVICE_LOCATION),
        store=store,
        **providers,
    )

    assert response.llm_output.intent == "RECOMMEND"
    assert response.llm_output.status is OutputStatus.COMPLETE
    assert response.state.user_conditions.current_location is None
    assert response.state.user_conditions.search_center is None
    assert response.recommendations is None
    assert providers["tool_provider"].call_count == 1
    assert providers["recommendation_provider"].call_count == 0


@pytest.mark.asyncio
async def test_agent_context_request_weather_not_mixed_with_provider_weather() -> None:
    """conditions.weather(5단계 사용자-명시)와 api_weather(3단계 Provider-정규화)가
    섞이지 않는지 검증한다(A-C Context Contract v0 §5.2).

    FakeWeatherProvider는 기본값으로 3단계 "neutral"을 돌려준다. 사용자가 "비"를
    언급하면 5단계 UserConditions.weather는 "rain"이 돼야 하고, 이는 "neutral"과
    다른 값이므로 둘이 뒤섞였다면(예: api_weather를 그대로 conditions.weather에
    대입) 이 테스트가 실패한다.
    2턴으로 나눈 이유: 세션이 아직 없는 최초 턴에는 GPS를 심을 세션이 없어
    api_weather가 항상 None으로 남는 알려진 한계가 있다(session_orchestrator.py
    모듈 docstring 참고) — 2턴째부터 GPS·날씨가 실제로 채워진다.
    """
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘", session_id=None, device_location=DEVICE_LOCATION
        ),
        store=store,
        **providers,
    )
    session_id = first.state.session_id

    second = await run_agent_flow(
        AgentRequest(
            user_input="비 오는데 경복궁 근처 카페 추천해줘",
            session_id=session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    tool_provider = providers["tool_provider"]
    assert tool_provider.last_request is not None
    # C에 보낸 요청의 conditions.weather는 사용자가 말한 5단계 값이다.
    assert tool_provider.last_request.conditions.weather == "rain"
    # B에 저장된 api_context.api_weather는 Provider가 정규화한 3단계 값으로, 위 값과 다르다.
    assert second.state.api_context.api_weather == "neutral"
    assert second.state.user_conditions.weather == "rain"


@pytest.mark.parametrize(
    "user_input",
    ["경복궁 오늘 열어?", "경복궁은 언제 지어졌어?", "주식 추천해줘"],
    ids=["info", "general", "out_of_scope"],
)
@pytest.mark.asyncio
async def test_non_recommend_modify_intents_skip_tool_and_recommendation(user_input: str) -> None:
    store = InMemoryStateStore()
    providers = _providers()

    response = await run_agent_flow(
        AgentRequest(user_input=user_input, session_id=None, device_location=DEVICE_LOCATION),
        store=store,
        **providers,
    )

    assert response.llm_output.intent not in ("RECOMMEND", "MODIFY")
    assert response.recommendations is None
    assert providers["tool_provider"].call_count == 0
    assert providers["recommendation_provider"].call_count == 0


@pytest.mark.asyncio
async def test_first_turn_gps_seeded_survives_to_next_turn() -> None:
    """ensure_current_context()는 세션을 만들 수 없어 최초 턴에는 GPS를 못 심는다.

    apply()로 세션이 생긴 직후 run_agent_flow가 update_api_context를 호출해야
    다음 턴부터 gps_expired가 False가 된다(session_orchestrator.py의 "알려진 한계"
    후속 처리 — interpret.py의 동일 테스트를 run_agent_flow 기준으로도 고정한다).
    """
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘", session_id=None, device_location=DEVICE_LOCATION
        ),
        store=store,
        **providers,
    )
    assert first.state.api_context.gps_expired is True  # 최초 턴엔 아직 반영 전

    second = await run_agent_flow(
        AgentRequest(
            user_input="무료인 곳으로", session_id=first.state.session_id, device_location=None
        ),
        store=store,
        **providers,
    )

    assert second.state.api_context.gps_expired is False
    assert second.state.api_context.gps_location == DEVICE_LOCATION


@pytest.mark.asyncio
async def test_invalid_gps_format_skips_turn_without_error() -> None:
    """잘못된 GPS 문자열은 예외 없이 이번 턴만 건너뛴다."""
    store = InMemoryStateStore()
    providers = _providers()

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location="not-a-gps-string",
        ),
        store=store,
        **providers,
    )

    assert response.state.api_context.gps_location is None
    assert response.state.api_context.gps_expired is True


@pytest.mark.asyncio
async def test_record_recommendation_reflected_in_session_context() -> None:
    store = InMemoryStateStore()
    providers = _providers()

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘", session_id=None, device_location=DEVICE_LOCATION
        ),
        store=store,
        **providers,
    )

    context = get_session_context(response.state.session_id, store=store)
    shown_ids = {item.place_id for item in response.recommendations.recommendations}
    assert shown_ids
    assert set(context.shown_place_ids) == shown_ids
    assert context.has_recommendation is True
