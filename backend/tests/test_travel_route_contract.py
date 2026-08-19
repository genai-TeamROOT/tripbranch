from __future__ import annotations

import pytest

from app.domain.travel_route import (
    GeoCoordinate,
    RouteSource,
    RouteStatus,
    TravelRoute,
)


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(90.1, 127.0), (-90.1, 127.0), (37.0, 180.1), (37.0, -180.1)],
)
def test_geo_coordinate_rejects_out_of_range_values(
    latitude: float, longitude: float
) -> None:
    with pytest.raises(ValueError):
        GeoCoordinate(latitude=latitude, longitude=longitude)


def test_successful_travel_route_requires_distance_and_duration() -> None:
    with pytest.raises(ValueError, match="거리와 소요 시간"):
        TravelRoute(
            place_id="place-1",
            status=RouteStatus.SUCCESS,
            source=RouteSource.KAKAO_WALKING,
        )


def test_unavailable_travel_route_can_omit_measurements() -> None:
    route = TravelRoute(
        place_id="place-1",
        status=RouteStatus.UNAVAILABLE,
        source=RouteSource.KAKAO_WALKING,
        error_code="PROVIDER_TIMEOUT",
    )

    assert route.distance_m is None
    assert route.duration_seconds is None
