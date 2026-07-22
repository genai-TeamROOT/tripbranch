"""추천 API 라우터.

역할: 확정된 조건과 노출 이력을 받아 추천 결과를 서비스 계층에서 조회한다.
입력: POST /api/recommendations JSON body의 RecommendationRequest.
출력: RecommendationResponse JSON 응답.
호출 시점: ConfirmPage에서 조건 확정 후 결과 화면으로 넘어갈 때 호출된다.
TODO: 조건 기반 실제 검색과 페이지네이션이 추가되면 서비스 입력 계약을 확장한다.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas import InterpretedConditions, RecommendationRequest, RecommendationResponse
from app.services.recommendations import get_recommendations

router = APIRouter(tags=["recommendations"])


@router.post("/recommendations", response_model=RecommendationResponse)
async def recommendations(request: RecommendationRequest) -> RecommendationResponse:
    conditions = InterpretedConditions(
        location_query=request.location_query,
        preferred_categories=request.preferred_categories,
        weather_condition=request.weather_condition,
        search_radius_km=request.search_radius_km,
    )
    return await get_recommendations(conditions, request.shown_place_ids)
