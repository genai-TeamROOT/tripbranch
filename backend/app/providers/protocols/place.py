# PlaceProvider 계약: 좌표+반경(+선호 카테고리, best-effort)으로 주변 장소를 검색.
# 반환값은 반드시 domain.models.Place 리스트여야 하고, 최종 필터링/점수는 도메인 책임이다.

from __future__ import annotations

from typing import Protocol

from app.domain.models import Place


class PlaceProvider(Protocol):
    async def search_places(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        categories: list[str] | None = None,
    ) -> list[Place]:
        """Search for candidate places near a point. Category filtering may
        be advisory only (best-effort) -- final filtering/ranking happens
        in domain/service code."""
        ...
