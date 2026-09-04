"""공중화장실 위치 저장소 테스트 더블."""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.models import PublicToilet
from app.geo import haversine_km


class FakePublicToiletRepository:
    def __init__(self, toilets: Sequence[PublicToilet] = ()) -> None:
        self._toilets = {toilet.toilet_id: toilet for toilet in toilets}

    async def find_near(
        self, latitude: float, longitude: float, *, radius_km: float, limit: int
    ) -> tuple[PublicToilet, ...]:
        # 실제 저장소는 바운딩 박스라 원보다 넓게 준다. 더블도 반지름을 정확히
        # 적용하지 않고 넉넉하게 줘서 호출부의 거리 재확인 로직이 테스트되게 한다.
        within = [
            toilet
            for toilet in self._toilets.values()
            if haversine_km(latitude, longitude, toilet.latitude, toilet.longitude)
            <= radius_km * 1.5
        ]
        within.sort(key=lambda t: haversine_km(latitude, longitude, t.latitude, t.longitude))
        return tuple(within[:limit])

    async def upsert_toilets(self, toilets: Sequence[PublicToilet]) -> None:
        self._toilets.update({toilet.toilet_id: toilet for toilet in toilets})


__all__ = ["FakePublicToiletRepository"]
