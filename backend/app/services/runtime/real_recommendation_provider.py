"""RecommendationProvider Protocol을 만족하는 실제 D(Recommendation) 호출 구현체.

역할: C가 만든 RecommendationContext를 D의 공개 진입점
(app.services.recommendation_pipeline.run_recommendation_pipeline_from_context())에
그대로 넘겨 실제 추천 결과를 받는다. D 내부(candidate_mapper/scoring/evidence/
explanation)는 이 진입점 하나만 거쳐 호출하고 직접 import하지 않는다.
AppError는 여기서 잡지 않고 그대로 전파한다 — RecommendationProvider Protocol의
반환 타입에 에러 variant가 없고, app.main의 전역 exception_handler(AppError)가
처리하도록 하는 게 기존 코드베이스 관례(run_recommendation_pipeline())와 일치한다.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.agent_context.enrichment_schemas import CandidateEnrichmentResponse
from app.schemas import ConcentrationIntent, RecommendationResponse, UserConditions
from app.services.recommendation_pipeline import (
    rerank_with_concentration,
    run_recommendation_pipeline_from_context,
)
from app.services.runtime.context_schemas import RecommendationContext
from app.services.runtime.recommendation_transform import to_search_radius_km

_KST = ZoneInfo("Asia/Seoul")
_RECOMMENDATION_LIMIT = 5


class RealRecommendationProvider:
    """RecommendationProvider Protocol 구현체 — D의 공개 진입점만 호출한다."""

    async def recommend(
        self,
        conditions: UserConditions,
        context: RecommendationContext,
        excluded_place_ids: list[str],
    ) -> RecommendationResponse:
        search_radius_km = to_search_radius_km(conditions)
        return await run_recommendation_pipeline_from_context(
            context,
            visit_at=datetime.now(_KST),
            search_radius_km=search_radius_km,
            shown_place_ids=frozenset(excluded_place_ids),
            recommendation_limit=_RECOMMENDATION_LIMIT,
        )

    async def rerank_with_concentration(
        self,
        conditions: UserConditions,
        context: RecommendationContext,
        first_pass: RecommendationResponse,
        concentration: CandidateEnrichmentResponse,
    ) -> RecommendationResponse:
        """D-040: 2차 Scoring. A는 concentration_intent가 AVOID/SEEK일 때만 이
        메서드를 호출한다(agent_runtime.py의 `_CONCENTRATION_RANK_INTENTS` 게이트) —
        그 외 값이 들어오면 방향을 정할 수 없으므로 AVOID(한적한 곳 선호)로 취급한다.
        """
        seek = conditions.concentration_intent is ConcentrationIntent.SEEK
        return await rerank_with_concentration(
            first_pass,
            context,
            concentration,
            seek=seek,
        )


__all__ = ["RealRecommendationProvider"]
