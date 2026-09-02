"""외부 API 없이 일정 구간의 거리·이동시간 추정값을 만든다."""

from __future__ import annotations

import math
from collections.abc import Sequence

from app.domain.schedule_travel import (
    ScheduleTravelCandidate,
    ScheduleTravelEdge,
    ScheduleTravelEstimateResult,
    ScheduleTravelPair,
    ScheduleTravelWarning,
    TravelConfidence,
)
from app.domain.travel_route import RouteSource, RouteStatus, TravelMode
from app.geo import haversine_km
from app.schemas import Transport

SCHEDULE_TRAVEL_DUPLICATE_PAIR_WARNING = "schedule_travel_duplicate_pair"
SCHEDULE_TRAVEL_SELF_PAIR_WARNING = "schedule_travel_self_pair"
SCHEDULE_TRAVEL_UNKNOWN_PLACE_WARNING = "schedule_travel_unknown_place"


def _validate_speeds(
    walking_speed_mps: float,
    transit_speed_mps: float,
    driving_speed_mps: float,
    walk_transfer_threshold_min: int,
) -> None:
    if walking_speed_mps <= 0 or transit_speed_mps <= 0 or driving_speed_mps <= 0:
        raise ValueError("이동수단별 속도는 0보다 커야 합니다.")
    if walk_transfer_threshold_min <= 0:
        raise ValueError("도보 전환 임계값은 0보다 커야 합니다.")


def _candidate_index(
    candidates: Sequence[ScheduleTravelCandidate],
) -> dict[str, ScheduleTravelCandidate]:
    result: dict[str, ScheduleTravelCandidate] = {}
    for candidate in candidates:
        if candidate.place_id in result:
            raise ValueError(f"후보 place_id는 중복될 수 없습니다: {candidate.place_id}")
        result[candidate.place_id] = candidate
    return result


def _select_mode(
    transport: Transport | None,
    *,
    distance_m: int,
    walking_speed_mps: float,
    walk_transfer_threshold_min: int,
) -> TravelMode:
    if transport is Transport.WALK:
        return TravelMode.WALKING
    if transport is Transport.CAR:
        return TravelMode.DRIVING

    walking_seconds = distance_m / walking_speed_mps
    if walking_seconds <= walk_transfer_threshold_min * 60:
        return TravelMode.WALKING
    return TravelMode.TRANSIT


def _speed_for_mode(
    mode: TravelMode,
    *,
    walking_speed_mps: float,
    transit_speed_mps: float,
    driving_speed_mps: float,
) -> float:
    if mode is TravelMode.WALKING:
        return walking_speed_mps
    if mode is TravelMode.TRANSIT:
        return transit_speed_mps
    return driving_speed_mps


def estimate_schedule_travel_edges(
    *,
    candidates: Sequence[ScheduleTravelCandidate],
    pairs: Sequence[ScheduleTravelPair],
    transport: Transport | None,
    walking_speed_mps: float,
    transit_speed_mps: float,
    driving_speed_mps: float,
    walk_transfer_threshold_min: int,
) -> ScheduleTravelEstimateResult:
    """요청된 방향 쌍만 직선거리 기반 일정 이동정보로 변환한다.

    이동수단 미지정과 대중교통 명시는 가까운 구간을 도보로 연결하고, 도보 예상시간이
    임계값을 넘는 구간만 대중교통으로 전환한다. 도보·자동차 명시는 그대로 유지한다.
    잘못된 일부 쌍은 전체 요청을 실패시키지 않고 건너뛰며, 사유와 그 방향 쌍을 담은
    `ScheduleTravelWarning`으로 드러낸다.

    속도 셋과 도보 전환 임계값은 이 함수가 설정을 직접 읽지 않고 인자로 받는다.
    호출자가 `Settings.walking_speed_mps`, `Settings.transit_speed_mps`,
    `Settings.driving_speed_mps`, `Settings.schedule_walk_transfer_threshold_min`을
    넘겨야 `.env` 값이 실제로 반영된다.
    """

    _validate_speeds(
        walking_speed_mps,
        transit_speed_mps,
        driving_speed_mps,
        walk_transfer_threshold_min,
    )
    candidate_by_id = _candidate_index(candidates)
    seen_pairs: set[tuple[str, str]] = set()
    edges: list[ScheduleTravelEdge] = []
    warnings: list[ScheduleTravelWarning] = []

    def _warn(code: str, pair: ScheduleTravelPair) -> None:
        warnings.append(
            ScheduleTravelWarning(
                code=code,
                from_place_id=pair.from_place_id,
                to_place_id=pair.to_place_id,
            )
        )

    for pair in pairs:
        key = (pair.from_place_id, pair.to_place_id)
        if key in seen_pairs:
            _warn(SCHEDULE_TRAVEL_DUPLICATE_PAIR_WARNING, pair)
            continue
        seen_pairs.add(key)

        if pair.from_place_id == pair.to_place_id:
            _warn(SCHEDULE_TRAVEL_SELF_PAIR_WARNING, pair)
            continue
        origin = candidate_by_id.get(pair.from_place_id)
        destination = candidate_by_id.get(pair.to_place_id)
        if origin is None or destination is None:
            _warn(SCHEDULE_TRAVEL_UNKNOWN_PLACE_WARNING, pair)
            continue

        distance_m = round(
            haversine_km(
                origin.coordinate.latitude,
                origin.coordinate.longitude,
                destination.coordinate.latitude,
                destination.coordinate.longitude,
            )
            * 1000
        )
        mode = _select_mode(
            transport,
            distance_m=distance_m,
            walking_speed_mps=walking_speed_mps,
            walk_transfer_threshold_min=walk_transfer_threshold_min,
        )
        speed_mps = _speed_for_mode(
            mode,
            walking_speed_mps=walking_speed_mps,
            transit_speed_mps=transit_speed_mps,
            driving_speed_mps=driving_speed_mps,
        )
        duration_min = math.ceil(distance_m / speed_mps / 60)
        edges.append(
            ScheduleTravelEdge(
                from_place_id=pair.from_place_id,
                to_place_id=pair.to_place_id,
                mode=mode,
                status=RouteStatus.SUCCESS,
                source=RouteSource.STRAIGHT_LINE_ESTIMATE,
                duration_min=duration_min,
                distance_m=distance_m,
                confidence=TravelConfidence.LOW,
            )
        )

    return ScheduleTravelEstimateResult(edges=tuple(edges), warnings=tuple(warnings))


__all__ = [
    "SCHEDULE_TRAVEL_DUPLICATE_PAIR_WARNING",
    "SCHEDULE_TRAVEL_SELF_PAIR_WARNING",
    "SCHEDULE_TRAVEL_UNKNOWN_PLACE_WARNING",
    "estimate_schedule_travel_edges",
]
