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
class SegmentWeather:
    """구간 이동수단 판정에 쓰는 날씨 **사실**. 좋다/나쁘다는 담지 않는다(D-051).

    C의 계약 타입(`agent_context.schemas.WeatherForecast`)을 그대로 쓰지 않는
    이유는 방향이다 — 이 모듈은 순수 계약이라 위쪽 계약을 import하면 의존이
    거꾸로 서고, `app.schedule.schemas`가 이 타입을 쓰는 순간 순환이 된다.
    담는 사실은 같고, 옮겨 담는 것은 A(`agent_runtime._segment_weather()`)가 한다.

    사용자가 발화에서 말한 날씨(`UserConditions.weather`)와 다르다. 그쪽은
    "말했다"는 사실이고 이쪽은 조회한 예보다.
    """

    precipitation: str | None = None
    sky: str | None = None
    temperature_celsius: float | None = None


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
    "SegmentWeather",
    "TravelConfidence",
]
