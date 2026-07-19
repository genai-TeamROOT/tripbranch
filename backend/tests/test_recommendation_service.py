# RecommendationService.recommend()의 통합 동작 검증(Fake Provider 조합 사용):
# 폐점 장소 제외, 운영시간 unknown 분리, shown_place_ids 제외, 존재하지 않는 위치 에러,
# 정렬 순서(total_score 내림차순)까지 서비스 계층에서 end-to-end로 확인한다.

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from app.core.errors import AppError
from app.domain.models import WeatherCondition
from app.providers.fake.geocoding import FakeGeocodingProvider
from app.providers.fake.places import FakePlaceProvider
from app.providers.fake.weather import FakeWeatherProvider
from app.services.recommendation_service import RecommendationQuery, RecommendationService

MONDAY_1745 = datetime(2024, 1, 15, 17, 45)


def _service() -> RecommendationService:
    return RecommendationService(
        geocoding_provider=FakeGeocodingProvider(),
        weather_provider=FakeWeatherProvider(condition=WeatherCondition.NEUTRAL),
        place_provider=FakePlaceProvider(),
    )


def _query(**overrides) -> RecommendationQuery:
    defaults = dict(
        location_query="경복궁",
        preferred_categories=["museum", "cafe"],
        weather_condition=WeatherCondition.NEUTRAL,
        search_radius_km=5.0,
        shown_place_ids=[],
    )
    defaults.update(overrides)
    return RecommendationQuery(**defaults)


def test_closed_places_are_excluded_from_both_groups() -> None:
    result = asyncio.run(_service().recommend(_query(), now=MONDAY_1745))

    all_ids = {c.place.id for c in result.recommendations} | {
        c.place.id for c in result.unverified_recommendations
    }
    assert "restaurant_1" not in all_ids  # already closed at MONDAY_1745
    assert "museum_2" not in all_ids  # closed every day


def test_unknown_operating_hours_are_kept_separate() -> None:
    result = asyncio.run(_service().recommend(_query(), now=MONDAY_1745))

    recommended_ids = {c.place.id for c in result.recommendations}
    unverified_ids = {c.place.id for c in result.unverified_recommendations}

    assert "cafe_2" in unverified_ids
    assert "cafe_2" not in recommended_ids


def test_shown_place_ids_are_excluded() -> None:
    first = asyncio.run(_service().recommend(_query(), now=MONDAY_1745))
    shown = [c.place.id for c in first.recommendations]

    second = asyncio.run(_service().recommend(_query(shown_place_ids=shown), now=MONDAY_1745))

    assert not (set(shown) & {c.place.id for c in second.recommendations})


def test_unknown_location_raises_location_not_found() -> None:
    with pytest.raises(AppError) as exc_info:
        asyncio.run(_service().recommend(_query(location_query="아무데나"), now=MONDAY_1745))

    assert exc_info.value.code == "location_not_found"


def test_recommendations_are_sorted_by_total_score_descending() -> None:
    result = asyncio.run(_service().recommend(_query(), now=MONDAY_1745))

    scores = [c.total_score for c in result.recommendations]
    assert scores == sorted(scores, reverse=True)
