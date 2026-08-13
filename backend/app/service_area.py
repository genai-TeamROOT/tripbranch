"""좌표가 MVP 지원 지역(서울 종로구) 안인지 판정한다.

역할: 지원 범위 밖 위치를 해석 단계에서 걸러 낸다. 그 아래 로직은 모두 "종로구 안"을
전제로 짜여 있어서(장소 검색이 lDongSignguCd를 종로구로 고정, 집중률 매핑도 종로구
장소만 보유), 밖의 좌표가 들어오면 "결과 없음"으로만 끝나고 이유가 전달되지 않는다.
입력: 위도·경도.
출력: 안이면 True.
호출 시점: ResolveLocationTool이 좌표를 얻은 직후.

경계는 `resources/boundaries/jongno.geojson`을 쓴다 — 출처와 선택 이유는 그 옆
README에 적었다. 정적 데이터라 프로세스당 한 번만 읽는다.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_BOUNDARY_PATH = (
    Path(__file__).resolve().parent.parent
    / "resources"
    / "boundaries"
    / "jongno.geojson"
)

# GeoJSON 좌표는 [경도, 위도] 순서다.
_Ring = list[list[float]]
_Polygon = list[_Ring]


@lru_cache(maxsize=1)
def _service_area_polygons() -> tuple[tuple[tuple[tuple[float, float], ...], ...], ...]:
    """(폴리곤, 링, 좌표) 3단 튜플. 첫 링이 외곽선이고 나머지는 구멍이다."""
    with _BOUNDARY_PATH.open(encoding="utf-8") as fp:
        feature = json.load(fp)
    geometry = feature["geometry"]
    geometry_type = geometry["type"]
    if geometry_type == "Polygon":
        polygons: list[_Polygon] = [geometry["coordinates"]]
    elif geometry_type == "MultiPolygon":
        polygons = list(geometry["coordinates"])
    else:
        raise ValueError(f"지원하지 않는 geometry 형식입니다: {geometry_type}")
    return tuple(
        tuple(tuple((float(point[0]), float(point[1])) for point in ring) for ring in polygon)
        for polygon in polygons
    )


def _is_inside_ring(
    longitude: float, latitude: float, ring: tuple[tuple[float, float], ...]
) -> bool:
    """Ray casting. 점에서 한 방향으로 반직선을 그어 변과 만나는 횟수를 센다."""
    inside = False
    count = len(ring)
    for index in range(count):
        x1, y1 = ring[index]
        x2, y2 = ring[(index + 1) % count]
        # 변이 점의 위도를 가로지를 때만 교차를 따진다.
        if (y1 > latitude) != (y2 > latitude):
            crossing_longitude = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
            if longitude < crossing_longitude:
                inside = not inside
    return inside


def is_within_service_area(latitude: float, longitude: float) -> bool:
    """좌표가 지원 지역 안이면 True.

    경계선에 붙은 지점은 2018년 경계 데이터의 정밀도 한계로 밖으로 판정될 수 있다
    (활성 장소 844건 중 2건). 저장소에서 해석된 장소는 이미 종로구로 등록된 것이라
    호출자가 판정을 생략한다.
    """
    for polygon in _service_area_polygons():
        outer, *holes = polygon
        if not _is_inside_ring(longitude, latitude, outer):
            continue
        if any(_is_inside_ring(longitude, latitude, hole) for hole in holes):
            continue
        return True
    return False


__all__ = ["is_within_service_area"]
