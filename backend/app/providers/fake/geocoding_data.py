# FakeGeocodingProvider가 사용하는 지명 -> (표시이름, 위도, 경도) 표.
# 사용법: 새 테스트 지명이 필요하면 여기에 한 줄 추가하면 됨(실제 서울 좌표 기준값 사용).

"""Known locations for FakeGeocodingProvider. Coordinates are approximate
real-world values for Seoul landmarks."""

from __future__ import annotations

KNOWN_LOCATIONS: dict[str, tuple[str, float, float]] = {
    "경복궁": ("경복궁", 37.579617, 126.977041),
    "서울역": ("서울역", 37.554648, 126.972559),
    "광화문": ("광화문", 37.575938, 126.976859),
}
