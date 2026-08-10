"""C(Tool Intelligence)/D(Recommendation) 테스트용 Fake 구현.

역할: 고정된 가짜 결과로 ToolProvider/RecommendationProvider 계약을 만족시켜, C/D 없이도
Agent Runtime 흐름을 끝까지 테스트할 수 있게 한다. app/providers/stub.py의 Fake provider들과
같은 결 — 실제 계산이 아니라 고정/임시 데이터를 반환한다.
ToolProvider·RecommendationProvider 모두 계약이 확정됐으므로([TECH-02]) run_agent()는
FakeToolProvider/FakeRecommendationProvider 대신 실제 구현체(get_context_provider(),
RealRecommendationProvider)를 기본 주입한다. 여기 두 Fake는 이제 테스트에서 Provider를
직접 주입할 때만 쓴다.
"""

from __future__ import annotations

from app.agent_context.enrichment_schemas import (
    CandidateEnrichmentRequest,
    CandidateEnrichmentResponse,
    CandidateEnrichmentResult,
    ConcentrationForecastData,
)
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
from app.services.runtime.info_context_schemas import (
    ConcentrationInfoResult,
    InfoContextRequest,
    InfoContextResponse,
)
from app.state.schema import now_kst

# concentration-conditions.md §3.3 근접치 fallback을 흉내 내는 고정 데이터.
# "관광지" 계열 이름은 직접 조회 성공(is_proxy=False), 그 외(카페 등)는 근접치
# fallback 성공(is_proxy=True)으로 시뮬레이션한다 — 실제 오케스트레이션은 C 구현.
_FAKE_ATTRACTION_NAMES = ("경복궁", "창덕궁", "종묘", "인사동", "광화문", "북촌한옥마을")
_FAKE_NEAREST_ATTRACTION = "경복궁"

