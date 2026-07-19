# FakeGeocodingProvider - 경복궁/서울역/광화문 등 정해진 지명만 좌표로 변환하는 가짜 지오코더.
# geocoding_data.py의 표를 substring 매칭으로 찾는다. 사용법: 테스트나 로컬 개발에서
# location_query에 위 지명 중 하나가 포함되면 성공, 아니면 AppError(location_not_found).
# TODO: 실제 서비스에서는 RealGeocodingProvider(providers/real/geocoding.py)로 교체될 대상.

from __future__ import annotations

from app.core.errors import AppError
from app.domain.models import GeocodeResult
from app.providers.fake.geocoding_data import KNOWN_LOCATIONS


class FakeGeocodingProvider:
    """Resolves a small, fixed set of well-known Seoul locations. Any query
    containing one of the known names (substring match) resolves to it."""

    async def geocode(self, query: str) -> GeocodeResult:
        normalized = query.strip()
        if not normalized:
            raise AppError(code="invalid_request", message="위치를 입력해주세요.")

        for name, (resolved_name, lat, lon) in KNOWN_LOCATIONS.items():
            if name in normalized:
                return GeocodeResult(
                    query=query, resolved_name=resolved_name, latitude=lat, longitude=lon
                )

        raise AppError(
            code="location_not_found",
            message=f"'{query}' 위치를 찾을 수 없어요.",
            retryable=False,
        )
