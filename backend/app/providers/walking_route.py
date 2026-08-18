"""외부 호출 없이 직선거리 기반 도보 이동을 추정하는 Provider."""

from __future__ import annotations

import math

from app.domain.travel_route import (
    GeoCoordinate,
    RouteDestination,
    RouteSource,
    RouteStatus,
    WalkingRoute,
    WalkingRouteBatch,
)
from app.geo import haversine_km
from app.providers.contracts import (
    ProviderResult,
    ProviderSource,
    ProviderStatus,
    provider_result,
)


class FakeWalkingRouteProvider:
    """카카오 미연동 환경과 향후 장애 fallback에서 사용할 직선거리 추정기."""

    def __init__(self, walking_speed_mps: float) -> None:
        if walking_speed_mps <= 0:
            raise ValueError("walking_speed_mps는 0보다 커야 합니다.")
        self._walking_speed_mps = walking_speed_mps

    async def get_routes(
        self,
        origin: GeoCoordinate,
        destinations: tuple[RouteDestination, ...],
        *,
        radius_m: int | None = None,
    ) -> ProviderResult[WalkingRouteBatch]:
        if radius_m is not None and radius_m <= 0:
            raise ValueError("radius_m는 0보다 커야 합니다.")

        routes = tuple(self._estimate_route(origin, destination) for destination in destinations)
        status = ProviderStatus.SUCCESS if routes else ProviderStatus.NO_DATA
        return provider_result(
            WalkingRouteBatch(routes=routes),
            source=ProviderSource.FAKE_WALKING_ROUTE,
            status=status,
        )

    def _estimate_route(
        self,
        origin: GeoCoordinate,
        destination: RouteDestination,
    ) -> WalkingRoute:
        distance_m = round(
            haversine_km(
                origin.latitude,
                origin.longitude,
                destination.coordinate.latitude,
                destination.coordinate.longitude,
            )
            * 1000
        )
        return WalkingRoute(
            place_id=destination.place_id,
            status=RouteStatus.SUCCESS,
            source=RouteSource.STRAIGHT_LINE_ESTIMATE,
            distance_m=distance_m,
            duration_seconds=math.ceil(distance_m / self._walking_speed_mps),
        )


__all__ = ["FakeWalkingRouteProvider"]
