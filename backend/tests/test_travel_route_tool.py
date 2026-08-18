from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domain.travel_route import (
    GeoCoordinate,
    RouteDestination,
    RouteSource,
    RouteStatus,
    WalkingRoute,
    WalkingRouteBatch,
)
from app.errors import ProviderTimeoutError
from app.providers.contracts import (
    ProviderSource,
    ProviderStatus,
    provider_result,
)
from app.providers.walking_route import FakeWalkingRouteProvider
from app.tools.contracts import ToolStatus
from app.tools.travel_route import (
    WALKING_ROUTE_FALLBACK_WARNING,
    TravelRouteQuery,
    TravelRouteTool,
)

_NOW = datetime(2026, 8, 18, tzinfo=UTC)


def _query() -> TravelRouteQuery:
    return TravelRouteQuery(
        origin=GeoCoordinate(37.57, 126.98),
        destinations=(
            RouteDestination("first", GeoCoordinate(37.571, 126.981)),
            RouteDestination("second", GeoCoordinate(37.572, 126.982)),
        ),
    )


class _PartialProvider:
    async def get_routes(self, origin, destinations, *, radius_m=None):
        return provider_result(
            WalkingRouteBatch(
                routes=(
                    WalkingRoute(
                        "first",
                        RouteStatus.SUCCESS,
                        RouteSource.KAKAO_WALKING,
                        distance_m=100,
                        duration_seconds=90,
                    ),
                    WalkingRoute(
                        "second",
                        RouteStatus.NO_DATA,
                        RouteSource.KAKAO_WALKING,
                        error_code="kakao_result_104",
                    ),
                )
            ),
            source=ProviderSource.KAKAO_WALKING_ROUTE,
            status=ProviderStatus.PARTIAL,
            clock=lambda: _NOW,
        )


class _FailingProvider:
    async def get_routes(self, origin, destinations, *, radius_m=None):
        raise ProviderTimeoutError("Kakao Walking Route")


@pytest.mark.asyncio
async def test_travel_route_tool_fills_only_failed_destination() -> None:
    result = await TravelRouteTool(
        _PartialProvider(),  # type: ignore[arg-type]
        FakeWalkingRouteProvider(walking_speed_mps=1.2),
    ).execute(_query())

    assert result.status is ToolStatus.PARTIAL
    assert [route.place_id for route in result.routes] == ["first", "second"]
    assert result.routes[0].source is RouteSource.KAKAO_WALKING
    assert result.routes[0].distance_m == 100
    assert result.routes[1].source is RouteSource.STRAIGHT_LINE_ESTIMATE
    assert result.warnings == (WALKING_ROUTE_FALLBACK_WARNING,)
    assert [metadata.source for metadata in result.provider_metadata] == [
        ProviderSource.KAKAO_WALKING_ROUTE,
        ProviderSource.FAKE_WALKING_ROUTE,
    ]


@pytest.mark.asyncio
async def test_travel_route_tool_falls_back_all_on_primary_failure() -> None:
    result = await TravelRouteTool(
        _FailingProvider(),  # type: ignore[arg-type]
        FakeWalkingRouteProvider(walking_speed_mps=1.2),
    ).execute(_query())

    assert result.status is ToolStatus.PARTIAL
    assert len(result.routes) == 2
    assert all(route.source is RouteSource.STRAIGHT_LINE_ESTIMATE for route in result.routes)
    assert result.warnings == (WALKING_ROUTE_FALLBACK_WARNING,)


@pytest.mark.asyncio
async def test_travel_route_tool_returns_unavailable_without_fallback() -> None:
    result = await TravelRouteTool(
        _FailingProvider()  # type: ignore[arg-type]
    ).execute(_query())

    assert result.status is ToolStatus.UNAVAILABLE
    assert result.routes == ()
    assert result.error is not None
    assert result.error.cause == "timeout"


@pytest.mark.asyncio
async def test_travel_route_tool_fake_mode_is_normal_success() -> None:
    result = await TravelRouteTool(FakeWalkingRouteProvider(walking_speed_mps=1.2)).execute(
        _query()
    )

    assert result.status is ToolStatus.SUCCESS
    assert result.warnings == ()
    assert len(result.provider_metadata) == 1


def test_travel_route_query_rejects_duplicate_place_ids() -> None:
    coordinate = GeoCoordinate(37.57, 126.98)
    with pytest.raises(ValueError, match="중복"):
        TravelRouteQuery(
            origin=coordinate,
            destinations=(
                RouteDestination("same", coordinate),
                RouteDestination("same", coordinate),
            ),
        )
