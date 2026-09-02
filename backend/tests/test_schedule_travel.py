from __future__ import annotations

import itertools
from dataclasses import replace

import pytest

from app.domain.schedule_travel import (
    ScheduleTravelCandidate,
    ScheduleTravelPair,
    ScheduleTravelWarning,
    TravelConfidence,
)
from app.domain.travel_route import (
    GeoCoordinate,
    RouteDestination,
    RouteSource,
    RouteStatus,
    TravelMode,
    TravelRoute,
    TravelRouteBatch,
)
from app.errors import ProviderTimeoutError
from app.providers.contracts import ProviderSource, ProviderStatus, provider_result
from app.providers.walking_route import FakeWalkingRouteProvider
from app.schemas import Transport
from app.tools.schedule_travel import (
    SCHEDULE_TRAVEL_DUPLICATE_PAIR_WARNING,
    SCHEDULE_TRAVEL_MEASURE_BUDGET_EXCEEDED_WARNING,
    SCHEDULE_TRAVEL_MEASURE_FAILED_WARNING,
    SCHEDULE_TRAVEL_MEASURE_UNAVAILABLE_WARNING,
    SCHEDULE_TRAVEL_SELF_PAIR_WARNING,
    SCHEDULE_TRAVEL_UNKNOWN_PLACE_WARNING,
    estimate_schedule_travel_edges,
    measure_schedule_travel_edges,
)
from app.tools.travel_route import TravelRouteProviders, TravelRouteTool

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


# --- 실측(measure_schedule_travel_edges) ------------------------------------

_MEASURED_SOURCE = {
    TravelMode.WALKING: RouteSource.KAKAO_WALKING,
    TravelMode.DRIVING: RouteSource.NAVER_DRIVING,
    TravelMode.TRANSIT: RouteSource.KAKAO_TRANSIT,
}


class _StubRouteProvider:
    """목적지별로 성공·실패를 미리 정해 돌려주는 경로 Provider."""

    def __init__(
        self,
        *,
        failed_place_ids: frozenset[str] = frozenset(),
        duration_seconds: int = 600,
    ) -> None:
        self._failed_place_ids = failed_place_ids
        self._duration_seconds = duration_seconds
        self.calls: list[tuple[GeoCoordinate, tuple[str, ...], TravelMode]] = []

    async def get_routes(
        self,
        origin: GeoCoordinate,
        destinations: tuple[RouteDestination, ...],
        *,
        mode: TravelMode = TravelMode.WALKING,
        radius_m: int | None = None,
    ):
        self.calls.append(
            (origin, tuple(item.place_id for item in destinations), mode)
        )
        routes = tuple(
            TravelRoute(
                place_id=item.place_id,
                mode=mode,
                status=RouteStatus.NO_DATA,
                source=_MEASURED_SOURCE[mode],
                error_code="stub_no_route",
            )
            if item.place_id in self._failed_place_ids
            else TravelRoute(
                place_id=item.place_id,
                mode=mode,
                status=RouteStatus.SUCCESS,
                source=_MEASURED_SOURCE[mode],
                distance_m=1_200,
                duration_seconds=self._duration_seconds,
            )
            for item in destinations
        )
        successful = sum(route.status is RouteStatus.SUCCESS for route in routes)
        return provider_result(
            TravelRouteBatch(routes=routes),
            source=ProviderSource.KAKAO_WALKING_ROUTE,
            status=ProviderStatus.SUCCESS
            if successful == len(routes)
            else ProviderStatus.PARTIAL,
        )


class _RaisingRouteProvider:
    """Provider가 통째로 죽은 상황."""

    async def get_routes(self, origin, destinations, *, mode=TravelMode.WALKING, radius_m=None):
        raise ProviderTimeoutError("Stub Route")


def _tool(primary, *, fallback=None, modes=(TravelMode.WALKING,)) -> TravelRouteTool:
    return TravelRouteTool(
        {
            mode: TravelRouteProviders(primary=primary, fallback=fallback)
            for mode in modes
        }
    )


def _estimated(candidates: list[ScheduleTravelCandidate], pairs: list[ScheduleTravelPair]):
    return _estimate(candidates, pairs).edges


