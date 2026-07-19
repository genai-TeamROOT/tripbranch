# 추천 흐름 전체를 조합하는 핵심 서비스: 지오코딩 -> (선택적) 날씨 조회 -> 장소 검색 ->
# 폐점 제외 -> 운영시간 unknown 분리 -> 점수 계산 -> 정렬 -> 이미 본 장소 제외 -> 개수 제한.
# domain/*.py의 순수 함수들을 여기서 순서대로 호출만 하고, provider 호출 실패는
# AppError(weather는 실패해도 통과 - 가중치 없는 버전으로 폴백, place/geocoding은 실패시
# 에러)로 변환한다.
# TODO: 후보가 MINIMUM_RECOMMENDATION_COUNT 미만일 때 자동으로 반경을 넓혀 재검색하는 로직이
# 아직 없음(현재는 프론트에서 사용자가 수동으로 반경을 넓혀 재요청). 자동 완화를 넣는다면
# 이 recommend() 안에서 재귀/루프 형태로 구현하되 무한 루프 방지용 최대 반경을 꼭 둘 것.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.errors import AppError
from app.domain.candidate import ScoredCandidate
from app.domain.distance import haversine_km
from app.domain.models import DayStatus, GeocodeResult, Place, WeatherCondition
from app.domain.operating_hours import current_day_status, remaining_open_minutes
from app.domain.scoring import (
    ScoreBreakdown,
    category_score,
    distance_score,
    remaining_open_time_score,
    weather_score,
    weighted_total_score,
)
from app.domain.sorting import exclude_shown, sort_candidates
from app.domain.weights import (
    MAXIMUM_RECOMMENDATION_COUNT,
    MINIMUM_RECOMMENDATION_COUNT,
)
from app.providers.protocols.geocoding import GeocodingProvider
from app.providers.protocols.place import PlaceProvider
from app.providers.protocols.weather import WeatherProvider


@dataclass(frozen=True)
class RecommendationQuery:
    location_query: str
    preferred_categories: list[str]
    weather_condition: WeatherCondition | None
    search_radius_km: float
    shown_place_ids: list[str]


@dataclass(frozen=True)
class RecommendationResult:
    recommendations: list[ScoredCandidate]
    unverified_recommendations: list[ScoredCandidate]


