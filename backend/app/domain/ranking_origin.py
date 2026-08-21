"""거리·경로·근거 문장이 함께 쓰는 랭킹 기준점을 정한다.

후보를 **모으는** 중심과 후보를 **줄 세우는** 기준점은 다르다(TP-112).

- 수집 중심은 검색 기준점(`context.location`)이다. "안국역 근처 갈만한 곳"이면
  안국역 주변을 뒤지는 게 맞다.
- 랭킹 기준점은 사용자 위치(`context.user_location`)다. 실제로 이동하는 사람은
  사용자이기 때문이다. 안국역에서 같은 거리에 있는 두 후보라도 사용자 쪽에 있는
  쪽이 실제로 더 가깝고, 타겟 기준으로는 그 둘이 동점이라 구분되지 않는다.

사용자 위치를 모르면(발화도 기기 GPS도 없는 요청) 검색 기준점으로 돌아간다 —
지어낸 좌표로 줄을 세우지 않는다.
"""

from __future__ import annotations

import math

from app.agent_context.schemas import (
    ContextValue,
    RecommendationContext,
    ResolvedLocation,
)
from app.place_search_policy import EARTH_RADIUS_KM


def haversine_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """두 좌표 사이 대권거리(km). 소수점 3자리에서 반올림한다."""

    latitude_delta = math.radians(latitude_b - latitude_a)
    longitude_delta = math.radians(longitude_b - longitude_a)
    value = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(math.radians(latitude_a))
        * math.cos(math.radians(latitude_b))
        * math.sin(longitude_delta / 2) ** 2
    )
    return round(EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(value)), 3)


def _usable(value: ContextValue[ResolvedLocation] | None) -> ResolvedLocation | None:
    """조회에 성공해 좌표가 실제로 들어 있는 것만 통과시킨다."""

    if value is None or value.status not in {"success", "partial"} or value.data is None:
        return None
    return value.data


def resolve_ranking_origin(context: RecommendationContext) -> ResolvedLocation | None:
    """거리·경로·근거 문장이 기준으로 삼을 좌표. 사용자 위치를 우선한다."""

    return _usable(context.user_location) or _usable(context.location)


def resolve_search_center(context: RecommendationContext) -> ResolvedLocation | None:
    """후보를 모은 중심. 랭킹 기준점과 달리 언제나 검색 기준점이다."""

    return _usable(context.location)


def resolve_user_to_target_km(context: RecommendationContext) -> float | None:
    """사용자 위치에서 검색 기준점까지의 직선거리(km).

    거리 점수의 분모를 사용자 기준으로 되돌리는 데 쓴다. 사용자가 이동시간을
    말하지 않은 요청은 분모가 `DEFAULT_PLACE_SEARCH_RADIUS_KM`인데, 이 값은
    "타겟 주변 얼마를 뒤지는가"라는 **수집 정책**에서 빌려온 거리라 원점이 타겟에
    묶여 있다. 분자만 사용자 기준으로 바꾸면 사용자가 타겟에서 멀 때 모든 후보가
    분모를 넘겨 거리 점수가 전부 0이 된다(가중치 0.20이 통째로 죽는다).

    후보는 전부 타겟 중심 수집 반경 안에 있으므로, 삼각부등식에 따라 사용자
    기준 거리는 이 값 + 수집 반경을 넘을 수 없다. 그래서 이 값을 분모에 더하면
    어떤 후보도 0으로 잘리지 않는다(`to_search_radius_km` 참고).

    사용자가 이동시간을 **말한** 요청에는 쓰지 않는다. 그때 분모는 사용자가 말한
    시간 약속이고, 시간 약속은 어디서 재든 같은 값이라 이미 원점이 없다 —
    거기 이 거리를 더하면 "30분"이 사실상 30분+α가 된다(scoring.py 참고).

    사용자 위치나 검색 기준점을 모르면 None이다. 둘이 같은 곳으로 해석됐으면
    0.0이 나오고, 그때는 분모가 그대로 유지된다.
    """

    origin = _usable(context.user_location)
    target = _usable(context.location)
    if origin is None or target is None:
        return None
    return haversine_km(
        origin.location.latitude,
        origin.location.longitude,
        target.location.latitude,
        target.location.longitude,
    )


__all__ = [
    "haversine_km",
    "resolve_ranking_origin",
    "resolve_search_center",
    "resolve_user_to_target_km",
]
