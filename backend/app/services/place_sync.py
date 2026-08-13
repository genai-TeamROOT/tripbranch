"""TourAPI 장소 목록과 운영정보를 Supabase에 동기화한다."""

from __future__ import annotations

import asyncio
import math
import random
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
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
from app.providers.upstream_errors import is_daily_quota_exceeded
from app.repositories.protocols import PlaceRepository

_ERROR_TIMEOUT = "TOUR_DETAIL_TIMEOUT"
_ERROR_RATE_LIMITED = "TOUR_DETAIL_RATE_LIMITED"
# 일일 한도는 초당 한도와 대응이 반대다 — 재시도해도 그날 안에는 성공하지 않는다.
_ERROR_QUOTA_EXCEEDED = "TOUR_DETAIL_QUOTA_EXCEEDED"
_ERROR_UNAVAILABLE = "TOUR_DETAIL_UNAVAILABLE"
_ERROR_INVALID_RESPONSE = "TOUR_DETAIL_INVALID_RESPONSE"
_ERROR_UNKNOWN = "TOUR_DETAIL_UNKNOWN"


class IncompletePlaceListError(RuntimeError):
    """지역 목록의 페이지·건수·식별자 완전성 검증이 실패했다."""


class DailyQuotaExceededError(RuntimeError):
    """상세조회 중 외부 API의 일일 요청 한도가 소진됐다.

    남은 대상은 시도조차 하지 않고 중단한다. 아직 부르지 않은 장소를 실패로 기록하면
    "그 장소의 상세정보가 없다"와 "오늘 못 불렀다"가 구분되지 않는다 — 기존 상태를
    그대로 두면 다음 실행에서 같은 규칙으로 다시 대상이 된다.
    """

    def __init__(self, content_id: str) -> None:
        super().__init__(f"일일 요청 한도 소진 (content_id={content_id})")
        self.content_id = content_id


@dataclass(frozen=True)
class SyncProgress:
    """진행 상황 한 조각. 관측 전용이라 동기화 판정에는 쓰이지 않는다.

    place_sync_runs 행은 시작과 종료에만 쓰이므로, 실행 중 진행률은 DB에서 읽을
    방법이 없다. 종로구 상세조회는 수백 건이라 그동안 "running"만 보이면 화면이
    무의미해진다.
    """

    phase: str
    processed: int
    total: int