_FAKE_CANDIDATES = (
    PlaceCandidate(
        place_id="runtime-stub-museum-1",
        name="런타임 스텁 박물관",
        category="cultural_facility",
        lcls_systm1="VE",
        lcls_systm2="VE07",
        lcls_systm3="VE070100",
        location={"latitude": 37.5796, "longitude": 126.9770},
        operating_hours_raw="09:00-18:00",
    ),
    PlaceCandidate(
        place_id="runtime-stub-cafe-1",
        name="런타임 스텁 카페",
        category="restaurant",
        lcls_systm1="FD",
        lcls_systm2="FD05",
        lcls_systm3="FD050100",
        location={"latitude": 37.5798, "longitude": 126.9772},
        operating_hours_raw="08:00-22:00",
    ),
    PlaceCandidate(
        place_id="runtime-stub-park-1",
        name="런타임 스텁 공원",
        category="attraction",
        lcls_systm1="VE",
        lcls_systm2="VE03",
        lcls_systm3="VE030100",
        location={"latitude": 37.5800, "longitude": 126.9774},
        operating_hours_raw="00:00-24:00",
    ),
    PlaceCandidate(
        place_id="runtime-stub-gallery-1",
        name="런타임 스텁 갤러리",
        category="cultural_facility",
        lcls_systm1="VE",
        lcls_systm2="VE07",
        lcls_systm3="VE070600",
        location={"latitude": 37.5802, "longitude": 126.9776},
        operating_hours_raw="10:00-19:00",
    ),
    # SCHEDULE-07부터 ScheduleLLMPlan.items가 min_length=3이라, 일정 재조정
    # 테스트(SCHEDULE-06)가 첫 턴에서 3곳을 제외한 뒤에도 두 번째 일정을 짤 만큼
    # 후보가 남아 있어야 한다. 4개로는 재조정 시 1개만 남아 planner.py의
    # "후보 3개 미만이면 LLM 미호출" 가드에 걸려버려 6개로 늘렸다.
    PlaceCandidate(
        place_id="runtime-stub-restaurant-1",
        name="런타임 스텁 식당",
        category="restaurant",
        lcls_systm1="FD",
        lcls_systm2="FD01",
        lcls_systm3="FD010100",
        location={"latitude": 37.5804, "longitude": 126.9778},
        operating_hours_raw="11:00-21:00",
    ),
    PlaceCandidate(
        place_id="runtime-stub-market-1",
        name="런타임 스텁 시장",
        category="attraction",
        lcls_systm1="VE",
        lcls_systm2="VE03",
        lcls_systm3="VE030300",
        location={"latitude": 37.5806, "longitude": 126.9780},
        operating_hours_raw="09:00-20:00",
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
                    # D-051: 실제 C가 내보내는 사실 3종(강수/하늘/기온)을 채운다.
                    # 하나라도 비면 D의 판정 입력이 결측이라 NEUTRAL로 굳어,
                    # 검증하려던 판정 로직이 한 줄도 실행되지 않는다.
                    data=WeatherForecast(
                        forecast_for=now_kst(),
                        precipitation="none",
                        sky="overcast",
                        temperature_celsius=22.0,
                    ),
                ),
                places=ContextValue(status="success", data=list(_FAKE_CANDIDATES)),
            ),
            warnings=[],
            error=None,
            metadata=metadata,
        )

    async def fetch_info_context(self, request: InfoContextRequest) -> InfoContextResponse:
        """concentration-conditions.md §3.3 흐름을 고정 데이터로 흉내 낸다.

        place_name이 없으면 needs_clarification, 알려진 관광지면 직접 성공,
        그 외(카페 등)는 근접치 fallback 성공을 시뮬레이션한다. 실제 장소
        해석·근접치 탐색 오케스트레이션은 C 내부 구현(A는 하지 않음).
        """
        if not request.place_name:
            return InfoContextResponse(
                request_id=request.request_id,
                status="needs_clarification",
                clarification=Clarification(
                    code="place_required",
                    missing_fields=["place_name"],
                    candidates=[],
                ),
            )

        if request.place_name in _FAKE_ATTRACTION_NAMES:
            return InfoContextResponse(
                request_id=request.request_id,
                status="success",
                result=ConcentrationInfoResult(
                    status="success",
                    is_proxy=False,
                    requested_place_name=request.place_name,
                    resolved_place_name=request.place_name,
                    forecast_date=request.visit_time or now_kst().date().isoformat(),
                    concentration_rate=42.0,
                    concentration_level="normal",
                    concentration_label="보통",
                ),
            )

        return InfoContextResponse(
            request_id=request.request_id,
            status="success",
            result=ConcentrationInfoResult(
                status="success",
                is_proxy=True,
                requested_place_name=request.place_name,
                resolved_place_name=_FAKE_NEAREST_ATTRACTION,
                forecast_date=request.visit_time or now_kst().date().isoformat(),
                concentration_rate=58.0,
                concentration_level="slightly_crowded",
                concentration_label="다소 혼잡",
            ),
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
        limit: int = 5,
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
                explanations=[],
                warnings=[],
                score=0.5,
                feature_scores={},
                weights_used={},
            )
            for candidate in candidates
            if candidate.place_id not in excluded
        ]
        return RecommendationResponse(
            recommendations=items[:limit],
            unverified_recommendations=[],
            elapsed_ms=0,
        )

    async def rerank_with_concentration(
        self,
        conditions: UserConditions,
        context: RecommendationContext,
        first_pass: RecommendationResponse,
        concentration: CandidateEnrichmentResponse,
    ) -> RecommendationResponse:
        """(D-040 확정 — agent-runtime-contract.md §6.5.2) 1차 결과를 역순으로
        재배열해 반환한다 — 실제 재채점이 아니라, 테스트에서 "2차 Scoring이
        정말 호출돼서 순서가 바뀌었는지"를 1차 결과와 구분해 확인하기 위한
        고정 로직이다.
        """
        items = [*first_pass.recommendations, *first_pass.unverified_recommendations]
        return RecommendationResponse(
            recommendations=list(reversed(items)),
            unverified_recommendations=[],
            elapsed_ms=0,
        )


class FakeEnrichmentProvider:
    """CandidateEnrichmentService를 흉내 내는 가짜 보강 provider.

    요청된 후보 전부에 고정 집중률(success, normal/보통)을 반환한다 —
    concentration-conditions.md §2.2.3 안 B의 A→C 호출부(6-1단계)를 C/D 없이
    테스트하기 위한 것.
    """

    async def enrich(self, request: CandidateEnrichmentRequest) -> CandidateEnrichmentResponse:
        results = [
            CandidateEnrichmentResult(
                place_id=target.place_id,
                name=target.name,
                latitude=target.latitude,
                longitude=target.longitude,
                status="success",
                concentration=[
                    ConcentrationForecastData(
                        place_name=target.name,
                        forecast_date=now_kst().date().isoformat(),
                        concentration_rate=42.0,
                        concentration_level="normal",
                        concentration_label="보통",
                    )
                ],
            )
            for target in request.candidates
        ]
        return CandidateEnrichmentResponse(
            request_id=request.request_id,
            status="success",
            candidates=results,
        )


__all__ = ["FakeToolProvider", "FakeRecommendationProvider", "FakeEnrichmentProvider"]
