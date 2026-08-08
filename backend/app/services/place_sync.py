"""TourAPI 장소 목록과 운영정보를 Supabase에 동기화한다."""

from __future__ import annotations

import asyncio
import math
import random
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.domain.models import (
    PlaceOperatingDetails,
    StoredPlaceState,
    TourPlacePage,
    TourPlaceRecord,
)
from app.domain.operating_hours import (
    OPERATING_PARSER_VERSION,
    ClosureRule,
    OperatingRule,
    OperatingSchedule,
    normalize_operating_schedule,
)
from app.errors import ProviderTimeoutError, ProviderUnavailableError
from app.providers.protocols import TourAreaPlaceProvider
from app.repositories.protocols import PlaceRepository

_ERROR_TIMEOUT = "TOUR_DETAIL_TIMEOUT"
_ERROR_RATE_LIMITED = "TOUR_DETAIL_RATE_LIMITED"
_ERROR_UNAVAILABLE = "TOUR_DETAIL_UNAVAILABLE"
_ERROR_INVALID_RESPONSE = "TOUR_DETAIL_INVALID_RESPONSE"
_ERROR_UNKNOWN = "TOUR_DETAIL_UNKNOWN"


class IncompletePlaceListError(RuntimeError):
    """지역 목록의 페이지·건수·식별자 완전성 검증이 실패했다."""


@dataclass(frozen=True)
class PlaceSyncResult:
    status: str
    dry_run: bool
    sync_run_id: UUID | None
    api_total_count: int
    processed_count: int
    success_count: int
    failed_count: int
    new_count: int
    updated_count: int
    deactivated_count: int
    detail_target_count: int
    detail_attempted_count: int
    reparse_count: int
    error_summary: Mapping[str, int]


@dataclass(frozen=True)
class _DetailOutcome:
    content_id: str
    details: PlaceOperatingDetails | None
    operating_schedule: Mapping[str, object] | None
    parse_status: str | None
    error_code: str | None


def serialize_operating_schedule(
    schedule: OperatingSchedule,
) -> dict[str, object]:
    """DB JSON 계약에 맞춰 운영정보 파싱 결과를 직렬화한다."""
    return {
        "availability": schedule.availability.value,
        "rules": [_serialize_rule(rule) for rule in schedule.rules],
        "closure_rules": [
            _serialize_closure_rule(rule) for rule in schedule.closure_rules
        ],
        "assumption_reason": schedule.assumption_reason,
        "warnings": list(schedule.warnings),
    }


def _serialize_rule(rule: OperatingRule) -> dict[str, object]:
    return {
        "months": sorted(rule.months) if rule.months is not None else None,
        "weekdays": sorted(rule.weekdays) if rule.weekdays is not None else None,
        "time_ranges": [
            {
                "start": item.start.isoformat(timespec="minutes"),
                "end": item.end.isoformat(timespec="minutes"),
                "crosses_midnight": item.crosses_midnight,
            }
            for item in rule.time_ranges
        ],
        "last_admission": (
            rule.last_admission.isoformat(timespec="minutes")
            if rule.last_admission is not None
            else None
        ),
        "source_text": rule.source_text,
    }


def _serialize_closure_rule(rule: ClosureRule) -> dict[str, object]:
    return {
        "weekdays": sorted(rule.weekdays),
        "source_text": rule.source_text,
    }


