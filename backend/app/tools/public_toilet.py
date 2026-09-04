"""근처 공중화장실 조회 Tool.

다른 Tool과 달리 외부 API가 아니라 적재된 저장소를 감싼다 — 서울시 API가 구·좌표
필터를 지원하지 않아 요청 때마다 전량을 받을 수 없기 때문이다(providers/
public_toilet.py 참고). 거리 정렬과 "지금 열림" 판정까지 여기서 끝내고, 위층은
정렬된 결과만 받는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.models import PublicToilet
from app.errors import AppError
from app.geo import haversine_km
from app.public_toilet_hours import OpenHours, is_open_at, parse_open_hours
from app.repositories.protocols import PublicToiletRepository
from app.tools.contracts import ToolError, ToolStatus

# 바운딩 박스에서 가져올 상한. 최종 노출은 2곳뿐이지만, 박스가 원보다 넓고
# "지금 열린 곳"만 골라내야 해서 넉넉히 받아 걸러낸다.
_FETCH_LIMIT = 60


@dataclass(frozen=True)
class PublicToiletQuery:
    latitude: float
    longitude: float
    radius_km: float = 1.0
    # 조회 시각. "지금 열려 있나"를 판정하는 기준이라 호출부가 주입한다.
    now: datetime | None = None


@dataclass(frozen=True)
class NearbyToilet:
    """거리와 개방 여부까지 판정한 화장실 한 곳."""

    toilet: PublicToilet
    distance_km: float
    hours: OpenHours
    # 지금 열려 있는지. 개방시간을 시각으로 읽지 못한 곳은 None이다 —
    # 열림/닫힘 둘 중 하나로 단정하면 급한 사용자를 닫힌 곳으로 보내게 된다.
    open_now: bool | None


@dataclass(frozen=True)
class PublicToiletToolResult:
    status: ToolStatus
    toilets: tuple[NearbyToilet, ...]
    error: ToolError | None
    provider_metadata: tuple[object, ...] = ()


class GetPublicToiletTool:
    def __init__(self, repository: PublicToiletRepository) -> None:
        self._repository = repository

    async def execute(self, query: PublicToiletQuery) -> PublicToiletToolResult:
        try:
            rows = await self._repository.find_near(
                query.latitude,
                query.longitude,
                radius_km=query.radius_km,
                limit=_FETCH_LIMIT,
            )
        except AppError as exc:
            return PublicToiletToolResult(
                status=ToolStatus.UNAVAILABLE,
                toilets=(),
                error=ToolError(
                    code="unavailable",
                    message="근처 공중화장실 정보를 가져오지 못했습니다.",
                    cause="timeout" if exc.code == "provider_timeout" else "upstream_error",
                    retryable=exc.retryable,
                ),
            )

        nearby = _rank_toilets(rows, query)
        return PublicToiletToolResult(
            status=ToolStatus.SUCCESS if nearby else ToolStatus.NO_DATA,
            toilets=nearby,
            error=None,
        )


def _rank_toilets(
    rows: tuple[PublicToilet, ...], query: PublicToiletQuery
) -> tuple[NearbyToilet, ...]:
    """반지름 안으로 걸러 "지금 열린 곳 → 가까운 곳" 순으로 정렬한다.

    급해서 묻는 질문이라 거리보다 "지금 들어갈 수 있는가"가 먼저다. 20m 더 가까운
    닫힌 화장실을 앞세우면 답이 쓸모없어진다. 개방 여부를 모르는 곳은 열린 곳
    뒤, 닫힌 곳 앞에 둔다 — 가능성은 있으니까.
    """

    weekday, minute_of_day = _now_parts(query.now)
    candidates: list[NearbyToilet] = []
    for toilet in rows:
        distance = haversine_km(
            query.latitude, query.longitude, toilet.latitude, toilet.longitude
        )
        if distance > query.radius_km:
            continue
        hours = parse_open_hours(toilet.open_hours_raw)
        candidates.append(
            NearbyToilet(
                toilet=toilet,
                distance_km=distance,
                hours=hours,
                open_now=is_open_at(hours, weekday, minute_of_day),
            )
        )

    candidates.sort(key=lambda item: (_open_rank(item.open_now), item.distance_km))
    return tuple(candidates)


def _open_rank(open_now: bool | None) -> int:
    if open_now is True:
        return 0
    if open_now is None:
        return 1
    return 2


def _now_parts(now: datetime | None) -> tuple[int, int]:
    moment = now if now is not None else datetime.now()
    return moment.weekday(), moment.hour * 60 + moment.minute


__all__ = [
    "GetPublicToiletTool",
    "NearbyToilet",
    "PublicToiletQuery",
    "PublicToiletToolResult",
]
