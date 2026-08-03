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

from app.agent_context.enrichment_schemas import (
    CandidateEnrichmentRequest,
    CandidateEnrichmentResponse,
)
from app.agent_context.schemas import (
    AgentContextRequest,
    AgentContextResponse,
    ContextValue,
    Coordinates,
    PlaceCandidate,
    RecommendationContext,
)
from app.providers.contracts import ProviderSource, provider_result
from app.providers.stub import FakeLLMProvider, FakeWeatherProvider
from app.schemas import (
    AgentRequest,
    ConcentrationIntent,
    OutputStatus,
    RecommendationItem,
    RecommendationResponse,
    UserConditions,
)
from app.services.runtime.agent_runtime import _apply_concentration_rerank, run_agent_flow
from app.services.runtime.info_context_schemas import InfoContextRequest, InfoContextResponse
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
        self._inner = FakeToolProvider()

    async def fetch_context(self, request: AgentContextRequest) -> AgentContextResponse:
        self.call_count += 1
        self.last_request = request
        return await self._inner.fetch_context(request)

    async def fetch_info_context(self, request: InfoContextRequest) -> InfoContextResponse:
        self.info_call_count += 1
        self.last_info_request = request
        return await self._inner.fetch_info_context(request)


class _CountingRecommendationProvider:
    """rerank_with_concentration()을 일부러 갖지 않는다 — Real D가 아직 2차
    Scoring을 구현하지 않은 상태를 재현한다(hasattr 가드 확인용, 기본 fixture)."""

    def __init__(self) -> None:
        self.call_count = 0
        self._inner = FakeRecommendationProvider()

    async def recommend(self, conditions, context, excluded_place_ids):
        self.call_count += 1
        return await self._inner.recommend(conditions, context, excluded_place_ids)


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
        "weather_provider": FakeWeatherProvider(),
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
async def test_info_other_question_type_does_not_call_tool_provider() -> None:
    """concentration이 아닌 INFO question_type은 기존처럼 C를 거치지 않는다(회귀 확인)."""
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
    assert providers["tool_provider"].info_call_count == 0
    assert "준비 중" in response.message


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
async def test_concentration_intent_not_yet_persisted_by_b_blocks_rerank() -> None:
    """알려진 갭(2026-07-30 발견): B의 StateUserConditions에 concentration_intent
    필드가 아직 없어서(state/schema.py, field_spec.py — B 확인 필요), LLM이
    SEEK/AVOID를 정확히 추출해도 apply()를 거치는 순간 사라진다. 그 결과 6-1
    분기(_apply_concentration_rerank) 자체가 지금은 실제 run_agent_flow() 흐름에서
    트리거되지 않는다 — B가 필드를 추가하면 이 테스트는 깨져야 정상이고, 그때
    아래 두 assert를 뒤집어서 실제 동작을 검증하는 테스트로 바꿔야 한다.
    6-1 분기 로직 자체(_apply_concentration_rerank)는 이 B 갭과 무관하게
    TestApplyConcentrationRerank에서 직접 단위 테스트한다.
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

    assert response.llm_output.recommend.conditions.concentration_intent == "SEEK"  # LLM은 맞음
    # B의 StateUserConditions에 필드 자체가 없다 — hasattr로 "필드 부재"를 직접 증명한다.
    assert not hasattr(response.state.user_conditions, "concentration_intent")
    assert providers["enrichment_provider"].call_count == 0  # 그래서 6-1이 안 탐


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