class PlaceSyncService:
    def __init__(
        self,
        provider: TourAreaPlaceProvider,
        repository: PlaceRepository,
        *,
        page_size: int = 100,
        detail_concurrency: int = 5,
        detail_ttl_days: int = 30,
        retry_count: int = 2,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not 1 <= page_size <= 100:
            raise ValueError("page_size는 1 이상 100 이하여야 합니다.")
        if detail_concurrency < 1:
            raise ValueError("detail_concurrency는 1 이상이어야 합니다.")
        if detail_ttl_days < 1:
            raise ValueError("detail_ttl_days는 1 이상이어야 합니다.")
        if retry_count < 0:
            raise ValueError("retry_count는 0 이상이어야 합니다.")
        self._provider = provider
        self._repository = repository
        self._page_size = page_size
        self._detail_concurrency = detail_concurrency
        self._detail_ttl = timedelta(days=detail_ttl_days)
        self._retry_count = retry_count
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(UTC))

    async def sync(
        self,
        area_code: str,
        district_code: str,
        *,
        dry_run: bool = False,
        details_limit: int | None = None,
        force_details: bool = False,
    ) -> PlaceSyncResult:
        if not area_code.strip() or not district_code.strip():
            raise ValueError("area_code와 district_code가 필요합니다.")
        if details_limit is not None and details_limit < 1:
            raise ValueError("details_limit은 1 이상이어야 합니다.")

        if dry_run:
            return await self._run(
                area_code,
                district_code,
                sync_run_id=None,
                dry_run=True,
                details_limit=details_limit,
                force_details=force_details,
            )

        sync_run_id = await self._repository.create_sync_run(area_code, district_code)
        acquired = await self._repository.try_acquire_sync_lock(
            area_code, district_code, sync_run_id
        )
        if not acquired:
            completed_at = self._now()
            await self._repository.complete_sync_run(
                sync_run_id,
                status="failed",
                api_total_count=None,
                processed_count=0,
                success_count=0,
                failed_count=0,
                new_count=0,
                updated_count=0,
                deactivated_count=0,
                error_summary={"SYNC_LOCK_UNAVAILABLE": 1},
                completed_at=completed_at,
            )
            return PlaceSyncResult(
                status="failed",
                dry_run=False,
                sync_run_id=sync_run_id,
                api_total_count=0,
                processed_count=0,
                success_count=0,
                failed_count=0,
                new_count=0,
                updated_count=0,
                deactivated_count=0,
                detail_target_count=0,
                detail_attempted_count=0,
                reparse_count=0,
                error_summary={"SYNC_LOCK_UNAVAILABLE": 1},
            )

        try:
            return await self._run(
                area_code,
                district_code,
                sync_run_id=sync_run_id,
                dry_run=False,
                details_limit=details_limit,
                force_details=force_details,
            )
        except Exception:
            await self._repository.complete_sync_run(
                sync_run_id,
                status="failed",
                api_total_count=None,
                processed_count=0,
                success_count=0,
                failed_count=0,
                new_count=0,
                updated_count=0,
                deactivated_count=0,
                error_summary={"SYNC_ABORTED": 1},
                completed_at=self._now(),
            )
            raise
        finally:
            await self._repository.release_sync_lock(
                area_code, district_code, sync_run_id
            )

    async def _run(
        self,
        area_code: str,
        district_code: str,
        *,
        sync_run_id: UUID | None,
        dry_run: bool,
        details_limit: int | None,
        force_details: bool,
    ) -> PlaceSyncResult:
        started_at = self._now()
        try:
            places, api_total_count = await self._collect_complete_list(
                area_code, district_code
            )
        except IncompletePlaceListError:
            if sync_run_id is not None:
                await self._repository.complete_sync_run(
                    sync_run_id,
                    status="failed",
                    api_total_count=None,
                    processed_count=0,
                    success_count=0,
                    failed_count=0,
                    new_count=0,
                    updated_count=0,
                    deactivated_count=0,
                    error_summary={"INCOMPLETE_PLACE_LIST": 1},
                    completed_at=self._now(),
                )
            return PlaceSyncResult(
                status="failed",
                dry_run=dry_run,
                sync_run_id=sync_run_id,
                api_total_count=0,
                processed_count=0,
                success_count=0,
                failed_count=0,
                new_count=0,
                updated_count=0,
                deactivated_count=0,
                detail_target_count=0,
                detail_attempted_count=0,
                reparse_count=0,
                error_summary={"INCOMPLETE_PLACE_LIST": 1},
            )

        existing = await self._repository.get_region_place_states(
            area_code, district_code
        )
        new_count = sum(place.content_id not in existing for place in places)
        updated_count = len(places) - new_count
        detail_targets, reparse_targets = self._select_targets(
            places,
            existing,
            now=started_at,
            force_details=force_details,
        )
        attempted_targets = (
            detail_targets[:details_limit]
            if details_limit is not None
            else detail_targets
        )

        if sync_run_id is not None:
            await self._repository.upsert_place_list(
                places, existing, sync_run_id, started_at
            )

        content_types = {
            place.content_id: place.content_type_id for place in places
        }
        reparse_failures: Counter[str] = Counter()
        for state in reparse_targets:
            try:
                schedule = normalize_operating_schedule(
                    content_type_id=content_types[state.content_id],
                    operating_hours=state.operating_hours_raw,
                    rest_date=state.rest_date_raw,
                )
                if sync_run_id is not None:
                    await self._repository.update_parsed_schedule(
                        state.content_id,
                        serialize_operating_schedule(schedule),
                        schedule.parse_status.value,
                        OPERATING_PARSER_VERSION,
                    )
            except Exception:
                reparse_failures["OPERATING_REPARSE_FAILED"] += 1

        outcomes = await self._fetch_details(attempted_targets)
        detail_failures: Counter[str] = Counter(
            outcome.error_code
            for outcome in outcomes
            if outcome.error_code is not None
        )
        if sync_run_id is not None:
            await self._store_detail_outcomes(outcomes, started_at)

        error_summary = reparse_failures + detail_failures
        failed_ids = {
            outcome.content_id for outcome in outcomes if outcome.error_code is not None
        }
        failed_count = len(failed_ids) + sum(reparse_failures.values())
        success_count = max(0, len(places) - failed_count)
        deactivated_count = 0
        if (
            sync_run_id is not None
            and details_limit is None
            and not dry_run
        ):
            deactivated_count = await self._repository.deactivate_unseen_places(
                area_code,
                district_code,
                sync_run_id,
                self._now(),
            )

        status = "partial_failure" if error_summary else "success"
        if sync_run_id is not None:
            await self._repository.complete_sync_run(
                sync_run_id,
                status=status,
                api_total_count=api_total_count,
                processed_count=len(places),
                success_count=success_count,
                failed_count=failed_count,
                new_count=new_count,
                updated_count=updated_count,
                deactivated_count=deactivated_count,
                error_summary=dict(error_summary) or None,
                completed_at=self._now(),
            )
        return PlaceSyncResult(
            status=status,
            dry_run=dry_run,
            sync_run_id=sync_run_id,
            api_total_count=api_total_count,
            processed_count=len(places),
            success_count=success_count,
            failed_count=failed_count,
            new_count=new_count,
            updated_count=updated_count,
            deactivated_count=deactivated_count,
            detail_target_count=len(detail_targets),
            detail_attempted_count=len(attempted_targets),
            reparse_count=len(reparse_targets),
            error_summary=dict(error_summary),
        )

    async def _collect_complete_list(
        self,
        area_code: str,
        district_code: str,
    ) -> tuple[list[TourPlaceRecord], int]:
        first = await self._provider.list_places_by_area(
            area_code, district_code, page_no=1, num_of_rows=self._page_size
        )
        self._validate_page(first, expected_page=1)
        page_count = (
            math.ceil(first.total_count / self._page_size)
            if first.total_count
            else 1
        )
        pages = [first]
        for page_no in range(2, page_count + 1):
            page = await self._provider.list_places_by_area(
                area_code,
                district_code,
                page_no=page_no,
                num_of_rows=self._page_size,
            )
            self._validate_page(page, expected_page=page_no)
            if page.total_count != first.total_count:
                raise IncompletePlaceListError("total_count changed between pages")
            pages.append(page)

        places = [place for page in pages for place in page.places]
        unique_ids = {place.content_id for place in places}
        if len(places) != first.total_count or len(unique_ids) != first.total_count:
            raise IncompletePlaceListError("place count does not match total_count")
        return places, first.total_count

    def _validate_page(self, page: TourPlacePage, *, expected_page: int) -> None:
        if page.page_no != expected_page:
            raise IncompletePlaceListError("unexpected page number")
        if not 0 <= page.num_of_rows <= self._page_size:
            raise IncompletePlaceListError("unexpected page size")
        if any(
            not place.content_id or not place.content_type_id or not place.title
            for place in page.places
        ):
            raise IncompletePlaceListError("place is missing a required field")

    def _select_targets(
        self,
        places: Sequence[TourPlaceRecord],
        existing: Mapping[str, StoredPlaceState],
        *,
        now: datetime,
        force_details: bool,
    ) -> tuple[list[TourPlaceRecord], list[StoredPlaceState]]:
        detail_targets: list[TourPlaceRecord] = []
        reparse_targets: list[StoredPlaceState] = []
        for place in places:
            state = existing.get(place.content_id)
            needs_detail = force_details or state is None
            if state is not None and not needs_detail:
                source_changed = (
                    place.source_modified_at is not None
                    and place.source_modified_at != state.source_modified_at
                )
                ttl_expired = (
                    state.detail_fetched_at is None
                    or now - state.detail_fetched_at >= self._detail_ttl
                )
                needs_detail = (
                    state.detail_fetch_status in {"pending", "failed"}
                    or source_changed
                    or ttl_expired
                )
            if needs_detail:
                detail_targets.append(place)
            elif (
                state is not None
                and state.operating_parser_version != OPERATING_PARSER_VERSION
            ):
                reparse_targets.append(state)
        return detail_targets, reparse_targets

    async def _fetch_details(
        self,
        targets: Sequence[TourPlaceRecord],
    ) -> list[_DetailOutcome]:
        semaphore = asyncio.Semaphore(self._detail_concurrency)

        async def fetch(place: TourPlaceRecord) -> _DetailOutcome:
            async with semaphore:
                return await self._fetch_detail_with_retry(place)

        return list(await asyncio.gather(*(fetch(place) for place in targets)))

    async def _fetch_detail_with_retry(
        self,
        place: TourPlaceRecord,
    ) -> _DetailOutcome:
        for attempt in range(self._retry_count + 1):
            try:
                details = await self._provider.get_operating_details(
                    place.content_id, place.content_type_id
                )
                schedule = normalize_operating_schedule(
                    content_type_id=details.content_type_id,
                    operating_hours=details.operating_hours_raw,
                    rest_date=details.rest_date_raw,
                )
                return _DetailOutcome(
                    place.content_id,
                    details,
                    serialize_operating_schedule(schedule),
                    schedule.parse_status.value,
                    None,
                )
            except ProviderTimeoutError:
                error_code = _ERROR_TIMEOUT
            except ProviderUnavailableError as exc:
                detail = str(exc.details or "")
                error_code = (
                    _ERROR_RATE_LIMITED if "429" in detail else _ERROR_UNAVAILABLE
                )
            except ValueError:
                return _DetailOutcome(
                    place.content_id,
                    None,
                    None,
                    None,
                    _ERROR_INVALID_RESPONSE,
                )
            except Exception:
                return _DetailOutcome(
                    place.content_id, None, None, None, _ERROR_UNKNOWN
                )

            if attempt < self._retry_count:
                delay = (2**attempt) * 0.25 + random.uniform(0, 0.1)
                await self._sleep(delay)
        return _DetailOutcome(place.content_id, None, None, None, error_code)

    async def _store_detail_outcomes(
        self,
        outcomes: Sequence[_DetailOutcome],
        fetched_at: datetime,
    ) -> None:
        for outcome in outcomes:
            if outcome.error_code is not None:
                await self._repository.mark_detail_failed(
                    outcome.content_id, outcome.error_code
                )
                continue
            details = outcome.details
            if (
                details is None
                or outcome.operating_schedule is None
                or outcome.parse_status is None
            ):
                raise RuntimeError("detail outcome has neither data nor error")
            await self._repository.update_operating_details(
                outcome.content_id,
                details.operating_hours_raw,
                details.rest_date_raw,
                outcome.operating_schedule,
                outcome.parse_status,
                OPERATING_PARSER_VERSION,
                fetched_at,
                parking_info_raw=details.parking_info_raw,
                parking_fee_raw=details.parking_fee_raw,
                use_fee_raw=details.use_fee_raw,
                discount_info_raw=details.discount_info_raw,
            )
