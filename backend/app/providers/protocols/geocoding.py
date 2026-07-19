# GeocodingProvider 계약: 자유 텍스트 위치를 좌표로 변환.
# 구현체는 실패 시 AppError(location_not_found / location_ambiguous)를 던져야 한다.
# 사용법: 새 지오코딩 제공사를 붙일 땐 이 Protocol의 geocode() 시그니처만 맞추면 됨.

from __future__ import annotations

from typing import Protocol

from app.domain.models import GeocodeResult


class GeocodingProvider(Protocol):
    async def geocode(self, query: str) -> GeocodeResult:
        """Resolve a free-text location query to coordinates.

        Implementations should raise AppError(code="location_not_found") or
        AppError(code="location_ambiguous") as appropriate rather than
        returning a sentinel value.
        """
        ...
