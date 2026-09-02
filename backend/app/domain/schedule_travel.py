"""일정 편성이 소비하는 방향성 구간 이동정보 계약."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.domain.travel_route import (
    GeoCoordinate,
    RouteSource,
    RouteStatus,
    TravelMode,
)


class TravelConfidence(StrEnum):
    """일정 구간 이동시간의 신뢰 수준."""

    HIGH = "high"
    LOW = "low"


@dataclass(frozen=True)
class ScheduleTravelCandidate:
    """일정 구간 계산에 필요한 장소 식별자와 좌표."""

    place_id: str
    coordinate: GeoCoordinate

    def __post_init__(self) -> None:
        if not self.place_id.strip():
            raise ValueError("place_id는 비어 있을 수 없습니다.")


@dataclass(frozen=True)
class ScheduleTravelPair:
    """이동정보가 필요한 방향성 장소 쌍."""

    from_place_id: str
    to_place_id: str

    def __post_init__(self) -> None:
        if not self.from_place_id.strip() or not self.to_place_id.strip():
            raise ValueError("구간의 place_id는 비어 있을 수 없습니다.")


@dataclass(frozen=True)
class ScheduleTravelEdge:
    """한 방향 구간의 정규화된 이동정보."""

    from_place_id: str
    to_place_id: str
    mode: TravelMode
    status: RouteStatus
    source: RouteSource
    duration_min: int
    distance_m: int | None
    confidence: TravelConfidence
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not self.from_place_id.strip() or not self.to_place_id.strip():
            raise ValueError("구간의 place_id는 비어 있을 수 없습니다.")
        if self.from_place_id == self.to_place_id:
            raise ValueError("자기 자신으로 향하는 이동 구간은 만들 수 없습니다.")
        if self.duration_min < 0:
            raise ValueError("duration_min은 0 이상이어야 합니다.")
        if self.distance_m is not None and self.distance_m < 0:
            raise ValueError("distance_m는 0 이상이어야 합니다.")


@dataclass(frozen=True)
class ScheduleTravelWarning:
    """건너뛴 구간 하나와 그 사유.

    경고 코드만 모아두면 후보가 10곳일 때 90개 요청 중 어느 구간이 빠졌는지
    알 수 없으므로, 사유와 함께 어느 방향 쌍에서 났는지를 같이 남긴다.
    """

    code: str
    from_place_id: str
    to_place_id: str


@dataclass(frozen=True)
class ScheduleTravelEstimateResult:
    """요청된 구간들의 추정 이동정보와 비차단 경고."""

    edges: tuple[ScheduleTravelEdge, ...]
    warnings: tuple[ScheduleTravelWarning, ...] = ()

    def edge_by_pair(self) -> dict[tuple[str, str], ScheduleTravelEdge]:
        return {
            (edge.from_place_id, edge.to_place_id): edge
            for edge in self.edges
        }


__all__ = [
    "ScheduleTravelCandidate",
    "ScheduleTravelEdge",
    "ScheduleTravelEstimateResult",
    "ScheduleTravelPair",
    "ScheduleTravelWarning",
    "TravelConfidence",
]
