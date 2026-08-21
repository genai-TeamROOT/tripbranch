"""개발자 Ops 패널 전용 API 라우터.

역할: 프론트 `/dev-ops` 화면이 쓰는 호출량 집계, 장소 DB 상태, 스냅샷 대조와
      동기화 실행을 제공한다.
입력: GET /api/dev/api-usage, GET /api/dev/db-status, POST /api/dev/place-sync/*.
출력: 관측용 JSON과 동기화 job 상태. 추천 판정에는 어떤 영향도 주지 않는다.
호출 시점: 개발자가 /dev-ops 화면을 열거나, 대조·반영을 실행할 때.

동기화는 대조와 반영 두 단계로 나눈다. 대조는 목록 API 1회로 스냅샷을 남기고
이전 스냅샷과 비교만 하며 DB를 건드리지 않는다. 반영은 그 대조 결과가 정한
대상에만 상세조회를 보내 DB에 쓴다. 한 버튼으로 합치면 "무엇이 바뀌는지" 모르는
채로 운영 DB에 쓰게 된다.

이 라우터는 `APP_ENV=local`일 때만 main.py가 등록한다 — 배포 환경에서는 경로
자체가 존재하지 않는다(404). DB 쓰기 엔드포인트가 붙을 자리라 노출 범위를
설정이 아니라 등록 여부로 끊는다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.agent_context.seoul_commercial_areas import select_nearest_commercial_area
from app.config import settings
from app.domain.models import TourPlacePage
from app.errors import AppError
from app.observability.api_exchanges import get_recorder
from app.observability.api_usage import (
    create_external_client,
    get_usage_snapshot,
    reset_usage,
)
from app.providers.real_place import RealPlaceProvider
from app.repositories.supabase_places import SupabasePlaceRepository
from app.services import place_snapshot
from app.services.place_sync import PlaceSyncService, SyncProgress
from app.services.place_sync_jobs import (
    SyncJobConflictError,
    SyncJobOutcome,
    get_job_registry,
)

router = APIRouter(prefix="/dev", tags=["dev"])


class DevPanelError(AppError):
    """개발자 패널이 그대로 보여줄 오류.

    HTTPException을 쓰면 main.py의 공통 핸들러가 메시지를 "요청 내용을
    확인해주세요."로 갈아끼워 원인이 사라진다. 원인을 화면에 띄우는 게 이 패널의
    목적이라 AppError 경로를 탄다.
    """

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(
            code="dev_panel_error",
            message=message,
            status_code=status_code,
            retryable=False,
        )


def status_client() -> httpx.AsyncClient:
    """상태 조회 전용 클라이언트 — 일부러 계측을 붙이지 않는다.

    `create_external_client()`를 쓰면 패널이 자기 조회를 자기 표에 집계한다.
    새로고침 한 번에 places / place_enrichments / place_concentration_mappings /
    place_sync_runs / place_sync_locks 다섯 줄이 늘어나, 추천 요청이 동기화
    테이블을 건드린 것처럼 보인다(실제로 추천 경로는 place_sync_*를 읽지 않는다).
    측정 도구가 측정값을 만들면 안 된다.

    반대로 패널에서 실행하는 동기화 job의 외부 호출은 계측 대상이다 — 그건
    관측하려는 트래픽 자체이므로 계측된 클라이언트를 쓴다.
    """
    return httpx.AsyncClient()


def _require_supabase() -> tuple[str, str]:
    """Supabase 자격증명이 없으면 조회 자체가 불가능하다는 걸 그대로 알린다."""
    url = settings.supabase_url.strip()
    key = settings.supabase_secret_key.strip()
    if not url or not key:
        raise DevPanelError(
            "SUPABASE_URL / SUPABASE_SECRET_KEY가 없어 DB 상태를 조회할 수 "
            "없습니다. backend/.env를 확인하세요."
        )
    return url, key


@router.get("/api-usage")
async def get_api_usage() -> dict[str, Any]:
    """이 프로세스가 기동 이후 보낸 외부 호출 집계."""
    return get_usage_snapshot()


@router.post("/api-usage/reset")
async def post_api_usage_reset() -> dict[str, Any]:
    reset_usage()
    return get_usage_snapshot()


class NearestAreaResponse(BaseModel):
    """좌표에 붙일 사람이 읽을 수 있는 지역 이름.

    기기 GPS는 좌표만 주므로 개발자 패널의 위치 뱃지에 찍을 이름이 없다. 서울시
    실시간 상권 82개 지역의 대표 좌표(agent_context/seoul_commercial_areas.py)에서
    최근접을 골라 근사 이름을 만든다 — 외부 호출은 하지 않는다.

    근사치라는 사실을 숨기지 않으려고 distance_km를 항상 함께 준다. 최근접이 2km를
    넘으면 세 값 모두 None이고, 그때는 표시할 이름이 없다는 뜻이다.
    """

    area_code: str | None = None
    area_name: str | None = None
    distance_km: float | None = None


@router.get("/nearest-area")
async def get_nearest_area(location: str) -> NearestAreaResponse:
    """`location`("위도,경도")에 가장 가까운 서울시 상권 지역 이름.

    추천 판정과 무관한 표시 전용 조회다. 좌표를 상권 지역으로 대체해 **조회**하는
    C의 경로(realtime_commercial)와 같은 표를 쓰지만, 여기서는 이름만 꺼내 쓰고
    상권 데이터를 부르지 않는다.
    """

    parts = location.split(",")
    if len(parts) != 2:
        raise DevPanelError("location은 '위도,경도' 형식이어야 합니다.")
    try:
        latitude, longitude = (float(part.strip()) for part in parts)
    except ValueError:
        raise DevPanelError("location의 위도·경도를 숫자로 읽을 수 없습니다.") from None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise DevPanelError("location의 위도·경도 범위가 올바르지 않습니다.")

    nearest = select_nearest_commercial_area(latitude=latitude, longitude=longitude)
    if nearest is None:
        return NearestAreaResponse()
    area, distance_km = nearest
    return NearestAreaResponse(
        area_code=area.code, area_name=area.name, distance_km=distance_km
    )


class CaptureRequest(BaseModel):
    enabled: bool


@router.get("/exchanges")
async def get_exchanges() -> dict[str, Any]:
    """최근 외부 API 요청·응답 원문(자격증명은 마스킹된 상태)."""
    return get_recorder().snapshot()


@router.post("/exchanges/capture")
async def post_exchange_capture(request: CaptureRequest) -> dict[str, Any]:
    """캡처를 켜고 끈다.

    기본은 꺼짐이고, 이 라우터가 APP_ENV=local에서만 등록되므로 배포 환경에서는
    켤 방법이 없다 — 응답 본문 버퍼링이 운영 메모리를 먹지 않게 하는 장치다.
    """
    recorder = get_recorder()
    recorder.set_enabled(request.enabled)
    return recorder.snapshot()


@router.post("/exchanges/clear")
async def post_exchange_clear() -> dict[str, Any]:
    recorder = get_recorder()
    recorder.clear()
    return recorder.snapshot()


@router.get("/db-status")
async def get_db_status(
    area_code: str | None = None,
    district_code: str | None = None,
    sync_run_limit: int = 10,
) -> dict[str, Any]:
    """장소 DB의 현재 상태와 최근 동기화 이력."""
    url, key = _require_supabase()
    area = area_code or settings.place_sync_area_code
    district = district_code or settings.place_sync_district_code

    async with status_client() as client:
        repository = SupabasePlaceRepository(
            supabase_url=url,
            secret_key=key,
            client=client,
            # 844행 조회는 챗봇 요청보다 오래 걸린다. 요청 경로용 공통 타임아웃을
            # 그대로 쓰면 패널이 아무 이유 없이 타임아웃으로 보인다.
            timeout_seconds=max(settings.external_api_timeout_seconds, 30.0),
        )
        places = await repository.get_region_place_summary(area, district)
        enrichment_count = await repository.count_rows("place_enrichments")
        concentration_mapping_count = await repository.count_rows(
            "place_concentration_mappings"
        )
        sync_runs = await repository.list_recent_sync_runs(sync_run_limit)
        locks = await repository.list_sync_locks()

    return {
        "area_code": area,
        "district_code": district,
        "places": places,
        "place_enrichments_count": enrichment_count,
        "place_concentration_mappings_count": concentration_mapping_count,
        "sync_runs": sync_runs,
        "sync_locks": locks,
        "detail_ttl_days": settings.place_sync_detail_ttl_days,
    }


# --- 동기화: 대조 → 반영 -----------------------------------------------------


class ReconcileRequest(BaseModel):
    area_code: str | None = None
    district_code: str | None = None
    baseline: str | None = Field(
        default=None,
        description="비교 기준 스냅샷 파일명. 생략하면 저장된 최신 스냅샷을 쓴다.",
    )


class ApplyRequest(BaseModel):
    area_code: str | None = None
    district_code: str | None = None
    snapshot: str = Field(description="반영에 사용할 스냅샷 파일명(대조 단계 산출물)")
    detail_content_ids: list[str] = Field(
        description="상세조회 대상 content_id. 대조 결과에서 정한다."
    )
    added_content_ids: list[str] = Field(
        default_factory=list,
        description=(
            "이번에 새로 들어온 content_id. 반영 후 집중률 매핑 유무를 확인하는 데 쓴다."
        ),
    )
    dry_run: bool = True
    confirm: str = Field(description="'<area>-<district>' 문자열. 오타 실행 방지용")


def _require_real_place_provider() -> str:
    """Fake 구성으로 운영 DB에 쓰는 사고를 막는다.

    Fake provider는 `"테스트 카페"` 같은 값을 돌려준다. 그게 places에 upsert되면
    되돌리기 어렵다(D-042의 조용한 fake 부팅과 같은 함정).
    """
    if settings.resolved_place_provider != "real":
        raise DevPanelError(
            "PLACE_PROVIDER가 real이 아니라 동기화를 실행할 수 없습니다. "
            "fake 데이터가 운영 DB에 들어가는 것을 막기 위한 제한이에요."
        )
    if not settings.tour_api_service_key.strip():
        raise DevPanelError("TOUR_API_SERVICE_KEY가 없어 TourAPI를 호출할 수 없습니다.")
    return settings.tour_api_service_key


def _snapshot_path(name: str) -> Path:
    """스냅샷 파일명을 데이터 디렉터리 안으로 가둔다."""
    candidate = (place_snapshot.DATA_DIR / Path(name).name).resolve()
    if candidate.parent != place_snapshot.DATA_DIR.resolve():
        raise DevPanelError("스냅샷 경로가 올바르지 않습니다.")
    if not candidate.exists():
        raise DevPanelError(f"스냅샷 파일을 찾을 수 없습니다: {candidate.name}")
    return candidate


@router.get("/place-sync/snapshots")
async def get_snapshots() -> dict[str, Any]:
    return {
        "snapshots": [path.name for path in place_snapshot.list_snapshots()],
        "data_dir": str(place_snapshot.DATA_DIR),
    }


@router.post("/place-sync/reconcile")
async def post_reconcile(request: ReconcileRequest) -> dict[str, Any]:
    """목록을 1회 조회해 스냅샷을 남기고 이전 스냅샷과 대조한다. DB는 안 건드린다."""
    api_key = _require_real_place_provider()
    area = request.area_code or settings.place_sync_area_code
    district = request.district_code or settings.place_sync_district_code
    now = datetime.now(place_snapshot.KST)

    async with create_external_client() as client:
        current = await place_snapshot.fetch_place_rows(
            client, api_key, area, district, now
        )

    snapshot_path = (
        place_snapshot.DATA_DIR / f"{place_snapshot.SNAPSHOT_PREFIX}{now:%Y%m%d}.csv"
    )
    baseline_path = (
        _snapshot_path(request.baseline)
        if request.baseline
        else place_snapshot.find_baseline(exclude=snapshot_path)
    )
    # 같은 날 다시 대조하면 덮어쓴다. 스냅샷은 git 추적 대상이라 덮어쓴 차이가
    # 그대로 diff로 남는다.
    place_snapshot.write_snapshot(current, snapshot_path)

    if baseline_path is None:
        return {
            "area_code": area,
            "district_code": district,
            "snapshot": snapshot_path.name,
            "snapshot_count": len(current),
            "baseline": None,
            "skipped_columns": [],
            "counts": {"added": 0, "removed": 0, "updated": 0},
            "detail_content_ids": sorted(current),
            "detail_excluded_ids": [],
            "rows": [],
            "message": "기준 스냅샷이 없어 대조를 건너뛰었습니다. 전량이 신규로 취급됩니다.",
        }

    baseline = place_snapshot.load_snapshot(baseline_path)
    baseline_columns = list(next(iter(baseline.values()), {}).keys())
    compared = place_snapshot.comparable_columns(baseline_columns)
    # 조용히 빼면 "안 바뀌었다"와 "안 봤다"가 결과에서 구분되지 않는다.
    skipped = [
        column for column in place_snapshot.COMPARED_COLUMNS if column not in compared
    ]
    rows = place_snapshot.build_reconciliation_rows(baseline, current, compared)
    reconciliation_path = (
        place_snapshot.DATA_DIR
        / f"{place_snapshot.RECONCILIATION_PREFIX}{now:%Y%m%d}.csv"
    )
    place_snapshot.write_reconciliation(
        rows, reconciliation_path, baseline_name=baseline_path.name, compared_at=now
    )
    detail_ids, excluded_ids = place_snapshot.select_detail_targets(rows)

    counts = {"added": 0, "removed": 0, "updated": 0}
    for row in rows:
        counts[str(row["change_type"])] += 1

    return {
        "area_code": area,
        "district_code": district,
        "snapshot": snapshot_path.name,
        "snapshot_count": len(current),
        "baseline": baseline_path.name,
        "baseline_count": len(baseline),
        "reconciliation": reconciliation_path.name,
        "skipped_columns": skipped,
        "counts": counts,
        "detail_content_ids": sorted(detail_ids),
        "detail_excluded_ids": sorted(excluded_ids),
        "rows": rows,
    }


class _SnapshotListProvider:
    """목록은 스냅샷에서, 상세조회는 TourAPI에서.

    대조에 쓴 목록과 DB에 반영하는 목록이 같은 데이터임을 보장한다 — 다시 조회하면
    그 사이 원본이 바뀌어 대조 결과와 실제 반영분이 어긋난다. 목록 API 호출도 0회다.
    """

    def __init__(self, snapshot_path: Path, inner: RealPlaceProvider) -> None:
        self._records = place_snapshot.records_from_snapshot(snapshot_path)
        self._inner = inner

    async def list_places_by_area(
        self,
        area_code: str,
        district_code: str,
        page_no: int,
        num_of_rows: int = 100,
    ) -> TourPlacePage:
        start = (page_no - 1) * num_of_rows
        return TourPlacePage(
            page_no=page_no,
            num_of_rows=num_of_rows,
            total_count=len(self._records),
            places=tuple(self._records[start : start + num_of_rows]),
        )

    async def get_operating_details(self, content_id: str, content_type_id: str):
        return await self._inner.get_operating_details(content_id, content_type_id)


@router.post("/place-sync/apply")
async def post_apply(request: ApplyRequest) -> dict[str, Any]:
    """대조가 정한 대상에만 상세조회를 보내 DB에 반영한다."""
    api_key = _require_real_place_provider()
    url, key = _require_supabase()
    area = request.area_code or settings.place_sync_area_code
    district = request.district_code or settings.place_sync_district_code

    expected = f"{area}-{district}"
    if request.confirm.strip() != expected:
        raise DevPanelError(
            f"확인 문자열이 일치하지 않습니다. '{expected}'를 입력하세요."
        )

    snapshot_path = _snapshot_path(request.snapshot)
    detail_ids = frozenset(request.detail_content_ids)

    async def run(on_progress: Callable[[SyncProgress], None]) -> SyncJobOutcome:
        # 동기화가 보내는 외부 호출은 계측 대상이다 — 상태 조회와 달리 이건
        # 관측하려는 트래픽 자체다.
        async with create_external_client() as client:
            provider = RealPlaceProvider(
                api_key=api_key,
                client=client,
                timeout_seconds=settings.external_api_timeout_seconds,
            )
            repository = SupabasePlaceRepository(
                supabase_url=url,
                secret_key=key,
                client=client,
                timeout_seconds=max(settings.external_api_timeout_seconds, 30.0),
            )
            service = PlaceSyncService(
                _SnapshotListProvider(snapshot_path, provider),
                repository,
                page_size=settings.place_sync_page_size,
                detail_concurrency=settings.place_sync_detail_concurrency,
                detail_ttl_days=settings.place_sync_detail_ttl_days,
                retry_count=settings.external_api_retry_count,
            )
            result = await service.sync(
                area,
                district,
                dry_run=request.dry_run,
                detail_content_ids=detail_ids,
                on_progress=on_progress,
            )
            # 새로 들어온 장소는 집중률 매핑이 없다. 매핑이 없으면 혼잡도 조회를
            # 아예 건너뛰므로(enrichment_service), 알리지 않으면 그 장소만 조용히
            # 판정에서 빠진 채 남는다. 매핑 적재는 별도 스크립트 소관이라 여기서는
            # 확인만 한다.
            unmapped = await repository.find_missing_concentration_mappings(
                request.added_content_ids
            )
            return SyncJobOutcome(result=result, unmapped_new_place_ids=unmapped)

    try:
        job = get_job_registry().start(
            {
                "area_code": area,
                "district_code": district,
                "snapshot": snapshot_path.name,
                "dry_run": request.dry_run,
                "detail_target_count": len(detail_ids),
                "added_count": len(request.added_content_ids),
            },
            run,
        )
    except SyncJobConflictError as exc:
        raise DevPanelError(str(exc), status_code=409) from None
    return job.snapshot()


@router.get("/place-sync/jobs/{job_id}")
async def get_sync_job(job_id: str) -> dict[str, Any]:
    job = get_job_registry().get(job_id)
    if job is None:
        raise DevPanelError("해당 job을 찾을 수 없습니다.", status_code=404)
    return job.snapshot()


@router.get("/place-sync/jobs")
async def get_running_sync_job() -> dict[str, Any]:
    job = get_job_registry().running()
    return {"running": job.snapshot() if job is not None else None}
