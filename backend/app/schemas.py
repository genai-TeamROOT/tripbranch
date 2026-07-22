"""TripBranch 백엔드 API의 요청/응답 스키마 정의.

역할: Pydantic 모델로 API 계약과 프론트엔드가 기대하는 데이터 형태를 고정한다.
입력: 라우터로 들어온 원시 JSON payload와 서비스가 반환하는 dict/model 값.
출력: 검증된 요청 모델, 직렬화 가능한 응답 모델, 공통 오류 모델.
호출 시점: FastAPI 요청 검증, 응답 직렬화, 서비스/테스트 타입 확인 때 사용된다.
TODO: 실제 도메인 확정 후 문자열 카테고리와 날씨 값은 Enum으로 좁힌다.
"""

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

class PlaceCandidate(BaseModel):
    """장소 API 원본 응답을 정규화한 공통 후보 모델.

    역할: 어떤 장소 API(TourAPI, 카카오 등)를 쓰든 Mapper가 이 모양으로
    변환해서 Recommendation Service에 넘긴다. Service는 이 모델만 알면 되고
    원본 API 응답 구조를 몰라도 된다.
    """

    place_id: str
    name: str
    category: str
    latitude: float
    longitude: float
    address: str | None = None
    operating_hours: str | None = None
    raw_source: str = Field(description="어떤 provider가 만든 후보인지 (예: 'tour_api')")