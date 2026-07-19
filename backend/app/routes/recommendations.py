from __future__ import annotations

from fastapi import APIRouter

from app.schemas import RecommendationRequest, RecommendationResponse
from app.services.recommendations import get_stub_recommendations

router = APIRouter(tags=["recommendations"])


@router.post("/recommendations", response_model=RecommendationResponse)
async def recommendations(request: RecommendationRequest) -> RecommendationResponse:
    return get_stub_recommendations(request.shown_place_ids)
