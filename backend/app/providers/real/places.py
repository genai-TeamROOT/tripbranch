# RealPlaceProvider placeholder - 실제 장소 검색 API(예: Kakao Local, Google Places) 연동 위치.
# TODO: search_places() 구현. 응답의 원본 shape이 이 클래스 밖으로 새어나가지 않도록
# 반드시 domain.models.Place로 변환해서 반환할 것.

from __future__ import annotations

from app.domain.models import Place


class RealPlaceProvider:
    """TODO: implement against a real places API (e.g. Kakao Local, Google
    Places). Convert each upstream result into the internal Place model
    (see app/domain/models.py) here -- recommendation code must never see
    the raw upstream shape."""

    def __init__(self, api_key: str | None, timeout_seconds: float) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    async def search_places(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        categories: list[str] | None = None,
    ) -> list[Place]:
        raise NotImplementedError("RealPlaceProvider is not implemented yet.")
