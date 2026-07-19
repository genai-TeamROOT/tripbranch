# FakePlaceProvider - places_data.py의 고정 장소 목록을 반경(radius_km) 기준으로 필터링해 반환.
# 카테고리 필터링은 하지 않는다(최종 랭킹/선호도 반영은 domain/service 책임이라는 원칙 때문).
# TODO: RealPlaceProvider(providers/real/places.py)로 교체될 대상 - 실제 API 응답을
# domain.models.Place로 변환하는 매핑 로직이 필요함.

from __future__ import annotations

from app.domain.distance import haversine_km
from app.domain.models import Place
from app.providers.fake.places_data import FAKE_PLACES


class FakePlaceProvider:
    """Filters the static fake dataset by radius. Category filtering here is
    intentionally loose (substring/None-safe) -- final ranking is a domain
    concern, not a provider concern."""

    async def search_places(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        categories: list[str] | None = None,
    ) -> list[Place]:
        results: list[Place] = []
        for place in FAKE_PLACES:
            distance_km = haversine_km(latitude, longitude, place.latitude, place.longitude)
            if distance_km <= radius_km:
                results.append(place)
        return results
