"""Agent Runtime이 C(Tool Intelligence)/D(Recommendation)에 의존하는 최소 계약.

역할: Runtime 코드(agent_runtime.py)가 C/D의 구체 클래스를 직접 import하지 않고 이
Protocol만 거치도록 강제한다. A–C 요청·응답은 app.agent_context.schemas를 단일 계약으로
사용하며, 실제 C Service(get_context_provider())가 stubs.py의 FakeToolProvider를 대체한다.
ToolProvider는 A-C Context Contract v0(docs/design/a-c-context-contract-draft.md)로
확정됐다 — excluded_place_ids는 여기 없다. C는 외부 데이터 조회·정규화만 담당하고, 이전
노출·거절 후보 제외는 D Recommendation의 책임이라고 계약서 §2가 명시한다.
RecommendationProvider(D)도 이 형태로 확정됐다([TECH-02]) — excluded_place_ids를 그대로
받아 D가 직접 필터링한다. RealRecommendationProvider(real_recommendation_provider.py)가
실제 구현체다.
"""

from __future__ import annotations

from typing import Protocol

from app.agent_context.schemas import (
    AgentContextRequest,
    AgentContextResponse,
    RecommendationContext,
)
from app.schemas import RecommendationResponse, UserConditions
from app.services.runtime.info_context_schemas import InfoContextRequest, InfoContextResponse


class ToolProvider(Protocol):
    async def fetch_context(self, request: AgentContextRequest) -> AgentContextResponse:
        """조건에 맞는 위치·날씨·장소 후보 등을 공통 AgentContextResponse로 반환한다."""
        ...

    async def fetch_info_context(self, request: InfoContextRequest) -> InfoContextResponse:
        """INFO의 혼잡도 질의(question_type=concentration)를 처리한다.

        (A 제안, C 확인 필요 — info_context_schemas.py, concentration-conditions.md
        §2.4/§3.3) 장소 해석·get_concentration 조회·근접치 fallback 오케스트레이션은
        전부 C 내부 책임이다. A는 구조화된 결과만 받는다.
        """
        ...


class RecommendationProvider(Protocol):
    async def recommend(
        self,
        conditions: UserConditions,
        context: RecommendationContext,
        excluded_place_ids: list[str],
    ) -> RecommendationResponse:
        """조건과 Tool 결과를 바탕으로 최종 추천 결과를 반환한다."""
        ...
