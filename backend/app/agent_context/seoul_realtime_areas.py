"""서울시 실시간 도시데이터가 지원하는 지역 목록과 좌표→지역 변환.

서울시 실시간 도시데이터 API(``citydata``/``citydata_ppltn``/``citydata_cmrcl``)는
좌표가 아니라 ``AREA_NM``으로만 조회한다. 그래서 사용자 좌표를 가장 가까운 지역
이름으로 바꿔 조회하는데, **API마다 지원하는 지역 수가 다르다**(2026-08-26 확인,
목록 출처와 근거는 ``resources/seoul_realtime/README.md`` 참고).

- 인구 혼잡도(``citydata`` 통합, ``citydata_ppltn`` 전용): 121개 지역
- 상권 활동(``citydata_cmrcl``): 82개 지역

**82개는 121개가 "아직 못 따라간" 목록이 아니라, 서울시가 설계 단계에서 정한
영구적인 부분집합이다**(실시간 도시데이터 매뉴얼 V8.5, 2026-04, 36p): 카드소비
데이터가 통계적으로 의미 있으려면 가맹점이 일정 수 이상 있어야 하는데, 공원 33곳
등 39곳은 애초에 그 조건을 못 채운다. 그래서 상권 API는 처음부터 82곳만 지원한다.
반대로 인구 API는 처음부터 121곳을 지원했다. 예전 코드는 이 사실을 모른 채 82개
목록 하나로 두 용도를 다 처리했고, 그 결과 인구 혼잡도를 물어도 API가 실제로 아는
지역(예: 경복궁)이 82개 목록엔 없어서 더 먼 지역(광화문·덕수궁)으로 대체되는
불필요한 정확도 손실이 있었다. 그래서 목록을 분리해 각 조회 경로가 API가 실제로
지원하는 범위만큼만 보게 한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.geo import haversine_km

_RESOURCE_DIR = Path(__file__).resolve().parent.parent.parent / "resources" / "seoul_realtime"
_POPULATION_PATH = _RESOURCE_DIR / "population_areas_121.json"
_COMMERCIAL_PATH = _RESOURCE_DIR / "commercial_areas_82.json"

# 중심 좌표만으로 지역 경계를 완전히 재현하지는 않는다. 따라서 이 거리 안에서만
# 최근접 대체를 허용한다. 응답에는 항상 대상 지역과 대체 거리를 함께 고지한다.
COMMERCIAL_AREA_PROXY_MAX_DISTANCE_KM = 2.0
# 실시간 인구 혼잡도는 "근처" 혼잡을 알려주는 용도이므로, 상권 활동 대체보다
# 더 보수적인 거리만 허용한다. 멀리 떨어진 관광특구의 인파를 특정 명소의 현재
# 혼잡처럼 보이게 하지 않기 위한 별도 기준이다.
POPULATION_AREA_PROXY_MAX_DISTANCE_KM = 1.0


@dataclass(frozen=True)
class SeoulRealtimeArea:
    code: str
    name: str
    latitude: float
    longitude: float


# 요청 장소 이름이 목록에 그대로(또는 오탈자 한 글자 차이로) 있는데도 중심좌표가
# 소수점 단위로 어긋나 "N km 떨어진 곳"으로 잘못 대체하는 걸 막는다("성수 카페거리"
# 지오코딩 결과 "성수동카페거리" vs 목록의 "성수카페거리", 2026-08-31 실측).
# resolve_location.py의 편집거리 기준과 맞춘다 — 기준이 다르면 어떤 단계에서
# "같은 장소"로 판단했다가 다음 단계에서 "다른 장소"로 뒤집히는 모순이 생긴다.
_NAME_MATCH_EDIT_DISTANCE_LIMIT = 1
_MIN_NAME_LEN_FOR_FUZZY_MATCH = 3


def _normalize_area_name(value: str) -> str:
    return value.casefold().replace(" ", "")


def _bounded_edit_distance(a: str, b: str, *, limit: int) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous_row = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current_row = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current_row[j] = min(
                previous_row[j] + 1, current_row[j - 1] + 1, previous_row[j - 1] + cost
            )
        previous_row = current_row
    return previous_row[-1]


def names_match(a: str, b: str) -> bool:
    """두 장소명이 사실상 같은 이름인지(공백 무시, 한 글자 차이까지 허용)."""

    normalized_a, normalized_b = _normalize_area_name(a), _normalize_area_name(b)
    if normalized_a == normalized_b:
        return True
    if min(len(normalized_a), len(normalized_b)) < _MIN_NAME_LEN_FOR_FUZZY_MATCH:
        return False
    return (
        _bounded_edit_distance(normalized_a, normalized_b, limit=_NAME_MATCH_EDIT_DISTANCE_LIMIT)
        <= _NAME_MATCH_EDIT_DISTANCE_LIMIT
    )


# 서울시 실시간 도시데이터 매뉴얼 V8.5(2026-04) 표 2-2/표 3-9에 실린 카테고리별
# 개수. 로드한 파일이 이 개수와 어긋나면 우리 스냅샷이 매뉴얼과 다른 걸 뜻하므로
# 조용히 넘어가지 않고 바로 예외로 끊는다.
_EXPECTED_CATEGORY_COUNTS: dict[str, dict[str, int]] = {
    "population_areas_121.json": {
        "고궁·문화유산": 5,
        "관광특구": 7,
        "공원": 33,
        "발달상권": 28,
        "인구밀집지역": 48,
    },
    "commercial_areas_82.json": {
        "관광특구": 7,
        "발달상권": 28,
        "인구밀집지역": 45,
        "고궁·문화유산": 2,
    },
}

_REQUIRED_FIELDS = ("code", "name", "latitude", "longitude")
# 대한민국 대략 bounding box. 이 범위 밖 좌표는 데이터 입력 실수로 본다.
_LATITUDE_RANGE = (33.0, 39.0)
_LONGITUDE_RANGE = (124.0, 132.0)


def _validate_rows(rows: list[dict[str, object]], *, filename: str) -> None:
    seen_codes: set[str] = set()
    category_counts: dict[str, int] = {}
    for index, row in enumerate(rows):
        missing = [field for field in _REQUIRED_FIELDS if row.get(field) in (None, "")]
        if missing:
            raise ValueError(f"{filename} {index}번째 항목에 필수 필드가 없습니다: {missing}")
        code = row["code"]
        if code in seen_codes:
            raise ValueError(f"{filename}에 코드가 중복됩니다: {code}")
        seen_codes.add(code)
        latitude, longitude = float(row["latitude"]), float(row["longitude"])
        if not (_LATITUDE_RANGE[0] <= latitude <= _LATITUDE_RANGE[1]):
            raise ValueError(f"{filename} {code}의 위도가 범위 밖입니다: {latitude}")
        if not (_LONGITUDE_RANGE[0] <= longitude <= _LONGITUDE_RANGE[1]):
            raise ValueError(f"{filename} {code}의 경도가 범위 밖입니다: {longitude}")
        category = row.get("category")
        if category is not None:
            category_counts[category] = category_counts.get(category, 0) + 1

    expected = _EXPECTED_CATEGORY_COUNTS.get(filename)
    if expected is not None and category_counts != expected:
        raise ValueError(
            f"{filename}의 카테고리별 개수가 서울시 실시간 도시데이터 매뉴얼과 "
            f"다릅니다. 기대값={expected}, 실제값={category_counts}"
        )


def _load_areas(path: Path) -> tuple[SeoulRealtimeArea, ...]:
    with path.open(encoding="utf-8") as fp:
        payload = json.load(fp)
    rows = payload["areas"]
    _validate_rows(rows, filename=path.name)
    return tuple(
        SeoulRealtimeArea(
            code=row["code"],
            name=row["name"],
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
        )
        for row in rows
    )


# 정적 데이터라 프로세스당 한 번만 읽는다.
POPULATION_AREAS = _load_areas(_POPULATION_PATH)
COMMERCIAL_AREAS = _load_areas(_COMMERCIAL_PATH)


def _select_nearest(
    areas: tuple[SeoulRealtimeArea, ...],
    *,
    latitude: float,
    longitude: float,
    max_distance_km: float,
    requested_name: str | None = None,
) -> tuple[SeoulRealtimeArea, float] | None:
    # 이름이 사실상 같은 지역이 목록에 있으면 좌표 최근접보다 그걸 우선한다 —
    # 중심좌표 오차 때문에 같은 장소를 "N km 떨어진 곳"으로 잘못 대체하지
    # 않기 위해서다. 이름 매칭은 82/121곳 안에서 편집거리 1 이내인 후보를
    # 찾는 것뿐이라 서로 다른 실존 지역을 혼동할 위험이 낮다.
    if requested_name:
        name_match = next(
            (candidate for candidate in areas if names_match(candidate.name, requested_name)),
            None,
        )
        if name_match is not None:
            distance_km = haversine_km(
                latitude, longitude, name_match.latitude, name_match.longitude
            )
            # 이름이 같아도 여전히 max_distance_km는 지킨다 — 좌표가 아예 서비스
            # 지역 밖(예: 지오코딩 오류)이면 "같은 이름"만으로 실제로는 대체
            # 불가능한 지역을 정답처럼 반환하면 안 된다.
            if distance_km <= max_distance_km:
                return name_match, round(distance_km, 2)

    area = min(
        areas,
        key=lambda candidate: haversine_km(
            latitude, longitude, candidate.latitude, candidate.longitude
        ),
    )
    distance_km = haversine_km(latitude, longitude, area.latitude, area.longitude)
    if distance_km > max_distance_km:
        return None
    return area, round(distance_km, 2)


def select_nearest_commercial_area(
    *,
    latitude: float,
    longitude: float,
    max_distance_km: float = COMMERCIAL_AREA_PROXY_MAX_DISTANCE_KM,
    requested_name: str | None = None,
) -> tuple[SeoulRealtimeArea, float] | None:
    """좌표에서 가장 가까운 **상권**(``citydata_cmrcl``) 제공 지역을 반환한다.

    82개 목록만 본다 — 상권 데이터는 이 82곳 밖에는 애초에 없어서, 더 넓은 인구
    목록을 봐도 대신할 데이터가 없다. ``requested_name``을 주면 좌표가 조금 어긋나도
    이름이 사실상 같은 지역을 최근접보다 우선한다.
    """

    return _select_nearest(
        COMMERCIAL_AREAS,
        latitude=latitude,
        longitude=longitude,
        max_distance_km=max_distance_km,
        requested_name=requested_name,
    )


def select_nearest_population_area(
    *,
    latitude: float,
    longitude: float,
    max_distance_km: float = POPULATION_AREA_PROXY_MAX_DISTANCE_KM,
    requested_name: str | None = None,
) -> tuple[SeoulRealtimeArea, float] | None:
    """좌표에서 가장 가까운 **인구 혼잡도**(``citydata``/``citydata_ppltn``) 제공 지역을 반환한다.

    121개 목록을 본다 — 상권 82개 목록에는 없는 경복궁·한강공원·고궁 등도 여기엔
    있어서, 상권 목록만 볼 때보다 더 가깝고 정확한 지역으로 맞힐 수 있다.
    ``requested_name``을 주면 좌표가 조금 어긋나도 이름이 사실상 같은 지역을
    최근접보다 우선한다.
    """

    return _select_nearest(
        POPULATION_AREAS,
        latitude=latitude,
        longitude=longitude,
        max_distance_km=max_distance_km,
        requested_name=requested_name,
    )


__all__ = [
    "COMMERCIAL_AREAS",
    "COMMERCIAL_AREA_PROXY_MAX_DISTANCE_KM",
    "POPULATION_AREAS",
    "POPULATION_AREA_PROXY_MAX_DISTANCE_KM",
    "SeoulRealtimeArea",
    "names_match",
    "select_nearest_commercial_area",
    "select_nearest_population_area",
]
