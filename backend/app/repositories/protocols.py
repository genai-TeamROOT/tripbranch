"""장소 동기화 저장소가 제공해야 하는 비동기 계약."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.models import (
    PlaceEvidenceMatch,
    StoredPlaceDetail,
    StoredPlaceLocation,
    StoredPlaceState,
    TourPlaceRecord,
)


class PlaceLocationRepository(Protocol):
    """장소명으로 저장된 TourAPI 기준 위치를 찾는 읽기 전용 계약."""

    async def find_active_places_by_name(
        self, name: str
    ) -> tuple[StoredPlaceLocation, ...]: ...


class ConcentrationMappingRepository(Protocol):
    """집중률 매핑이 있는 장소 목록을 읽는 읽기 전용 계약."""

    async def find_concentration_mapped_places(
        self,
    ) -> tuple[StoredPlaceLocation, ...]: ...


class PlaceDetailsReadRepository(Protocol):
    """content_id로 상세 행만 읽는 읽기 전용 계약.

    동기화용 PlaceRepository와 분리한 이유는 소비자가 읽기만 하기 때문이다 —
    카드 조립처럼 조회만 하는 쪽이 동기화 메서드 전부를 구현한 저장소를 요구하면
    fake를 만들 때 쓰지도 않는 메서드를 채워야 한다.
    """

    async def get_active_place_details(
        self,
        content_ids: Sequence[str],
    ) -> dict[str, StoredPlaceDetail]: ...


class PlaceRepository(Protocol):
    async def create_sync_run(self, area_code: str, district_code: str) -> UUID: ...

    async def try_acquire_sync_lock(
        self,
        area_code: str,
        district_code: str,
        sync_run_id: UUID,
        lock_ttl: str = "2 hours",
    ) -> bool: ...

    async def release_sync_lock(
        self,
        area_code: str,
        district_code: str,
        sync_run_id: UUID,
    ) -> bool: ...

    async def get_region_place_states(
        self,
        area_code: str,
        district_code: str,
    ) -> dict[str, StoredPlaceState]: ...

    async def get_active_place_details(
        self,
        content_ids: Sequence[str],
    ) -> dict[str, StoredPlaceDetail]: ...

    async def upsert_place_list(
        self,
        places: Sequence[TourPlaceRecord],
        existing_states: Mapping[str, StoredPlaceState],
        sync_run_id: UUID,
        fetched_at: datetime,
    ) -> None: ...

    async def update_operating_details(
        self,
        content_id: str,
        operating_hours_raw: str | None,
        rest_date_raw: str | None,
        operating_schedule: Mapping[str, object] | None,
        parse_status: str,
        parser_version: str,
        fetched_at: datetime,
        parking_info_raw: str | None = None,
        parking_fee_raw: str | None = None,
        use_fee_raw: str | None = None,
        discount_info_raw: str | None = None,
        info_center_raw: str | None = None,
        baby_carriage_raw: str | None = None,
        pet_raw: str | None = None,
        credit_card_raw: str | None = None,
        restroom_raw: str | None = None,
    ) -> None: ...

    async def update_parsed_schedule(
        self,
        content_id: str,
        operating_schedule: Mapping[str, object] | None,
        parse_status: str,
        parser_version: str,
    ) -> None: ...

    async def mark_detail_failed(self, content_id: str, error_code: str) -> None: ...

    async def reactivate_source_missing_places(
        self,
        content_ids: Sequence[str],
    ) -> int: ...

    async def deactivate_unseen_places(
        self,
        area_code: str,
        district_code: str,
        sync_run_id: UUID,
        inactive_at: datetime,
    ) -> int: ...

    async def complete_sync_run(
        self,
        sync_run_id: UUID,
        *,
        status: str,
        api_total_count: int | None,
        processed_count: int,
        success_count: int,
        failed_count: int,
        new_count: int,
        updated_count: int,
        deactivated_count: int,
        detail_attempted_count: int,
        error_summary: Mapping[str, object] | None = None,
        completed_at: datetime,
    ) -> None: ...


class PlaceEvidenceRepository(Protocol):
    """취향 근거를 벡터 검색으로 찾는 읽기 전용 계약.

    후보를 반드시 좁혀서 부른다 — RPC가 후보 상한(500)을 강제하고, 좁히지 않으면
    40,389행 전체를 훑어 6~9초가 걸린다(2026-08-18 실측).
    """

    async def search_place_evidence(
        self,
        query_embedding: Sequence[float],
        candidate_content_ids: Sequence[str],
        *,
        match_count: int,
        min_similarity: float,
    ) -> tuple[PlaceEvidenceMatch, ...]: ...
