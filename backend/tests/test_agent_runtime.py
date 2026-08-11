"""Agent Runtime(run_agent_flow)의 A→B→A→C→A→D→A→B 흐름 통합 테스트.

FakeLLMProvider/FakeToolProvider/FakeRecommendationProvider와 B의
실제 apply()/get_session_context()를 조합해서 검증한다(팩토리는 거치지 않음 —
test_state_integration.py와 같은 스타일).
FakeToolProvider는 A-C Context Contract v0(docs/design/a-c-context-contract-draft.md)를
그대로 흉내 낸다 — C 단계 자체의 needs_clarification은 LLM 단계 needs_clarification과
별개 레이어라 따로 테스트한다.
"""

from __future__ import annotations

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
    RecommendationContext,
    ResolvedLocation,
    ResponseMetadata,
)
from app.domain.scoring import SCORING_VERSION
from app.providers.contracts import ProviderSource, provider_result
from app.providers.gemini_prompts import PROMPT_VERSION
from app.providers.stub import FakeLLMProvider
from app.schemas import (
    AgentRequest,
    ConcentrationIntent,
    OutputStatus,
    RecommendationItem,
    RecommendationResponse,
    UserConditions,
)
from app.services.runtime.agent_runtime import _apply_concentration_rerank, run_agent_flow
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
from app.state.service import get_session_context
from app.state.store import InMemoryStateStore

DEVICE_LOCATION = "37.5788,126.9770"


class _LLMProviderWithGeneralAnswer(FakeLLMProvider):
    """FakeLLMProvider + generate_general_answer()만 로컬로 보강한 테스트 전용 더블.

    app/providers/stub.py의 FakeLLMProvider는 건드리지 않는다(Fake 유지보수는
    이번 작업 범위 밖) — compose_chat_message()의 GENERAL 분기만 테스트하기 위한
    최소 보강이다.
    """

    async def generate_general_answer(self, topic, original_question):
        return provider_result("(테스트용 고정 답변)", source=ProviderSource.FAKE_LLM)


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

    async def fetch_compare_context(
        self, request: CompareContextRequest
    ) -> CompareContextResponse:
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

    async def recommend(self, conditions, context, excluded_place_ids, limit=5):
        self.call_count += 1
        self.last_limit = limit
        return await self._inner.recommend(conditions, context, excluded_place_ids, limit)


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
    assert by_step["llm_interpret"].prompt_version == PROMPT_VERSION
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
    assert compared.comparison.criteria == "distance"
    assert tool_provider.call_count == 1  # 첫 RECOMMEND의 일반 Context 조회만 수행
    assert tool_provider.compare_call_count == 1
    assert tool_provider.last_compare_request is not None
    assert [item.rank for item in tool_provider.last_compare_request.candidates] == [1, 2, 3, 4, 5]
    assert "런타임 스텁" in compared.message
    assert compared.tool_execution is not None
    assert compared.tool_execution.operation == "compare_fetch"


@pytest.mark.asyncio
async def test_second_turn_sends_consumed_place_ids_to_context_provider() -> None:
    """"다른 곳 보여줘"의 2회차에는 1회차 노출분이 C 요청에 실려야 한다.

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
    assert [execution.operation for execution in response.tool_executions] == [
        "info_concentration"
    ]
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
            user_input="경복궁 오늘 행사 있어?",
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
        assert [item.place_id for item in result.recommendations] == list(
            reversed(place_ids)
        )[:5]
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

    빈 후보로 Scoring을 돌려도 결과가 같으므로 호출하지 않는다. 사용자에게 나가는
    문구는 기존과 동일해야 한다 — 장애가 아니라 "조건에 맞는 곳이 없음"이다.
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
    assert "조건에 맞는 곳을 찾지 못했어요" in response.message
    # 일시적 장애 문구로 새면 안 된다.
    assert "일시적으로" not in response.message


@pytest.mark.asyncio
async def test_no_data_marks_pending_clarification_so_next_turn_keeps_conditions() -> None:
    """"범위를 넓혀볼까요?"에 대한 답변은 새 요청이 아니라 이번 요청의 연속이다.

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
    assert context.pending_clarification == "no_candidate"


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
    assert get_session_context(session_id, store=store).pending_clarification == "no_candidate"

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
    "time_ranges": [
        {"open_time": "00:00", "close_time": "23:59", "crosses_midnight": False}
    ],
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
                        location=Coordinates(latitude=37.5788, longitude=126.9770),
                    ),
                ),
                places=ContextValue(status="partial", data=self._places),
            ),
            metadata=ResponseMetadata(),
        )


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
    unverified = [
        item.place_id for item in response.recommendations.unverified_recommendations
    ]

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
