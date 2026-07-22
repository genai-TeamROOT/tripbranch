"""GeocodingProvider 계약과 구현체.

계약: 자유 텍스트(주소 또는 장소명)를 좌표로 변환한다. 결과가 없으면
AppError(code="location_not_found")를 던진다. 검색 결과가 여러 건이면 API가
반환한 순서(관련도/거리순) 중 첫 번째 결과를 채택한다 - 모호함을 사용자에게
되묻는 흐름은 이번 범위에 포함하지 않는다.
"""

from __future__ import annotations

from typing import Protocol

from app.domain.models import GeocodeResult
from app.errors import AppError


class GeocodingProvider(Protocol):
    async def geocode(self, query: str) -> GeocodeResult:
        """자유 텍스트 위치 질의를 좌표로 변환한다.

        결과를 찾지 못하면 AppError(code="location_not_found")를 던진다.
        """
        ...


# 로컬 개발/테스트용 고정 지명 테이블. substring 매칭으로 찾는다.
_KNOWN_LOCATIONS: dict[str, tuple[str, float, float]] = {
    "경복궁": ("경복궁", 37.5796, 126.9770),
    "서울역": ("서울역", 37.5547, 126.9707),
    "광화문": ("광화문", 37.5759, 126.9769),
    "강남역": ("강남역", 37.4979, 127.0276),
}


class FakeGeocodingProvider:
    """정해진 소수의 지명만 좌표로 변환하는 가짜 구현."""

    async def geocode(self, query: str) -> GeocodeResult:
        normalized = query.strip()
        if not normalized:
            raise AppError(code="invalid_request", message="위치를 입력해주세요.")

        for name, (resolved_name, lat, lon) in _KNOWN_LOCATIONS.items():
            if name in normalized:
                return GeocodeResult(
                    query=query, resolved_name=resolved_name, latitude=lat, longitude=lon
                )

        raise AppError(
            code="location_not_found",
            message=f"'{query}' 위치를 찾을 수 없어요.",
        )
