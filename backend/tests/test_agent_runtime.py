"""Agent Runtime(run_agent_flow)의 A→B→A→C→A→D→A→B 흐름 통합 테스트.

FakeLLMProvider/FakeToolProvider/FakeRecommendationProvider와 B의
실제 apply()/get_session_context()를 조합해서 검증한다(팩토리는 거치지 않음 —
test_state_integration.py와 같은 스타일).
FakeToolProvider는 A-C Context Contract v0(docs/design/a-c-context-contract-draft.md)를
그대로 흉내 낸다 — C 단계 자체의 needs_clarification은 LLM 단계 needs_clarification과
별개 레이어라 따로 테스트한다.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest

from app.agent_context.enrichment_schemas import (
    CandidateEnrichmentRequest,
    CandidateEnrichmentResponse,
)
from app.agent_context.schemas import (
    AgentContextRequest,
    AgentContextResponse,
    Clarification,
    ContextError,
    ContextValue,
    Coordinates,
    PlaceCandidate,
    ProviderMetadata,
    RecommendationContext,
    ResolvedLocation,
    ResponseMetadata,
    WeatherForecast,
)
from app.auth.principal import Principal
from app.config import settings
from app.domain.scoring import SCORING_VERSION
from app.domain.travel_route import TravelMode, TravelRoute
from app.prompts.registry import turn_prompt_version
from app.providers.contracts import ProviderSource, provider_result
from app.providers.driving_route import FakeDrivingRouteProvider
from app.providers.kakao_transit_route import FakeTransitRouteProvider
from app.providers.stub import FakeLLMProvider
from app.providers.walking_route import FakeWalkingRouteProvider
from app.schemas import (
    AgentRequest,
    CompareCriteria,
    ComparisonItem,
    ComparisonResult,
    ConcentrationIntent,
    Intent,
    IntentClassificationResult,
    OutputStatus,
    RecommendationItem,
    RecommendationResponse,
    RecommendPayload,
    Transport,
    TravelOrigin,
    UserConditions,
)
from app.service_area import supported_district_label
from app.services.runtime import agent_runtime as agent_runtime_module
from app.services.runtime.agent_runtime import (
    _WIDEN_RADIUS_MAX_TRAVEL_TIME,
    _apply_concentration_rerank,
    _fetch_compare_travel_routes,
    run_agent_flow,
    summarize_turn,
)
from app.services.runtime.compare_context_schemas import (
    CompareContextRequest,
    CompareContextResponse,
)
from app.services.runtime.info_context_schemas import InfoContextRequest, InfoContextResponse
from app.services.runtime.real_recommendation_provider import RealRecommendationProvider
from app.services.runtime.stubs import (
    FakeEnrichmentProvider,
    FakeRecommendationProvider,
    FakeToolProvider,
)
from app.state.schema import now_kst
from app.state.service import (
    SetPendingClarificationRequest,
    get_session_context,
    set_pending_clarification,
)
from app.state.store import InMemoryStateStore
from app.tools.contracts import ToolStatus
from app.tools.travel_route import (
    TravelRouteProviders,
    TravelRouteTool,
    TravelRouteToolResult,
)

DEVICE_LOCATION = "37.5788,126.9770"


class _LLMProviderWithGeneralAnswer(FakeLLMProvider):
    """FakeLLMProvider + generate_general_answer()만 로컬로 보강한 테스트 전용 더블.

    app/providers/stub.py의 FakeLLMProvider는 건드리지 않는다(Fake 유지보수는
    이번 작업 범위 밖) — compose_chat_message()의 GENERAL 분기만 테스트하기 위한
    최소 보강이다.
    """

    async def generate_general_answer(self, topic, original_question):
        return provider_result("(테스트용 고정 답변)", source=ProviderSource.FAKE_LLM)


class _LLMProviderForcingCompareWithFewShown(_LLMProviderWithGeneralAnswer):
    """FakeLLMProvider는 shown_place_count>=2일 때만 COMPARE를 낸다(실제 규칙과 일치).

    thinking 예산에 따라 Real Gemini가 이 전제조건을 무시하고 COMPARE로 분류하는
    불안정성(케이스 3, 2026-08-11 68건 테스트 결과)을 재현하려고, 트리거 문구
    "억지비교"에 한해 그 가드만 우회한다 — 나머지 발화는 평소 Fake 규칙 그대로다.
    """

    async def classify_intent(self, user_input, **kwargs):
        if "억지비교" in user_input:
            return provider_result(
                IntentClassificationResult(intent=Intent.COMPARE),
                source=ProviderSource.FAKE_LLM,
            )
        return await super().classify_intent(user_input, **kwargs)


class _CountingToolProvider:
    """실제 FakeToolProvider를 감싸서 호출 횟수를 세고, 마지막 요청을 검사용으로 보관한다."""

    def __init__(self) -> None:
        self.call_count = 0
        self.last_request: AgentContextRequest | None = None
        self.info_call_count = 0
        self.last_info_request: InfoContextRequest | None = None
        self.compare_call_count = 0
        self.last_compare_request: CompareContextRequest | None = None
        self._inner = FakeToolProvider()

    async def fetch_context(self, request: AgentContextRequest) -> AgentContextResponse:
        self.call_count += 1
        self.last_request = request
        return await self._inner.fetch_context(request)

    async def fetch_info_context(self, request: InfoContextRequest) -> InfoContextResponse:
        self.info_call_count += 1
        self.last_info_request = request
        return await self._inner.fetch_info_context(request)

    async def fetch_compare_context(self, request: CompareContextRequest) -> CompareContextResponse:
        self.compare_call_count += 1
        self.last_compare_request = request
        return await self._inner.fetch_compare_context(request)


class _CountingRecommendationProvider:
    """rerank_with_concentration()을 일부러 갖지 않는다 — Real D가 아직 2차
    Scoring을 구현하지 않은 상태를 재현한다(hasattr 가드 확인용, 기본 fixture)."""

    def __init__(self) -> None:
        self.call_count = 0
        self.last_limit: int | None = None
        self._inner = FakeRecommendationProvider()

    async def recommend(
        self, conditions, context, excluded_place_ids, limit=5, ignore_operating_hours=False
    ):
        self.call_count += 1
        self.last_limit = limit
        return await self._inner.recommend(
            conditions, context, excluded_place_ids, limit, ignore_operating_hours
        )


class _CountingRecommendationProviderWithRerank(_CountingRecommendationProvider):
    """rerank_with_concentration()을 갖춘 버전 — D가 2차 Scoring을 구현한 상태를
    재현한다."""

    def __init__(self) -> None:
        super().__init__()
        self.rerank_call_count = 0

    async def rerank_with_concentration(
        self,
        conditions: UserConditions,
        context: RecommendationContext,
        first_pass: RecommendationResponse,
        concentration: CandidateEnrichmentResponse,
    ) -> RecommendationResponse:
        self.rerank_call_count += 1
        return await self._inner.rerank_with_concentration(
            conditions, context, first_pass, concentration
        )


class _CountingEnrichmentProvider:
    """실제 FakeEnrichmentProvider를 감싸서 호출 횟수를 세고, 마지막 요청을 보관한다."""

    def __init__(self) -> None:
        self.call_count = 0
        self.last_request: CandidateEnrichmentRequest | None = None
        self._inner = FakeEnrichmentProvider()

    async def enrich(self, request: CandidateEnrichmentRequest) -> CandidateEnrichmentResponse:
        self.call_count += 1
        self.last_request = request
        return await self._inner.enrich(request)


def _providers():
    return {
        "llm": _LLMProviderWithGeneralAnswer(),
        "tool_provider": _CountingToolProvider(),
        "recommendation_provider": _CountingRecommendationProvider(),
        "enrichment_provider": _CountingEnrichmentProvider(),
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
    assert providers["tool_provider"].last_request.gps_location == Coordinates(
        latitude=37.5788, longitude=126.9770
    )


@pytest.mark.asyncio
async def test_recommend_stream_starts_template_before_showing_cards() -> None:
    """SSE 추천은 LLM 요약 없이 템플릿 답변 시작 후 카드를 같은 시점에 노출한다."""

    store = InMemoryStateStore()
    providers = _providers()
    events: list[tuple[str, dict[str, object]]] = []

    async def sink(event: str, payload: dict[str, object]) -> None:
        events.append((event, payload))

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        stream_event_sink=sink,
        stream_recommendation_summary=True,
        **providers,
    )

    names = [event for event, _ in events]
    assert names[:4] == ["progress", "progress", "progress", "progress"]
    assert names.index("message_start") < names.index("message_delta") < names.index("result")
    assert [payload["stage"] for event, payload in events if event == "progress"] == [
        "interpreting",
        "merging_conditions",
        "fetching_context",
        "scoring",
        "composing_message",
    ]
    assert (
        "".join(payload["text"] for event, payload in events if event == "message_delta")
        == response.message
    )


@pytest.mark.asyncio
async def test_general_stream_opens_message_before_text_deltas() -> None:
    """GENERAL은 카드가 없으므로 message_start가 움직이는 로딩 말풍선을 연다."""

    store = InMemoryStateStore()
    providers = _providers()
    events: list[tuple[str, dict[str, object]]] = []

    async def sink(event: str, payload: dict[str, object]) -> None:
        events.append((event, payload))

    response = await run_agent_flow(
        AgentRequest(user_input="트리비는 뭐 할 수 있어?", session_id=None),
        store=store,
        stream_event_sink=sink,
        stream_recommendation_summary=True,
        **providers,
    )

    names = [event for event, _ in events]
    assert response.llm_output.intent is Intent.GENERAL
    assert names.index("message_start") < names.index("message_delta")
    assert [payload["stage"] for event, payload in events if event == "progress"][-1] == (
        "composing_message"
    )
    streamed_message = "".join(
        payload["text"] for event, payload in events if event == "message_delta"
    )
    assert streamed_message == response.message


@pytest.mark.asyncio
async def test_recommend_flow_records_traces_for_llm_tool_and_scoring() -> None:
    """B-07: LLM/Tool/Scoring 3단계가 같은 run_id로 기록되는지 확인한다."""
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

    traces = store.get_traces(response.state.session_id)
    steps = [trace.step for trace in traces]
    assert steps == ["llm_interpret", "tool_fetch", "scoring"]
    assert all(trace.run_id == response.state.run_id for trace in traces)
    assert all(trace.latency_ms is not None and trace.latency_ms >= 0 for trace in traces)

    by_step = {trace.step: trace for trace in traces}
    assert by_step["llm_interpret"].prompt_version == turn_prompt_version(Intent.RECOMMEND)
    assert by_step["llm_interpret"].scoring_version is None
    assert by_step["tool_fetch"].prompt_version is None
    assert by_step["tool_fetch"].scoring_version is None
    assert by_step["scoring"].prompt_version is None
    assert by_step["scoring"].scoring_version == SCORING_VERSION


@pytest.mark.asyncio
async def test_needs_clarification_records_only_llm_trace() -> None:
    """LLM이 되물으면 Tool/Scoring은 호출 자체가 안 되니 trace도 llm_interpret만 남는다."""
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
    traces = store.get_traces(response.state.session_id)
    assert [trace.step for trace in traces] == ["llm_interpret"]


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
async def test_location_only_turn_after_recommend_is_modify_and_keeps_prior_conditions() -> None:
    """TP-67: 이전 추천 뒤 위치만 바꾸는 발화는 soft reset 없이 기존 조건을 유지한다."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="비 오는데 경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert first.state.user_conditions.weather == "rain"
    assert first.state.user_conditions.weather_intent == "AVOID"
    assert first.state.user_conditions.environment == "indoor"

    second = await run_agent_flow(
        AgentRequest(
            user_input="광화문 근처에서",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert second.llm_output.intent == "MODIFY"
    assert second.state.user_conditions.search_center == "광화문"
    assert second.state.user_conditions.weather == "rain"
    assert second.state.user_conditions.weather_intent == "AVOID"
    assert second.state.user_conditions.environment == "indoor"


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

    (2026-08-12, PR 2/A2) location_required는 이제 종로구 대표 스팟 되묻기 버튼을
    붙인다(docs/design/clarification-options.md 7절) — agent_runtime이 llm_output을
    NEEDS_CLARIFICATION + options로 덮어써서 프론트가 버튼을 렌더링할 수 있게 한다.
    """
    store = InMemoryStateStore()
    providers = _providers()

    response = await run_agent_flow(
        AgentRequest(user_input="카페 추천해줘", session_id=None, device_location=DEVICE_LOCATION),
        store=store,
        **providers,
    )

    assert response.llm_output.intent == "RECOMMEND"
    assert response.llm_output.status is OutputStatus.NEEDS_CLARIFICATION
    assert response.state.user_conditions.current_location is None
    assert response.state.user_conditions.search_center is None
    assert response.recommendations is None
    assert providers["tool_provider"].call_count == 1
    assert providers["recommendation_provider"].call_count == 0

    clarification = response.llm_output.clarification
    assert clarification is not None
    assert clarification.message == (
        "어디 근처에서 찾아드릴까요? 현재 위치나 원하시는 지역을 알려주세요."
    )
    option_ids = {option.id for option in clarification.options}
    assert option_ids == {"경복궁", "인사동", "광화문", "북촌"}
    assert all(option.resolved_intent == "RECOMMEND" for option in clarification.options)

    context = get_session_context(response.state.session_id, store=store)
    assert context.pending_clarification == "location_required"


@pytest.mark.asyncio
async def test_agent_context_request_weather_not_mixed_with_provider_weather() -> None:
    """conditions.weather(5단계 사용자-명시)가 api_weather(B의 옛 3단계 Provider
    필드)와 섞이지 않는지 검증한다(A-C Context Contract v0 §5.2).

    사용자가 "비"를 언급하면 5단계 UserConditions.weather는 "rain"이 돼야 한다.
    (2026-08-05, D-038) api_weather를 채우던 session_orchestrator.py의 날씨 조회
    경로는 제거했다 — 이 값을 읽는 소비자가 없어서다(decision-log.md D-038).
    그래서 api_weather는 이제 영구히 None이다 — 이 테스트는 "혹시 conditions.weather
    계산에 api_weather 같은 다른 소스가 섞여 들어가지 않는지"를 여전히 지킨다.

    (2026-08-06, D-053 후속) 2턴째는 이제 MODIFY 경로를 탄다 — 이전 추천이 있는 상태의
    "지명 + 근처 + 다른 조건" 발화를 Fake도 실 Gemini처럼 MODIFY로 분류하게 맞췄기
    때문이다. 같은 검증의 RECOMMEND 경로 판은
    `test_agent_recommend_path_weather_not_mixed_with_provider_weather`가 맡는다.
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
    assert second.llm_output.intent == "MODIFY"
    # C에 보낸 요청의 conditions.weather는 사용자가 말한 5단계 값이다.
    assert tool_provider.last_request.conditions.weather == "rain"
    # api_weather는 더 이상 채워지지 않는다(제거됨) — conditions.weather와 섞이지 않는다.
    assert second.state.api_context.api_weather is None
    assert second.state.user_conditions.weather == "rain"


@pytest.mark.asyncio
async def test_agent_recommend_path_weather_not_mixed_with_provider_weather() -> None:
    """위 테스트의 RECOMMEND 경로 판.

    이전 추천이 없으면 같은 발화가 RECOMMEND로 분류된다(D-053에서 맞춘 Fake 분류의
    반대 방향 회귀). 이 경로에서도 conditions.weather는 사용자가 말한 값이어야 하고
    api_weather가 섞여 들어오지 않아야 한다.
    """
    store = InMemoryStateStore()
    providers = _providers()

    response = await run_agent_flow(
        AgentRequest(
            user_input="비 오는데 경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    tool_provider = providers["tool_provider"]
    assert response.llm_output.intent == "RECOMMEND"
    assert tool_provider.last_request is not None
    assert tool_provider.last_request.conditions.weather == "rain"
    assert response.state.api_context.api_weather is None
    assert response.state.user_conditions.weather == "rain"


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
async def test_schedule_intent_reaches_planner_and_returns_schedule() -> None:
    """SCHEDULE-04: 조건 추출 → C/D 호출(D는 limit=10) → 일정 편성 모듈까지 실제로
    이어진다(docs/design/int-07-schedule.md 4절)."""
    store = InMemoryStateStore()
    providers = _providers()
    events: list[tuple[str, dict[str, object]]] = []

    async def sink(event: str, payload: dict[str, object]) -> None:
        events.append((event, payload))

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처에서 반나절 코스 짜줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        stream_event_sink=sink,
        **providers,
    )

    assert response.llm_output.intent == "SCHEDULE"
    assert response.llm_output.status is OutputStatus.COMPLETE
    assert response.state.user_conditions.search_center == "경복궁"

    assert providers["tool_provider"].call_count == 1
    assert providers["recommendation_provider"].call_count == 1
    assert providers["recommendation_provider"].last_limit == 10

    assert response.recommendations is None
    assert response.schedule is not None
    assert 1 <= len(response.schedule.items) <= 5
    assert response.schedule.basis_note
    assert "코스를 짜봤어요" in response.message

    progress_stages = [payload["stage"] for event, payload in events if event == "progress"]
    assert "scheduling" in progress_stages
    assert progress_stages.index("scoring") < progress_stages.index("scheduling")
    assert progress_stages.index("scheduling") < progress_stages.index("composing_message")

    context = get_session_context(response.state.session_id, store=store)
    schedule_ids = {item.place_id for item in response.schedule.items}
    assert schedule_ids
    assert set(context.shown_place_ids) == schedule_ids


@pytest.mark.asyncio
async def test_schedule_then_reject_all_modify_reroutes_to_new_schedule() -> None:
    """SCHEDULE-06: SCHEDULE 다음 턴 "다른 곳 보여줘"는 classify_intent()에서
    여전히 MODIFY로 분류되지만(docs/design/int-07-schedule.md 3.1절), 직전
    턴이 SCHEDULE로 완료됐다면 agent_runtime이 B의 last_intent를 보고 일정
    재편성으로 재라우팅한다. classify_intent/extract_modify_conditions는
    수정하지 않았다 — REJECT_ALL로 직전 일정 장소가 rejected에 들어가 새
    일정에서 자동 제외되는지까지 함께 확인한다."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처에서 반나절 코스 짜줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert first.llm_output.intent == "SCHEDULE"
    first_ids = {item.place_id for item in first.schedule.items}
    assert first_ids

    second = await run_agent_flow(
        AgentRequest(
            user_input="다른 곳 보여줘",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    # A가 실제로 분류했을 raw intent는 MODIFY다 — agent_runtime이 결과 라벨만
    # SCHEDULE로 바꿔치기했다는 걸 응답으로 간접 확인한다(recommendations가
    # 아니라 schedule이 채워짐).
    assert second.llm_output.intent == "SCHEDULE"
    assert second.recommendations is None
    assert second.schedule is not None
    second_ids = {item.place_id for item in second.schedule.items}
    assert second_ids
    assert second_ids.isdisjoint(first_ids)

    context = get_session_context(second.state.session_id, store=store)
    assert set(context.shown_place_ids) == second_ids


@pytest.mark.asyncio
async def test_schedule_then_change_condition_modify_merges_before_rerouting() -> None:
    """SCHEDULE-06 PR 리뷰에서 A가 요청한 시나리오: REJECT_ALL이 아니라
    CHANGE_CONDITION("실내 위주로 바꿔줘")도 조건이 먼저 B에 병합된 뒤에만
    일정 재편성으로 재라우팅돼야 한다 — llm_output.intent를 조건 병합 전에
    SCHEDULE로 바꿔치기하면 modify.condition_changes(environment=INDOOR)가
    반영되지 않을 수 있다는 우려였다. agent_runtime.py의 override는 이미
    apply()/transform() 뒤에 위치해 이 순서를 지키고 있음을 확인한다."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처에서 반나절 코스 짜줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert first.llm_output.intent == "SCHEDULE"

    second = await run_agent_flow(
        AgentRequest(
            user_input="실내로 바꿔줘",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    # raw 분류는 MODIFY(CHANGE_CONDITION)였다는 걸 간접 확인 — REJECT_ALL과
    # 달리 이번엔 이전 일정 장소를 배제하는 게 아니라 조건만 바뀐다.
    assert second.llm_output.intent == "SCHEDULE"
    assert second.schedule is not None
    # 조건 병합이 relabel보다 먼저 일어났다는 증거: 병합된 State에 반영됨
    assert second.state.user_conditions.environment == "indoor"


@pytest.mark.asyncio
async def test_schedule_then_ambiguous_recommend_triggers_clarification() -> None:
    """docs/design/clarification-options.md 5절(PR 1, 케이스 1): SCHEDULE 완료 직후
    "카페 추천해줘"류는 classify_intent()에서 MODIFY(CHANGE_CONDITION)로 나오지만
    "일정 재조정"인지 "그냥 추천"인지 글자로 구분이 안 된다 — SCHEDULE로 강제
    라벨링하지 않고 되묻기 버튼 2개로 끝나야 한다."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처에서 반나절 코스 짜줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert first.llm_output.intent == "SCHEDULE"

    second = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert second.llm_output.status == OutputStatus.NEEDS_CLARIFICATION
    assert second.recommendations is None
    assert second.schedule is None
    assert second.llm_output.clarification is not None
    clarification = second.llm_output.clarification
    option_ids = {option.id for option in clarification.options}
    assert option_ids == {"schedule_continue", "recommend_only"}

    # 이번 턴에서 추출된 카테고리(카페)가 범용 "장소" 대신 문구/버튼에 그대로 들어간다.
    assert clarification.message == "이어서 일정을 다시 짜드릴까요, 아니면 카페만 추천해드릴까요?"
    recommend_only = next(o for o in clarification.options if o.id == "recommend_only")
    assert recommend_only.label == "카페만 추천받기"

    context = get_session_context(second.state.session_id, store=store)
    assert context.pending_clarification == "schedule06_ambiguous_recommend"


@pytest.mark.asyncio
async def test_schedule_then_ambiguous_recommend_without_category_uses_generic_label() -> None:
    """카테고리를 언급하지 않은 모호 발화("경복궁 근처 알려줘")는 추출된 카테고리가
    없으므로 범용 "장소만 추천받기" 문구로 폴백해야 한다."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처에서 반나절 코스 짜줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert first.llm_output.intent == "SCHEDULE"

    second = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 알려줘",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert second.llm_output.status == OutputStatus.NEEDS_CLARIFICATION
    clarification = second.llm_output.clarification
    assert clarification is not None
    assert clarification.message == "이어서 일정을 다시 짜드릴까요, 아니면 장소만 추천해드릴까요?"
    recommend_only = next(o for o in clarification.options if o.id == "recommend_only")
    assert recommend_only.label == "장소만 추천받기"


@pytest.mark.asyncio
async def test_clarification_choice_location_quick_pick_resolves_to_recommend() -> None:
    """docs/design/clarification-options.md 7절(PR 2, A2): location_required 되묻기
    버튼("경복궁 근처") 클릭 시 classify_intent() 재호출 없이 원래 intent(RECOMMEND)로
    바로 해소되고, 고른 지명이 search_center에 반영돼야 한다."""
    store = InMemoryStateStore()
    providers = _providers()

    ambiguous = await run_agent_flow(
        AgentRequest(
            user_input="카페 추천해줘", session_id=None, device_location=DEVICE_LOCATION
        ),
        store=store,
        **providers,
    )
    assert ambiguous.llm_output.status == OutputStatus.NEEDS_CLARIFICATION

    resolved = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처",
            session_id=ambiguous.state.session_id,
            device_location=DEVICE_LOCATION,
            clarification_choice="경복궁",
        ),
        store=store,
        **providers,
    )

    assert resolved.llm_output.intent == "RECOMMEND"
    assert resolved.llm_output.status == OutputStatus.COMPLETE
    assert resolved.recommendations is not None
    assert resolved.state.user_conditions.search_center == "경복궁"
    context = get_session_context(resolved.state.session_id, store=store)
    assert context.pending_clarification is None


@pytest.mark.asyncio
async def test_clarification_choice_location_quick_pick_resolves_to_schedule() -> None:
    """location_required 되묻기가 SCHEDULE 턴에서 발생한 경우, 버튼 클릭이
    last_intent(SCHEDULE)를 복원해 일정 편성까지 이어져야 한다."""
    store = InMemoryStateStore()
    providers = _providers()

    ambiguous = await run_agent_flow(
        AgentRequest(
            user_input="반나절 코스 짜줘", session_id=None, device_location=DEVICE_LOCATION
        ),
        store=store,
        **providers,
    )
    assert ambiguous.llm_output.intent == "SCHEDULE"
    assert ambiguous.llm_output.status == OutputStatus.NEEDS_CLARIFICATION

    resolved = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처",
            session_id=ambiguous.state.session_id,
            device_location=DEVICE_LOCATION,
            clarification_choice="경복궁",
        ),
        store=store,
        **providers,
    )

    assert resolved.llm_output.intent == "SCHEDULE"
    assert resolved.llm_output.status == OutputStatus.COMPLETE
    assert resolved.schedule is not None
    assert resolved.state.user_conditions.search_center == "경복궁"


@pytest.mark.asyncio
async def test_stale_location_clarification_choice_falls_back_to_normal_classification() -> None:
    """세션에 location_required 되묻기가 없는 상태에서 온 clarification_choice는
    죽지 않고 평소 build_interpretation() 경로로 폴백해야 한다."""
    store = InMemoryStateStore()
    providers = _providers()

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
            clarification_choice="경복궁",  # 이 세션엔 되묻기가 없었다
        ),
        store=store,
        **providers,
    )

    assert response.llm_output.status == OutputStatus.COMPLETE
    assert response.llm_output.intent == "RECOMMEND"
    assert response.recommendations is not None


