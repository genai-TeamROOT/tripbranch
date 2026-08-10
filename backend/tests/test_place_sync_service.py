from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.domain.models import (
    PlaceOperatingDetails,
    StoredPlaceState,
    TourPlacePage,
    TourPlaceRecord,
)
from app.domain.operating_hours import OPERATING_PARSER_VERSION
from app.errors import ProviderTimeoutError
from app.services.place_sync import PlaceSyncService

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
NOW = datetime(2026, 7, 24, 3, 0, tzinfo=UTC)


def _place(index: int) -> TourPlaceRecord:
    return TourPlaceRecord(
        content_id=str(index),
        content_type_id="12",
        title=f"장소 {index}",
        address=None,
        latitude=37.5,
        longitude=127.0,
        area_code="11",
        district_code="110",
        lcls_systm1=None,
        lcls_systm2=None,
        lcls_systm3=None,
        source_modified_at=NOW,
    )


def _state(
    content_id: str,
    *,
    parser_version: str = OPERATING_PARSER_VERSION,
    detail_status: str = "success",
) -> StoredPlaceState:
    return StoredPlaceState(
        content_id=content_id,
        source_modified_at=NOW,
        detail_fetched_at=NOW,
        detail_fetch_status=detail_status,
        operating_parser_version=parser_version,
        operating_hours_raw="09:00~18:00",
        rest_date_raw="매주 화요일",
        is_active=True,
        inactive_reason=None,
    )


class FakeAreaProvider:
    def __init__(
        self,
        places: Sequence[TourPlaceRecord],
        *,
        page_size: int = 100,
        failing_ids: set[str] | None = None,
    ) -> None:
        self.places = list(places)
        self.page_size = page_size
        self.failing_ids = failing_ids or set()
        self.list_calls: list[int] = []
        self.detail_calls: list[str] = []
        self.active_details = 0
        self.max_active_details = 0

    async def list_places_by_area(
        self,
        area_code: str,
        district_code: str,
        page_no: int,
        num_of_rows: int = 100,
    ) -> TourPlacePage:
        self.list_calls.append(page_no)
        start = (page_no - 1) * num_of_rows
        page_places = tuple(self.places[start : start + num_of_rows])
        return TourPlacePage(
            page_no=page_no,
            num_of_rows=len(page_places),
            total_count=len(self.places),
            places=page_places,
        )

    async def get_operating_details(
        self,
        content_id: str,
        content_type_id: str,
    ) -> PlaceOperatingDetails:
        self.detail_calls.append(content_id)
        self.active_details += 1
        self.max_active_details = max(self.max_active_details, self.active_details)
        await asyncio.sleep(0)
        self.active_details -= 1
        if content_id in self.failing_ids:
            raise ProviderTimeoutError("TourAPI")
        return PlaceOperatingDetails(
            content_id=content_id,
            content_type_id=content_type_id,
            operating_hours_raw="09:00~18:00",
            rest_date_raw="매주 화요일",
            parking_info_raw="가능 (54대)",
            parking_fee_raw="무료",
            use_fee_raw="3,000원",
            discount_info_raw="경로 50%",
        )


