from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

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
from app.providers.contracts import (
    ProviderSource,
    ProviderStatus,
    provider_result,
)
from app.providers.walking_route import FakeWalkingRouteProvider
from app.tools.contracts import ToolStatus
from app.tools.travel_route import (
    TRAVEL_ROUTE_FALLBACK_WARNING,
    TRAVEL_ROUTE_MODE_UNSUPPORTED_WARNING,
    TravelRouteProviders,
    TravelRouteQuery,
    TravelRouteTool,
)

_NOW = datetime(2026, 8, 18, tzinfo=UTC)


def _tool(primary, fallback=None) -> TravelRouteTool:
    """도보만 등록한 Tool. 실제 factory 구성과 같은 모양이다."""
    return TravelRouteTool(
        {TravelMode.WALKING: TravelRouteProviders(primary=primary, fallback=fallback)}
    )


def _query() -> TravelRouteQuery:
    return TravelRouteQuery(
        origin=GeoCoordinate(37.57, 126.98),
        destinations=(
            RouteDestination("first", GeoCoordinate(37.571, 126.981)),
            RouteDestination("second", GeoCoordinate(37.572, 126.982)),
        ),
        mode=TravelMode.WALKING,
    )


class _PartialProvider:
    async def get_routes(self, origin, destinations, *, mode=TravelMode.WALKING, radius_m=None):
        return provider_result(
            TravelRouteBatch(
                routes=(
                    TravelRoute(
                        place_id="first",
                        mode=TravelMode.WALKING,
                        status=RouteStatus.SUCCESS,
                        source=RouteSource.KAKAO_WALKING,
                        distance_m=100,
                        duration_seconds=90,
                    ),
                    TravelRoute(
                        place_id="second",
                        mode=TravelMode.WALKING,
                        status=RouteStatus.NO_DATA,
                        source=RouteSource.KAKAO_WALKING,
                        error_code="kakao_result_104",
                    ),
                )
            ),
            source=ProviderSource.KAKAO_WALKING_ROUTE,
            status=ProviderStatus.PARTIAL,
            clock=lambda: _NOW,
        )


class _FailingProvider:
    async def get_routes(self, origin, destinations, *, mode=TravelMode.WALKING, radius_m=None):
        raise ProviderTimeoutError("Kakao Walking Route")


@pytest.mark.asyncio
async def test_travel_route_tool_fills_only_failed_destination() -> None:
    result = await _tool(
        _PartialProvider(),
        FakeWalkingRouteProvider(walking_speed_mps=1.2),
    ).execute(_query())

    assert result.status is ToolStatus.PARTIAL
    assert [route.place_id for route in result.routes] == ["first", "second"]
    assert result.routes[0].source is RouteSource.KAKAO_WALKING
    assert result.routes[0].distance_m == 100
    assert result.routes[1].source is RouteSource.STRAIGHT_LINE_ESTIMATE
    assert result.warnings == (TRAVEL_ROUTE_FALLBACK_WARNING,)
    assert [metadata.source for metadata in result.provider_metadata] == [
        ProviderSource.KAKAO_WALKING_ROUTE,
        ProviderSource.FAKE_WALKING_ROUTE,
    ]


@pytest.mark.asyncio
async def test_travel_route_tool_logs_when_estimate_replaces_real_route(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """폴백 대체는 예외 없이 일어나므로, 로그가 유일한 노출 경로다(D-042)."""
    with caplog.at_level(logging.WARNING, logger="app.tools.travel_route"):
        await _tool(
            _PartialProvider(),
            FakeWalkingRouteProvider(walking_speed_mps=1.2),
        ).execute(_query())

    messages = [record.getMessage() for record in caplog.records]
    assert any("1/2건을 직선거리 추정으로 대체" in message for message in messages)
    assert any("kakao_result_104" in message for message in messages)


@pytest.mark.asyncio
async def test_travel_route_tool_does_not_log_fallback_when_all_routes_succeed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.tools.travel_route"):
        await _tool(
            FakeWalkingRouteProvider(walking_speed_mps=1.2),
            FakeWalkingRouteProvider(walking_speed_mps=1.2),
        ).execute(_query())

    assert caplog.records == []


@pytest.mark.asyncio
async def test_travel_route_tool_falls_back_all_on_primary_failure() -> None:
    result = await _tool(
        _FailingProvider(),
        FakeWalkingRouteProvider(walking_speed_mps=1.2),
    ).execute(_query())

    assert result.status is ToolStatus.PARTIAL
    assert len(result.routes) == 2
    assert all(route.source is RouteSource.STRAIGHT_LINE_ESTIMATE for route in result.routes)
    assert result.warnings == (TRAVEL_ROUTE_FALLBACK_WARNING,)


@pytest.mark.asyncio
async def test_travel_route_tool_returns_unavailable_without_fallback() -> None:
    result = await _tool(_FailingProvider()).execute(_query())

    assert result.status is ToolStatus.UNAVAILABLE
    assert result.routes == ()
    assert result.error is not None
    assert result.error.cause == "timeout"


@pytest.mark.asyncio
async def test_travel_route_tool_fake_mode_is_normal_success() -> None:
    result = await _tool(FakeWalkingRouteProvider(walking_speed_mps=1.2)).execute(_query())

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
            mode=TravelMode.WALKING,
        )


class _CountingProvider:
    """호출 여부만 세는 Provider — 미등록 이동수단에서 호출이 없어야 한다."""

    def __init__(self) -> None:
        self.calls = 0

    async def get_routes(self, origin, destinations, *, mode=TravelMode.WALKING, radius_m=None):
        self.calls += 1
        raise AssertionError("미등록 이동수단에서는 Provider가 호출되지 않아야 한다.")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [TravelMode.TRANSIT, TravelMode.DRIVING])
async def test_travel_route_tool_returns_no_data_for_unregistered_mode(mode: TravelMode) -> None:
    """미등록 이동수단은 조회도, 추정 대체도 하지 않는다.

    도보 속도로 추정한 값을 자동차 실측인 척 내보내면 D-042가 막으려던 상황이
    된다. 값이 없으면 소비 측이 직선거리로 돌아가므로 없는 편이 안전하다.
    """
    primary = _CountingProvider()
    fallback = _CountingProvider()
    tool = TravelRouteTool(
        {TravelMode.WALKING: TravelRouteProviders(primary=primary, fallback=fallback)}
    )

    result = await tool.execute(
        TravelRouteQuery(
            origin=GeoCoordinate(37.57, 126.98),
            destinations=(RouteDestination("first", GeoCoordinate(37.571, 126.981)),),
            mode=mode,
        )
    )

    assert result.status is ToolStatus.NO_DATA
    assert result.routes == ()
    assert result.warnings == (TRAVEL_ROUTE_MODE_UNSUPPORTED_WARNING,)
    assert (primary.calls, fallback.calls) == (0, 0)


@pytest.mark.asyncio
async def test_travel_route_tool_passes_requested_mode_to_provider() -> None:
    captured: list[TravelMode] = []

    class _RecordingProvider:
        async def get_routes(self, origin, destinations, *, mode, radius_m=None):
            captured.append(mode)
            return await FakeWalkingRouteProvider(walking_speed_mps=1.2).get_routes(
                origin, destinations, mode=mode, radius_m=radius_m
            )

    await _tool(_RecordingProvider()).execute(_query())

    assert captured == [TravelMode.WALKING]


def test_travel_route_tool_rejects_empty_provider_registry() -> None:
    with pytest.raises(ValueError, match="등록되지 않았습니다"):
        TravelRouteTool({})