@pytest.mark.asyncio
async def test_travel_origin_override_resolves_without_classification() -> None:
    """"OO 기준으로 다시 보기" 버튼(travel_origin_override, D-071)은
    classify_intent()를 건너뛰고 직전 조건에 travel_origin만 덮어써 재실행해야
    한다. 이를 증명하기 위해 이번 턴 user_input에 OUT_OF_SCOPE 마커("주식")를
    넣는다 — classify_intent()가 실제로 호출됐다면 OUT_OF_SCOPE로 분류될
    문장인데, 그대로 RECOMMEND/COMPLETE로 나오면 건너뛴 것이 증명된다."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert first.llm_output.status == OutputStatus.COMPLETE
    assert first.recommendations is not None

    resolved = await run_agent_flow(
        AgentRequest(
            user_input="주식 얘기처럼 보이지만 버튼 클릭이라 실제로는 해석되지 않는다",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
            travel_origin_override=TravelOrigin.SEARCH_CENTER,
        ),
        store=store,
        **providers,
    )

    assert resolved.llm_output.intent == "RECOMMEND"
    assert resolved.llm_output.status == OutputStatus.COMPLETE
    assert resolved.recommendations is not None
    assert resolved.state.user_conditions.search_center == "경복궁"
    assert resolved.state.user_conditions.travel_origin == "search_center"


@pytest.mark.asyncio
async def test_travel_origin_override_falls_back_without_prior_recommendation() -> None:
    """추천 결과가 아직 없는 세션에서 온 override는 평소 경로로 폴백해야 한다."""
    store = InMemoryStateStore()
    providers = _providers()

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
            travel_origin_override=TravelOrigin.SEARCH_CENTER,  # 이 세션엔 아직 추천이 없다
        ),
        store=store,
        **providers,
    )

    assert response.llm_output.status == OutputStatus.COMPLETE
    assert response.llm_output.intent == "RECOMMEND"
    assert response.recommendations is not None


@pytest.mark.asyncio
async def test_schedule_bare_restart_during_location_ask_triggers_clarification() -> None:
    """docs/design/clarification-options.md 케이스 4(PR 4): SCHEDULE이 위치를 못
    찾아 되묻는 중(location_required) 목적어 없는 "처음부터 다시"는 classify_intent()
    호출 없이 결정적으로 되물어야 한다."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="카페 위주로 일정 짜줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert first.llm_output.intent == "SCHEDULE"
    assert first.llm_output.status == OutputStatus.NEEDS_CLARIFICATION
    context = get_session_context(first.state.session_id, store=store)
    assert context.pending_clarification == "location_required"

    second = await run_agent_flow(
        AgentRequest(
            user_input="처음부터 다시",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert second.llm_output.intent == "SCHEDULE"
    assert second.llm_output.status == OutputStatus.NEEDS_CLARIFICATION
    clarification = second.llm_output.clarification
    assert clarification is not None
    option_ids = {option.id for option in clarification.options}
    assert option_ids == {"restart", "keep_asking"}
    context = get_session_context(second.state.session_id, store=store)
    assert context.pending_clarification == "schedule_bare_restart"


@pytest.mark.asyncio
async def test_clarification_choice_schedule_restart_wipes_conditions() -> None:
    """"네, 처음부터 다시 잡을게요" 클릭은 조건을 비우고 다시 location_required로
    이어져야 한다(PR 2의 종로구 대표 스팟 버튼으로 자연스럽게 연결)."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="카페 위주로 일정 짜줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert "카페" in first.state.user_conditions.place_tags
    await run_agent_flow(
        AgentRequest(
            user_input="처음부터 다시",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    resolved = await run_agent_flow(
        AgentRequest(
            user_input="네, 처음부터 다시 잡을게요",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
            clarification_choice="restart",
        ),
        store=store,
        **providers,
    )

    assert resolved.llm_output.intent == "SCHEDULE"
    assert resolved.llm_output.status == OutputStatus.NEEDS_CLARIFICATION
    assert resolved.state.user_conditions.place_tags == []
    context = get_session_context(resolved.state.session_id, store=store)
    assert context.pending_clarification == "location_required"


@pytest.mark.asyncio
async def test_clarification_choice_schedule_keep_asking_preserves_conditions() -> None:
    """"아니요, 위치만 알려드릴게요" 클릭은 조건을 그대로 두고 같은
    location_required를 다시 띄워야 한다."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="카페 위주로 일정 짜줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    await run_agent_flow(
        AgentRequest(
            user_input="처음부터 다시",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    resolved = await run_agent_flow(
        AgentRequest(
            user_input="아니요, 위치만 알려드릴게요",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
            clarification_choice="keep_asking",
        ),
        store=store,
        **providers,
    )

    assert resolved.llm_output.intent == "SCHEDULE"
    assert resolved.llm_output.status == OutputStatus.NEEDS_CLARIFICATION
    assert "카페" in resolved.state.user_conditions.place_tags
    context = get_session_context(resolved.state.session_id, store=store)
    assert context.pending_clarification == "location_required"


@pytest.mark.asyncio
async def test_bare_restart_during_active_recommend_triggers_clarification() -> None:
    """docs/design/clarification-options.md 케이스 5(PR 4): 되묻기 중이 아닌 활성
    RECOMMEND 흐름에서 목적어 없는 "처음부터 다시"는 결정적으로 되물어야 한다."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert first.llm_output.intent == "RECOMMEND"
    assert first.recommendations is not None

    second = await run_agent_flow(
        AgentRequest(
            user_input="처음부터 다시",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert second.llm_output.status == OutputStatus.NEEDS_CLARIFICATION
    clarification = second.llm_output.clarification
    assert clarification is not None
    # 장소(경복궁 근처) + 카테고리(카페) 둘 다 채워졌으므로 우선순위 규칙대로 둘 다
    # 들어간다(장소 → 날씨 → 카테고리, 최대 2개).
    assert clarification.message == (
        "경복궁 근처 카페로 다시 알아볼까요, 아니면 새로운 목적지로 찾아볼까요?"
    )
    option_ids = {option.id for option in clarification.options}
    assert option_ids == {"keep_context", "full_reset"}
    context = get_session_context(second.state.session_id, store=store)
    assert context.pending_clarification == "bare_restart_active"


@pytest.mark.asyncio
async def test_clarification_choice_keep_context_resolves_to_modify_reject_all() -> None:
    """"경복궁 근처로 다시 찾아주세요" 클릭은 조건은 유지한 채 REJECT_ALL로
    재조회해야 한다."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    await run_agent_flow(
        AgentRequest(
            user_input="처음부터 다시",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    resolved = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처로 다시 찾아주세요",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
            clarification_choice="keep_context",
        ),
        store=store,
        **providers,
    )

    assert resolved.llm_output.intent == "MODIFY"
    assert resolved.llm_output.status == OutputStatus.COMPLETE
    assert resolved.recommendations is not None
    assert resolved.state.user_conditions.search_center == "경복궁"


@pytest.mark.asyncio
async def test_clarification_choice_full_reset_wipes_conditions_without_auto_searching() -> None:
    """"새로 시작할게요" 클릭은 조건을 전부 비우되, Tool을 바로 부르지 않고 새
    목적지/조건을 직접 말해달라는 터미널 문구로 끝나야 한다.

    (2026-08-13 실사용 재현) 예전엔 조건을 비운 뒤 그대로 Tool까지 이어져서,
    GPS만 있으면 그걸로 조용히 추천이 나가버렸다("현재 계신 곳에서 가까운
    두가헌 레스토랑을...") — "새로 시작"이라는 사용자 의도(새 조건을 직접
    말하고 싶다)와 어긋난다."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    await run_agent_flow(
        AgentRequest(
            user_input="처음부터 다시",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    tool_calls_before_resolution = providers["tool_provider"].call_count
    resolved = await run_agent_flow(
        AgentRequest(
            user_input="새로 시작할게요",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
            clarification_choice="full_reset",
        ),
        store=store,
        **providers,
    )

    assert resolved.llm_output.intent == "RECOMMEND"
    assert resolved.llm_output.status == OutputStatus.COMPLETE
    assert resolved.recommendations is None
    assert resolved.schedule is None
    assert resolved.message == "새로운 목적지를 입력하거나 원하시는 조건을 알려주세요!"
    assert resolved.state.user_conditions.search_center is None
    assert resolved.state.user_conditions.place_tags == []
    # 이 해소 턴에서는 Tool이 추가로 불리지 않아야 한다 — GPS만으로 조용히
    # 추천이 나가는 걸 막는 게 이번 수정의 핵심이다.
    assert providers["tool_provider"].call_count == tool_calls_before_resolution
    context = get_session_context(resolved.state.session_id, store=store)
    assert context.pending_clarification is None


@pytest.mark.asyncio
async def test_bare_restart_after_schedule_completed_triggers_clarification() -> None:
    """실사용 재현(2026-08-13): SCHEDULE이 되묻기 없이 성공적으로 완료된 뒤 목적어
    없는 "처음부터 다시"는 케이스 4/5 어디에도 안 걸려서 SCHEDULE-06이 무조건 같은
    조건으로 재편성을 시도했고, 후보가 부족하면 "일정을 만들지 못했어요" 실패
    문구로 샜다. SCHEDULE 전용 되묻기로 잡아야 한다."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처에서 반나절 코스 짜줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert first.llm_output.intent == "SCHEDULE"
    assert first.llm_output.status == OutputStatus.COMPLETE

    second = await run_agent_flow(
        AgentRequest(
            user_input="처음부터 다시",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert second.llm_output.intent == "SCHEDULE"
    assert second.llm_output.status == OutputStatus.NEEDS_CLARIFICATION
    clarification = second.llm_output.clarification
    assert clarification is not None
    option_ids = {option.id for option in clarification.options}
    assert option_ids == {"retry_schedule", "full_reset"}
    context = get_session_context(second.state.session_id, store=store)
    assert context.pending_clarification == "schedule_bare_restart_completed"


@pytest.mark.asyncio
async def test_clarification_choice_retry_schedule_keeps_conditions_and_replans() -> None:
    """"{조건}로 다시 짜주세요" 클릭은 같은 조건으로 SCHEDULE 재편성해야 한다
    (REJECT_ALL이 아니다 — MODIFY 결과 모양은 SCHEDULE에 안 맞는다)."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처에서 반나절 코스 짜줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    await run_agent_flow(
        AgentRequest(
            user_input="처음부터 다시",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    resolved = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처로 다시 짜주세요",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
            clarification_choice="retry_schedule",
        ),
        store=store,
        **providers,
    )

    assert resolved.llm_output.intent == "SCHEDULE"
    assert resolved.llm_output.status == OutputStatus.COMPLETE
    assert resolved.schedule is not None
    assert resolved.state.user_conditions.search_center == "경복궁"


@pytest.mark.asyncio
async def test_clarification_choice_schedule_full_reset_wipes_conditions() -> None:
    """SCHEDULE 완료 후 되묻기의 "새로 시작할게요"는 RECOMMEND로 전환하고 조건을
    비운다 — 케이스 5의 full_reset과 동일하게 Tool 호출 없이 터미널 문구로 끝난다."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처에서 반나절 코스 짜줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    await run_agent_flow(
        AgentRequest(
            user_input="처음부터 다시",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    resolved = await run_agent_flow(
        AgentRequest(
            user_input="새로 시작할게요",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
            clarification_choice="full_reset",
        ),
        store=store,
        **providers,
    )

    assert resolved.llm_output.intent == "RECOMMEND"
    assert resolved.llm_output.status == OutputStatus.COMPLETE
    assert resolved.recommendations is None
    assert resolved.schedule is None
    assert resolved.message == "새로운 목적지를 입력하거나 원하시는 조건을 알려주세요!"
    assert resolved.state.user_conditions.search_center is None


@pytest.mark.asyncio
async def test_clarification_choice_schedule_continue_resolves_to_schedule() -> None:
    """되묻기 버튼 "일정 다시 짜기" 클릭 시 classify_intent() 재호출 없이 바로
    SCHEDULE로 해소돼야 한다(docs/design/clarification-options.md 3절)."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처에서 반나절 코스 짜줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    ambiguous = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert ambiguous.llm_output.status == OutputStatus.NEEDS_CLARIFICATION

    resolved = await run_agent_flow(
        AgentRequest(
            user_input="일정 다시 짜기",
            session_id=ambiguous.state.session_id,
            device_location=DEVICE_LOCATION,
            clarification_choice="schedule_continue",
        ),
        store=store,
        **providers,
    )

    assert resolved.llm_output.intent == "SCHEDULE"
    assert resolved.llm_output.status == OutputStatus.COMPLETE
    assert resolved.schedule is not None
    assert resolved.recommendations is None
    # 되묻기 답변 턴을 소비했으므로 다음 턴 판단에 영향을 주지 않는다.
    context = get_session_context(resolved.state.session_id, store=store)
    assert context.pending_clarification is None


@pytest.mark.asyncio
async def test_clarification_choice_recommend_only_resolves_to_recommend() -> None:
    """되묻기 버튼 "장소만 추천받기" 클릭 시 RECOMMEND로 해소되고, 되묻기 턴에서
    이미 병합된 조건(search_center=경복궁, place_tags=카페)이 그대로 쓰인다."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처에서 반나절 코스 짜줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    ambiguous = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert ambiguous.state.user_conditions.search_center == "경복궁"

    resolved = await run_agent_flow(
        AgentRequest(
            user_input="장소만 추천받기",
            session_id=ambiguous.state.session_id,
            device_location=DEVICE_LOCATION,
            clarification_choice="recommend_only",
        ),
        store=store,
        **providers,
    )

    assert resolved.llm_output.intent == "RECOMMEND"
    assert resolved.llm_output.status == OutputStatus.COMPLETE
    assert resolved.schedule is None
    assert resolved.recommendations is not None
    assert resolved.state.user_conditions.search_center == "경복궁"


@pytest.mark.asyncio
async def test_stale_clarification_choice_falls_back_to_normal_classification() -> None:
    """세션에 남은 pending_clarification과 안 맞는(또는 없는) clarification_choice는
    죽지 않고 평소 build_interpretation() 경로로 폴백해야 한다 — 새로고침 후 오래된
    버튼 클릭 같은 상황을 흉내 낸다."""
    store = InMemoryStateStore()
    providers = _providers()

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
            clarification_choice="schedule_continue",  # 이 세션엔 되묻기가 없었다
        ),
        store=store,
        **providers,
    )

    assert response.llm_output.status == OutputStatus.COMPLETE
    assert response.llm_output.intent == "RECOMMEND"
    assert response.recommendations is not None


@pytest.mark.asyncio
async def test_schedule_then_reject_specific_modify_keeps_other_items() -> None:
    """SCHEDULE-09 2단계: "두 번째는 별로야"는 REJECT_ALL과 달리 지목한 자리만
    갈아끼운다. classify_intent()가 순번+거절 신호 조합을 MODIFY로 분류하고
    (D-059 갭 수정분), extract_modify_conditions()가 target_indices=[2]를
    뽑아내면, agent_runtime이 이전 shown_recommendations에서 1·3번은 그대로
    pinned_items로 옮기고 plan_partial_schedule()이 2번 자리만 D의 새 후보로
    채운다 — 통째로 새 일정을 짜는 REJECT_ALL 경로(위 테스트)와 대비된다."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처에서 반나절 코스 짜줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert first.llm_output.intent == "SCHEDULE"
    assert first.schedule is not None
    assert len(first.schedule.items) == 3
    first_by_order = {item.order: item.place_id for item in first.schedule.items}

    second = await run_agent_flow(
        AgentRequest(
            user_input="두 번째는 별로야",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    # raw 분류는 MODIFY(REJECT_SPECIFIC)였다는 걸 간접 확인 — relabel로
    # intent만 SCHEDULE로 바뀌었을 뿐, recommendations가 아니라 schedule이
    # 채워진다.
    assert second.llm_output.intent == "SCHEDULE"
    assert second.recommendations is None
    assert second.schedule is not None
    second_by_order = {item.order: item.place_id for item in second.schedule.items}
    assert set(second_by_order) == {1, 2, 3}

    # 1번·3번은 그대로 유지, 2번만 새 장소로 교체.
    assert second_by_order[1] == first_by_order[1]
    assert second_by_order[3] == first_by_order[3]
    assert second_by_order[2] != first_by_order[2]
    assert second_by_order[2] not in first_by_order.values()

    context = get_session_context(second.state.session_id, store=store)
    assert set(context.shown_place_ids) == set(second_by_order.values())

    # B의 rejected 이력에는 지목된 2번 장소만 들어가야 한다 — 1번·3번은
    # REJECT_ALL과 달리 거절 처리되지 않는다.
    history = store.get_history(second.state.session_id)
    assert history is not None
    rejected_ids = {item.place_id for item in history.rejected}
    assert rejected_ids == {first_by_order[2]}


@pytest.mark.asyncio
async def test_schedule_reject_specific_chains_across_consecutive_turns() -> None:
    """SCHEDULE-09 후속(D-061): REJECT_SPECIFIC 재조정이 연속으로 이어질 때도
    매번 부분 재편성이 걸려야 한다. apply()는 매 턴 relabel 이전의 원본
    intent(MODIFY)로 last_intent를 저장하는데, 3-3절 relabel 직후 그 값을
    다시 SCHEDULE로 맞춰주지 않으면(set_last_intent) 두 번째 REJECT_SPECIFIC
    턴이 직전 턴을 last_intent="MODIFY"로 보게 되어 재조정 감지 자체가
    실패한다 — 실사용 테스트에서 "두 번째는 별로야" 다음에 "세 번째 장소
    별로야"를 보내면 전체가 새로 짜이는 것으로 재현됐다."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처에서 반나절 코스 짜줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert first.llm_output.intent == "SCHEDULE"
    first_by_order = {item.order: item.place_id for item in first.schedule.items}

    second = await run_agent_flow(
        AgentRequest(
            user_input="두 번째는 별로야",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert second.llm_output.intent == "SCHEDULE"
    assert second.schedule is not None
    second_by_order = {item.order: item.place_id for item in second.schedule.items}
    assert second_by_order[1] == first_by_order[1]
    assert second_by_order[3] == first_by_order[3]

    # 두 번째 재조정 턴: 이번엔 3번을 지목한다. 직전 턴(SCHEDULE로 relabel된
    # MODIFY)이 last_intent="SCHEDULE"로 올바르게 저장돼 있어야 재조정
    # 감지가 걸린다 — 실패하면 intent가 MODIFY로 남고 recommendations가
    # 채워진다(위 다른 테스트들과 동일한 증거 패턴).
    third = await run_agent_flow(
        AgentRequest(
            user_input="세 번째 장소 별로야",
            session_id=second.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert third.llm_output.intent == "SCHEDULE"
    assert third.recommendations is None
    assert third.schedule is not None
    third_by_order = {item.order: item.place_id for item in third.schedule.items}
    assert set(third_by_order) == {1, 2, 3}

    # 1번(첫 턴부터 유지)·2번(직전 턴에서 새로 채워짐)은 그대로, 3번만 교체.
    assert third_by_order[1] == first_by_order[1]
    assert third_by_order[2] == second_by_order[2]
    assert third_by_order[3] != second_by_order[3]
    assert third_by_order[3] not in second_by_order.values()

    history = store.get_history(third.state.session_id)
    assert history is not None
    rejected_ids = {item.place_id for item in history.rejected}
    assert rejected_ids == {first_by_order[2], second_by_order[3]}


@pytest.mark.asyncio
async def test_schedule_then_reject_specific_exclusion_pattern_keeps_only_mentioned() -> None:
    """SCHEDULE-09 후속: "두 번째 말고는 다 마음에 안 들어"는 지목한 자리만
    직접 거부하는 것과 정반대다 — 2번만 남기고 1·3번을 새 장소로 채운다.
    표면상 REJECT_ALL 예문("다 마음에 안 들어")과 겹치지만, "말고는"으로
    특정 순번을 예외 처리했으므로 REJECT_SPECIFIC(여집합)이어야 한다."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처에서 반나절 코스 짜줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert first.llm_output.intent == "SCHEDULE"
    first_by_order = {item.order: item.place_id for item in first.schedule.items}

    second = await run_agent_flow(
        AgentRequest(
            user_input="두 번째 말고는 다 마음에 안 들어",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert second.llm_output.intent == "SCHEDULE"
    assert second.recommendations is None
    assert second.schedule is not None
    second_by_order = {item.order: item.place_id for item in second.schedule.items}
    assert set(second_by_order) == {1, 2, 3}

    # 2번만 유지, 1번·3번은 새 장소로 교체.
    assert second_by_order[2] == first_by_order[2]
    assert second_by_order[1] != first_by_order[1]
    assert second_by_order[3] != first_by_order[3]
    assert second_by_order[1] not in first_by_order.values()
    assert second_by_order[3] not in first_by_order.values()

    history = store.get_history(second.state.session_id)
    assert history is not None
    rejected_ids = {item.place_id for item in history.rejected}
    assert rejected_ids == {first_by_order[1], first_by_order[3]}


@pytest.mark.asyncio
async def test_schedule_then_reject_by_name_keeps_other_items() -> None:
    """SCHEDULE-09 후속(이름 지목): 순번이 아니라 장소 이름으로 "OO는 빼줘"라고
    해도 그 자리만 교체돼야 한다 — B가 이제 이름도 저장하므로(SCHEDULE-09 후속),
    agent_runtime이 InterpretRequest.shown_place_names로 이름 목록을 전달하고
    FakeLLMProvider가 이름→순번 매칭까지 해낸다."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처에서 반나절 코스 짜줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert first.llm_output.intent == "SCHEDULE"
    first_by_order = {item.order: item.place_id for item in first.schedule.items}
    target_name = first.schedule.items[1].place_name  # order=2

    second = await run_agent_flow(
        AgentRequest(
            user_input=f"{target_name}은 빼줘",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert second.llm_output.intent == "SCHEDULE"
    assert second.recommendations is None
    assert second.schedule is not None
    second_by_order = {item.order: item.place_id for item in second.schedule.items}

    # 1번·3번은 그대로, 이름으로 지목한 2번만 새 장소로 교체.
    assert second_by_order[1] == first_by_order[1]
    assert second_by_order[3] == first_by_order[3]
    assert second_by_order[2] != first_by_order[2]


@pytest.mark.asyncio
async def test_schedule_modify_reroute_skipped_when_pending_clarification() -> None:
    """SCHEDULE-06 안전장치: 직전 턴이 SCHEDULE였어도(last_intent="SCHEDULE")
    되묻기가 아직 안 끝났다면(pending_clarification이 남아있음) 재조정
    오버라이드가 걸리지 않는다 — 완료되지 않은 SCHEDULE을 재편성 대상으로
    오인하면 안 된다.

    develop 머지로 들어온 D-059(app/providers/stub.py의 FakeLLMProvider.
    classify_intent)는 last_intent="SCHEDULE" + pending_clarification 존재 시
    단순 후속 발화를 곧바로 SCHEDULE로 분류해 그 되묻기를 이어간다 — 이건 그
    자체로 올바른 동작이라 이 시나리오에서는 이 테스트가 검증하려는 override
    분기(llm_output.intent is Intent.MODIFY 조건)를 아예 타지 않는다. 그래서
    명시적 재시작 문구("처음부터 다시")로 D-059 분기를 우회하고 REJECT_ALL
    문구("다른 곳")로 MODIFY 분류를 유도해, override가 실제로 검사되는 경로를
    직접 태운다."""
    from app.state import session as session_module
    from app.state.history import record_recommended
    from app.state.schema import RecommendedItemInput

    store = InMemoryStateStore()
    providers = _providers()

    state, _ = session_module.get_or_create_session(store, None)
    state.last_intent = "SCHEDULE"
    state.pending_clarification = "ambiguous:weather_intent"
    store.save_state(state)
    record_recommended(
        store,
        state.session_id,
        "run_seed",
        [RecommendedItemInput(place_id="runtime-stub-museum-1", rank=1)],
    )

    response = await run_agent_flow(
        AgentRequest(
            user_input="처음부터 다시 다른 곳 보여줘",
            session_id=state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert response.llm_output.intent == "MODIFY"
    assert response.schedule is None


@pytest.mark.asyncio
async def test_schedule_continuation_during_pending_clarification_does_not_build_schedule() -> None:
    """D-059 분기(직전 SCHEDULE 되묻기 중 후속 발화를 SCHEDULE로 이어 분류)를 탄
    경우에도, 되묻기가 안 끝났으므로 실제 일정 편성은 이번 턴에 실행되지
    않는다 — intent 라벨과 무관하게 지켜져야 하는 안전 속성이다."""
    from app.state import session as session_module
    from app.state.history import record_recommended
    from app.state.schema import RecommendedItemInput

    store = InMemoryStateStore()
    providers = _providers()

    state, _ = session_module.get_or_create_session(store, None)
    state.last_intent = "SCHEDULE"
    state.pending_clarification = "ambiguous:weather_intent"
    store.save_state(state)
    record_recommended(
        store,
        state.session_id,
        "run_seed",
        [RecommendedItemInput(place_id="runtime-stub-museum-1", rank=1)],
    )

    response = await run_agent_flow(
        AgentRequest(
            user_input="다른 곳 보여줘",
            session_id=state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert response.llm_output.intent == "SCHEDULE"
    assert response.schedule is None


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
    assert providers["tool_provider"].last_request.gps_location == Coordinates(
        latitude=37.5788, longitude=126.9770
    )

    second = await run_agent_flow(
        AgentRequest(
            user_input="무료인 곳으로", session_id=first.state.session_id, device_location=None
        ),
        store=store,
        **providers,
    )

    assert second.state.api_context.gps_expired is False
    assert second.state.api_context.gps_location == DEVICE_LOCATION
    assert providers["tool_provider"].last_request.gps_location == Coordinates(
        latitude=37.5788, longitude=126.9770
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_gps", ["not-a-gps-string", "91.0,126.9770"])
async def test_invalid_gps_format_skips_turn_without_error(invalid_gps: str) -> None:
    """형식 또는 좌표 범위가 잘못된 GPS는 예외 없이 이번 턴만 건너뛴다."""
    store = InMemoryStateStore()
    providers = _providers()

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=invalid_gps,
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


@pytest.mark.asyncio
async def test_record_recommendation_carries_compare_feature_snapshot() -> None:
    """COMPARE 데이터 출처 A안(2026-08-11): agent_runtime이 record_recommendation을
    호출할 때 distance_km/remaining_minutes/environment_type을 함께 넘겨,
    B의 이력에 그대로 저장되는지 확인한다."""
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
    assert context.shown_recommendations
    by_id = {item.place_id: item for item in context.shown_recommendations}
    for item in response.recommendations.recommendations:
        stored = by_id[item.place_id]
        assert stored.distance_km == item.distance_km
        assert stored.remaining_minutes == item.remaining_minutes
        assert stored.environment_type == item.environment_type


@pytest.mark.asyncio
async def test_compare_flow_uses_last_recommendation_snapshots_and_returns_summary() -> None:
    """COMPARE는 새 후보 검색 없이 B의 마지막 추천 스냅샷만 C에 전달한다."""

    store = InMemoryStateStore()
    providers = _providers()
    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    compared = await run_agent_flow(
        AgentRequest(
            user_input="어디가 더 가까워?",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    tool_provider = providers["tool_provider"]
    assert compared.llm_output.intent == "COMPARE"
    assert compared.comparison is not None
    assert compared.comparison.criteria == "travel_time"
    assert tool_provider.call_count == 1  # 첫 RECOMMEND의 일반 Context 조회만 수행
    assert tool_provider.compare_call_count == 1
    assert tool_provider.last_compare_request is not None
    assert [item.rank for item in tool_provider.last_compare_request.candidates] == [1, 2, 3, 4, 5]
    assert "런타임 스텁" in compared.message
    assert compared.tool_execution is not None
    assert compared.tool_execution.operation == "compare_fetch"


def _providers_with_forced_compare():
    return {
        "llm": _LLMProviderForcingCompareWithFewShown(),
        "tool_provider": _CountingToolProvider(),
        "recommendation_provider": _CountingRecommendationProvider(),
        "enrichment_provider": _CountingEnrichmentProvider(),
    }


@pytest.mark.asyncio
async def test_compare_with_single_shown_triggers_clarification() -> None:
    """docs/design/clarification-options.md 케이스 3(PR 3): COMPARE 전제조건(노출
    2개 이상)을 위반한 채로 분류돼도(thinking 예산에 따라 실제로 발생, 2026-08-11
    68건 테스트) 그대로 비교를 시도하지 않고 되묻기 버튼 2개로 끝나야 한다."""
    store = InMemoryStateStore()
    providers = _providers_with_forced_compare()

    response = await run_agent_flow(
        AgentRequest(
            user_input="억지비교 어디가 좋아?",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert response.llm_output.intent == "COMPARE"
    assert response.llm_output.status == OutputStatus.NEEDS_CLARIFICATION
    assert response.comparison is None
    assert response.recommendations is None
    assert providers["tool_provider"].compare_call_count == 0

    clarification = response.llm_output.clarification
    assert clarification is not None
    assert clarification.message == "지금 보여드린 곳이 마음에 드시나요, 다른 곳도 보여드릴까요?"
    option_ids = {option.id for option in clarification.options}
    assert option_ids == {"keep_current", "show_more"}

    context = get_session_context(response.state.session_id, store=store)
    assert context.pending_clarification == "compare_single_shown"


@pytest.mark.asyncio
async def test_clarification_choice_compare_show_more_resolves_to_recommend() -> None:
    """"다른 곳도 보여주세요" 클릭은 REJECT_ALL로 재조회하는 기존 검증된 경로를
    그대로 탄다.

    검색 중심점이 있어야 REJECT_ALL 재조회가 location_required로 새지 않으므로,
    먼저 정상 RECOMMEND 턴으로 조건을 만든 뒤 compare_single_shown 되묻기 상태만
    직접 심는다(실제 COMPARE 오분류 재현은 위 detection 테스트가 이미 검증했다)."""
    store = InMemoryStateStore()
    providers = _providers_with_forced_compare()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    set_pending_clarification(
        SetPendingClarificationRequest(
            session_id=first.state.session_id, code="compare_single_shown"
        ),
        store=store,
    )

    resolved = await run_agent_flow(
        AgentRequest(
            user_input="다른 곳도 보여주세요",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
            clarification_choice="show_more",
        ),
        store=store,
        **providers,
    )

    assert resolved.llm_output.intent == "MODIFY"
    assert resolved.llm_output.status == OutputStatus.COMPLETE
    assert resolved.recommendations is not None
    context = get_session_context(resolved.state.session_id, store=store)
    assert context.pending_clarification is None


@pytest.mark.asyncio
async def test_clarification_choice_compare_keep_current_returns_canned_message() -> None:
    """"지금 장소가 마음에 들어요" 클릭은 조회할 것이 없으므로 Tool/LLM 호출 없이
    고정 문구로 바로 끝나야 한다."""
    store = InMemoryStateStore()
    providers = _providers_with_forced_compare()

    ambiguous = await run_agent_flow(
        AgentRequest(
            user_input="억지비교 어디가 좋아?",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert ambiguous.llm_output.status == OutputStatus.NEEDS_CLARIFICATION

    resolved = await run_agent_flow(
        AgentRequest(
            user_input="지금 장소가 마음에 들어요",
            session_id=ambiguous.state.session_id,
            device_location=DEVICE_LOCATION,
            clarification_choice="keep_current",
        ),
        store=store,
        **providers,
    )

    assert resolved.llm_output.intent == "GENERAL"
    assert resolved.llm_output.status == OutputStatus.COMPLETE
    assert resolved.message == "네, 좋은 여행 되세요!"
    assert resolved.recommendations is None
    assert providers["tool_provider"].call_count == 0
    assert providers["tool_provider"].compare_call_count == 0
    context = get_session_context(resolved.state.session_id, store=store)
    assert context.pending_clarification is None


@pytest.mark.asyncio
async def test_stale_compare_clarification_choice_falls_back_to_normal_classification() -> None:
    """세션에 compare_single_shown 되묻기가 없는 상태에서 온 clarification_choice는
    죽지 않고 평소 build_interpretation() 경로로 폴백해야 한다."""
    store = InMemoryStateStore()
    providers = _providers_with_forced_compare()

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
            clarification_choice="keep_current",  # 이 세션엔 되묻기가 없었다
        ),
        store=store,
        **providers,
    )

    assert response.llm_output.status == OutputStatus.COMPLETE
    assert response.llm_output.intent == "RECOMMEND"
    assert response.recommendations is not None


@pytest.mark.asyncio
async def test_second_turn_sends_consumed_place_ids_to_context_provider() -> None:
    """ "다른 곳 보여줘"의 2회차에는 1회차 노출분이 C 요청에 실려야 한다.

    D에만 넘기고 C에는 안 넘기면, C가 같은 앞쪽 후보를 다시 가져오고 D가 그걸
    전부 걸러내 추천이 0건이 된다. 계약 필드가 배선에서 빠지는 걸 여기서 잡는다.
    """
    store = InMemoryStateStore()
    providers = _providers()
    tool_provider = providers["tool_provider"]

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert tool_provider.last_request is not None
    assert tool_provider.last_request.excluded_place_ids == []
    shown_ids = {item.place_id for item in first.recommendations.recommendations}
    assert shown_ids

    await run_agent_flow(
        AgentRequest(
            user_input="다른 곳 보여줘",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert tool_provider.last_request is not None
    assert set(tool_provider.last_request.excluded_place_ids) == shown_ids


@pytest.mark.asyncio
async def test_info_concentration_flow_calls_tool_provider_once() -> None:
    """question_type=concentration만 C(fetch_info_context)를 거치고, D는 호출하지 않는다."""
    store = InMemoryStateStore()
    providers = _providers()

    response = await run_agent_flow(
        AgentRequest(
            user_input="창덕궁 사람 많아?",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert response.llm_output.intent == "INFO"
    assert response.llm_output.info.question_type == "concentration"
    assert response.recommendations is None
    assert providers["tool_provider"].info_call_count == 1
    assert providers["tool_provider"].call_count == 0  # fetch_context(RECOMMEND용)는 안 씀
    assert [execution.operation for execution in response.tool_executions] == ["info_concentration"]
    assert providers["recommendation_provider"].call_count == 0
    assert "창덕궁" in response.message
    assert "보통" in response.message  # FakeToolProvider 고정 데이터


class _ToolProviderWithoutInfoContext:
    """fetch_info_context()가 아직 없는 C Real 구현체를 흉내 낸다(과도기 상태)."""

    def __init__(self) -> None:
        self._inner = FakeToolProvider()

    async def fetch_context(self, request: AgentContextRequest) -> AgentContextResponse:
        return await self._inner.fetch_context(request)


@pytest.mark.asyncio
async def test_info_concentration_falls_back_gracefully_without_fetch_info_context() -> None:
    """C가 fetch_info_context()를 아직 구현하지 않아도 AttributeError로 죽지 않고
    기존 '준비 중' 문구로 안전하게 낮아진다(실제 ContextService로 재현된 회귀)."""
    store = InMemoryStateStore()
    providers = _providers()
    providers["tool_provider"] = _ToolProviderWithoutInfoContext()

    response = await run_agent_flow(
        AgentRequest(
            user_input="창덕궁 사람 많아?",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert response.llm_output.intent == "INFO"
    assert response.llm_output.info.question_type == "concentration"
    assert "준비 중" in response.message


@pytest.mark.asyncio
async def test_fake_tool_provider_proxy_fallback_discloses_source() -> None:
    """알려진 관광지가 아닌 장소는 FakeToolProvider의 근접치 fallback 시뮬레이션을 탄다.

    stub.py의 place-name 사전이 FakeToolProvider의 관광지 목록과 겹쳐서(둘 다
    같은 6개 이름), 전체 파이프라인으로는 이 케이스를 자연스럽게 재현할 수
    없다 — FakeToolProvider.fetch_info_context()를 직접 호출해 검증한다.
    """
    provider = FakeToolProvider()
    request = InfoContextRequest(
        request_id="r1", place_name="용리단길카페", place_context="explicit"
    )

    response = await provider.fetch_info_context(request)

    assert response.status == "success"
    assert response.result.is_proxy is True
    assert response.result.requested_place_name == "용리단길카페"
    assert response.result.resolved_place_name == "경복궁"


@pytest.mark.asyncio
async def test_info_operating_hours_question_type_calls_tool_provider() -> None:
    """D-054/D-059: concentration 외 question_type도 이제 C를 거쳐 실제 응답을 받는다."""
    store = InMemoryStateStore()
    providers = _providers()

    response = await run_agent_flow(
        AgentRequest(
            user_input="창덕궁 오늘 열어?",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert response.llm_output.intent == "INFO"
    assert response.llm_output.info.question_type == "operating_hours"
    assert providers["tool_provider"].info_call_count == 1
    assert "준비 중" not in response.message
    # 운영시간 원문은 말풍선이 아니라 아래 info_place_card가 싣는다.
    assert "운영시간을 확인했어요" in response.message
    assert response.info_place_card is not None
    assert response.info_place_card.answer_fields["operating_hours"] == "09:00~18:00"
    assert response.info_place_card.overview == "조선 왕조의 법궁으로 1395년에 창건된 궁궐이다."


@pytest.mark.asyncio
async def test_info_walking_time_uses_current_gps_and_route_tool() -> None:
    """INFO location_info도 현재 GPS가 있으면 카카오 도보 경로 계약을 재사용한다."""
    store = InMemoryStateStore()
    providers = _providers()

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 가는데 얼마나 걸려?",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        travel_route_tool=TravelRouteTool(
            {
                TravelMode.WALKING: TravelRouteProviders(
                    primary=FakeWalkingRouteProvider(walking_speed_mps=1.2)
                )
            }
        ),
        **providers,
    )

    assert response.llm_output.intent is Intent.INFO
    assert response.llm_output.info is not None
    assert response.llm_output.info.question_type.value == "location_info"
    assert "현재 위치에서 경복궁까지 도보 약" in response.message
    assert "이동 거리는 약" in response.message


@pytest.mark.asyncio
async def test_info_general_info_question_type_shows_overview_raw() -> None:
    """general_info는 LLM 요약 없이 overview 원문을 그대로 보여준다(사용자 결정)."""
    store = InMemoryStateStore()
    providers = _providers()

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 개요 알려줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert response.llm_output.intent == "INFO"
    assert response.llm_output.info.question_type == "general_info"
    assert providers["tool_provider"].info_call_count == 1
    assert "조선 왕조의 법궁" in response.message


@pytest.mark.asyncio
async def test_info_event_question_type_distinguishes_direct_and_nearby() -> None:
    """D-055: is_direct_match=False인 행사를 그 장소의 행사로 말하지 않는다."""
    store = InMemoryStateStore()
    providers = _providers()

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 행사 있어?",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert response.llm_output.intent == "INFO"
    assert response.llm_output.info.question_type == "event"
    assert providers["tool_provider"].info_call_count == 1
    assert "경복궁에서 진행 중인 행사예요. 경복궁 별빛야행" in response.message
    assert "경복궁 근처에서 진행 중인 행사예요. 종로구 전통문화행사" in response.message


def _place(place_id: str, *, latitude: float = 37.5, longitude: float = 127.0) -> PlaceCandidate:
    return PlaceCandidate(
        place_id=place_id,
        name=f"장소-{place_id}",
        category="cafe",
        location=Coordinates(latitude=latitude, longitude=longitude),
    )


def _item(place_id: str) -> RecommendationItem:
    return RecommendationItem(
        place_id=place_id,
        name=f"장소-{place_id}",
        category="cafe",
        distance_km=0.3,
        remaining_minutes=60,
        environment_type="indoor",
        recommendation_reason="테스트용",
        explanations=[],
        warnings=[],
        score=0.5,
        feature_scores={},
        weights_used={},
    )


class TestApplyConcentrationRerank:
    """_apply_concentration_rerank()를 run_agent_flow() 전체를 거치지 않고 직접
    단위 테스트한다 — B가 concentration_intent 필드를 아직 안 가지고 있어도
    (agent_conditions를 직접 만들어 주입하므로) 6-1 분기 로직 자체는 검증할 수 있다.
    """

    def _context(self, place_ids: list[str]) -> RecommendationContext:
        return RecommendationContext(
            places=ContextValue(status="success", data=[_place(pid) for pid in place_ids])
        )

    def _first_pass(self, place_ids: list[str]) -> RecommendationResponse:
        return RecommendationResponse(
            recommendations=[_item(pid) for pid in place_ids],
            unverified_recommendations=[],
            elapsed_ms=0,
        )

    @pytest.mark.asyncio
    async def test_ignore_intent_skips_enrichment_entirely(self) -> None:
        conditions = UserConditions(concentration_intent=ConcentrationIntent.IGNORE)
        enrichment_provider = _CountingEnrichmentProvider()

        result = await _apply_concentration_rerank(
            conditions,
            self._context(["a"]),
            self._first_pass(["a"]),
            recommendation_provider=_CountingRecommendationProvider(),
            enrichment_provider=enrichment_provider,
        )

        assert enrichment_provider.call_count == 0
        assert [item.place_id for item in result.recommendations] == ["a"]

    @pytest.mark.asyncio
    async def test_seek_with_rerank_capable_provider_reorders_and_caps_to_five(self) -> None:
        conditions = UserConditions(concentration_intent=ConcentrationIntent.SEEK)
        enrichment_provider = _CountingEnrichmentProvider()
        recommendation_provider = _CountingRecommendationProviderWithRerank()
        # 실제 1차 Scoring은 최대 5개까지만 넘기지만(_RECOMMENDATION_LIMIT), 이
        # 슬라이싱 자체가 5개 초과 입력에서도 정확히 잘리는지 확인하려고 6개를 준다.
        place_ids = ["a", "b", "c", "d", "e", "f"]

        result = await _apply_concentration_rerank(
            conditions,
            self._context(place_ids),
            self._first_pass(place_ids),
            recommendation_provider=recommendation_provider,
            enrichment_provider=enrichment_provider,
        )

        assert enrichment_provider.call_count == 1
        assert recommendation_provider.rerank_call_count == 1
        # FakeRecommendationProvider.rerank_with_concentration()은 1차 결과를 역순으로
        # 반환한다 — 실제로 2차 결과로 교체됐는지, 그리고 5개로 잘렸는지 확인한다.
        assert [item.place_id for item in result.recommendations] == list(reversed(place_ids))[:5]
        assert result.unverified_recommendations == []

    @pytest.mark.asyncio
    async def test_final_limit_defaults_to_five_but_schedule_can_request_ten(self) -> None:
        """SCHEDULE-04 회귀: final_limit을 안 넘기면 기존과 동일하게 5개로 잘리지만,
        SCHEDULE처럼 10을 명시하면 재순위 후에도 10개가 그대로 유지돼야 한다 —
        예전에는 _CONCENTRATION_FINAL_LIMIT=5가 무조건 적용돼 SCHEDULE의 10개가
        조용히 5개로 잘리는 버그가 있었다."""
        conditions = UserConditions(concentration_intent=ConcentrationIntent.SEEK)
        place_ids = [f"p{i}" for i in range(10)]

        default_result = await _apply_concentration_rerank(
            conditions,
            self._context(place_ids),
            self._first_pass(place_ids),
            recommendation_provider=_CountingRecommendationProviderWithRerank(),
            enrichment_provider=_CountingEnrichmentProvider(),
        )
        assert len(default_result.recommendations) == 5

        schedule_result = await _apply_concentration_rerank(
            conditions,
            self._context(place_ids),
            self._first_pass(place_ids),
            recommendation_provider=_CountingRecommendationProviderWithRerank(),
            enrichment_provider=_CountingEnrichmentProvider(),
            final_limit=10,
        )
        assert len(schedule_result.recommendations) == 10

    @pytest.mark.asyncio
    async def test_avoid_without_rerank_capable_provider_falls_back_to_first_pass(self) -> None:
        """D(rerank_with_concentration 없음)에서도 C 보강 조회는 크래시 없이
        호출되지만, 결과는 1차 그대로(개수 제한도 없이) 반환된다."""
        conditions = UserConditions(concentration_intent=ConcentrationIntent.AVOID)
        enrichment_provider = _CountingEnrichmentProvider()
        place_ids = ["a", "b", "c", "d"]

        result = await _apply_concentration_rerank(
            conditions,
            self._context(place_ids),
            self._first_pass(place_ids),
            recommendation_provider=_CountingRecommendationProvider(),
            enrichment_provider=enrichment_provider,
        )

        assert enrichment_provider.call_count == 1
        assert [item.place_id for item in result.recommendations] == place_ids

    @pytest.mark.asyncio
    async def test_seek_with_no_matching_places_skips_enrichment(self) -> None:
        """1차 결과의 place_id가 context.places에 하나도 없으면(재조인 실패) 보강
        조회 자체를 건너뛰고 1차 결과를 그대로 쓴다."""
        conditions = UserConditions(concentration_intent=ConcentrationIntent.SEEK)
        enrichment_provider = _CountingEnrichmentProvider()

        result = await _apply_concentration_rerank(
            conditions,
            self._context(["other"]),
            self._first_pass(["a"]),
            recommendation_provider=_CountingRecommendationProviderWithRerank(),
            enrichment_provider=enrichment_provider,
        )

        assert enrichment_provider.call_count == 0
        assert [item.place_id for item in result.recommendations] == ["a"]


@pytest.mark.asyncio
async def test_concentration_intent_persisted_by_b_triggers_rerank() -> None:
    """B-06으로 concentration_intent 필드가 추가된 뒤: LLM이 추출한 SEEK/AVOID가
    B의 State까지 정상적으로 저장되고, 그 결과 6-1 분기(_apply_concentration_rerank)가
    실제 run_agent_flow() 흐름에서 트리거된다.
    """
    store = InMemoryStateStore()
    providers = _providers()

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 핫한 곳 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert response.llm_output.recommend.conditions.concentration_intent == "SEEK"
    assert response.state.user_conditions.concentration_intent == "SEEK"
    assert providers["enrichment_provider"].call_count == 1
    assert [execution.operation for execution in response.tool_executions] == [
        "context_fetch",
        "candidate_enrichment",
    ]
    # RECOMMEND 기본 limit=5. _FAKE_CANDIDATES가 SCHEDULE-07에서 6개로 늘어(재조정
    # 테스트가 3개 미만 가드에 걸리지 않도록) 5개로 잘려 enrichment 대상이 된다.
    assert response.tool_executions[1].candidate_status_counts == {"success": 5}


@pytest.mark.asyncio
async def test_concentration_ignore_skips_enrichment_call() -> None:
    """concentration_intent가 IGNORE/null이면 혼잡도 보강 조회 자체가 없다(회귀 확인)."""
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

    assert response.llm_output.recommend.conditions.concentration_intent in (None, "IGNORE")
    assert providers["enrichment_provider"].call_count == 0


@pytest.mark.asyncio
async def test_clarification_answer_keeps_conditions_from_previous_turn() -> None:
    """되묻기 답변은 새 요청이 아니므로 앞 턴 조건이 유지되어야 한다.

    1턴 "카페 추천해줘" → 위치가 없어 C가 needs_clarification.
    2턴 "경복궁 근처 카페 추천해줘" → 위치가 채워지고 place_tags도 살아 있어야 한다.
    """
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(user_input="카페 추천해줘", session_id=None, device_location=DEVICE_LOCATION),
        store=store,
        **providers,
    )
    session_id = first.state.session_id
    assert first.recommendations is None
    # 되묻기로 끝났으므로 B에 사유가 남는다.
    assert get_session_context(session_id, store=store).pending_clarification is not None

    second = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert second.state.user_conditions.search_center == "경복궁"
    assert "카페" in second.state.user_conditions.place_tags
    # 소비되어 지워진다.
    assert get_session_context(session_id, store=store).pending_clarification is None


@pytest.mark.asyncio
async def test_bare_place_after_location_clarification_becomes_modify_and_sets_center() -> None:
    """TP-67: 위치 되묻기 다음 '경복궁'은 INFO가 아닌 MODIFY로 이어져야 한다.

    아직 추천 결과가 없는 첫 요청에서도 B에 저장된 앞 턴 조건을 MODIFY 추출기에
    전달해, search_center만 추가한 뒤 추천을 이어간다.
    """
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(user_input="근처 갈곳 추천해줘", session_id=None, device_location=None),
        store=store,
        **providers,
    )
    session_id = first.state.session_id
    assert first.llm_output.intent == "RECOMMEND"
    assert get_session_context(session_id, store=store).pending_clarification == "location_required"

    second = await run_agent_flow(
        AgentRequest(user_input="경복궁", session_id=session_id, device_location=None),
        store=store,
        **providers,
    )

    assert second.llm_output.intent == "MODIFY"
    assert second.llm_output.modify.changed_fields == ["search_center"]
    assert second.state.user_conditions.search_center == "경복궁"
    assert second.recommendations is not None
    assert get_session_context(session_id, store=store).pending_clarification is None


@pytest.mark.asyncio
async def test_new_recommendation_without_location_keeps_previous_search_center() -> None:
    """TP-67: 목적지 뒤 새 RECOMMEND가 와도 목적지를 다시 묻지 않는다."""
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    second = await run_agent_flow(
        AgentRequest(
            user_input="박물관 추천해줘",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert second.llm_output.intent == "RECOMMEND"
    assert second.state.user_conditions.search_center == "경복궁"
    assert "박물관" in second.state.user_conditions.place_tags
    assert second.recommendations is not None


@pytest.mark.asyncio
async def test_schedule_clarification_answer_stays_schedule() -> None:
    """D-059: SCHEDULE 되묻기에 지명만 답하면 MODIFY가 아니라 SCHEDULE을 유지해야 한다.

    1턴 "일정 짜줘"(위치 없음) → C가 needs_clarification(location_required).
    2턴 "광화문 근처로" → 되묻기 답변인데도 MODIFY로 오분류되면(수정 전 버그) 바꿀
    이전 추천 결과가 없어 흐름이 깨진다. SCHEDULE로 이어지고 pending_clarification도
    소비되어 사라져야 한다.
    """
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(user_input="일정 짜줘", session_id=None, device_location=DEVICE_LOCATION),
        store=store,
        **providers,
    )
    session_id = first.state.session_id
    assert first.llm_output.intent == "SCHEDULE"
    assert first.recommendations is None
    session_context = get_session_context(session_id, store=store)
    assert session_context.pending_clarification is not None
    assert session_context.last_intent == "SCHEDULE"

    second = await run_agent_flow(
        AgentRequest(
            user_input="광화문 근처로",
            session_id=session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert second.llm_output.intent == "SCHEDULE"
    assert second.state.user_conditions.search_center == "광화문"
    # 소비되어 지워진다(수정 전에는 SCHEDULE이 되묻기 소비 화이트리스트에 없어 안 지워졌다).
    assert get_session_context(session_id, store=store).pending_clarification is None


@pytest.mark.asyncio
async def test_clarification_answer_keeps_weather_and_environment() -> None:
    """되묻기 답변에 위치만 담겨도 앞 턴의 비 회피·실내 조건이 살아 있어야 한다.

    1턴 "비 오는데 카페 추천해줘"(위치 없음) → 되묻기.
    2턴 "경복궁 근처에서" → search_center만 채워지고 weather/environment는 유지.
    이 턴은 RECOMMEND로 분류되지만 pending_clarification 덕에 soft reset을 건너뛴다.
    """
    store = InMemoryStateStore()
    providers = _providers()

    first = await run_agent_flow(
        AgentRequest(
            user_input="비 오는데 카페 추천해줘", session_id=None, device_location=DEVICE_LOCATION
        ),
        store=store,
        **providers,
    )
    session_id = first.state.session_id
    assert first.state.user_conditions.weather == "rain"
    assert first.state.user_conditions.environment == "indoor"
    assert get_session_context(session_id, store=store).pending_clarification is not None

    second = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처에서",
            session_id=session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert second.state.user_conditions.search_center == "경복궁"
    assert second.state.user_conditions.weather == "rain"
    assert second.state.user_conditions.weather_intent == "AVOID"
    assert second.state.user_conditions.environment == "indoor"


@pytest.mark.asyncio
async def test_successful_recommendation_leaves_no_pending_clarification() -> None:
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

    assert response.recommendations is not None
    context = get_session_context(response.state.session_id, store=store)
    assert context.pending_clarification is None


@pytest.mark.asyncio
async def test_추천_응답에_C_실행_정보가_실린다() -> None:
    """AgentResponse.tool_execution은 감사 표시 전용이지만, 비어 있으면 /dev-chat의
    C Tool 탭이 다시 추측만 하게 된다. 실제 값이 실리는지 확인한다."""

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=InMemoryStateStore(),
        **_providers(),
    )

    assert response.tool_execution is not None
    assert response.tool_execution.status == "success"
    assert response.tool_execution.latency_ms is not None
    assert [execution.operation for execution in response.tool_executions] == ["context_fetch"]
    assert [item.key for item in response.tool_execution.context_items] == [
        "location",
        "weather",
        "places",
        "holidays",
    ]


@pytest.mark.asyncio
async def test_modify_change_condition_calls_context_again_with_merged_conditions() -> None:
    """MODIFY로 조건이 바뀌면 C를 다시 호출하고, 그 요청에 병합된 조건이 실려야 한다.

    재호출하지 않으면 조건만 바뀌고 후보는 1턴 그대로 남는다. 횟수만 세면 "부르긴
    했는데 옛 조건으로 불렀다"를 놓치므로 요청 내용까지 확인한다.
    """
    store = InMemoryStateStore()
    providers = _providers()
    tool_provider = providers["tool_provider"]

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘", session_id=None, device_location=DEVICE_LOCATION
        ),
        store=store,
        **providers,
    )
    assert tool_provider.call_count == 1
    assert tool_provider.last_request.conditions.budget is None

    await run_agent_flow(
        AgentRequest(
            user_input="무료인 곳으로",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert tool_provider.call_count == 2
    # 2턴 요청에는 병합 결과가 실린다 — 바뀐 budget과 유지된 search_center가 함께.
    assert tool_provider.last_request.conditions.budget == "free"
    assert tool_provider.last_request.conditions.search_center == "경복궁"


@pytest.mark.asyncio
async def test_modify_reject_all_calls_context_again() -> None:
    """REJECT_ALL은 조건이 그대로라도 C를 다시 호출한다.

    조건이 같다고 이전 Context를 재사용하면 제외 목록이 반영되지 않아 같은 장소가
    다시 노출된다.
    """
    store = InMemoryStateStore()
    providers = _providers()
    tool_provider = providers["tool_provider"]

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘", session_id=None, device_location=DEVICE_LOCATION
        ),
        store=store,
        **providers,
    )

    await run_agent_flow(
        AgentRequest(
            user_input="다른 곳 보여줘",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert tool_provider.call_count == 2
    assert tool_provider.last_request.conditions.search_center == "경복궁"


class _LocationAmbiguousToolProvider:
    """C 대역 — location_ambiguous를 후보 이름과 함께 돌려준다.

    resolve_location.py가 실제로 찾아낸 이름을 candidate_names로 흘려보내는
    것과 같은 모양을 흉내 낸다(docs/design/clarification-options.md 7절 확장).
    """

    def __init__(self, candidates: list[str]) -> None:
        self._candidates = candidates
        self.call_count = 0

    async def fetch_context(self, request: AgentContextRequest) -> AgentContextResponse:
        self.call_count += 1
        return AgentContextResponse(
            request_id=request.request_id,
            intent="RECOMMEND",
            status="needs_clarification",
            clarification=Clarification(code="location_ambiguous", candidates=self._candidates),
            metadata=ResponseMetadata(),
        )


@pytest.mark.asyncio
async def test_location_ambiguous_with_candidates_shows_them_as_buttons() -> None:
    """docs/design/clarification-options.md 7절 확장: 동명이인 후보 이름을 Tool이
    실제로 찾아내면(예: "종각" → "종각역"/"종각 지하도상가") 텍스트 재질문 대신
    후보 이름 버튼으로 보여줘야 한다."""
    store = InMemoryStateStore()
    providers = _providers()
    providers["tool_provider"] = _LocationAmbiguousToolProvider(["종각역", "종각 지하도상가"])

    response = await run_agent_flow(
        AgentRequest(
            user_input="종각 근처 카페 추천해",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert response.llm_output.status == OutputStatus.NEEDS_CLARIFICATION
    clarification = response.llm_output.clarification
    assert clarification is not None
    option_ids = {option.id for option in clarification.options}
    assert option_ids == {"종각역", "종각 지하도상가"}
    context = get_session_context(response.state.session_id, store=store)
    assert context.pending_clarification == "location_ambiguous"


@pytest.mark.asyncio
async def test_location_ambiguous_without_candidates_falls_back_to_quick_picks() -> None:
    """실사용 피드백(2026-08-13): resolve_location.py가 식당·상점을 이미 걸러내고
    남는 후보가 하나도 없으면(전부 식당·상점뿐이었던 경우), 빈 후보 대신 A2와
    같은 종로구 대표 스팟 고정 버튼을 보여줘야 한다 — "그냥 지하철역으로만 가자"."""
    store = InMemoryStateStore()
    providers = _providers()
    providers["tool_provider"] = _LocationAmbiguousToolProvider([])

    response = await run_agent_flow(
        AgentRequest(
            user_input="종로 근처 식당 추천",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert response.llm_output.status == OutputStatus.NEEDS_CLARIFICATION
    clarification = response.llm_output.clarification
    assert clarification is not None
    option_ids = {option.id for option in clarification.options}
    assert option_ids == {"경복궁", "인사동", "광화문", "북촌"}
    labels = {option.label for option in clarification.options}
    assert labels == {"경복궁 근처", "인사동 근처", "광화문 근처", "북촌 근처"}


@pytest.mark.asyncio
async def test_clarification_choice_location_ambiguous_candidate_resolves_search_center() -> None:
    """후보 버튼 클릭 시 classify_intent() 재호출 없이 그 이름으로 바로 검색해야
    한다."""
    store = InMemoryStateStore()
    providers = _providers()
    providers["tool_provider"] = _LocationAmbiguousToolProvider(["종각역", "종각 지하도상가"])

    ambiguous = await run_agent_flow(
        AgentRequest(
            user_input="종각 근처 카페 추천해",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert ambiguous.llm_output.status == OutputStatus.NEEDS_CLARIFICATION

    # 해소 턴은 위치가 확정됐다고 보고 정상 응답을 돌려줘야 하므로, 이 턴만 보통의
    # FakeToolProvider로 바꿔 끼운다(location_ambiguous를 계속 강제하면 안 풀린다).
    providers["tool_provider"] = _CountingToolProvider()
    resolved = await run_agent_flow(
        AgentRequest(
            user_input="종각역",
            session_id=ambiguous.state.session_id,
            device_location=DEVICE_LOCATION,
            clarification_choice="종각역",
        ),
        store=store,
        **providers,
    )

    assert resolved.llm_output.intent == "RECOMMEND"
    assert resolved.llm_output.status == OutputStatus.COMPLETE
    assert resolved.state.user_conditions.search_center == "종각역"
    context = get_session_context(resolved.state.session_id, store=store)
    assert context.pending_clarification is None


class _FixedStatusToolProvider:
    """지정한 status만 돌려주는 C 대역. 상태 분기만 보기 위해 내용은 최소로 채운다."""

    def __init__(self, status: str) -> None:
        self._status = status
        self.call_count = 0

    async def fetch_context(self, request: AgentContextRequest) -> AgentContextResponse:
        self.call_count += 1
        payload: dict = {
            "request_id": request.request_id,
            "intent": "RECOMMEND",
            "status": self._status,
            "metadata": ResponseMetadata(),
        }
        if self._status in {"success", "partial", "no_data"}:
            payload["context"] = RecommendationContext(
                location=ContextValue(
                    status="success",
                    data=ResolvedLocation(
                        requested_query="경복궁",
                        resolved_name="경복궁",
                        source="query",
                        location=Coordinates(latitude=37.5788, longitude=126.9770),
                    ),
                ),
                places=ContextValue(status=self._status, data=[]),
            )
        elif self._status == "needs_clarification":
            payload["clarification"] = Clarification(
                code="location_required", missing_fields=["current_location"]
            )
        else:
            payload["error"] = ContextError(
                code=self._status, message="테스트용 오류", retryable=False
            )
        return AgentContextResponse(**payload)


@pytest.mark.parametrize(
    ("tool_status", "reaches_recommendation"),
    [
        ("success", True),
        # partial은 "가능한 데이터로 계속"이라 D까지 간다(계약 §5.4).
        ("partial", True),
        # 아래 넷은 _TOOL_TERMINAL_STATUSES — 안내만 하고 끝난다.
        # no_data는 넘길 후보가 없어 D를 부르지 않고 조건 조정을 되묻는다.
        ("no_data", False),
        ("needs_clarification", False),
        ("unsupported", False),
        ("unavailable", False),
    ],
)
@pytest.mark.asyncio
async def test_tool_status_decides_whether_recommendation_runs(
    tool_status: str, reaches_recommendation: bool
) -> None:
    """C의 6개 status가 D 호출 여부를 어떻게 가르는지 한곳에 고정한다.

    개별 케이스는 다른 테스트에도 흩어져 있지만, 경계를 한 표로 모아두면 "partial은
    어떻게 되지?"를 한눈에 답할 수 있고 정책이 바뀔 때 이 표만 고치면 된다.
    """
    tool_provider = _FixedStatusToolProvider(tool_status)
    recommendation_provider = _CountingRecommendationProvider()

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        llm=_LLMProviderWithGeneralAnswer(),
        tool_provider=tool_provider,
        recommendation_provider=recommendation_provider,
        enrichment_provider=_CountingEnrichmentProvider(),
        store=InMemoryStateStore(),
    )

    assert tool_provider.call_count == 1
    assert recommendation_provider.call_count == (1 if reaches_recommendation else 0)
    assert (response.recommendations is not None) is reaches_recommendation


@pytest.mark.asyncio
async def test_location_required_clarification_reaches_user_message() -> None:
    """C의 clarification.code가 A를 거쳐 되묻기 문장까지 이어지는지 확인한다."""
    tool_provider = _FixedStatusToolProvider("needs_clarification")

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        llm=_LLMProviderWithGeneralAnswer(),
        tool_provider=tool_provider,
        recommendation_provider=_CountingRecommendationProvider(),
        enrichment_provider=_CountingEnrichmentProvider(),
        store=InMemoryStateStore(),
    )

    assert "어디 근처에서" in response.message


@pytest.mark.asyncio
async def test_no_data_asks_to_adjust_conditions_without_calling_recommendation() -> None:
    """후보가 없으면 D를 부르지 않고 조건을 바꿔볼지 되묻는다.

    빈 후보로 Scoring을 돌려도 결과가 같으므로 호출하지 않는다. TourAPI
    provider_metadata가 없으면(원인 구분 신호 자체가 없음) 원인1+3(no_data_empty)
    되묻기로 처리한다 — 조사 결과(2026-08-13) TourAPI가 애초에 0건일 때와 반경이
    좁아 0건일 때는 신호가 같아 구분할 수 없다.
    """
    tool_provider = _FixedStatusToolProvider("no_data")
    recommendation_provider = _CountingRecommendationProvider()

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        llm=_LLMProviderWithGeneralAnswer(),
        tool_provider=tool_provider,
        recommendation_provider=recommendation_provider,
        enrichment_provider=_CountingEnrichmentProvider(),
        store=InMemoryStateStore(),
    )

    assert recommendation_provider.call_count == 0
    assert response.recommendations is None
    assert response.llm_output.status == OutputStatus.NEEDS_CLARIFICATION
    assert response.llm_output.clarification is not None
    assert response.llm_output.clarification.code == "no_data_empty"
    assert f"{supported_district_label()} 안에서 찾지 못했어요" in response.message
    option_ids = {option.id for option in response.llm_output.clarification.options}
    assert option_ids == {"widen_radius", "widen_category"}
    # 일시적 장애 문구로 새면 안 된다.
    assert "일시적으로" not in response.message


@pytest.mark.asyncio
async def test_no_data_marks_pending_clarification_so_next_turn_keeps_conditions() -> None:
    """ "범위를 넓혀볼까요?"에 대한 답변은 새 요청이 아니라 이번 요청의 연속이다.

    표시해두지 않으면 다음 턴이 RECOMMEND로 분류되며 soft reset이 걸려 앞 턴 조건이
    사라진다(D-039와 같은 이유).
    """
    store = InMemoryStateStore()
    tool_provider = _FixedStatusToolProvider("no_data")

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        llm=_LLMProviderWithGeneralAnswer(),
        tool_provider=tool_provider,
        recommendation_provider=_CountingRecommendationProvider(),
        enrichment_provider=_CountingEnrichmentProvider(),
        store=store,
    )

    context = get_session_context(response.state.session_id, store=store)
    assert context.pending_clarification == "no_data_empty"


@pytest.mark.asyncio
async def test_bare_place_after_no_data_restarts_search_around_that_place() -> None:
    """후보 없음 뒤 단순 지명은 INFO가 아니라 해당 장소 주변 재추천 요청이다."""
    store = InMemoryStateStore()

    first = await run_agent_flow(
        AgentRequest(user_input="카페 추천해줘", session_id=None, device_location=DEVICE_LOCATION),
        llm=_LLMProviderWithGeneralAnswer(),
        tool_provider=_FixedStatusToolProvider("no_data"),
        recommendation_provider=_CountingRecommendationProvider(),
        enrichment_provider=_CountingEnrichmentProvider(),
        store=store,
    )
    session_id = first.state.session_id
    assert get_session_context(session_id, store=store).pending_clarification == "no_data_empty"

    second = await run_agent_flow(
        AgentRequest(user_input="광화문", session_id=session_id, device_location=DEVICE_LOCATION),
        llm=_LLMProviderWithGeneralAnswer(),
        tool_provider=FakeToolProvider(),
        recommendation_provider=_CountingRecommendationProvider(),
        enrichment_provider=_CountingEnrichmentProvider(),
        store=store,
    )

    assert second.llm_output.intent == "RECOMMEND"
    assert second.state.user_conditions.search_center == "광화문"
    assert "카페" in second.state.user_conditions.place_tags
    assert second.recommendations is not None


def test_terminal_status_sets_match_between_runtime_and_composer() -> None:
    """두 모듈이 같은 집합을 각자 들고 있다 — 어긋나면 메시지가 엉뚱한 분기로 샌다."""
    from app.services.runtime.agent_runtime import _TOOL_TERMINAL_STATUSES as runtime_set
    from app.services.runtime.response_composer import (
        _TOOL_TERMINAL_STATUSES as composer_set,
    )

    assert runtime_set == composer_set


# C가 내려주는 operating_schedule 직렬화 형태. 24시간 열려 있어 Scoring이 폐점으로
# 걸러내지 않는 값으로 둔다 — 여기서 보려는 건 운영시간 유무에 따른 분류다.
_OPEN_ALL_DAY_SCHEDULE = {
    "availability": "scheduled",
    "rules": [
        {
            "months": None,
            "weekdays": None,
            "time_ranges": [
                {"open_time": "00:00", "close_time": "23:59", "crosses_midnight": False}
            ],
        }
    ],
    "time_ranges": [{"open_time": "00:00", "close_time": "23:59", "crosses_midnight": False}],
    "closure_rules": [],
    "parse_status": "parsed",
    "assumption_reason": None,
    "warnings": [],
}


def _context_place(place_id: str, *, with_schedule: bool) -> PlaceCandidate:
    return PlaceCandidate(
        place_id=place_id,
        name=f"장소-{place_id}",
        category="cafe",
        location=Coordinates(latitude=37.5790, longitude=126.9772),
        operating_hours_raw="09:00~22:00" if with_schedule else None,
        operating_schedule=_OPEN_ALL_DAY_SCHEDULE if with_schedule else None,
    )


class _PartialPlacesToolProvider:
    """운영정보가 일부만 채워진 partial Context를 돌려주는 C 대역."""

    def __init__(self, places: list[PlaceCandidate]) -> None:
        self._places = places

    async def fetch_context(self, request: AgentContextRequest) -> AgentContextResponse:
        return AgentContextResponse(
            request_id=request.request_id,
            intent="RECOMMEND",
            status="partial",
            context=RecommendationContext(
                location=ContextValue(
                    status="success",
                    data=ResolvedLocation(
                        requested_query="경복궁",
                        resolved_name="경복궁",
                        source="query",
                        location=Coordinates(latitude=37.5788, longitude=126.9770),
                    ),
                ),
                places=ContextValue(status="partial", data=self._places),
            ),
            metadata=ResponseMetadata(),
        )


_CLOSED_ALL_WEEK_SCHEDULE = {
    "availability": "all_day",
    "rules": [],
    "closure_rules": [
        {
            "weekdays": [
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            ]
        }
    ],
}


class _RefillPlacesToolProvider(FakeToolProvider):
    """제외 ID 다음의 후보를 페이지 단위로 반환하는 C 보충 조회 대역.

    실제 C처럼 excluded_place_ids만큼 뒤 후보를 채워 주고, 남은 후보가
    page_size보다 적으면 그만큼만 반환한다 — A가 "limit보다 적게 왔다"를 풀
    소진 신호로 쓰기 때문에 그 모양을 그대로 흉내 낸다.
    """

    def __init__(
        self,
        *,
        total: int = 25,
        page_size: int = 10,
        open_indexes: set[int] | None = None,
    ) -> None:
        self.requests: list[AgentContextRequest] = []
        self._page_size = page_size
        is_open = (
            (lambda index: index in open_indexes)
            if open_indexes is not None
            else (lambda index: index in {0, 10} or index >= 20)
        )
        self._places = [
            PlaceCandidate(
                place_id=f"refill-{index}",
                name=f"보충 장소 {index}",
                category="cafe",
                location=Coordinates(
                    latitude=37.5790 + index * 0.0001,
                    longitude=126.9772 + index * 0.0001,
                ),
                operating_schedule=(
                    _OPEN_ALL_DAY_SCHEDULE if is_open(index) else _CLOSED_ALL_WEEK_SCHEDULE
                ),
            )
            for index in range(total)
        ]

    def _build_context(
        self,
        places: list[PlaceCandidate],
        call_index: int,
    ) -> RecommendationContext:
        return RecommendationContext(
            location=ContextValue(
                status="success",
                data=ResolvedLocation(
                    requested_query="경복궁",
                    resolved_name="경복궁",
                    source="query",
                    location=Coordinates(latitude=37.5788, longitude=126.9770),
                ),
            ),
            places=ContextValue(status="success", data=places),
        )

    async def fetch_context(self, request: AgentContextRequest) -> AgentContextResponse:
        self.requests.append(request)
        call_index = len(self.requests) - 1
        excluded = set(request.excluded_place_ids)
        places = [place for place in self._places if place.place_id not in excluded]
        places = places[: self._page_size]
        return AgentContextResponse(
            request_id=request.request_id,
            intent="RECOMMEND",
            status="success",
            context=self._build_context(places, call_index),
            metadata=ResponseMetadata(),
        )


class _RecordingTravelRouteTool:
    def __init__(self) -> None:
        self.queries = []
        self._delegate = TravelRouteTool(
            {
                TravelMode.WALKING: TravelRouteProviders(
                    primary=FakeWalkingRouteProvider(walking_speed_mps=1.2)
                )
            }
        )

    async def execute(self, query):
        self.queries.append(query)
        return await self._delegate.execute(query)


class _UnavailableTravelRouteTool:
    async def execute(self, query):
        return TravelRouteToolResult(status=ToolStatus.UNAVAILABLE, routes=())


def _all_modes_travel_route_tool() -> TravelRouteTool:
    """도보·자동차·대중교통 세 provider를 모두 등록한 실측 도구.

    COMPARE의 _fetch_compare_travel_routes()가 세 수단을 병렬로 조회하므로,
    단위 테스트도 세 provider가 모두 필요하다.
    """
    return TravelRouteTool(
        {
            TravelMode.WALKING: TravelRouteProviders(
                primary=FakeWalkingRouteProvider(walking_speed_mps=1.2)
            ),
            TravelMode.DRIVING: TravelRouteProviders(
                primary=FakeDrivingRouteProvider(driving_speed_mps=8.0)
            ),
            TravelMode.TRANSIT: TravelRouteProviders(
                primary=FakeTransitRouteProvider(transit_speed_mps=5.0)
            ),
        }
    )


class TestFetchCompareTravelRoutes:
    """COMPARE의 TRAVEL_TIME 실측 연결(2026-08-21, TP-105/106) 전용 단위 테스트."""

    def _comparison(self, *, criteria=CompareCriteria.TRAVEL_TIME) -> ComparisonResult:
        return ComparisonResult(
            criteria=criteria,
            items=[
                ComparisonItem(
                    place_id="p1",
                    place_name="경복궁",
                    rank=1,
                    latitude=37.5796,
                    longitude=126.9770,
                ),
                ComparisonItem(
                    place_id="p2",
                    place_name="창덕궁",
                    rank=2,
                    latitude=37.5824,
                    longitude=126.9910,
                ),
            ],
        )

    @pytest.mark.asyncio
    async def test_returns_unchanged_when_criteria_is_not_travel_time(self) -> None:
        comparison = self._comparison(criteria=CompareCriteria.TIME)
        tool = _RecordingTravelRouteTool()

        result = await _fetch_compare_travel_routes(
            tool, origin_location="37.5760,126.9769", comparison=comparison
        )

        assert result is comparison
        assert tool.queries == []

    @pytest.mark.asyncio
    async def test_fetches_all_three_modes_and_fills_fields(self) -> None:
        comparison = self._comparison()
        tool = _all_modes_travel_route_tool()

        result = await _fetch_compare_travel_routes(
            tool, origin_location="37.5760,126.9769", comparison=comparison
        )

        for item in result.items:
            assert item.travel_walking_minutes is not None
            assert item.travel_driving_minutes is not None
            assert item.travel_transit_minutes is not None
            assert item.travel_distance_km is not None
            # 도보가 가장 느린 수단이라 소요시간이 가장 길어야 한다.
            assert item.travel_walking_minutes > item.travel_driving_minutes

    @pytest.mark.asyncio
    async def test_missing_provider_leaves_that_mode_none_others_filled(self) -> None:
        """대중교통 provider가 미설정이어도(TP-106 이전 상태 재현) 나머지 수단은 채워진다."""
        comparison = self._comparison()
        tool = TravelRouteTool(
            {
                TravelMode.WALKING: TravelRouteProviders(
                    primary=FakeWalkingRouteProvider(walking_speed_mps=1.2)
                ),
                TravelMode.DRIVING: TravelRouteProviders(
                    primary=FakeDrivingRouteProvider(driving_speed_mps=8.0)
                ),
            }
        )

        result = await _fetch_compare_travel_routes(
            tool, origin_location="37.5760,126.9769", comparison=comparison
        )

        for item in result.items:
            assert item.travel_walking_minutes is not None
            assert item.travel_driving_minutes is not None
            assert item.travel_transit_minutes is None

    @pytest.mark.asyncio
    async def test_items_without_coordinates_are_left_untouched(self) -> None:
        comparison = ComparisonResult(
            criteria=CompareCriteria.TRAVEL_TIME,
            items=[ComparisonItem(place_id="p1", place_name="좌표 없는 곳", rank=1)],
        )
        tool = _all_modes_travel_route_tool()

        result = await _fetch_compare_travel_routes(
            tool, origin_location="37.5760,126.9769", comparison=comparison
        )

        assert result is comparison

    @pytest.mark.asyncio
    async def test_no_origin_location_returns_unchanged(self) -> None:
        comparison = self._comparison()
        tool = _all_modes_travel_route_tool()

        result = await _fetch_compare_travel_routes(
            tool, origin_location=None, comparison=comparison
        )

        assert result is comparison


class _RecordingWalkingRoutesRecommendationProvider(RealRecommendationProvider):
    def __init__(self) -> None:
        self.travel_routes: tuple[TravelRoute, ...] = ()

    async def score_prepared(
        self,
        conditions,
        prepared,
        *,
        travel_routes=(),
        limit=5,
    ):
        self.travel_routes = travel_routes
        return await super().score_prepared(
            conditions,
            prepared,
            travel_routes=travel_routes,
            limit=limit,
        )


@pytest.mark.asyncio
async def test_staged_recommendation_refills_candidates_up_to_target() -> None:
    store = InMemoryStateStore()
    tool_provider = _RefillPlacesToolProvider()

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        llm=_LLMProviderWithGeneralAnswer(),
        tool_provider=tool_provider,
        recommendation_provider=RealRecommendationProvider(),
        enrichment_provider=_CountingEnrichmentProvider(),
        store=store,
    )

    assert response.recommendations is not None
    shown = [
        *response.recommendations.recommendations,
        *response.recommendations.unverified_recommendations,
    ]
    assert len(shown) == 5
    assert len(tool_provider.requests) == 3
    assert len(tool_provider.requests[0].excluded_place_ids) == 0
    assert len(tool_provider.requests[1].excluded_place_ids) == 10
    assert len(tool_provider.requests[2].excluded_place_ids) == 20
    assert any(item.place_id.startswith("refill-2") for item in shown)

    session = get_session_context(response.state.session_id, store=store)
    # TP-82: 화면에 보여준 5개뿐 아니라, 리필 도중 폐점이라 걸러진 후보(3라운드에
    # 걸쳐 refill-1~9, 11~19 총 18개)도 B에 기록되어 다음 회차 제외 목록에
    # 들어간다 — 안 그러면 "다른 곳 보여줘"를 반복할 때마다 같은 폐점 후보를
    # 다시 리필해 뽑는 낭비가 반복된다.
    assert set(session.excluded_place_ids) == {item.place_id for item in shown} | set(
        response.recommendations.excluded_closed_place_ids
    )
    assert response.recommendations.excluded_closed_place_ids != []


@pytest.mark.asyncio
async def test_repeated_reject_all_does_not_refetch_closed_candidates() -> None:
    """TP-82 완료 조건: 같은 세션에서 "다른 곳 보여줘"를 반복해도, 이전에
    폐점으로 판명된 후보는 다음 회차 C 조회에서 다시 뽑히지 않는다.

    후보 15개 중 5개(0~4)만 영업 중, 10개(5~14)는 폐점 — 1턴에서 5개가
    노출되고 10개가 폐점으로 걸러진다. 2턴("다른 곳 보여줘")에서 C가 받는
    excluded_place_ids에 그 10개가 이미 포함돼 있어야, 폐점 후보를 매번
    다시 조회해 낭비하지 않는다(밤 시간대 폐점 비율이 높을 때 카드 수가
    점점 줄어드는 원인이었다).
    """
    store = InMemoryStateStore()
    tool_provider = _RefillPlacesToolProvider(
        total=15, page_size=15, open_indexes={0, 1, 2, 3, 4}
    )
    providers = {
        "llm": _LLMProviderWithGeneralAnswer(),
        "tool_provider": tool_provider,
        "recommendation_provider": RealRecommendationProvider(),
        "enrichment_provider": _CountingEnrichmentProvider(),
    }

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘", session_id=None, device_location=DEVICE_LOCATION
        ),
        store=store,
        **providers,
    )
    first_shown = {
        item.place_id
        for item in [
            *first.recommendations.recommendations,
            *first.recommendations.unverified_recommendations,
        ]
    }
    assert len(first_shown) == 5
    closed_ids = {f"refill-{i}" for i in range(5, 15)}
    assert set(first.recommendations.excluded_closed_place_ids) == closed_ids

    second = await run_agent_flow(
        AgentRequest(
            user_input="다른 곳 보여줘",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    # 2턴 C 조회의 excluded_place_ids가 1턴 폐점 후보 10개를 이미 포함해야
    # 한다 — 후보 풀에 남은 게 없으므로(전부 노출 or 폐점) 결과가 0건이어도
    # 정상이다. 여기서 확인하려는 건 "재조회 자체를 안 한다"는 것이다.
    assert len(second.state.excluded_place_ids) >= 15
    assert closed_ids.issubset(set(second.state.excluded_place_ids))
    second_request_excluded = set(tool_provider.requests[-1].excluded_place_ids)
    assert closed_ids.issubset(second_request_excluded)


@pytest.mark.asyncio
async def test_staged_recommendation_passes_only_eligible_routes_to_d_after_refill() -> None:
    context_provider = _RefillPlacesToolProvider()
    route_tool = _RecordingTravelRouteTool()
    recommendation_provider = _RecordingWalkingRoutesRecommendationProvider()

    await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        llm=_LLMProviderWithGeneralAnswer(),
        tool_provider=context_provider,
        recommendation_provider=recommendation_provider,
        enrichment_provider=_CountingEnrichmentProvider(),
        travel_route_tool=route_tool,
        store=InMemoryStateStore(),
    )

    assert len(context_provider.requests) == 3
    assert len(route_tool.queries) == 1
    requested_ids = [destination.place_id for destination in route_tool.queries[0].destinations]
    assert requested_ids == ["refill-0", "refill-10", *[f"refill-{i}" for i in range(20, 25)]]
    assert [route.place_id for route in recommendation_provider.travel_routes] == requested_ids
    assert "refill-1" not in requested_ids


class _LLMProviderWithTransport(_LLMProviderWithGeneralAnswer):
    """이동수단과 이동시간을 못 박는 더블 — FakeLLMProvider는 transport를 만들지 않는다."""

    def __init__(self, transport: Transport | None, max_travel_time: int = 30) -> None:
        super().__init__()
        self._transport = transport
        self._max_travel_time = max_travel_time

    async def extract_recommend_conditions(self, user_input):
        result = await super().extract_recommend_conditions(user_input)
        output = result.data
        assert output.recommend is not None
        conditions = output.recommend.conditions.model_copy(
            update={"transport": self._transport, "max_travel_time": self._max_travel_time}
        )
        return provider_result(
            output.model_copy(update={"recommend": RecommendPayload(conditions=conditions)}),
            source=ProviderSource.FAKE_LLM,
        )


@pytest.mark.asyncio
async def test_staged_recommendation_asks_driving_mode_and_gets_nothing_for_car_request() -> None:
    """자동차 요청은 자동차 mode로 묻고, 등록된 Provider가 없어 값 없이 돌아온다.

    도보 실측을 자동차 요청에 쓰지 않는다는 결과는 이전과 같고(D가 버렸다),
    이제 그 판단이 Tool에서 나므로 카카오 도보 호출이 일어나지 않는다 — 호출이
    0건인지는 test_travel_route_tool.py가 Provider 호출 수로 못 박는다.
    """
    route_tool = _RecordingTravelRouteTool()
    recommendation_provider = _RecordingWalkingRoutesRecommendationProvider()

    await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        llm=_LLMProviderWithTransport(Transport.CAR),
        tool_provider=_RefillPlacesToolProvider(),
        recommendation_provider=recommendation_provider,
        enrichment_provider=_CountingEnrichmentProvider(),
        travel_route_tool=route_tool,
        store=InMemoryStateStore(),
    )

    assert [query.mode for query in route_tool.queries] == [TravelMode.DRIVING]
    assert recommendation_provider.travel_routes == ()


@pytest.mark.asyncio
async def test_staged_recommendation_skips_route_lookup_when_transport_is_unstated() -> None:
    """이동수단 미언급 + 이동시간 언급은 무엇으로 재야 할지 정할 수 없어 조회하지 않는다.

    반경이 20km/h 가정으로 커져 있는데 그게 대중교통인지 자동차인지는 발화에
    없다(to_travel_mode). 지금도 D가 이 경우 도보 실측을 버렸으므로 결과는 같다.
    """
    route_tool = _RecordingTravelRouteTool()
    recommendation_provider = _RecordingWalkingRoutesRecommendationProvider()

    await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        llm=_LLMProviderWithTransport(None),
        tool_provider=_RefillPlacesToolProvider(),
        recommendation_provider=recommendation_provider,
        enrichment_provider=_CountingEnrichmentProvider(),
        travel_route_tool=route_tool,
        store=InMemoryStateStore(),
    )

    assert route_tool.queries == []
    assert recommendation_provider.travel_routes == ()


@pytest.mark.asyncio
async def test_staged_recommendation_requests_walking_mode_for_walk_request() -> None:
    """도보 요청은 mode=WALKING으로 조회한다 — 반경도 도보 속도로 만들어진다."""
    route_tool = _RecordingTravelRouteTool()

    await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        llm=_LLMProviderWithGeneralAnswer(),
        tool_provider=_RefillPlacesToolProvider(),
        recommendation_provider=_RecordingWalkingRoutesRecommendationProvider(),
        enrichment_provider=_CountingEnrichmentProvider(),
        travel_route_tool=route_tool,
        store=InMemoryStateStore(),
    )

    assert [query.mode for query in route_tool.queries] == [TravelMode.WALKING]


@pytest.mark.asyncio
async def test_staged_recommendation_passes_empty_routes_when_route_tool_is_unavailable() -> None:
    recommendation_provider = _RecordingWalkingRoutesRecommendationProvider()

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        llm=_LLMProviderWithGeneralAnswer(),
        tool_provider=_RefillPlacesToolProvider(total=6),
        recommendation_provider=recommendation_provider,
        enrichment_provider=_CountingEnrichmentProvider(),
        travel_route_tool=_UnavailableTravelRouteTool(),
        store=InMemoryStateStore(),
    )

    assert response.recommendations is not None
    assert recommendation_provider.travel_routes == ()


@pytest.mark.asyncio
async def test_staged_recommendation_stops_after_max_refill_attempts() -> None:
    store = InMemoryStateStore()
    tool_provider = _RefillPlacesToolProvider()
    tool_provider._places = [
        place.model_copy(update={"operating_schedule": _CLOSED_ALL_WEEK_SCHEDULE})
        for place in tool_provider._places
    ]

    await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        llm=_LLMProviderWithGeneralAnswer(),
        tool_provider=tool_provider,
        recommendation_provider=RealRecommendationProvider(),
        enrichment_provider=_CountingEnrichmentProvider(),
        store=store,
    )

    # 최초 1회 + 보충 최대 2회. 후보가 계속 부족해도 네 번째 호출은 하지 않는다.
    assert len(tool_provider.requests) == 3


async def _run_staged_recommend(
    tool_provider: FakeToolProvider,
    *,
    store: InMemoryStateStore | None = None,
    user_input: str = "경복궁 근처 카페 추천해줘",
    stream_event_sink=None,
):
    """실제 D(RealRecommendationProvider)를 태워 staged 경로만 돌리는 공통 실행부."""
    return await run_agent_flow(
        AgentRequest(
            user_input=user_input,
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        llm=_LLMProviderWithGeneralAnswer(),
        tool_provider=tool_provider,
        recommendation_provider=RealRecommendationProvider(),
        enrichment_provider=_CountingEnrichmentProvider(),
        store=store if store is not None else InMemoryStateStore(),
        stream_event_sink=stream_event_sink,
    )


@pytest.mark.parametrize(
    ("candidate_limit", "page_size", "expected_requests"),
    [
        # 첫 조회에서 6곳이 하드 필터를 통과한다. result_limit(5)은 이미 넘었지만
        # candidate_limit(10)에는 못 미치므로 보충이 돈다 — 목표가 result_limit이면
        # 여기서 1회로 끝나버린다.
        (10, 10, 3),
        # 같은 6곳이라도 candidate_limit이 6이면 목표를 채웠으니 보충하지 않는다.
        (6, 6, 1),
    ],
)
@pytest.mark.asyncio
async def test_staged_recommendation_refill_target_is_candidate_limit(
    monkeypatch: pytest.MonkeyPatch,
    candidate_limit: int,
    page_size: int,
    expected_requests: int,
) -> None:
    """보충 조회 목표는 recommendation_candidate_limit이다.

    하드 필터를 통과한 후보를 설정된 후보 상한만큼 모아두고 그 안에서 고른다 —
    최종 노출 개수(result_limit)를 채운 시점에 멈추지 않는다.
    """
    monkeypatch.setattr(
        "app.services.runtime.agent_runtime.settings.recommendation_candidate_limit",
        candidate_limit,
    )
    tool_provider = _RefillPlacesToolProvider(
        page_size=page_size,
        open_indexes={0, 1, 2, 3, 4, 5},
    )

    response = await _run_staged_recommend(tool_provider)

    assert len(tool_provider.requests) == expected_requests
    assert response.recommendations is not None


@pytest.mark.asyncio
async def test_staged_recommendation_skips_refill_when_pool_smaller_than_limit() -> None:
    """C가 candidate_limit보다 적게 반환했으면 반경을 다 긁은 것이라 보충하지 않는다.

    candidate_pool_truncated 경고는 C가 상한(100행)을 넘겨 요청했을 때만 서기
    때문에, 반경 안에 후보가 애초에 몇 개 없는 흔한 경우는 이 조건으로만 걸린다.
    """
    # 전체 6곳(열린 곳은 refill-0 하나) < candidate_limit(10).
    tool_provider = _RefillPlacesToolProvider(total=6)

    response = await _run_staged_recommend(tool_provider)

    assert len(tool_provider.requests) == 1
    assert response.recommendations is not None


class _WeatherDivergingRefillToolProvider(_RefillPlacesToolProvider):
    """최초 조회에만 날씨를 싣는 대역 — 보충 조회에서 기상 조회가 실패한 상황."""

    def _build_context(
        self,
        places: list[PlaceCandidate],
        call_index: int,
    ) -> RecommendationContext:
        context = super()._build_context(places, call_index)
        if call_index > 0:
            return context
        return context.model_copy(
            update={
                "weather": ContextValue(
                    status="success",
                    data=WeatherForecast(
                        forecast_for=now_kst(),
                        precipitation="rain",
                        sky="cloudy",
                        temperature_celsius=18.0,
                    ),
                )
            }
        )


@pytest.mark.asyncio
async def test_staged_recommendation_reuses_first_batch_weather_for_refill_batches() -> None:
    """보충 조회에서 날씨가 빠져도 배치를 버리지 않고 첫 배치 판정을 재사용한다.

    보충 조회는 같은 요청·같은 시각·같은 좌표를 다시 조회하는 것이라, 날씨가
    달라졌다면 그건 판정이 바뀐 게 아니라 그쪽 기상 조회가 실패한 것이다.
    하드 필터는 날씨를 입력으로 받지도 않으므로(prepare_candidates), 여기서
    배치를 거부하면 멀쩡한 보충 후보만 통째로 버리게 된다.
    """
    tool_provider = _WeatherDivergingRefillToolProvider()

    response = await _run_staged_recommend(tool_provider)

    # 날씨가 달라져도 보충이 중단되지 않는다.
    assert len(tool_provider.requests) == 3
    assert response.recommendations is not None
    shown = [
        *response.recommendations.recommendations,
        *response.recommendations.unverified_recommendations,
    ]
    # 날씨가 없던 보충 배치의 후보도 추천에 남아 있다.
    from_refill_batches = [item for item in shown if item.place_id != "refill-0"]
    assert from_refill_batches
    # 그리고 첫 배치의 날씨 판정으로 채점됐다 — 재사용이 아니었다면 weather
    # Feature가 결측(None)이 되고 "날씨 확인 못 함" warning이 붙는다.
    for item in from_refill_batches:
        assert item.feature_scores.get("weather") is not None


class _BrokenLocationRefillToolProvider(_RefillPlacesToolProvider):
    """보충 조회 응답만 location을 잃은 대역 — D의 prepare()가 AppError를 던진다."""

    def _build_context(
        self,
        places: list[PlaceCandidate],
        call_index: int,
    ) -> RecommendationContext:
        context = super()._build_context(places, call_index)
        if call_index == 0:
            return context
        return context.model_copy(update={"location": None})


@pytest.mark.asyncio
async def test_staged_recommendation_drops_refill_batch_when_prepare_raises() -> None:
    """보충 Context가 장소는 실었지만 location이 없으면 prepare()가 AppError를 던진다.

    응답 status와 place_id 유무만 보는 가드로는 이 조합이 안 걸려서, 보충 실패가
    요청 전체를 죽였다.
    """
    tool_provider = _BrokenLocationRefillToolProvider()

    response = await _run_staged_recommend(tool_provider)

    assert len(tool_provider.requests) == 2
    assert response.recommendations is not None
    shown = [
        *response.recommendations.recommendations,
        *response.recommendations.unverified_recommendations,
    ]
    assert [item.place_id for item in shown] == ["refill-0"]


@pytest.mark.asyncio
async def test_staged_recommendation_refill_progress_does_not_move_backwards() -> None:
    """보충 조회 중에도 progress stage는 scoring을 유지한다.

    프론트(AgentProgressMessage.tsx)는 stage로 진행 순서를 그리고 문구만 서버
    message로 덮어쓴다 — 여기서 fetching_context를 다시 보내면 완료 표시가 뒤로
    돌아간다.
    """
    events: list[tuple[str, dict[str, object]]] = []

    async def sink(event: str, payload: dict[str, object]) -> None:
        events.append((event, payload))

    tool_provider = _RefillPlacesToolProvider()
    await _run_staged_recommend(tool_provider, stream_event_sink=sink)

    assert len(tool_provider.requests) > 1  # 보충이 실제로 돌았다
    stages = [payload["stage"] for event, payload in events if event == "progress"]
    assert "scoring" in stages
    # scoring 이후에는 그보다 앞 단계로 되돌아가지 않는다.
    assert "fetching_context" not in stages[stages.index("scoring") :]
    messages = [payload["message"] for event, payload in events if event == "progress"]
    assert "조건에 맞는 장소를 조금 더 찾고 있어요." in messages


@pytest.mark.asyncio
async def test_staged_recommendation_all_closed_triggers_no_data_closed() -> None:
    """보충까지 돌고도 전부 폐점이면 no_data_closed 되묻기로 이어져야 한다.

    excluded_all_closed는 병합된 제외 목록 전체가 CLOSED일 때만 참이다 —
    배치를 합치면서 제외 사유 집계가 어긋나면 이 되묻기가 조용히 사라진다.
    """
    tool_provider = _RefillPlacesToolProvider()
    tool_provider._places = [
        place.model_copy(update={"operating_schedule": _CLOSED_ALL_WEEK_SCHEDULE})
        for place in tool_provider._places
    ]
    store = InMemoryStateStore()

    response = await _run_staged_recommend(tool_provider, store=store)

    assert response.llm_output.status == OutputStatus.NEEDS_CLARIFICATION
    clarification = response.llm_output.clarification
    assert clarification is not None
    assert clarification.code == "no_data_closed"
    context = get_session_context(response.state.session_id, store=store)
    assert context.pending_clarification == "no_data_closed"


@pytest.mark.asyncio
async def test_staged_recommendation_merges_refill_places_into_tool_context() -> None:
    """보충으로 받은 장소도 tool_context에 합쳐져 후속 C 보강 조회로 넘어가야 한다.

    to_candidate_enrichment_request()는 원본 places에서 place_id를 못 찾은 후보를
    조용히 버린다 — 병합을 빠뜨리면 보충으로 추천된 장소만 혼잡도 보강에서
    사라지고, 그 사실이 아무 데도 안 드러난다.
    """
    tool_provider = _RefillPlacesToolProvider()
    enrichment_provider = _CountingEnrichmentProvider()

    response = await run_agent_flow(
        AgentRequest(
            # "조용" → FakeLLMProvider가 concentration_intent=AVOID를 세워
            # 6-1단계 혼잡도 보강 조회가 실제로 돈다.
            user_input="경복궁 근처 조용한 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        llm=_LLMProviderWithGeneralAnswer(),
        tool_provider=tool_provider,
        recommendation_provider=RealRecommendationProvider(),
        enrichment_provider=enrichment_provider,
        store=InMemoryStateStore(),
    )

    assert len(tool_provider.requests) > 1
    assert response.recommendations is not None
    shown = [
        *response.recommendations.recommendations,
        *response.recommendations.unverified_recommendations,
    ]
    refill_ids = {item.place_id for item in shown if item.place_id != "refill-0"}
    assert refill_ids  # 보충으로 들어온 후보가 실제로 추천됐다
    assert enrichment_provider.last_request is not None
    enriched_ids = {target.place_id for target in enrichment_provider.last_request.candidates}
    assert refill_ids <= enriched_ids


async def _run_with_partial_places(places: list[PlaceCandidate]):
    """실제 D(RealRecommendationProvider)까지 태워 A→C→D 전파를 확인한다.

    _CountingRecommendationProvider는 호출 횟수만 세는 stub이라 분류 로직을 타지
    않는다. 통합 검증에는 실제 구현을 주입해야 한다.
    """
    return await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        llm=_LLMProviderWithGeneralAnswer(),
        tool_provider=_PartialPlacesToolProvider(places),
        recommendation_provider=RealRecommendationProvider(),
        enrichment_provider=_CountingEnrichmentProvider(),
        store=InMemoryStateStore(),
    )


@pytest.mark.asyncio
async def test_partial_context_keeps_all_candidates_and_splits_unverified() -> None:
    """partial Context의 후보가 누락 없이 D까지 가고, 운영정보 유무로 나뉜다.

    Supabase 상세조회로 전환한 뒤 DB에 없는 장소는 운영정보가 비는데(detail no_data),
    그 후보가 중간에 사라지면 추천 수가 조용히 줄고, 잘못 분류되면 운영시간을 모르는
    곳을 확정 추천하게 된다.
    """
    response = await _run_with_partial_places(
        [
            _context_place("with-1", with_schedule=True),
            _context_place("without-1", with_schedule=False),
            _context_place("without-2", with_schedule=False),
        ]
    )

    assert response.recommendations is not None
    verified = [item.place_id for item in response.recommendations.recommendations]
    unverified = [item.place_id for item in response.recommendations.unverified_recommendations]

    # C가 준 3건이 그대로 유지된다.
    assert len(verified) + len(unverified) == 3
    assert verified == ["with-1"]
    assert sorted(unverified) == ["without-1", "without-2"]


@pytest.mark.asyncio
async def test_partial_context_with_no_operating_hours_returns_only_unverified() -> None:
    """전건 운영정보가 없으면 확정 추천은 비고 unverified만 남는다.

    현재는 이 경우에도 "이런 곳들을 찾아봤어요:"가 나간다 — 첫 문장에서 미확인임을
    알리는 편이 나을 수 있으나, 메시지 정책은 별도 판단 대상이라 현 동작을 고정한다.
    """
    response = await _run_with_partial_places(
        [
            _context_place("without-1", with_schedule=False),
            _context_place("without-2", with_schedule=False),
        ]
    )

    assert response.recommendations is not None
    assert response.recommendations.recommendations == []
    assert len(response.recommendations.unverified_recommendations) == 2


class _ClosedOnlyRecommendationProvider:
    """D 대역 — ignore_operating_hours 유무로 결과 유무가 바뀐다.

    실제로는 domain/scoring.py가 폐점 후보를 걸러내고 D의
    recommendation_pipeline.py가 excluded_all_closed를 계산하지만
    (test_scoring.py/test_recommendation_pipeline.py가 그 계산 자체를 검증한다),
    여기서는 그 결과 모양만 고정으로 흉내 내 no_data_closed 되묻기의 A 쪽 배선
    (agent_runtime.py)만 검증한다.
    """

    def __init__(self) -> None:
        self.calls: list[bool] = []

    async def recommend(
        self,
        conditions: UserConditions,
        context: RecommendationContext,
        excluded_place_ids: list[str],
        limit: int = 5,
        ignore_operating_hours: bool = False,
    ) -> RecommendationResponse:
        self.calls.append(ignore_operating_hours)
        if not ignore_operating_hours:
            return RecommendationResponse(
                recommendations=[],
                unverified_recommendations=[],
                elapsed_ms=0,
                excluded_all_closed=True,
            )
        return RecommendationResponse(
            recommendations=[],
            unverified_recommendations=[_item("closed-1")],
            elapsed_ms=0,
        )


@pytest.mark.asyncio
async def test_no_data_closed_triggers_clarification_with_show_closed_button() -> None:
    """실사용 피드백(2026-08-13): "조건에 맞는 곳을 찾지 못했어요" 대신, 원인이
    전부 폐점이면 "운영 중이 아닌 곳도 확인하시겠어요?" 되묻기 버튼을 띄워야
    한다."""
    store = InMemoryStateStore()
    providers = _providers()
    providers["recommendation_provider"] = _ClosedOnlyRecommendationProvider()

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert response.llm_output.status == OutputStatus.NEEDS_CLARIFICATION
    clarification = response.llm_output.clarification
    assert clarification is not None
    assert clarification.code == "no_data_closed"
    option_ids = {option.id for option in clarification.options}
    assert option_ids == {"show_closed"}
    context = get_session_context(response.state.session_id, store=store)
    assert context.pending_clarification == "no_data_closed"


@pytest.mark.asyncio
async def test_clarification_choice_show_closed_reruns_ignoring_operating_hours() -> None:
    """"운영 중이 아닌 곳도 볼게요" 클릭은 classify_intent() 재호출 없이 같은
    조건으로 D를 다시 부르되, 이번엔 ignore_operating_hours=True로 폐점 후보도
    채점에 포함해야 한다."""
    store = InMemoryStateStore()
    providers = _providers()
    provider = _ClosedOnlyRecommendationProvider()
    providers["recommendation_provider"] = provider

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert first.llm_output.status == OutputStatus.NEEDS_CLARIFICATION

    resolved = await run_agent_flow(
        AgentRequest(
            user_input="운영 중이 아닌 곳도 볼게요",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
            clarification_choice="show_closed",
        ),
        store=store,
        **providers,
    )

    assert resolved.llm_output.status == OutputStatus.COMPLETE
    assert resolved.recommendations is not None
    assert len(resolved.recommendations.unverified_recommendations) == 1
    assert provider.calls == [False, True]
    context = get_session_context(resolved.state.session_id, store=store)
    assert context.pending_clarification is None


@pytest.mark.asyncio
async def test_show_closed_choice_keeps_ignoring_operating_hours_on_later_turns() -> None:
    """실사용 피드백(2026-08-13): "운영 중이 아닌 곳도 볼게요"를 한 번 누르면,
    이후 버튼을 다시 누르지 않은 새 RECOMMEND 요청에서도 TTL 동안은 계속
    폐점 후보를 포함해야 한다 — 매 턴 다시 물으면 안 된다."""
    store = InMemoryStateStore()
    providers = _providers()
    provider = _ClosedOnlyRecommendationProvider()
    providers["recommendation_provider"] = provider

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    resolved = await run_agent_flow(
        AgentRequest(
            user_input="운영 중이 아닌 곳도 볼게요",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
            clarification_choice="show_closed",
        ),
        store=store,
        **providers,
    )
    assert resolved.llm_output.status == OutputStatus.COMPLETE

    later = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 박물관도 추천해줘",
            session_id=resolved.state.session_id,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert later.llm_output.status == OutputStatus.COMPLETE
    assert later.llm_output.clarification is None
    assert later.recommendations is not None
    assert len(later.recommendations.unverified_recommendations) == 1
    assert provider.calls == [False, True, True]
    context = get_session_context(later.state.session_id, store=store)
    assert context.ignore_operating_hours_until is not None


class _ExhaustedNoDataToolProvider:
    """C 대역 — TourAPI raw candidates는 있었지만 excluded_place_ids로 전부
    소진된 상황(원인2)을 흉내 낸다. places.status는 "no_data"지만
    provider_metadata.status는 "success"로 남긴다(nearby_place_details.py의
    `if not selected:` 경로와 agent_context/mappers.py::map_places_context가
    원본 metadata를 그대로 싣는 것을 흉내 낸다)."""

    def __init__(self) -> None:
        self.call_count = 0

    async def fetch_context(self, request: AgentContextRequest) -> AgentContextResponse:
        self.call_count += 1
        return AgentContextResponse(
            request_id=request.request_id,
            intent="RECOMMEND",
            status="no_data",
            context=RecommendationContext(
                location=ContextValue(
                    status="success",
                    data=ResolvedLocation(
                        requested_query="경복궁",
                        resolved_name="경복궁",
                        source="query",
                        location=Coordinates(latitude=37.5788, longitude=126.9770),
                    ),
                ),
                places=ContextValue(
                    status="no_data",
                    data=[],
                    provider_metadata=[
                        ProviderMetadata(
                            source="tourapi",
                            status="success",
                            retrieved_at=datetime.now(UTC),
                        )
                    ],
                ),
            ),
            metadata=ResponseMetadata(),
        )


@pytest.mark.asyncio
async def test_no_data_exhausted_triggers_clarification_with_five_buttons() -> None:
    """원인2(이전 노출/거절 소진)는 provider_metadata가 "success"로 남아 원인1+3과
    구분된다 — "제외했던 곳도 다시 보기" 대신 조건을 바꾸는 선택지들을 보여준다
    (실사용 피드백 후속 조사, 2026-08-13)."""
    store = InMemoryStateStore()
    providers = _providers()
    providers["tool_provider"] = _ExhaustedNoDataToolProvider()

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert response.llm_output.status == OutputStatus.NEEDS_CLARIFICATION
    clarification = response.llm_output.clarification
    assert clarification is not None
    assert clarification.code == "no_data_exhausted"
    option_ids = {option.id for option in clarification.options}
    assert option_ids == {
        "widen_category",
        "widen_radius",
        "different_area",
        "ignore_weather",
        "custom_conditions",
    }
    assert len(clarification.options) <= 5
    context = get_session_context(response.state.session_id, store=store)
    assert context.pending_clarification == "no_data_exhausted"


@pytest.mark.asyncio
async def test_clarification_choice_no_data_exhausted_widens_category_and_reruns() -> None:
    store = InMemoryStateStore()
    providers = _providers()
    providers["tool_provider"] = _ExhaustedNoDataToolProvider()

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert first.llm_output.status == OutputStatus.NEEDS_CLARIFICATION

    providers["tool_provider"] = _CountingToolProvider()
    resolved = await run_agent_flow(
        AgentRequest(
            user_input="다른 종류의 장소도 보기",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
            clarification_choice="widen_category",
        ),
        store=store,
        **providers,
    )

    assert resolved.llm_output.status == OutputStatus.COMPLETE
    assert resolved.state.user_conditions.place_types == []
    assert resolved.state.user_conditions.place_tags == []
    context = get_session_context(resolved.state.session_id, store=store)
    assert context.pending_clarification is None


@pytest.mark.asyncio
async def test_clarification_choice_no_data_exhausted_custom_conditions_is_terminal() -> None:
    """"새로운 조건 직접 말할게요"는 Tool을 다시 부르지 않고 바로 끝난다(케이스5의
    full_reset과 동일 패턴)."""
    store = InMemoryStateStore()
    providers = _providers()
    tool_provider = _ExhaustedNoDataToolProvider()
    providers["tool_provider"] = tool_provider

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    resolved = await run_agent_flow(
        AgentRequest(
            user_input="새로운 조건 직접 말할게요",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
            clarification_choice="custom_conditions",
        ),
        store=store,
        **providers,
    )

    assert resolved.llm_output.status == OutputStatus.COMPLETE
    assert resolved.recommendations is None
    assert resolved.message == "새로운 조건을 알려주세요!"
    assert tool_provider.call_count == 1
    context = get_session_context(resolved.state.session_id, store=store)
    assert context.pending_clarification is None


@pytest.mark.asyncio
async def test_clarification_choice_no_data_empty_widen_radius_reruns_search() -> None:
    store = InMemoryStateStore()
    providers = _providers()
    providers["tool_provider"] = _FixedStatusToolProvider("no_data")

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert first.llm_output.clarification is not None
    assert first.llm_output.clarification.code == "no_data_empty"

    providers["tool_provider"] = _CountingToolProvider()
    resolved = await run_agent_flow(
        AgentRequest(
            user_input="검색 범위 넓히기",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
            clarification_choice="widen_radius",
        ),
        store=store,
        **providers,
    )

    assert resolved.llm_output.status == OutputStatus.COMPLETE
    assert resolved.state.user_conditions.max_travel_time == _WIDEN_RADIUS_MAX_TRAVEL_TIME
    context = get_session_context(resolved.state.session_id, store=store)
    assert context.pending_clarification is None


class _TwoCandidateRecommendationProvider:
    """D 대역 — SCHEDULE-10 최소 개수(3개, time_available>=210분)보다 적은 2개만
    돌려준다. planner.py의 `len(request.candidates) < min_items` 가드가 걸려
    plan_schedule()이 LLM 호출 없이 바로 빈 ScheduleResult를 반환한다."""

    def __init__(self) -> None:
        self.calls: list[UserConditions] = []

    async def recommend(
        self,
        conditions: UserConditions,
        context: RecommendationContext,
        excluded_place_ids: list[str],
        limit: int = 5,
        ignore_operating_hours: bool = False,
    ) -> RecommendationResponse:
        self.calls.append(conditions)
        return RecommendationResponse(
            recommendations=[_item("p1"), _item("p2")],
            unverified_recommendations=[],
            elapsed_ms=0,
        )


@pytest.mark.asyncio
async def test_clarification_choice_schedule_no_candidates_stays_schedule_intent() -> None:
    """실사용 버그(2026-08-13): SCHEDULE 후보 부족 되묻기의 "다른 종류의 장소도
    포함해서 찾기"를 누르면, 조건 병합이 MODIFY/CHANGE_CONDITION 경로를 타더라도
    최종 라벨은 SCHEDULE로 유지돼야 한다 — 그래야 다시 일정 편성을 시도하지,
    RECOMMEND 결과로 새지 않는다."""
    store = InMemoryStateStore()
    providers = _providers()
    provider = _TwoCandidateRecommendationProvider()
    providers["recommendation_provider"] = provider

    first = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처에서 2시간 코스 짜줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )
    assert first.llm_output.intent == "SCHEDULE"
    assert first.llm_output.status == OutputStatus.NEEDS_CLARIFICATION
    assert first.llm_output.clarification is not None
    assert first.llm_output.clarification.code == "schedule_no_candidates"
    option_ids = {option.id for option in first.llm_output.clarification.options}
    assert option_ids == {"schedule_relax_area", "schedule_relax_category"}
    assert all(
        option.resolved_intent == "SCHEDULE" for option in first.llm_output.clarification.options
    )

    resolved = await run_agent_flow(
        AgentRequest(
            user_input="다른 종류의 장소도 포함해서 찾기",
            session_id=first.state.session_id,
            device_location=DEVICE_LOCATION,
            clarification_choice="schedule_relax_category",
        ),
        store=store,
        **providers,
    )

    # 후보는 여전히 2개뿐이라 이번에도 편성엔 실패하지만, 핵심 회귀 포인트는
    # intent가 MODIFY로 새지 않고 SCHEDULE로 유지되는지다.
    assert resolved.llm_output.intent == "SCHEDULE"
    assert resolved.llm_output.status == OutputStatus.NEEDS_CLARIFICATION
    assert resolved.recommendations is None
    assert resolved.state.user_conditions.place_types == []
    assert resolved.state.user_conditions.place_tags == []
    context = get_session_context(resolved.state.session_id, store=store)
    assert context.last_intent == "SCHEDULE"


@pytest.mark.asyncio
async def test_schedule_offers_show_closed_before_no_candidates_loop() -> None:
    """실사용 버그(2026-08-13): "경복궁 반나절 코스 짜줘"가 심야라 전부 폐점 후보뿐이면,
    SCHEDULE도 RECOMMEND/MODIFY와 동일하게 "운영 중이 아닌 곳도 볼게요"를 먼저
    제안해야 한다. 그렇지 않으면 실제 원인(운영시간)과 무관한 지역/카테고리 변경
    버튼(schedule_no_candidates)만 계속 돌아 무한 되묻기가 된다."""
    store = InMemoryStateStore()
    providers = _providers()
    providers["recommendation_provider"] = _ClosedOnlyRecommendationProvider()

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처에서 반나절 코스 짜줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        **providers,
    )

    assert response.llm_output.intent == "SCHEDULE"
    assert response.llm_output.status == OutputStatus.NEEDS_CLARIFICATION
    clarification = response.llm_output.clarification
    assert clarification is not None
    assert clarification.code == "no_data_closed"
    option_ids = {option.id for option in clarification.options}
    assert option_ids == {"show_closed"}
    assert clarification.options[0].resolved_intent == "SCHEDULE"
    context = get_session_context(response.state.session_id, store=store)
    assert context.pending_clarification == "no_data_closed"


class _SlowSchedulePlanLLM(_LLMProviderWithGeneralAnswer):
    """generate_schedule_plan()이 heartbeat 간격보다 오래 걸리는 상황을 흉내 낸다.

    실사용 피드백(2026-08-13): SCHEDULE 편성 호출이 수십 초씩 걸리는데 로딩
    화면이 그동안 "장소 순서와 머무는 시간을 구성하고 있어요." 문구 하나로
    멈춰 보인다 — _await_with_heartbeat()가 이 구간에도 progress 이벤트를
    주기적으로 흘려보내는지 검증한다.
    """

    async def generate_schedule_plan(self, request):
        await asyncio.sleep(0.05)
        return await super().generate_schedule_plan(request)


@pytest.mark.asyncio
async def test_schedule_heartbeat_emits_progress_during_slow_planning() -> None:
    store = InMemoryStateStore()
    providers = _providers()
    providers["llm"] = _SlowSchedulePlanLLM()
    events: list[tuple[str, dict[str, object]]] = []

    async def sink(event: str, payload: dict[str, object]) -> None:
        events.append((event, payload))

    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처에서 반나절 코스 짜줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=store,
        stream_event_sink=sink,
        **providers,
    )

    assert response.llm_output.intent == "SCHEDULE"
    scheduling_events = [
        payload
        for event, payload in events
        if event == "progress" and payload["stage"] == "scheduling"
    ]
    # 최초 1건("장소 순서와...")은 항상 있다. heartbeat 간격(6초)보다 훨씬 짧게 재웠으니
    # 추가 heartbeat는 안 왔어야 정상 — 이 테스트는 "느릴 때 최소 1건은 보장된다"만
    # 확인하고, 실제 heartbeat 반복은 아래 단위 테스트가 별도로 검증한다.
    assert len(scheduling_events) >= 1


@pytest.mark.asyncio
async def test_await_with_heartbeat_emits_progress_until_task_completes() -> None:
    from app.services.runtime.agent_runtime import _await_with_heartbeat

    events: list[tuple[str, dict[str, object]]] = []

    async def sink(event: str, payload: dict[str, object]) -> None:
        events.append((event, payload))

    async def slow_task() -> str:
        await asyncio.sleep(0.05)
        return "done"

    result = await _await_with_heartbeat(
        slow_task(),
        sink=sink,
        stage="scheduling",
        messages=("계속 진행 중이에요.",),
        interval_seconds=0.01,
    )

    assert result == "done"
    scheduling_events = [p for e, p in events if e == "progress" and p["stage"] == "scheduling"]
    assert len(scheduling_events) >= 2
    assert all(p["message"] == "계속 진행 중이에요." for p in scheduling_events)


@pytest.mark.asyncio
async def test_turn_opens_a_root_observation_so_it_stays_one_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """한 턴은 관측에서 **trace 하나**여야 한다 — 루트 span이 그 부모 자리다.

    2026-08-25 첫 실측에서 실제로 깨져 있었다. 속성만 전파하고(`trace_attributes`)
    루트 span을 안 만들면, 부모가 없는 observation이 저마다 자기가 trace 루트가
    되어 `classify_intent`와 `extract_recommend_conditions`가 **별도 trace**로
    올라갔다. 화면에서 "이 턴이 무슨 일을 했나"를 볼 수 없다.

    실 서버까지 확인하는 건 `scripts/verify_langfuse_tracing.py`의 기준 (e)다.
    여기서는 네트워크 없이 루트가 열리는지, 그리고 **본체보다 먼저** 열리는지만
    잡는다 — 나중에 열면 앞선 LLM 호출이 이미 밖으로 나가버린다.
    """

    opened: list[str] = []
    real_observe_step = agent_runtime_module.observe_step

    @contextmanager
    def _spy(name: str, **kwargs: object):
        opened.append(name)
        with real_observe_step(name, **kwargs) as recorder:  # type: ignore[arg-type]
            yield recorder

    monkeypatch.setattr(agent_runtime_module, "observe_step", _spy)

    providers = _providers()
    await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        store=InMemoryStateStore(),
        **providers,
    )

    assert opened, "턴을 감싸는 루트 관측이 열리지 않았다 — trace가 조각난다."
    assert opened[0] == "agent_turn"


# --- 루트 span 요약: 목록 화면이 읽히게 한다 ---------------------------------


@pytest.mark.asyncio
async def test_turn_summary_says_what_the_turn_was() -> None:
    """루트는 SPAN이라 토큰·비용이 없다. 그래서 요약이 없으면 행에 이름과 지연만 남는다."""
    providers = _providers()
    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        **providers,
    )

    summary = summarize_turn(response)

    # 같은 객체에서 뽑은 값끼리 비교하면 항진명제다 — 기대값을 직접 적는다.
    assert summary["intent"] == "RECOMMEND"
    assert summary["status"] == "complete"
    assert summary["card_count"] > 0
    assert summary["message_length"] == len(response.message)
    # 목록 행에 뜨는 한 줄. 마스킹을 타지 않는 자리로 나간다.
    assert summary["headline"].startswith("RECOMMEND · complete · 카드 ")


@pytest.mark.asyncio
async def test_turn_summary_carries_no_utterance_or_answer_text() -> None:
    """발화도 답변도 싣지 않는다 — intent와 결과 모양만으로 목록이 읽힌다."""
    providers = _providers()
    response = await run_agent_flow(
        AgentRequest(
            user_input="경복궁 근처 카페 추천해줘",
            session_id=None,
            device_location=DEVICE_LOCATION,
        ),
        **providers,
    )

    blob = json.dumps(summarize_turn(response), ensure_ascii=False)

    assert "경복궁 근처 카페 추천해줘" not in blob
    if response.message:
        assert response.message not in blob


def test_turn_summary_names_the_payload_shape() -> None:
    """카드·일정·비교·장소정보 중 무엇이 나갔는지가 headline에 드러난다."""

    class _Resp:
        recommendations = None
        schedule = object()
        comparison = None
        info_place_card = None
        message = "일정을 만들었어요."

        class llm_output:  # noqa: N801
            class intent:
                value = "SCHEDULE"

            class status:
                value = "complete"

    summary = summarize_turn(_Resp())  # type: ignore[arg-type]

    assert summary["has_schedule"] is True
    assert summary["card_count"] == 0
    assert summary["headline"] == "SCHEDULE · complete · 일정"


def test_user_id_stays_off_until_the_switch_is_turned_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """개인정보를 외부 SaaS에 올리는 것은 팀 합의가 먼저다 — 코드가 먼저 들어가도 꺼짐이다.

    `capture_content`와 별개 축이라는 것도 함께 잠근다. 원문을 가려도 user_id는
    trace 속성이라 mask를 타지 않으므로, 묶어두면 "발화는 가리고 신원만 쌓는" 상태가
    실수로 만들어진다.
    """
    principal = Principal(user_id="user-abc", is_anonymous=False)
    monkeypatch.setattr(settings, "langfuse_capture_content", True)

    monkeypatch.setattr(settings, "langfuse_capture_user_id", False)
    assert agent_runtime_module._observed_user_id(principal) is None

    monkeypatch.setattr(settings, "langfuse_capture_user_id", True)
    assert agent_runtime_module._observed_user_id(principal) == "user-abc"
    assert agent_runtime_module._observed_user_id(None) is None