class FakePlaceRepository:
    def __init__(
        self,
        states: Mapping[str, StoredPlaceState] | None = None,
        *,
        lock_acquired: bool = True,
    ) -> None:
        self.states = dict(states or {})
        self.lock_acquired = lock_acquired
        self.created = 0
        self.released = 0
        self.upserted: list[TourPlaceRecord] = []
        self.detail_updates: list[str] = []
        self.detail_extras: dict[
            str, tuple[str | None, str | None, str | None, str | None]
        ] = {}
        self.detail_failures: list[tuple[str, str]] = []
        self.parsed_updates: list[str] = []
        self.deactivate_calls = 0
        self.completed: list[dict[str, object]] = []

    async def create_sync_run(self, area_code: str, district_code: str) -> UUID:
        self.created += 1
        return RUN_ID

    async def try_acquire_sync_lock(
        self,
        area_code: str,
        district_code: str,
        sync_run_id: UUID,
        lock_ttl: str = "2 hours",
    ) -> bool:
        return self.lock_acquired

    async def release_sync_lock(
        self, area_code: str, district_code: str, sync_run_id: UUID
    ) -> bool:
        self.released += 1
        return True

    async def get_region_place_states(
        self, area_code: str, district_code: str
    ) -> dict[str, StoredPlaceState]:
        return self.states

    async def upsert_place_list(
        self,
        places: Sequence[TourPlaceRecord],
        existing_states: Mapping[str, StoredPlaceState],
        sync_run_id: UUID,
        fetched_at: datetime,
    ) -> None:
        self.upserted.extend(places)

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
    ) -> None:
        self.detail_updates.append(content_id)
        # 받은 값을 버리면 provider가 채운 주차·요금이 저장 경로까지 실제로 오는지
        # 검증할 수 없다.
        self.detail_extras[content_id] = (
            parking_info_raw,
            parking_fee_raw,
            use_fee_raw,
            discount_info_raw,
        )

    async def update_parsed_schedule(
        self,
        content_id: str,
        operating_schedule: Mapping[str, object] | None,
        parse_status: str,
        parser_version: str,
    ) -> None:
        self.parsed_updates.append(content_id)

    async def mark_detail_failed(self, content_id: str, error_code: str) -> None:
        self.detail_failures.append((content_id, error_code))

    async def reactivate_source_missing_places(
        self, content_ids: Sequence[str]
    ) -> int:
        return 0

    async def deactivate_unseen_places(
        self,
        area_code: str,
        district_code: str,
        sync_run_id: UUID,
        inactive_at: datetime,
    ) -> int:
        self.deactivate_calls += 1
        return 2

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
        error_summary: Mapping[str, object] | None = None,
        completed_at: datetime,
    ) -> None:
        self.completed.append(
            {
                "status": status,
                "api_total_count": api_total_count,
                "processed_count": processed_count,
                "success_count": success_count,
                "failed_count": failed_count,
                "new_count": new_count,
                "updated_count": updated_count,
                "deactivated_count": deactivated_count,
                "error_summary": error_summary,
            }
        )


async def _no_sleep(delay: float) -> None:
    return None


@pytest.mark.asyncio
async def test_sync_collects_three_pages_and_limits_detail_concurrency() -> None:
    provider = FakeAreaProvider([_place(index) for index in range(250)])
    repository = FakePlaceRepository()
    service = PlaceSyncService(
        provider,
        repository,
        detail_concurrency=5,
        retry_count=0,
        now=lambda: NOW,
    )

    result = await service.sync("11", "110")

    assert provider.list_calls == [1, 2, 3]
    assert provider.max_active_details == 5
    assert len(repository.upserted) == 250
    assert len(repository.detail_updates) == 250
    assert repository.deactivate_calls == 1
    assert repository.released == 1
    assert result.status == "success"
    assert result.success_count == 250
    assert result.deactivated_count == 2


@pytest.mark.asyncio
async def test_detail_failure_retries_and_finishes_partial_failure() -> None:
    provider = FakeAreaProvider([_place(1), _place(2)], failing_ids={"2"})
    repository = FakePlaceRepository()
    service = PlaceSyncService(
        provider,
        repository,
        retry_count=1,
        sleep=_no_sleep,
        now=lambda: NOW,
    )

    result = await service.sync("11", "110")

    assert provider.detail_calls.count("2") == 2
    assert repository.detail_failures == [("2", "TOUR_DETAIL_TIMEOUT")]
    assert result.status == "partial_failure"
    assert result.success_count == 1
    assert result.failed_count == 1
    assert result.error_summary == {"TOUR_DETAIL_TIMEOUT": 1}