@pytest.mark.asyncio
async def test_measured_edges_carry_provider_source_and_high_confidence() -> None:
    candidates = [_candidate("a", 126.900), _candidate("b", 126.901)]
    estimated = _estimated(candidates, [ScheduleTravelPair("a", "b")])

    result = await measure_schedule_travel_edges(
        tool=_tool(_StubRouteProvider(duration_seconds=630)),
        candidates=candidates,
        estimated_edges=estimated,
        max_measured_segments=10,
    )

    [edge] = result.edges
    assert edge.source is RouteSource.KAKAO_WALKING
    assert edge.confidence is TravelConfidence.HIGH
    assert edge.distance_m == 1_200
    # 630초는 10.5분이라 11분으로 올린다.
    assert edge.duration_min == 11
    assert edge.error_code is None
    assert result.warnings == ()


@pytest.mark.asyncio
async def test_opposite_directions_are_queried_separately() -> None:
    candidates = [_candidate("a", 126.900), _candidate("b", 126.901)]
    estimated = _estimated(
        candidates, [ScheduleTravelPair("a", "b"), ScheduleTravelPair("b", "a")]
    )
    provider = _StubRouteProvider()

    result = await measure_schedule_travel_edges(
        tool=_tool(provider),
        candidates=candidates,
        estimated_edges=estimated,
        max_measured_segments=10,
    )

    assert set(result.edge_by_pair()) == {("a", "b"), ("b", "a")}
    # 출발지가 다르므로 그룹이 갈리고, 각 호출의 목적지는 하나씩이다.
    assert [destinations for _, destinations, _ in provider.calls] == [("b",), ("a",)]
    assert provider.calls[0][0] != provider.calls[1][0]


@pytest.mark.asyncio
async def test_segments_with_different_modes_are_measured_in_one_request() -> None:
    candidates = [_candidate("a", 126.900), _candidate("b", 126.901), _candidate("c", 127.000)]
    # a→b는 가까워 도보, a→c는 멀어 대중교통으로 추정된다.
    estimated = _estimated(
        candidates, [ScheduleTravelPair("a", "b"), ScheduleTravelPair("a", "c")]
    )
    assert {edge.mode for edge in estimated} == {TravelMode.WALKING, TravelMode.TRANSIT}
    provider = _StubRouteProvider()

    result = await measure_schedule_travel_edges(
        tool=_tool(provider, modes=(TravelMode.WALKING, TravelMode.TRANSIT)),
        candidates=candidates,
        estimated_edges=estimated,
        max_measured_segments=10,
    )

    measured = result.edge_by_pair()
    assert measured[("a", "b")].mode is TravelMode.WALKING
    assert measured[("a", "c")].mode is TravelMode.TRANSIT
    assert all(edge.confidence is TravelConfidence.HIGH for edge in result.edges)
    # 출발지는 같지만 이동수단이 달라 그룹이 갈린다.
    assert [mode for _, _, mode in provider.calls] == [
        TravelMode.WALKING,
        TravelMode.TRANSIT,
    ]


@pytest.mark.asyncio
async def test_measured_mode_never_differs_from_estimated_mode() -> None:
    candidates = [_candidate("a", 126.90), _candidate("b", 127.00)]
    estimated = _estimated(candidates, [ScheduleTravelPair("a", "b")])
    assert estimated[0].mode is TravelMode.TRANSIT

    result = await measure_schedule_travel_edges(
        tool=_tool(_StubRouteProvider(), modes=(TravelMode.WALKING, TravelMode.TRANSIT)),
        candidates=candidates,
        estimated_edges=estimated,
        max_measured_segments=10,
    )

    [edge] = result.edges
    assert edge.mode is TravelMode.TRANSIT


@pytest.mark.asyncio
async def test_failed_segment_keeps_estimate_and_reports_error_code() -> None:
    candidates = [_candidate("a", 126.900), _candidate("b", 126.901)]
    [estimate] = _estimated(candidates, [ScheduleTravelPair("a", "b")])

    result = await measure_schedule_travel_edges(
        tool=_tool(_StubRouteProvider(failed_place_ids=frozenset({"b"}))),
        candidates=candidates,
        estimated_edges=[estimate],
        max_measured_segments=10,
    )

    [edge] = result.edges
    assert edge.duration_min == estimate.duration_min
    assert edge.source is RouteSource.STRAIGHT_LINE_ESTIMATE
    assert edge.confidence is TravelConfidence.LOW
    assert edge.error_code == "stub_no_route"
    assert result.warnings == (
        ScheduleTravelWarning(SCHEDULE_TRAVEL_MEASURE_FAILED_WARNING, "a", "b"),
    )