ProgressCallback = Callable[[SyncProgress], None]


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
        detail_min_interval_seconds: float = 0.0,
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
        if detail_min_interval_seconds < 0:
            raise ValueError("detail_min_interval_seconds는 0 이상이어야 합니다.")
        if retry_count < 0:
            raise ValueError("retry_count는 0 이상이어야 합니다.")
        self._provider = provider
        self._repository = repository
        self._page_size = page_size
        self._detail_concurrency = detail_concurrency
        self._detail_ttl = timedelta(days=detail_ttl_days)
        self._detail_min_interval = detail_min_interval_seconds
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
        detail_content_ids: frozenset[str] | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> PlaceSyncResult:
        """지역 장소 목록과 상세정보를 DB에 반영한다.

        detail_content_ids를 주면 상세조회 대상을 그 집합으로 고정한다. 스냅샷
        대조가 이미 "무엇이 바뀌었는가"를 정한 경우에 쓴다 — TTL 만료로 안 바뀐
        장소까지 다시 부르는 일을 막는다(종로구 기준 844건 전량). None이면 기존
        규칙(신규·수정시각 변경·TTL 만료)을 그대로 쓴다.
        """
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
                detail_content_ids=detail_content_ids,
                on_progress=on_progress,
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
                detail_content_ids=detail_content_ids,
                on_progress=on_progress,
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
        detail_content_ids: frozenset[str] | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> PlaceSyncResult:
        def report(phase: str, processed: int, total: int) -> None:
            if on_progress is not None:
                on_progress(SyncProgress(phase=phase, processed=processed, total=total))

        started_at = self._now()
        report("list", 0, 0)
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

        report("list", len(places), len(places))

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
            detail_content_ids=detail_content_ids,
        )
        attempted_targets = (
            detail_targets[:details_limit]
            if details_limit is not None
            else detail_targets
        )

        if sync_run_id is not None:
            report("upsert", 0, len(places))
            await self._repository.upsert_place_list(
                places, existing, sync_run_id, started_at
            )
            report("upsert", len(places), len(places))

        content_types = {
            place.content_id: place.content_type_id for place in places
        }
        reparse_failures: Counter[str] = Counter()
        report("reparse", 0, len(reparse_targets))
        for reparsed, state in enumerate(reparse_targets, start=1):
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
            report("reparse", reparsed, len(reparse_targets))

        outcomes = await self._fetch_details(attempted_targets, report)
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
            report("deactivate", 0, 0)
            deactivated_count = await self._repository.deactivate_unseen_places(
                area_code,
                district_code,
                sync_run_id,
                self._now(),
            )
            report("deactivate", deactivated_count, deactivated_count)

        status = "partial_failure" if error_summary else "success"
        report("done", len(places), len(places))
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
            # 계획한 수가 아니라 실제로 부른 수다 — 일일 한도로 중단하면 적다.
            detail_attempted_count=len(outcomes),
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
        detail_content_ids: frozenset[str] | None = None,
    ) -> tuple[list[TourPlaceRecord], list[StoredPlaceState]]:
        detail_targets: list[TourPlaceRecord] = []
        reparse_targets: list[StoredPlaceState] = []
        for place in places:
            state = existing.get(place.content_id)
            needs_detail = force_details or state is None
            if state is not None and not needs_detail:
                if detail_content_ids is not None:
                    # 스냅샷 대조가 이미 변경분을 정했다. TTL과 수정시각을 다시
                    # 보면 안 바뀐 장소까지 끌려 들어와 대조 결과와 실제 호출
                    # 건수가 어긋난다. 다만 지난 실행에서 못 채운 건은 남긴다 —
                    # 빼면 pending·failed가 영영 그대로 남는다.
                    needs_detail = (
                        place.content_id in detail_content_ids
                        or state.detail_fetch_status in {"pending", "failed"}
                    )
                else:
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
        report: Callable[[str, int, int], None] | None = None,
    ) -> list[_DetailOutcome]:
        """상세조회 결과를 모은다. 시도하지 않은 장소는 결과에 넣지 않는다.

        일일 한도가 소진되면 남은 장소를 부르지 않고 건너뛴다 — 결과 개수가 대상
        개수보다 적은 것이 "오늘 여기까지 했다"는 표시다. 건너뛴 장소를 실패로
        기록하지 않으므로 기존 상태가 유지되고, 다음 실행에서 같은 규칙으로 다시
        대상이 된다.
        """
        semaphore = asyncio.Semaphore(self._detail_concurrency)
        throttle_lock = asyncio.Lock()
        completed = 0
        total = len(targets)
        next_allowed = 0.0
        quota_exhausted = False
        if report is not None:
            report("details", 0, total)

        async def throttle() -> None:
            """호출 간 최소 간격을 지킨다.

            동시성만으로는 속도를 잡을 수 없다 — 응답이 100ms대라 동시성 1에서도
            초당 8회쯤 나간다(2026-08-10 실측). 간격이 0이면 아무것도 하지 않아
            기존 동작 그대로다.
            """
            nonlocal next_allowed
            if self._detail_min_interval <= 0:
                return
            async with throttle_lock:
                now = monotonic()
                wait = next_allowed - now
                if wait > 0:
                    await self._sleep(wait)
                next_allowed = max(now, next_allowed) + self._detail_min_interval

        async def fetch(place: TourPlaceRecord) -> _DetailOutcome | None:
            nonlocal completed, quota_exhausted
            async with semaphore:
                if quota_exhausted:
                    return None
                await throttle()
                try:
                    outcome = await self._fetch_detail_with_retry(place)
                except DailyQuotaExceededError:
                    quota_exhausted = True
                    outcome = _DetailOutcome(
                        place.content_id, None, None, None, _ERROR_QUOTA_EXCEEDED
                    )
            completed += 1
            if report is not None:
                report("details", completed, total)
            return outcome

        results = await asyncio.gather(*(fetch(place) for place in targets))
        return [outcome for outcome in results if outcome is not None]

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
                if is_daily_quota_exceeded(detail):
                    # 재시도하지 않고 즉시 올린다. 그날 안에는 무엇을 해도 실패하는데,
                    # 계속 던지면 남은 대상까지 같은 실패를 반복하며 한도만 더 태운다.
                    raise DailyQuotaExceededError(place.content_id) from None
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
                info_center_raw=details.info_center_raw,
                baby_carriage_raw=details.baby_carriage_raw,
                pet_raw=details.pet_raw,
                credit_card_raw=details.credit_card_raw,
                restroom_raw=details.restroom_raw,
            )
