"""좌표가 MVP 지원 지역(서울 25개 구 전체, SUPPORTED_DISTRICTS 참고) 안인지 판정한다.

역할: 지원 범위 밖 위치를 해석 단계에서 걸러 낸다. 밖의 좌표가 들어오면 그 아래
로직이 "결과 없음"으로만 끝나고 이유가 전달되지 않아서다(D-044).
입력: 위도·경도.
출력: 지원 구 중 어느 하나 안이면 True.
호출 시점: ResolveLocationTool이 좌표를 얻은 직후.

경계는 `resources/boundaries/seoul.geojson` 한 장을 쓴다. 서울 25개 구가 모두 들어
있고 그중 어디를 지원할지는 `SUPPORTED_DISTRICTS`가 정한다 — 구를 늘릴 때 파일
작업 없이 목록 한 줄로 끝나게 하기 위해서다. 출처와 선택 이유는 그 옆 README에 적었다.
정적 데이터라 프로세스당 한 번만 읽는다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_BOUNDARY_PATH = (
    Path(__file__).resolve().parent.parent / "resources" / "boundaries" / "seoul.geojson"
)

# GeoJSON 좌표는 [경도, 위도] 순서다.
_Ring = tuple[tuple[float, float], ...]
_Polygon = tuple[_Ring, ...]


@dataclass(frozen=True)
class ServiceDistrict:
    """지원 구 한 곳."""

    # TourAPI 법정동 코드의 시군구 부분(lDongSignguCd). 경계 파일 안의
    # properties.code(KOSTAT 11010 등)와는 다른 코드 체계라 섞어 쓰지 않는다.
    district_code: str
    # 경계 파일의 properties.name과 정확히 같아야 한다. 이 이름으로 폴리곤을 찾는다.
    name: str


# 지원 구는 여기서 정한다. 경계 파일에는 서울 25개 구가 다 들어 있으므로, 구를
# 늘릴 때 할 일은 이 목록에 한 줄을 더하는 것뿐이다.
#
# 파일에 있는 구를 전부 지원하는 방식은 쓰지 않는다 — 지원 범위는 팀이 합의하는
# 결정이라 코드에 드러나고 리뷰를 거쳐야 한다. 목록에 있는데 경계 파일에 그 구가
# 없으면 첫 판정에서 예외로 끊는다.
#
# 2026-08-25: Supabase `places`에 이미 적재된 8개 구를 추가했다(D-083) —
# 광진구·동대문구·중랑구·성북구·강북구·도봉구·노원구·은평구. district_code는
# TourAPI 응답 실측(각 구 표본 2건)으로 주소와 대조해 확인했다.
#
# 2026-08-26: 서대문구·마포구·양천구·강서구를 추가했다(D-086) — place-sync로
# 목록·상세정보를 새로 적재한 4개 구다. district_code는 place-sync가 실제로
# 적재한 TourAPI 응답 주소와 대조해 확인했다(app/resources/tour_api/
# tour_api_ldong_codes.json과 동일).
#
# 2026-08-28: 구로구·금천구·영등포구·동작구·관악구·서초구를 추가했다(D-108) — place-sync로
# 새로 적재된 6개 구다(활성 1,516건). district_code는 순서로 짐작하지 않고 각 구
# 표본 주소로 대조해 확인했다 — 코드 순서와 구 이름이 한 칸씩 어긋나 있어(530이
# 영등포가 아니라 구로) 짐작하면 전부 틀린다.
#
# 2026-08-29: 강남구·송파구·강동구를 추가해 서울 25개 구 전부가 지원 범위가 됐다.
# district_code는 각 구 표본 주소로 대조해 확인했다. 강남구는 상세 조회가 322/1,133
# 건에서 멈춘 상태로 들어온다 — 상세가 없어도 추천·혼잡도는 동작하고, 지원 목록에
# 없으면 후보로 아예 나오지 않아 그쪽이 더 나쁘다. 남은 810건은 place-sync를 다시
# 돌리면 detail_fetch_status=pending부터 이어받는다.
#
# 이제 경계 파일의 25개 구와 지원 목록이 같아졌다. 그래도 "파일에 있는 구를 전부
# 지원"으로 바꾸지 않는다 — 지원 범위는 팀이 합의하는 결정이라 코드에 드러나야
# 한다는 판단은 그대로다(D-083에서 두 번 기각).
#
# 스물다섯 곳 모두 서울특별시라 lDongRegnCd는 "11"로 같다.
SUPPORTED_DISTRICTS: tuple[ServiceDistrict, ...] = (
    ServiceDistrict("110", "종로구"),
    ServiceDistrict("140", "중구"),
    ServiceDistrict("170", "용산구"),
    ServiceDistrict("200", "성동구"),
    ServiceDistrict("215", "광진구"),
    ServiceDistrict("230", "동대문구"),
    ServiceDistrict("260", "중랑구"),
    ServiceDistrict("290", "성북구"),
    ServiceDistrict("305", "강북구"),
    ServiceDistrict("320", "도봉구"),
    ServiceDistrict("350", "노원구"),
    ServiceDistrict("380", "은평구"),
    ServiceDistrict("410", "서대문구"),
    ServiceDistrict("440", "마포구"),
    ServiceDistrict("470", "양천구"),
    ServiceDistrict("500", "강서구"),
    ServiceDistrict("530", "구로구"),
    ServiceDistrict("545", "금천구"),
    ServiceDistrict("560", "영등포구"),
    ServiceDistrict("590", "동작구"),
    ServiceDistrict("620", "관악구"),
    ServiceDistrict("650", "서초구"),
    ServiceDistrict("680", "강남구"),
    ServiceDistrict("710", "송파구"),
    ServiceDistrict("740", "강동구"),
)

# 좌표 판정(폴리곤)과 장소 검색(TourAPI 응답의 lDongSignguCd)이 같은 목록을 봐야
# 한 쪽만 늘어나는 일이 없다. 검색 쪽은 이 집합으로 응답을 거른다(D-025).
SUPPORTED_DISTRICT_CODES: frozenset[str] = frozenset(
    district.district_code for district in SUPPORTED_DISTRICTS
)


def _to_polygons(geometry: Mapping[str, object]) -> tuple[_Polygon, ...]:
    """(폴리곤, 링, 좌표) 3단 튜플. 각 폴리곤의 첫 링이 외곽선이고 나머지는 구멍이다."""
    geometry_type = geometry["type"]
    if geometry_type == "Polygon":
        raw_polygons = [geometry["coordinates"]]
    elif geometry_type == "MultiPolygon":
        raw_polygons = list(geometry["coordinates"])  # type: ignore[arg-type]
    else:
        raise ValueError(f"지원하지 않는 geometry 형식입니다: {geometry_type}")
    return tuple(
        tuple(
            tuple((float(point[0]), float(point[1])) for point in ring)
            for ring in polygon
        )
        for polygon in raw_polygons
    )


@lru_cache(maxsize=1)
def _all_district_polygons() -> tuple[tuple[str, tuple[_Polygon, ...]], ...]:
    """경계 파일에 든 모든 구의 (이름, 폴리곤들). 지원 여부와 무관하게 전부 읽는다."""
    with _BOUNDARY_PATH.open(encoding="utf-8") as fp:
        collection = json.load(fp)
    if collection.get("type") != "FeatureCollection":
        raise ValueError("경계 파일은 FeatureCollection이어야 합니다.")
    return tuple(
        (str(feature["properties"]["name"]), _to_polygons(feature["geometry"]))
        for feature in collection["features"]
    )


def _select_supported(
    all_polygons: tuple[tuple[str, tuple[_Polygon, ...]], ...],
    districts: tuple[ServiceDistrict, ...],
) -> tuple[tuple[str, tuple[_Polygon, ...]], ...]:
    """지원 구의 폴리곤만 목록 순서대로 고른다. 경계가 없는 구는 예외로 끊는다."""
    by_name = dict(all_polygons)
    missing = [district.name for district in districts if district.name not in by_name]
    if missing:
        raise ValueError(
            f"경계 파일에 없는 구가 SUPPORTED_DISTRICTS에 있습니다: {', '.join(missing)}. "
            f"{_BOUNDARY_PATH.name}를 다시 뽑아야 합니다."
        )
    return tuple(
        (district.district_code, by_name[district.name]) for district in districts
    )


@lru_cache(maxsize=1)
def _service_area_polygons() -> tuple[tuple[str, tuple[_Polygon, ...]], ...]:
    """(구 코드, 폴리곤들) 쌍의 튜플. 구가 늘어도 판정 방식은 그대로다."""
    return _select_supported(_all_district_polygons(), SUPPORTED_DISTRICTS)


def _is_inside_ring(longitude: float, latitude: float, ring: _Ring) -> bool:
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


def _is_inside_polygon(longitude: float, latitude: float, polygon: _Polygon) -> bool:
    outer, *holes = polygon
    if not _is_inside_ring(longitude, latitude, outer):
        return False
    return not any(_is_inside_ring(longitude, latitude, hole) for hole in holes)


def is_within_service_area(latitude: float, longitude: float) -> bool:
    """좌표가 지원 구 중 어느 하나 안이면 True.

    경계선에 붙은 지점은 2018년 경계 데이터의 정밀도 한계로 밖으로 판정될 수 있다
    (구별 활성 장소의 0.3% 미만, README의 정밀도 표 참고). 저장소에서 해석된
    장소는 이미 지원 구로 등록된 것이라 호출자가 판정을 생략한다.
    """
    return find_containing_district(latitude, longitude) is not None


def find_containing_district(latitude: float, longitude: float) -> ServiceDistrict | None:
    """좌표를 포함하는 지원 구. 지원 구 밖이면 None.

    `is_within_service_area`가 bool만 필요한 호출부용이라면, 이건 "어느 구인지"까지
    필요한 호출부용이다(TP-160 위치 되묻기 대체 버튼, `app.service_area_landmarks`).
    """
    by_code = {district.district_code: district for district in SUPPORTED_DISTRICTS}
    for district_code, polygons in _service_area_polygons():
        if any(
            _is_inside_polygon(longitude, latitude, polygon) for polygon in polygons
        ):
            return by_code[district_code]
    return None


def supported_district_label(*, with_city: bool = False) -> str:
    """안내 문구에 넣을 지원 구 이름. "종로구·중구·용산구·성동구·..." (SUPPORTED_DISTRICTS 순서).

    문구가 이 목록을 읽게 해야 구를 늘릴 때 SUPPORTED_DISTRICTS 한 줄로 끝난다.
    사람이 쓴 문자열로 두면 목록만 늘고 문구는 옛 범위를 말하는 상태가 된다 —
    실제로 지원 구가 넷으로 늘어난 뒤에도 "종로구만 지원합니다"가 나갔다.

    with_city는 "서울특별시"를 앞에 붙인다. 모두 서울특별시이므로 구 이름만
    반복하지 않고 한 번만 쓴다.
    """
    names = "·".join(district.name for district in SUPPORTED_DISTRICTS)
    return f"서울특별시 {names}" if with_city else names


__all__ = [
    "SUPPORTED_DISTRICTS",
    "SUPPORTED_DISTRICT_CODES",
    "ServiceDistrict",
    "find_containing_district",
    "is_within_service_area",
    "supported_district_label",
]
