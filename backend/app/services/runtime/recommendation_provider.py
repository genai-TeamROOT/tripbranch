"""RecommendationProvider(D) Protocol의 실제 구현체.

FakeRecommendationProvider(stubs.py)를 대체한다. C가 만든 RecommendationContext를
`run_recommendation_pipeline_from_context()`에 그대로 넘겨 Scoring→Evidence→
Explanation을 D 내부에서 전부 처리한다([TECH-02]). search_radius_km은
`recommendation_transform.to_search_radius_km()`으로 conditions에서 계산하고,
visit_at은 현재 KST 시각을 쓴다 — 사용자가 미래 방문 시각을 지정하는 입력 경로가
아직 없기 때문이다.
"""

from __future__ import annotations

from app.agent_context.schemas import RecommendationContext
from app.schemas import RecommendationResponse, UserConditions
from app.services.recommendation_pipeline import run_recommendation_pipeline_from_context
from app.services.runtime.recommendation_transform import to_search_radius_km
from app.state.schema import now_kst


class RealRecommendationProvider:
    """RecommendationContext를 D의 주력 진입점으로 전달하는 실제 provider."""

    async def recommend(
        self,
        conditions: UserConditions,
        context: RecommendationContext,
        excluded_place_ids: list[str],
    ) -> RecommendationResponse:
        return await run_recommendation_pipeline_from_context(
            context,
            visit_at=now_kst(),
            search_radius_km=to_search_radius_km(conditions),
            shown_place_ids=frozenset(excluded_place_ids),
        )


__all__ = ["RealRecommendationProvider"]