@pytest.mark.asyncio
async def test_parser_version_change_reparses_without_tour_api_call() -> None:
    provider = FakeAreaProvider([_place(1)])
    repository = FakePlaceRepository(
        {"1": _state("1", parser_version="operating-hours-0.9.0")}
    )
    service = PlaceSyncService(provider, repository, now=lambda: NOW)

    result = await service.sync("11", "110")

    assert provider.detail_calls == []
    assert repository.parsed_updates == ["1"]
    assert repository.detail_updates == []
    assert result.reparse_count == 1


@pytest.mark.asyncio
async def test_details_limit_skips_deactivation() -> None:
    provider = FakeAreaProvider([_place(index) for index in range(5)])
    repository = FakePlaceRepository()
    service = PlaceSyncService(provider, repository, retry_count=0, now=lambda: NOW)

    result = await service.sync("11", "110", details_limit=2)

    assert len(provider.detail_calls) == 2
    assert result.detail_target_count == 5
    assert result.detail_attempted_count == 2
    assert repository.deactivate_calls == 0


@pytest.mark.asyncio
async def test_dry_run_does_not_write_or_lock() -> None:
    provider = FakeAreaProvider([_place(1)])
    repository = FakePlaceRepository()
    service = PlaceSyncService(provider, repository, retry_count=0, now=lambda: NOW)

    result = await service.sync("11", "110", dry_run=True, details_limit=1)

    assert result.dry_run is True
    assert result.sync_run_id is None
    assert repository.created == 0
    assert repository.upserted == []
    assert repository.detail_updates == []
    assert repository.completed == []
    assert repository.released == 0


@pytest.mark.asyncio
async def test_lock_failure_stops_before_provider_call() -> None:
    provider = FakeAreaProvider([_place(1)])
    repository = FakePlaceRepository(lock_acquired=False)
    service = PlaceSyncService(provider, repository, now=lambda: NOW)

    result = await service.sync("11", "110")

    assert result.status == "failed"
    assert provider.list_calls == []
    assert repository.completed[0]["error_summary"] == {
        "SYNC_LOCK_UNAVAILABLE": 1
    }
    assert repository.released == 0


@pytest.mark.asyncio
async def test_incomplete_list_never_upserts_or_deactivates() -> None:
    class IncompleteProvider(FakeAreaProvider):
        async def list_places_by_area(
            self,
            area_code: str,
            district_code: str,
            page_no: int,
            num_of_rows: int = 100,
        ) -> TourPlacePage:
            return TourPlacePage(
                page_no=page_no,
                num_of_rows=num_of_rows,
                total_count=2,
                places=(_place(1),) if page_no == 1 else (),
            )

    provider = IncompleteProvider([_place(1)])
    repository = FakePlaceRepository()
    service = PlaceSyncService(provider, repository, now=lambda: NOW)

    result = await service.sync("11", "110")

    assert result.status == "failed"
    assert repository.upserted == []
    assert repository.deactivate_calls == 0
    assert repository.completed[0]["error_summary"] == {
        "INCOMPLETE_PLACE_LIST": 1
    }
    assert repository.released == 1


@pytest.mark.asyncio
async def test_detail_sync_persists_parking_and_fee_fields() -> None:
    """provider가 채운 주차·요금이 저장 호출까지 그대로 도달하는지 못 박는다.

    Fake 저장소가 인자를 받기만 하고 버리면 D-056 배선이 끊겨도 테스트가 통과한다.
    """
    provider = FakeAreaProvider([_place(1)])
    repository = FakePlaceRepository()
    service = PlaceSyncService(provider, repository, now=lambda: NOW)

    await service.sync("11", "110")

    assert repository.detail_extras["1"] == (
        "가능 (54대)",
        "무료",
        "3,000원",
        "경로 50%",
    )


