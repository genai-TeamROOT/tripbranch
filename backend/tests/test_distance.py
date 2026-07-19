# domain/distance.py의 haversine_km 테스트: 동일 좌표 거리 0, 실제 서울 두 지점 간 근사 거리 검증.

from __future__ import annotations

import math

from app.domain.distance import haversine_km


def test_haversine_zero_distance_for_identical_points() -> None:
    assert haversine_km(37.5796, 126.9770, 37.5796, 126.9770) == 0.0


def test_haversine_known_distance_gyeongbokgung_to_seoul_station() -> None:
    # Real-world distance is roughly 2.9km.
    distance = haversine_km(37.579617, 126.977041, 37.554648, 126.972559)

    assert math.isclose(distance, 2.9, abs_tol=0.3)
