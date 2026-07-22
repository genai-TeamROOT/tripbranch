"""추천 결과를 조립하는 도메인 서비스.

역할: 설정에 따라 fake 고정 응답을 반환하거나, geocoding → place 검색 →
      필터링 → 응답 조립으로 이어지는 실행 순서를 수행한다.
입력: 해석된 조건(InterpretedConditions), 이미 노출된 place_id 목록.
출력: RecommendationResponse 모델.
호출 시점: /api/recommendations 라우터가 get_recommendations()를 호출한다.
TODO: 실제 운영시간 기반 remaining_minutes 계산은 app/core/clock.py 연동 후 처리한다.
"""

from __future__ import annotations

import math

import httpx

from app.config import settings
from app.providers.protocols import GeocodingProvider, PlaceProvider
from app.schemas import (
    InterpretedConditions,
    PlaceCandidate,
    RecommendationItem,
    RecommendationResponse,
)

_INDOOR_CATEGORIES = {"museum", "cafe", "gallery", "restaurant"}
_OUTDOOR_CATEGORIES = {"park", "trail", "beach"}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return radius_km * 2 * math.asin(math.sqrt(a))


def _environment_type(category: str) -> str:
    if category in _INDOOR_CATEGORIES:
        return "indoor"
    if category in _OUTDOOR_CATEGORIES:
        return "outdoor"
    return "unknown"


def _build_reason(candidate: PlaceCandidate, conditions: InterpretedConditions) -> str:
    if candidate.category in conditions.preferred_categories:
        return f"선호하신 '{candidate.category}' 카테고리와 일치하는 장소예요."
    return "현재 위치에서 가까운 장소예요."


def _to_recommendation_item(
    candidate: PlaceCandidate,
    origin_lat: float,
    origin_lon: float,
    conditions: InterpretedConditions,
) -> RecommendationItem:
    return RecommendationItem(
        place_id=candidate.place_id,
        name=candidate.name,
        category=candidate.category,
        distance_km=round(
            _haversine_km(origin_lat, origin_lon, candidate.latitude, candidate.longitude), 2
        ),
        remaining_minutes=None,  # TODO: core/clock.py 연동 후 계산
        environment_type=_environment_type(candidate.category),
        recommendation_reason=_build_reason(candidate, conditions),
        warnings=[] if candidate.operating_hours else ["방문 전에 운영 여부를 확인해주세요."],
    )


async def build_recommendations(
    conditions: InterpretedConditions,
    shown_place_ids: list[str],
    geocoding_provider: GeocodingProvider,
    place_provider: PlaceProvider,
) -> RecommendationResponse:
    """실제 provider 파이프라인 실행 순서.

    1. location_query → 좌표 변환
    2. 좌표 기반 장소 후보 조회
    3. 이미 노출된 place_id 제외
    4. 항목 변환 (거리, 실내외, 추천 이유)
    5. 운영시간 검증 여부로 recommendations / unverified 분리
    """
    geocode_result = await geocoding_provider.geocode(conditions.location_query)
    latitude = geocode_result.latitude
    longitude = geocode_result.longitude

    candidates = await place_provider.search_places(
        latitude=latitude,
        longitude=longitude,
        preferred_categories=conditions.preferred_categories,
        search_radius_km=conditions.search_radius_km,
    )

    shown = set(shown_place_ids)
    candidates = [c for c in candidates if c.place_id not in shown]

    verified: list[RecommendationItem] = []
    unverified: list[RecommendationItem] = []
    for candidate in candidates:
        item = _to_recommendation_item(candidate, latitude, longitude, conditions)
        (verified if candidate.operating_hours else unverified).append(item)

    return RecommendationResponse(
        recommendations=verified,
        unverified_recommendations=unverified,
    )


def get_stub_recommendations(shown_place_ids: list[str]) -> RecommendationResponse:
    """레거시 고정 stub 응답. 기존 회귀 테스트가 이 결과를 검증한다."""
    stub_items = [
        RecommendationItem(
            place_id="stub-museum-1",
            name="테스트 박물관",
            category="museum",
            distance_km=0.4,
            remaining_minutes=150,
            environment_type="indoor",
            recommendation_reason="비 오는 날 방문하기 좋은 실내 장소예요.",
            warnings=[],
        ),
        RecommendationItem(
            place_id="stub-cafe-1",
            name="테스트 카페",
            category="cafe",
            distance_km=0.7,
            remaining_minutes=80,
            environment_type="indoor",
            recommendation_reason="현재 위치에서 가까운 장소예요.",
            warnings=[],
        ),
        RecommendationItem(
            place_id="stub-park-1",
            name="테스트 공원",
            category="park",
            distance_km=0.9,
            remaining_minutes=200,
            environment_type="outdoor",
            recommendation_reason="가까운 야외 장소예요.",
            warnings=["현재 날씨를 확인해주세요."],
        ),
    ]
    stub_unverified = [
        RecommendationItem(
            place_id="stub-gallery-1",
            name="운영시간 미확인 갤러리",
            category="gallery",
            distance_km=0.8,
            remaining_minutes=None,
            environment_type="indoor",
            recommendation_reason="선호한 문화 장소와 비슷한 장소예요.",
            warnings=["방문 전에 운영 여부를 확인해주세요."],
        )
    ]

    shown = set(shown_place_ids)
    return RecommendationResponse(
        recommendations=[i for i in stub_items if i.place_id not in shown],
        unverified_recommendations=[i for i in stub_unverified if i.place_id not in shown],
    )


async def get_recommendations(
    conditions: InterpretedConditions, shown_place_ids: list[str]
) -> RecommendationResponse:
    """라우터가 호출하는 단일 진입점.

    설정이 둘 다 fake면 기존 고정 stub 응답(회귀 테스트 호환)을 반환하고,
    하나라도 real이면 실제 provider 파이프라인(build_recommendations)을 실행한다.
    """
    if (
        settings.resolved_place_provider == "fake"
        and settings.resolved_geocoding_provider == "fake"
    ):
        return get_stub_recommendations(shown_place_ids)

    from app.providers.factory import get_geocoding_provider, get_place_provider

    async with httpx.AsyncClient() as client:
        return await build_recommendations(
            conditions,
            shown_place_ids,
            geocoding_provider=get_geocoding_provider(client),
            place_provider=get_place_provider(client),
        )