class RecommendationService:
    def __init__(
        self,
        geocoding_provider: GeocodingProvider,
        weather_provider: WeatherProvider,
        place_provider: PlaceProvider,
    ) -> None:
        self._geocoding_provider = geocoding_provider
        self._weather_provider = weather_provider
        self._place_provider = place_provider

    async def recommend(self, query: RecommendationQuery, now: datetime) -> RecommendationResult:
        if not query.location_query.strip():
            raise AppError(code="invalid_request", message="기준 위치를 입력해주세요.")
        if query.search_radius_km <= 0:
            raise AppError(code="invalid_request", message="검색 반경은 0보다 커야 해요.")

        geocode_result = await self._geocode(query.location_query)

        weather_condition = query.weather_condition
        if weather_condition is None:
            weather_condition = await self._try_get_weather(
                geocode_result.latitude, geocode_result.longitude
            )

        try:
            places = await self._place_provider.search_places(
                latitude=geocode_result.latitude,
                longitude=geocode_result.longitude,
                radius_km=query.search_radius_km,
                categories=query.preferred_categories,
            )
        except Exception as exc:
            raise AppError(
                code="place_provider_unavailable",
                message="주변 장소 정보를 불러오지 못했어요.",
                retryable=True,
            ) from exc

        known_candidates: list[ScoredCandidate] = []
        unknown_candidates: list[ScoredCandidate] = []

        for place in places:
            day_status = current_day_status(place.opening_hours, now)
            if day_status == DayStatus.CLOSED:
                continue

            distance_km = _distance_km(geocode_result.latitude, geocode_result.longitude, place)
            rank = _category_rank(place.category, query.preferred_categories)
            warnings: list[str] = []

            if day_status == DayStatus.UNKNOWN:
                candidate = _build_candidate(
                    place=place,
                    distance_km=distance_km,
                    remaining_minutes=None,
                    rank=rank,
                    weather_condition=weather_condition,
                    search_radius_km=query.search_radius_km,
                    warnings=["운영시간을 확인할 수 없어요."],
                )
                unknown_candidates.append(candidate)
                continue

            remaining_minutes = remaining_open_minutes(place.opening_hours, now)
            if remaining_minutes is not None and remaining_minutes < 30:
                warnings.append("곧 문을 닫아요.")

            candidate = _build_candidate(
                place=place,
                distance_km=distance_km,
                remaining_minutes=remaining_minutes,
                rank=rank,
                weather_condition=weather_condition,
                search_radius_km=query.search_radius_km,
                warnings=warnings,
            )
            known_candidates.append(candidate)

        shown_ids = set(query.shown_place_ids)
        known_candidates = exclude_shown(sort_candidates(known_candidates), shown_ids)
        unknown_candidates = exclude_shown(sort_candidates(unknown_candidates), shown_ids)

        known_candidates = known_candidates[:MAXIMUM_RECOMMENDATION_COUNT]
        if len(known_candidates) < MINIMUM_RECOMMENDATION_COUNT:
            # TODO: implement radius-widening / condition-relaxation retry once
            # product decides the exact relaxation UX (see ResultsPage spec).
            pass

        return RecommendationResult(
            recommendations=known_candidates,
            unverified_recommendations=unknown_candidates[:MAXIMUM_RECOMMENDATION_COUNT],
        )

    async def _geocode(self, location_query: str) -> GeocodeResult:
        try:
            return await self._geocoding_provider.geocode(location_query)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code="location_not_found",
                message=f"'{location_query}' 위치를 찾을 수 없어요.",
            ) from exc

    async def _try_get_weather(self, latitude: float, longitude: float) -> WeatherCondition | None:
        try:
            return await self._weather_provider.get_current_condition(latitude, longitude)
        except Exception:
            # Weather is optional: fall back to the no-weather weight set
            # rather than failing the whole recommendation request.
            return None


def _distance_km(origin_lat: float, origin_lon: float, place: Place) -> float:
    return haversine_km(origin_lat, origin_lon, place.latitude, place.longitude)


def _category_rank(category: str, preferred_categories: list[str]) -> int:
    try:
        return preferred_categories.index(category) + 1
    except ValueError:
        return len(preferred_categories) + 1 if preferred_categories else 1


def _build_candidate(
    *,
    place: Place,
    distance_km: float,
    remaining_minutes: int | None,
    rank: int,
    weather_condition: WeatherCondition | None,
    search_radius_km: float,
    warnings: list[str],
) -> ScoredCandidate:
    cat_score = category_score(rank)
    time_score = remaining_open_time_score(
        remaining_minutes if remaining_minutes is not None else 0
    )
    dist_score = distance_score(distance_km, search_radius_km)
    weather_component = (
        weather_score(weather_condition, place.environment_type)
        if weather_condition is not None
        else None
    )

    breakdown = ScoreBreakdown(
        category=cat_score,
        remaining_open_time=time_score,
        distance=dist_score,
        weather=weather_component,
    )
    total = weighted_total_score(breakdown)

    reason = _build_reason(place, rank, remaining_minutes)

    return ScoredCandidate(
        place=place,
        distance_km=round(distance_km, 3),
        remaining_minutes=remaining_minutes,
        environment_type=place.environment_type,
        score_breakdown=breakdown,
        total_score=round(total, 4),
        recommendation_reason=reason,
        warnings=warnings,
    )


def _build_reason(place: Place, rank: int, remaining_minutes: int | None) -> str:
    parts = [f"'{place.category}' 카테고리 선호도 {rank}순위"]
    if remaining_minutes is not None:
        parts.append(f"남은 운영시간 {remaining_minutes}분")
    return ", ".join(parts)
