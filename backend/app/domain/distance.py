# 두 좌표 간 직선거리(Haversine) 계산. 외부 라이브러리 없이 math 모듈만 사용.
# 사용법: haversine_km(lat1, lon1, lat2, lon2) -> km 단위 float.
# 정확도가 더 필요해지면(예: 실제 경로 거리) 이 함수를 바꾸는 게 아니라
# PlaceProvider/GeocodingProvider 쪽에 별도 "경로 거리" 개념을 추가하는 걸 권장
# (직선거리 자체는 이 정도 정밀도로 충분한 용도로 설계됨).

"""Straight-line distance calculations."""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in kilometers."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS_KM * c
