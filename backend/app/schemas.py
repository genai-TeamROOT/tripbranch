from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str


class ErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: object | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class InterpretRequest(BaseModel):
    user_input: str = Field(..., min_length=1)


class InterpretedConditions(BaseModel):
    location_query: str
    preferred_categories: list[str]
    weather_condition: str | None
    search_radius_km: float


class RecommendationRequest(InterpretedConditions):
    shown_place_ids: list[str] = Field(default_factory=list)


class RecommendationItem(BaseModel):
    place_id: str
    name: str
    category: str
    distance_km: float
    remaining_minutes: int | None
    environment_type: str
    recommendation_reason: str
    warnings: list[str]


class RecommendationResponse(BaseModel):
    recommendations: list[RecommendationItem]
    unverified_recommendations: list[RecommendationItem]
