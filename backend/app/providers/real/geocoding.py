# RealGeocodingProvider placeholder - 실제 지오코딩 API(예: Kakao/Naver/Google) 연동 위치.
# TODO: geocode() 구현. httpx.AsyncClient를 생성자 주입으로 받도록 바꾸고,
# 응답을 domain.models.GeocodeResult로 변환할 것. 실패 시 AppError(location_not_found 등)로 감쌀 것.

from __future__ import annotations

from app.domain.models import GeocodeResult


class RealGeocodingProvider:
    """TODO: implement against a real geocoding API (e.g. Kakao/Naver Local
    Search, Google Geocoding). Read the API key from Settings.geocoding
    config and inject an httpx.AsyncClient rather than constructing one
    per call."""

    def __init__(self, api_key: str | None, timeout_seconds: float) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    async def geocode(self, query: str) -> GeocodeResult:
        raise NotImplementedError("RealGeocodingProvider is not implemented yet.")
