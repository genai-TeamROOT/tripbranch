# POST /api/recommendations - 확정된 조건으로 주변 장소를 검색하고 점수를 매겨 추천 목록을 반환.
# RecommendationService에 위임하고, 도메인 ScoredCandidate -> RecommendationItem 스키마 변환만 담당.
# 사용법: 프론트 ConfirmPage(최초 추천) / ResultsPage(다른 장소 보기, shown_place_ids 포함)에서
# 호출. "지금 몇 시인지"는 이 파일에서 직접 정하지 않고 core/clock.py의 Clock을 주입받는다 -
# 운영 환경은 실제 시각(SystemClock), Fake 환경은 고정 시각(FixedClock)을 자동으로 쓴다
# (api/deps.py의 get_clock 참고). 이렇게 해야 Fake 추천 결과가 실행 시각에 따라
# 오락가락하지 않는다.

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_clock, get_recommendation_service
from app.core.clock import Clock
from app.domain.candidate import ScoredCandidate
from app.schemas.common import ErrorResponse
from app.schemas.recommendations import (
    RecommendationItem,
    RecommendationRequest,
    RecommendationResponse,
)
from app.services.recommendation_service import RecommendationQuery, RecommendationService

router = APIRouter(tags=["recommendations"])


@router.post(
    "/recommendations",
    response_model=RecommendationResponse,
    responses={"default": {"model": ErrorResponse, "description": "Common error envelope"}},
)
async def get_recommendations(
    request: RecommendationRequest,
    service: RecommendationService = Depends(get_recommendation_service),
    clock: Clock = Depends(get_clock),
) -> RecommendationResponse:
    query = RecommendationQuery(
        location_query=request.location_query,
        preferred_categories=request.preferred_categories,
        weather_condition=request.weather_condition,
        search_radius_km=request.search_radius_km,
        shown_place_ids=request.shown_place_ids,
    )

    result = await service.recommend(query, now=clock.now())

    return RecommendationResponse(
        recommendations=[_to_item(c) for c in result.recommendations],
        unverified_recommendations=[_to_item(c) for c in result.unverified_recommendations],
    )


def _to_item(candidate: ScoredCandidate) -> RecommendationItem:
    return RecommendationItem(
        place_id=candidate.place.id,
        name=candidate.place.name,
        category=candidate.place.category,
        distance_km=candidate.distance_km,
        remaining_minutes=candidate.remaining_minutes,
        environment_type=candidate.environment_type,
        recommendation_reason=candidate.recommendation_reason,
        warnings=candidate.warnings,
        total_score=candidate.total_score,
        score_breakdown=candidate.score_breakdown.as_dict(),
    )
