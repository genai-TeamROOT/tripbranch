"""Supabase 없이 동작하는 장소 저장소 fake.

역할: PLACE_PROVIDER=fake 환경에서도 장소명 해석과 INFO 집중률 경로가 끝까지
동작하도록 종로구 대표 장소 몇 곳을 메모리로 제공한다.
입력: 장소명(정확 일치, 공백 무시).
출력: StoredPlaceLocation 튜플.
호출 시점: providers.factory가 Supabase 설정이 없을 때 주입한다.

집중률 조회는 매핑된 장소명으로만 나간다(D-043). Fake 환경에 매핑 저장소가 없으면
INFO 혼잡도가 전부 no_data로 떨어져 개발 중 경로 확인이 불가능해진다. 좌표는
FakeGeocodingProvider의 _KNOWN_LOCATIONS와 같은 값을 쓴다 — 해석 경로가
달라져도 좌표가 흔들리지 않아야 한다.
"""

from __future__ import annotations

from app.domain.models import StoredPlaceLocation
from app.providers.contracts import ProviderSource

_FAKE_PLACES: tuple[StoredPlaceLocation, ...] = (
    StoredPlaceLocation(
        content_id="126508",
        title="경복궁",
        address="서울특별시 종로구 사직로 161",
        latitude=37.5788,
        longitude=126.9770,
        concentration_name="경복궁",
    ),
    StoredPlaceLocation(
        content_id="126509",
        title="창덕궁",
        address="서울특별시 종로구 율곡로 99",
        latitude=37.5826,
        longitude=126.9919,
        concentration_name="창덕궁과 후원 [유네스코 세계유산]",
    ),
    StoredPlaceLocation(
        content_id="126510",
        title="종묘",
        address="서울특별시 종로구 종로 157",
        latitude=37.5739,
        longitude=126.9945,
        concentration_name="종묘 [유네스코 세계유산]",
    ),
    StoredPlaceLocation(
        content_id="126537",
        title="북촌한옥마을",
        address="서울특별시 종로구 계동길 37",
        latitude=37.5826,
        longitude=126.9850,
        concentration_name="북촌한옥마을",
    ),
    # 매핑이 없는 장소도 하나 둔다 — 인근 대체 경로를 fake로 확인할 수 있어야 한다.
    StoredPlaceLocation(
        content_id="264337",
        title="쌈지길",
        address="서울특별시 종로구 인사동길 44",
        latitude=37.5740,
        longitude=126.9855,
        concentration_name=None,
    ),
)


def _key(value: str) -> str:
    return value.replace(" ", "").casefold()


class FakePlaceLocationRepository:
    """장소명 조회와 집중률 매핑 목록을 메모리로 돌려주는 fake 저장소."""

    # 응답 metadata에 실저장소로 보이면 안 된다(D-042).
    provider_source = ProviderSource.FAKE_PLACES

    def __init__(self, places: tuple[StoredPlaceLocation, ...] = _FAKE_PLACES) -> None:
        self._places = places

    async def find_active_places_by_name(
        self, name: str
    ) -> tuple[StoredPlaceLocation, ...]:
        # 실제 저장소와 같이 공백 차이는 표기 차이로 본다.
        wanted = _key(name.strip())
        if not wanted:
            return ()
        return tuple(place for place in self._places if _key(place.title) == wanted)

    async def find_concentration_mapped_places(self) -> tuple[StoredPlaceLocation, ...]:
        return tuple(place for place in self._places if place.concentration_name)


__all__ = ["FakePlaceLocationRepository"]
