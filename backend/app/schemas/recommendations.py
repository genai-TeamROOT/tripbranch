# POST /api/recommendations 요청/응답 스키마.
# RecommendationItem에는 total_score/score_breakdown처럼 개발 편의용 필드도 포함돼 있는데,
# 이건 프론트에서 기본적으로 화면에 노출하지 않기로 되어 있음(스펙 참고) - 디버깅/QA용.

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.models import EnvironmentType, WeatherCondition
from app.domain.weights import DEFAULT_SEARCH_RADIUS_KM


class RecommendationRequest(BaseModel):
    location_query: str = Field(..., min_length=1)
    preferred_categories: list[str] = Field(default_factory=list)
    weather_condition: WeatherCondition | None = None
    search_radius_km: float = Field(default=DEFAULT_SEARCH_RADIUS_KM, gt=0)
    shown_place_ids: list[str] = Field(default_factory=list)


class RecommendationItem(BaseModel):
    place_id: str
    name: str
    category: str
    distance_km: float
    remaining_minutes: int | None
    environment_type: EnvironmentType
    recommendation_reason: str
    warnings: list[str]
    total_score: float
    score_breakdown: dict[str, float]


class RecommendationResponse(BaseModel):
    recommendations: list[RecommendationItem]
    unverified_recommendations: list[RecommendationItem]
