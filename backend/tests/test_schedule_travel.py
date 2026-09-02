from __future__ import annotations

import itertools

import pytest

from app.domain.schedule_travel import (
    ScheduleTravelCandidate,
    ScheduleTravelPair,
    ScheduleTravelWarning,
    TravelConfidence,
)
from app.domain.travel_route import GeoCoordinate, RouteSource, RouteStatus, TravelMode
from app.schemas import Transport
from app.tools.schedule_travel import (
    SCHEDULE_TRAVEL_DUPLICATE_PAIR_WARNING,
    SCHEDULE_TRAVEL_SELF_PAIR_WARNING,
    SCHEDULE_TRAVEL_UNKNOWN_PLACE_WARNING,
    estimate_schedule_travel_edges,
)

WALKING_SPEED_MPS = 1.0
TRANSIT_SPEED_MPS = 5.5
DRIVING_SPEED_MPS = 5.5
WALK_THRESHOLD_MIN = 20


def _candidate(place_id: str, longitude: float) -> ScheduleTravelCandidate:
    return ScheduleTravelCandidate(
        place_id=place_id,
        coordinate=GeoCoordinate(latitude=37.5, longitude=longitude),
    )


def _estimate(
    candidates: list[ScheduleTravelCandidate],
    pairs: list[ScheduleTravelPair],
    *,
    transport: Transport | None = None,
):
    return estimate_schedule_travel_edges(
        candidates=candidates,
        pairs=pairs,
        transport=transport,
        walking_speed_mps=WALKING_SPEED_MPS,
        transit_speed_mps=TRANSIT_SPEED_MPS,
        driving_speed_mps=DRIVING_SPEED_MPS,
        walk_transfer_threshold_min=WALK_THRESHOLD_MIN,
    )


def test_requested_full_directional_pairs_create_six_edges_for_three_places() -> None:
    candidates = [_candidate("a", 126.90), _candidate("b", 126.91), _candidate("c", 126.92)]
    pairs = [
        ScheduleTravelPair(first.place_id, second.place_id)
        for first, second in itertools.permutations(candidates, 2)
    ]

    result = _estimate(candidates, pairs)

    assert len(result.edges) == 6
    assert set(result.edge_by_pair()) == {
        ("a", "b"),
        ("a", "c"),
        ("b", "a"),
        ("b", "c"),
        ("c", "a"),
        ("c", "b"),
    }


def test_only_requested_pairs_are_created() -> None:
    candidates = [_candidate("a", 126.90), _candidate("b", 126.91), _candidate("c", 126.92)]

    result = _estimate(
        candidates,
        [ScheduleTravelPair("a", "b"), ScheduleTravelPair("b", "c")],
    )

    assert set(result.edge_by_pair()) == {("a", "b"), ("b", "c")}


@pytest.mark.parametrize("transport", [None, Transport.PUBLIC])
def test_unspecified_or_public_transport_walks_short_segment(
    transport: Transport | None,
) -> None:
    candidates = [_candidate("a", 126.900), _candidate("b", 126.901)]

    [edge] = _estimate(
        candidates, [ScheduleTravelPair("a", "b")], transport=transport
    ).edges

    assert edge.mode is TravelMode.WALKING


@pytest.mark.parametrize("transport", [None, Transport.PUBLIC])
def test_unspecified_or_public_transport_uses_transit_for_long_segment(
    transport: Transport | None,
) -> None:
    candidates = [_candidate("a", 126.90), _candidate("b", 127.00)]

    [edge] = _estimate(
        candidates, [ScheduleTravelPair("a", "b")], transport=transport
    ).edges

    assert edge.mode is TravelMode.TRANSIT


def test_explicit_walking_does_not_silently_switch_long_segment_to_transit() -> None:
    candidates = [_candidate("a", 126.90), _candidate("b", 127.00)]

    [edge] = _estimate(
        candidates,
        [ScheduleTravelPair("a", "b")],
        transport=Transport.WALK,
    ).edges

    assert edge.mode is TravelMode.WALKING


def test_explicit_car_uses_driving() -> None:
    candidates = [_candidate("a", 126.900), _candidate("b", 126.901)]

    [edge] = _estimate(
        candidates,
        [ScheduleTravelPair("a", "b")],
        transport=Transport.CAR,
    ).edges

    assert edge.mode is TravelMode.DRIVING


def test_estimated_edge_exposes_source_status_confidence_and_rounded_minutes() -> None:
    candidates = [_candidate("a", 126.9000), _candidate("b", 126.9001)]

    [edge] = _estimate(candidates, [ScheduleTravelPair("a", "b")]).edges

    assert edge.distance_m > 0
    assert edge.duration_min == 1
    assert edge.status is RouteStatus.SUCCESS
    assert edge.source is RouteSource.STRAIGHT_LINE_ESTIMATE
    assert edge.confidence is TravelConfidence.LOW


def test_distinct_places_at_same_coordinate_can_have_zero_duration() -> None:
    candidates = [_candidate("a", 126.90), _candidate("b", 126.90)]

    [edge] = _estimate(candidates, [ScheduleTravelPair("a", "b")]).edges

    assert edge.distance_m == 0
    assert edge.duration_min == 0


def test_duplicate_candidate_ids_are_rejected() -> None:
    candidates = [_candidate("same", 126.90), _candidate("same", 126.91)]

    with pytest.raises(ValueError, match="중복"):
        _estimate(candidates, [])


def test_invalid_pairs_are_skipped_and_reported_as_warnings() -> None:
    candidates = [_candidate("a", 126.90), _candidate("b", 126.91)]
    pairs = [
        ScheduleTravelPair("a", "b"),
        ScheduleTravelPair("a", "b"),
        ScheduleTravelPair("a", "a"),
        ScheduleTravelPair("a", "missing"),
    ]

    result = _estimate(candidates, pairs)

    assert len(result.edges) == 1
    assert result.warnings == (
        ScheduleTravelWarning(SCHEDULE_TRAVEL_DUPLICATE_PAIR_WARNING, "a", "b"),
        ScheduleTravelWarning(SCHEDULE_TRAVEL_SELF_PAIR_WARNING, "a", "a"),
        ScheduleTravelWarning(SCHEDULE_TRAVEL_UNKNOWN_PLACE_WARNING, "a", "missing"),
    )


@pytest.mark.parametrize(
    ("walking", "transit", "driving", "threshold"),
    [
        (0.0, 5.5, 5.5, 20),
        (1.0, 0.0, 5.5, 20),
        (1.0, 5.5, 0.0, 20),
        (1.0, 5.5, 5.5, 0),
    ],
)
def test_non_positive_speed_or_threshold_is_rejected(
    walking: float,
    transit: float,
    driving: float,
    threshold: int,
) -> None:
    with pytest.raises(ValueError):
        estimate_schedule_travel_edges(
            candidates=[],
            pairs=[],
            transport=None,
            walking_speed_mps=walking,
            transit_speed_mps=transit,
            driving_speed_mps=driving,
            walk_transfer_threshold_min=threshold,
        )
