"""C(Tool Intelligence)/D(Recommendation) 실제 계약 확정 전까지 쓰는 Fake 구현.

역할: 고정된 가짜 결과로 ToolProvider/RecommendationProvider 계약을 만족시켜, C/D 없이도
Agent Runtime 흐름을 끝까지 테스트할 수 있게 한다. app/providers/stub.py의 Fake provider들과
같은 결 — 실제 계산이 아니라 고정/임시 데이터를 반환한다.
ToolProvider는 A-C Context Contract v0으로 이미 확정됐으므로 FakeToolProvider는 실제
AgentContextResponse 구조를 그대로 흉내 낸다(계약이 바뀌기 전까지는 이 부분을 다시 갈아
엎을 필요가 없다). excluded_place_ids는 C의 책임이 아니므로 FakeToolProvider는 이제 후보를
거르지 않는다 — 그 필터링은 여전히 계약이 확정 전인 D 쪽 FakeRecommendationProvider가 한다.
호출 시점: app.services.runtime.agent_runtime.run_agent()가 C/D 계약 확정 전까지 기본으로
주입한다.
TODO: D 계약이 확정되면 FakeRecommendationProvider와 실제 구현체 분기를 손본다.
"""

from __future__ import annotations

from app.agent_context.schemas import (
    AgentContextRequest,
    AgentContextResponse,
    Clarification,
    ContextValue,
    PlaceCandidate,
    RecommendationContext,
    ResponseMetadata,
    WeatherForecast,
)
from app.schemas import RecommendationItem, RecommendationResponse, UserConditions
from app.state.schema import now_kst

_FAKE_CANDIDATES = (
    PlaceCandidate(
        place_id="runtime-stub-museum-1",
        name="런타임 스텁 박물관",
        category="museum",
        location={"latitude": 37.5796, "longitude": 126.9770},
        operating_hours_raw="09:00-18:00",
    ),
    PlaceCandidate(
        place_id="runtime-stub-cafe-1",
        name="런타임 스텁 카페",
        category="cafe",
        location={"latitude": 37.5798, "longitude": 126.9772},
        operating_hours_raw="08:00-22:00",
    ),
)


class FakeToolProvider:
    """조건과 무관하게 고정 후보·날씨를 반환하는 가짜 Tool provider.

    current_location과 search_center가 둘 다 없으면 계약(문서 §4.4)대로
    needs_clarification을 반환한다 — 형식 오류가 아니라 정상 상태다.
    """

    async def fetch_context(self, request: AgentContextRequest) -> AgentContextResponse:
        conditions = request.conditions
        metadata = ResponseMetadata()

        if not conditions.current_location and not conditions.search_center:
            return AgentContextResponse(
                request_id=request.request_id,
                intent=request.intent,
                contract_version="draft-v0",
                status="needs_clarification",
                context=None,
                clarification=Clarification(
                    code="location_required",
                    missing_fields=["current_location", "search_center"],
                    candidates=[],
                ),
                warnings=[],
                error=None,
                metadata=metadata,
            )

        return AgentContextResponse(
            request_id=request.request_id,
            intent=request.intent,
            contract_version="draft-v0",
            status="success",
            context=RecommendationContext(
                weather=ContextValue(
                    status="success",
                    data=WeatherForecast(condition="neutral", forecast_for=now_kst()),
                ),
                places=ContextValue(status="success", data=list(_FAKE_CANDIDATES)),
            ),
            warnings=[],
            error=None,
            metadata=metadata,
        )


class FakeRecommendationProvider:
    """RecommendationContext.places를 그대로 고정 추천 결과로 변환하는 가짜 provider.

    excluded_place_ids 필터링은 D의 책임이라 여기서 적용한다(C는 필터링하지 않는다).
    """

    async def recommend(
        self,
        conditions: UserConditions,
        context: RecommendationContext,
        excluded_place_ids: list[str],
    ) -> RecommendationResponse:
        excluded = set(excluded_place_ids)
        candidates = context.places.data if context.places and context.places.data else []
        items = [
            RecommendationItem(
                place_id=candidate.place_id,
                name=candidate.name,
                category=candidate.category,
                distance_km=0.3,
                remaining_minutes=120,
                environment_type="indoor",
                recommendation_reason="Agent Runtime 골격 검증용 고정 추천입니다.",
                warnings=[],
                score=0.5,
                feature_scores={},
                weights_used={},
            )
            for candidate in candidates
            if candidate.place_id not in excluded
        ]
        return RecommendationResponse(
            recommendations=items,
            unverified_recommendations=[],
            elapsed_ms=0,
        )


__all__ = ["FakeToolProvider", "FakeRecommendationProvider"]