@pytest.mark.asyncio
async def test_dead_provider_keeps_estimate_and_reports_unavailable() -> None:
    candidates = [_candidate("a", 126.900), _candidate("b", 126.901)]
    [estimate] = _estimated(candidates, [ScheduleTravelPair("a", "b")])

    result = await measure_schedule_travel_edges(
        # 자동차·대중교통처럼 추정 fallback이 등록되지 않은 구성이다(D-042).
        tool=_tool(_RaisingRouteProvider()),
        candidates=candidates,
        estimated_edges=[estimate],
        max_measured_segments=10,
    )

    [edge] = result.edges
    assert edge.duration_min == estimate.duration_min
    assert edge.source is RouteSource.STRAIGHT_LINE_ESTIMATE
    assert edge.error_code is not None
    assert result.warnings == (
        ScheduleTravelWarning(SCHEDULE_TRAVEL_MEASURE_UNAVAILABLE_WARNING, "a", "b"),
    )


@pytest.mark.asyncio
async def test_tool_level_walking_fallback_is_reported_as_estimate() -> None:
    candidates = [_candidate("a", 126.900), _candidate("b", 126.901)]
    [estimate] = _estimated(candidates, [ScheduleTravelPair("a", "b")])

    result = await measure_schedule_travel_edges(
        # 도보만 추정 fallback이 붙어 있어 Tool 안에서 값이 채워져 돌아온다.
        tool=_tool(
            _StubRouteProvider(failed_place_ids=frozenset({"b"})),
            fallback=FakeWalkingRouteProvider(walking_speed_mps=WALKING_SPEED_MPS),
        ),
        candidates=candidates,
        estimated_edges=[estimate],
        max_measured_segments=10,
    )

    [edge] = result.edges
    # 값이 채워져 왔어도 실측이 아니므로 실측으로 올리지 않는다.
    assert edge.source is RouteSource.STRAIGHT_LINE_ESTIMATE
    assert edge.confidence is TravelConfidence.LOW
    assert edge.error_code == "stub_no_route"
    assert result.warnings == (
        ScheduleTravelWarning(SCHEDULE_TRAVEL_MEASURE_FAILED_WARNING, "a", "b"),
    )


@pytest.mark.asyncio
async def test_segments_beyond_budget_stay_estimated_in_input_order() -> None:
    candidates = [_candidate("a", 126.900), _candidate("b", 126.901), _candidate("c", 126.902)]
    estimated = _estimated(
        candidates,
        [
            ScheduleTravelPair("a", "b"),
            ScheduleTravelPair("b", "c"),
            ScheduleTravelPair("c", "a"),
        ],
    )
    provider = _StubRouteProvider()

    result = await measure_schedule_travel_edges(
        tool=_tool(provider),
        candidates=candidates,
        estimated_edges=estimated,
        max_measured_segments=2,
    )

    measured = result.edge_by_pair()
    assert measured[("a", "b")].confidence is TravelConfidence.HIGH
    assert measured[("b", "c")].confidence is TravelConfidence.HIGH
    assert measured[("c", "a")].confidence is TravelConfidence.LOW
    assert len(provider.calls) == 2
    assert result.warnings == (
        ScheduleTravelWarning(SCHEDULE_TRAVEL_MEASURE_BUDGET_EXCEEDED_WARNING, "c", "a"),
    )


@pytest.mark.asyncio
async def test_segment_without_coordinates_is_not_measured_and_does_not_spend_budget() -> None:
    candidates = [_candidate("a", 126.900), _candidate("b", 126.901)]
    [known] = _estimated(candidates, [ScheduleTravelPair("a", "b")])
    unknown = replace(known, from_place_id="a", to_place_id="missing")
    provider = _StubRouteProvider()

    result = await measure_schedule_travel_edges(
        tool=_tool(provider),
        candidates=candidates,
        estimated_edges=[unknown, known],
        max_measured_segments=1,
    )

    measured = result.edge_by_pair()
    assert measured[("a", "missing")].confidence is TravelConfidence.LOW
    # 좌표를 몰라 건너뛴 구간이 상한을 깎지 않으므로 뒤 구간이 실측된다.
    assert measured[("a", "b")].confidence is TravelConfidence.HIGH
    assert result.warnings == (
        ScheduleTravelWarning(SCHEDULE_TRAVEL_UNKNOWN_PLACE_WARNING, "a", "missing"),
    )


@pytest.mark.asyncio
async def test_measure_rejects_non_positive_budget() -> None:
    with pytest.raises(ValueError):
        await measure_schedule_travel_edges(
            tool=_tool(_StubRouteProvider()),
            candidates=[],
            estimated_edges=[],
            max_measured_segments=0,
        )
