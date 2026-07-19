# POST /api/interpret 요청/응답 스키마. InterpretResponse는 domain.models.InterpretedInput과
# 필드가 1:1로 대응한다(의도적 중복 - API 계약과 도메인 모델을 분리하기 위함).

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.models import WeatherCondition
from app.domain.weights import DEFAULT_SEARCH_RADIUS_KM


class InterpretRequest(BaseModel):
    user_input: str = Field(..., min_length=1)


class InterpretResponse(BaseModel):
    location_query: str
    preferred_categories: list[str]
    weather_condition: WeatherCondition | None
    search_radius_km: float = DEFAULT_SEARCH_RADIUS_KM