@pytest.mark.asyncio
async def test_detail_content_ids_limits_calls_to_snapshot_diff() -> None:
    """스냅샷 대조가 정한 변경분만 상세조회한다.

    TTL(기본 30일)이 지나면 기존 규칙은 안 바뀐 장소까지 전부 재조회 대상으로
    삼는다. 종로구 844건이 통째로 나가는 상황이라 대조 결과로 대상을 고정한다.
    """
    provider = FakeAreaProvider([_place(index) for index in range(5)])
    # 마지막 상세조회가 TTL(30일)을 훨씬 넘긴 상태 — 기존 규칙이면 5건 전부 대상이다.
    stale = NOW - timedelta(days=90)
    repository = FakePlaceRepository(
        {
            str(index): StoredPlaceState(
                content_id=str(index),
                source_modified_at=NOW,
                detail_fetched_at=stale,
                detail_fetch_status="success",
                operating_parser_version=OPERATING_PARSER_VERSION,
                operating_hours_raw="09:00~18:00",
                rest_date_raw="매주 화요일",
                is_active=True,
                inactive_reason=None,
            )
            for index in range(5)
        }
    )
    service = PlaceSyncService(provider, repository, retry_count=0, now=lambda: NOW)

    result = await service.sync("11", "110", detail_content_ids=frozenset({"2"}))

    assert provider.detail_calls == ["2"]
    assert result.detail_target_count == 1


@pytest.mark.asyncio
async def test_detail_content_ids_still_retries_pending_and_failed() -> None:
    """지난 실행에서 못 채운 건은 대조 결과에 없어도 다시 시도한다.

    빼면 pending·failed가 영영 그대로 남는다.
    """
    provider = FakeAreaProvider([_place(1), _place(2)])
    repository = FakePlaceRepository(
        {
            "1": _state("1", detail_status="failed"),
            "2": _state("2", detail_status="success"),
        }
    )
    service = PlaceSyncService(provider, repository, retry_count=0, now=lambda: NOW)

    result = await service.sync("11", "110", detail_content_ids=frozenset())

    assert provider.detail_calls == ["1"]
    assert result.detail_target_count == 1


@pytest.mark.asyncio
async def test_detail_content_ids_none_keeps_existing_ttl_rule() -> None:
    """인자를 안 주면 기존 동작 그대로 — CLI 경로는 바뀌지 않는다."""
    provider = FakeAreaProvider([_place(1)])
    stale = NOW - timedelta(days=90)
    repository = FakePlaceRepository(
        {
            "1": StoredPlaceState(
                content_id="1",
                source_modified_at=NOW,
                detail_fetched_at=stale,
                detail_fetch_status="success",
                operating_parser_version=OPERATING_PARSER_VERSION,
                operating_hours_raw="09:00~18:00",
                rest_date_raw="매주 화요일",
                is_active=True,
                inactive_reason=None,
            )
        }
    )
    service = PlaceSyncService(provider, repository, retry_count=0, now=lambda: NOW)

    result = await service.sync("11", "110")

    assert provider.detail_calls == ["1"]
    assert result.detail_target_count == 1


@pytest.mark.asyncio
async def test_on_progress_reports_detail_completion() -> None:
    """place_sync_runs 행은 시작·종료만 남으므로 진행률은 콜백으로만 알 수 있다."""
    provider = FakeAreaProvider([_place(index) for index in range(3)])
    repository = FakePlaceRepository()
    service = PlaceSyncService(provider, repository, retry_count=0, now=lambda: NOW)
    seen: list[tuple[str, int, int]] = []

    await service.sync(
        "11",
        "110",
        on_progress=lambda progress: seen.append(
            (progress.phase, progress.processed, progress.total)
        ),
    )

    phases = [phase for phase, _, _ in seen]
    assert phases[0] == "list"
    assert phases[-1] == "done"
    detail_progress = [item for item in seen if item[0] == "details"]
    assert detail_progress[0] == ("details", 0, 3)
    assert detail_progress[-1] == ("details", 3, 3)
