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

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.agent_context.seoul_realtime_areas import select_nearest_commercial_area
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
from app.providers.tour_barrier_free import RealBarrierFreeProvider
from app.providers.tour_ldong_registry import find_district_name, list_districts
from app.repositories.supabase_places import SupabasePlaceRepository
from app.services import place_snapshot
from app.services.place_sync import (
    PlaceSyncService,
    SyncProgress,
    barrier_free_candidate_ids,
    barrier_free_stale_ids,
)
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
    실시간 상권 82개 지역의 대표 좌표(agent_context/seoul_realtime_areas.py)에서
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
async def get_db_status(sync_run_limit: int = 10) -> dict[str, Any]:
    """장소 DB의 현재 상태와 최근 동기화 이력.

    장소 요약은 적재된 구별로 나누고 전 구 합계를 함께 준다 — 패널이 탭으로 나눠
    보여준다. 예전에는 설정값(`place_sync_district_code`) 한 구만 세었는데, 같은
    화면의 동기화 이력은 전 구를 보여주고 있어 "용산구 486건 신규"와 "활성 844"가
    나란히 놓였다. 두 숫자가 서로 다른 범위를 세고 있다는 걸 화면에서 알 방법이
    없었다.

    구 목록을 파라미터로 받지 않는 이유: 어떤 구가 적재돼 있는지는 places가 아는
    사실이지 호출자가 정할 값이 아니다. 목록을 넘기게 하면 새 구를 넣고도 화면에
    안 보이는 상태가 생긴다.

    place_enrichments와 집중률 매핑은 구 열이 없어(둘 다 content_id 기준) 전체
    건수만 센다. 구별로 쪼개려면 places와 대조해야 하는데, 이 두 테이블은 장소
    동기화가 건드리지 않아 구별로 볼 실익이 없다.

    `detail_calls_today`는 오늘 detailIntro2를 몇 번 불렀는지를 place_sync_runs에서
    센 값이다. 호출량 표(api-usage)는 프로세스 메모리라 재시작하면 0이 되고
    backend/scripts 실행분도 놓치는데, 이 값은 둘 다 살아남는다. 그래도 하한이다 —
    재시도가 안 세지고, 중간에 죽은 실행은 열이 비어 있다.
    """
    url, key = _require_supabase()

    async with status_client() as client:
        repository = SupabasePlaceRepository(
            supabase_url=url,
            secret_key=key,
            client=client,
            # 2,300행 조회는 챗봇 요청보다 오래 걸린다. 요청 경로용 공통 타임아웃을
            # 그대로 쓰면 패널이 아무 이유 없이 타임아웃으로 보인다.
            timeout_seconds=max(settings.external_api_timeout_seconds, 30.0),
        )
        summaries = await repository.get_place_summaries_by_district()
        barrier_free_counts = await repository.count_barrier_free_by_district()
        enrichment_count = await repository.count_rows("place_enrichments")
        concentration_mapping_count = await repository.count_rows(
            "place_concentration_mappings"
        )
        sync_runs = await repository.list_recent_sync_runs(sync_run_limit)
        locks = await repository.list_sync_locks()
        detail_calls = await repository.summarize_detail_calls_since(
            _today_start_kst()
        )

    districts = [
        {
            **summary,
            # 이름을 못 찾아도 코드는 그대로 남는다 — 화면이 코드로 표시한다.
            "district_name": find_district_name(
                str(summary.get("area_code") or ""),
                str(summary.get("district_code") or ""),
            ),
            **_barrier_free_summary(
                barrier_free_counts.get(
                    (
                        str(summary.get("area_code") or ""),
                        str(summary.get("district_code") or ""),
                    )
                )
            ),
        }
        for summary in _as_summary_list(summaries.get("districts"))
    ]

    overall = summaries.get("overall")
    if isinstance(overall, Mapping):
        overall = {
            **overall,
            # 전 구 합계는 구별 값을 더한다 — 따로 세면 한쪽만 규칙이 바뀐 채 남는다.
            **_barrier_free_summary(
                {
                    "active": sum(c["active"] for c in barrier_free_counts.values()),
                    "total": sum(c["total"] for c in barrier_free_counts.values()),
                }
            ),
        }

    return {
        "overall": overall,
        "districts": districts,
        "place_enrichments_count": enrichment_count,
        "place_concentration_mappings_count": concentration_mapping_count,
        "sync_runs": sync_runs,
        "sync_locks": locks,
        "detail_ttl_days": settings.place_sync_detail_ttl_days,
        "detail_calls_today": {
            **detail_calls,
            "daily_limit": settings.tour_api_daily_call_limit,
        },
    }


def _barrier_free_summary(counts: Mapping[str, int] | None) -> dict[str, int]:
    """무장애 행 수를 요약에 실을 모양으로 바꾼다.

    행이 없는 구는 0으로 채운다 — 키를 빼면 화면이 "아직 안 채웠다"와 "이 응답에는
    그 값이 없다"를 구분할 수 없다.
    """
    return {
        "barrier_free_active": (counts or {}).get("active", 0),
        "barrier_free_total": (counts or {}).get("total", 0),
    }


def _today_start_kst() -> datetime:
    """오늘 0시(KST). TourAPI 일일 한도가 그 경계로 초기화된다."""
    return datetime.now(place_snapshot.KST).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _as_summary_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


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
    details_limit: int | None = Field(
        default=None,
        ge=1,
        description=(
            "이번 실행에서 부를 상세조회 상한. 새 구는 대상이 수백 건이라 하루 "
            "한도(1,000회)를 한 번에 소진할 수 있어 나눠 받는다. 상한이 걸린 "
            "실행은 비활성화를 건너뛴다 — 목록을 다 처리하지 못했으므로 "
            "'사라진 장소'를 판정할 수 없다."
        ),
    )
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


def _require_snapshot_region(
    snapshot: dict[str, dict[str, str]],
    snapshot_name: str,
    area_code: str,
    district_code: str,
) -> None:
    """스냅샷이 담은 구가 지금 다루는 구와 같은지 내용으로 확인한다.

    다른 구 스냅샷으로 반영하면 그 구에 없는 장소, 즉 **대상 구의 활성 장소 전부**가
    "목록에서 사라진 것"으로 판정돼 비활성화된다(`deactivate_unseen_places`).
    되돌리려면 동기화를 다시 돌려야 하고, 그 사이 추천은 결과 없음이 된다.

    대조 쪽도 같은 함수로 막는다 — 다른 구를 기준으로 잡으면 "전량 삭제 + 전량
    신규"가 나오는데, 이 모양은 실제 대량 변경과 구분이 안 된다(2026-08-20 중구
    사례).
    """
    regions = place_snapshot.snapshot_regions(snapshot)
    expected = (area_code.strip(), district_code.strip())
    if not regions or regions == {expected}:
        return
    found = ", ".join(sorted(f"{area}-{district}" for area, district in regions))
    raise DevPanelError(
        f"스냅샷 {snapshot_name}은 {found} 자료라 "
        f"{expected[0]}-{expected[1]}에 쓸 수 없습니다."
    )


@router.get("/place-sync/snapshots")
async def get_snapshots() -> dict[str, Any]:
    return {
        "snapshots": [path.name for path in place_snapshot.list_snapshots()],
        "data_dir": str(place_snapshot.DATA_DIR),
    }


@router.get("/place-sync/districts")
async def get_sync_districts() -> dict[str, Any]:
    """동기화 화면이 고를 수 있는 구와, 코드 입력을 검증할 사전.

    `loaded`는 자료가 있는 구다 — places에 행이 있거나 스냅샷 파일이 있는 구.
    파일만 있는 구도 넣는 이유는, 대조만 하고 아직 반영하지 않은 구가 화면에서
    사라지지 않게 하기 위해서다.

    `known`은 시군구 사전이다. 화면이 "구 추가" 입력을 이걸로 검증한다 — 없는
    코드로 동기화를 걸면 TourAPI가 빈 목록을 돌려주고, 그 결과는 "장소가 0건인
    구"와 구분되지 않는다.

    새 구를 목록에 저장해두지 않는다. 한 번 대조하면 스냅샷 파일이 생기고 반영하면
    places에 행이 생기므로, 자료가 곧 목록이 된다. 따로 저장하면 자료 없이 이름만
    남은 구가 목록에 쌓인다.
    """
    url, key = _require_supabase()

    async with status_client() as client:
        repository = SupabasePlaceRepository(
            supabase_url=url,
            secret_key=key,
            client=client,
            timeout_seconds=max(settings.external_api_timeout_seconds, 30.0),
        )
        summaries = await repository.get_place_summaries_by_district()

    loaded: dict[tuple[str, str], dict[str, Any]] = {}
    for summary in _as_summary_list(summaries.get("districts")):
        area_code = str(summary.get("area_code") or "")
        district_code = str(summary.get("district_code") or "")
        active_count = int(summary.get("active", 0) or 0)
        loaded[(area_code, district_code)] = {
            "area_code": area_code,
            "district_code": district_code,
            "district_name": find_district_name(area_code, district_code),
            "place_count": summary.get("total", 0),
            "active_count": active_count,
            "latest_snapshot": None,
            "list_call_estimate": _list_call_estimate(active_count),
        }

    for path in place_snapshot.list_snapshots():
        codes = place_snapshot.district_from_snapshot_name(path.name)
        if codes is None:
            continue
        entry = loaded.setdefault(
            codes,
            {
                "area_code": codes[0],
                "district_code": codes[1],
                "district_name": find_district_name(*codes),
                "place_count": 0,
                "active_count": 0,
                "latest_snapshot": None,
                "list_call_estimate": 1,
            },
        )
        # 최신순 목록이라 그 구에서 처음 만난 파일이 가장 최근 것이다.
        if entry["latest_snapshot"] is None:
            entry["latest_snapshot"] = path.name

    return {
        "loaded": [loaded[key] for key in sorted(loaded)],
        "known": list_districts(settings.place_sync_area_code),
    }


@router.post("/place-sync/reconcile")
async def post_reconcile(request: ReconcileRequest) -> dict[str, Any]:
    """목록을 1회 조회해 스냅샷을 남기고 이전 스냅샷과 대조한다. DB에는 쓰지 않는다.

    기준으로 쓸 스냅샷 파일이 없으면 places에서 그 구의 장소를 읽어 기준을 만든다.
    그러지 않으면 전량이 신규로 잡혀, 이미 DB에 있는 장소에 detailIntro2를 한 번씩
    더 쓴다(용산구 486건이면 하루 한도 1,000회의 절반이다).

    DB로 만든 기준은 파일로 남기지 않는다. 파일명 날짜가 오늘과 겹치면 이번 대조가
    쓰는 파일과 이름이 같아, 만들자마자 덮어써지고 기준이 사라진다. 무엇과
    비교했는지는 대조 결과 CSV의 baseline 칸에 `places@2026-08-21` 꼴로 남긴다.
    """
    api_key = _require_real_place_provider()
    area = request.area_code or settings.place_sync_area_code
    district = request.district_code or settings.place_sync_district_code
    now = datetime.now(place_snapshot.KST)

    async with create_external_client() as client:
        current = await place_snapshot.fetch_place_rows(
            client, api_key, area, district, now
        )

    snapshot_path = place_snapshot.DATA_DIR / place_snapshot.snapshot_file_name(
        area, district, now
    )
    baseline_path = (
        _snapshot_path(request.baseline)
        if request.baseline
        else place_snapshot.find_baseline(
            area_code=area, district_code=district, exclude=snapshot_path
        )
    )
    # 같은 날 다시 대조하면 덮어쓴다. 스냅샷은 git 추적 대상이라 덮어쓴 차이가
    # 그대로 diff로 남는다.
    place_snapshot.write_snapshot(current, snapshot_path)

    barrier_free_calls, barrier_free_checked = await _barrier_free_detail_count(
        api_key, area, district, current
    )

    if baseline_path is not None:
        baseline = place_snapshot.load_snapshot(baseline_path)
        baseline_label = baseline_path.name
        baseline_source = "file"
    else:
        baseline, baseline_source = await _baseline_from_database(area, district)
        baseline_label = f"places@{now:%Y-%m-%d}" if baseline else None

    if not baseline:
        return {
            "area_code": area,
            "district_code": district,
            "snapshot": snapshot_path.name,
            "snapshot_count": len(current),
            "baseline": None,
            "baseline_source": baseline_source,
            "skipped_columns": [],
            "counts": {"added": 0, "removed": 0, "updated": 0},
            "detail_content_ids": sorted(current),
            "detail_excluded_ids": [],
            "detail_backfill_ids": [],
            "detail_backfill_checked": True,
            "barrier_free_detail_count": barrier_free_calls,
            "barrier_free_checked": barrier_free_checked,
            "rows": [],
            "message": _NO_BASELINE_MESSAGES[baseline_source],
        }

    _require_snapshot_region(baseline, baseline_label or "", area, district)
    baseline_columns = list(next(iter(baseline.values()), {}).keys())
    compared = place_snapshot.comparable_columns(baseline_columns)
    # 조용히 빼면 "안 바뀌었다"와 "안 봤다"가 결과에서 구분되지 않는다.
    skipped = [
        column for column in place_snapshot.COMPARED_COLUMNS if column not in compared
    ]
    rows = place_snapshot.build_reconciliation_rows(baseline, current, compared)
    reconciliation_path = (
        place_snapshot.DATA_DIR
        / place_snapshot.reconciliation_file_name(area, district, now)
    )
    place_snapshot.write_reconciliation(
        rows, reconciliation_path, baseline_name=baseline_label or "", compared_at=now
    )
    detail_ids, excluded_ids = place_snapshot.select_detail_targets(rows)
    backfill_ids, backfill_checked = await _detail_backfill_ids(
        area, district, current, detail_ids
    )

    counts = {"added": 0, "removed": 0, "updated": 0}
    for row in rows:
        counts[str(row["change_type"])] += 1

    return {
        "area_code": area,
        "district_code": district,
        "snapshot": snapshot_path.name,
        "snapshot_count": len(current),
        "baseline": baseline_label,
        "baseline_source": baseline_source,
        "baseline_count": len(baseline),
        "reconciliation": reconciliation_path.name,
        "skipped_columns": skipped,
        "counts": counts,
        "detail_content_ids": sorted(detail_ids),
        "detail_excluded_ids": sorted(excluded_ids),
        "detail_backfill_ids": backfill_ids,
        "detail_backfill_checked": backfill_checked,
        "barrier_free_detail_count": barrier_free_calls,
        "barrier_free_checked": barrier_free_checked,
        "rows": rows,
    }


_NO_BASELINE_MESSAGES = {
    "none": (
        "기준 스냅샷도 없고 DB에도 이 구의 장소가 없어 대조를 건너뛰었습니다. "
        "전량이 신규로 취급됩니다."
    ),
    "unavailable": (
        "기준 스냅샷이 없고 SUPABASE_URL / SUPABASE_SECRET_KEY가 없어 DB를 "
        "확인하지 못했습니다. 전량이 신규로 취급됩니다 — DB에 이 구의 장소가 "
        "이미 있다면 상세조회를 그만큼 낭비하게 됩니다."
    ),
}


def _list_call_estimate(place_count: int) -> int:
    """대조 한 번이 쓸 목록 API 호출 수.

    `areaBasedList2`도 오퍼레이션 단위로 일일 한도가 걸려 있다(2026-08-07 소진).
    한 번에 1회라 작아 보이지만 구를 바꿔가며 누르면 그만큼 쌓이고, 지금은 화면에
    그 사실이 보이지 않는다.

    쪽수는 DB의 활성 장소 수로 어림한다 — 실제 기준은 TourAPI의 totalCount라
    불러봐야 알 수 있고, 그걸 알려고 부르면 세려던 호출을 먼저 쓰게 된다.
    """
    pages, remainder = divmod(max(place_count, 0), place_snapshot.LIST_PAGE_SIZE)
    return max(1, pages + (1 if remainder else 0))


async def _detail_backfill_ids(
    area_code: str,
    district_code: str,
    current: Mapping[str, Mapping[str, str]],
    detail_ids: frozenset[str],
) -> tuple[list[str], bool]:
    """이번 반영이 변경분과 **함께** 부를 장소들.

    동기화는 대조가 정한 변경분 외에 pending·failed 장소도 부른다
    (`PlaceSyncService._select_targets`). 그걸 빼고 계산하면 화면이 "상세조회
    15회"라고 해놓고 실제로는 157회를 쓴다 — 2026-08-21 종로구 대조가 그 상태였다.
    한도가 왜 줄었는지 아무도 설명할 수 없게 된다.

    목록에 없는 장소는 제외한다. 동기화는 이번 목록에 있는 장소만 훑으므로,
    비활성이라 목록에서 빠진 장소는 아무리 pending이어도 불리지 않는다.

    두 번째 반환값은 "확인했는가"다. 자격증명이 없어 못 본 것과 "보충할 게 없다"를
    같은 0으로 뭉개면, 화면이 예상 호출수를 확정된 값처럼 보여주게 된다.
    """
    url = settings.supabase_url.strip()
    key = settings.supabase_secret_key.strip()
    if not url or not key:
        return [], False

    async with status_client() as client:
        repository = SupabasePlaceRepository(
            supabase_url=url,
            secret_key=key,
            client=client,
            timeout_seconds=max(settings.external_api_timeout_seconds, 30.0),
        )
        pending = await repository.list_detail_backfill_ids(area_code, district_code)
    return [
        content_id
        for content_id in pending
        if content_id in current and content_id not in detail_ids
    ], True


async def _barrier_free_detail_count(
    api_key: str,
    area_code: str,
    district_code: str,
    current: Mapping[str, Mapping[str, str]],
) -> tuple[int, bool]:
    """이번 반영이 무장애 상세(detailWithTour2)를 몇 번 부를지.

    무장애 목록을 1회 불러 실제 대상을 센다. 목록을 부르지 않고 "아직 확인하지 않은
    장소 수"를 그대로 보여주면 4.6배 부풀려진다 — 종로구에서 755회로 표시되지만
    실제 상세 호출은 164회다. 무장애 레코드가 있는 장소가 19%뿐이기 때문이다.
    한도 옆에 붙는 숫자라 상한보다 실제에 가까운 값이 낫고, 목록은 구당 1회다.

    순서와 규칙을 동기화(`_sync_barrier_free`)와 똑같이 맞춘다 — 목록 → 등록된
    장소만 추림 → 확인 시각 조회 → TTL 판정. 조건을 따로 적으면 한쪽만 고쳤을 때
    화면이 실제와 다른 수를 보여주게 된다.

    두 번째 반환값은 "확인했는가"다. 자격증명이 없거나 목록 조회가 실패해 못 본
    것과 "부를 게 없다"를 같은 0으로 뭉개면, 화면이 0회를 확정된 값처럼 보여준다.
    """
    url = settings.supabase_url.strip()
    key = settings.supabase_secret_key.strip()
    if not url or not key:
        return 0, False

    candidates = barrier_free_candidate_ids(
        {
            content_id: str(row.get("content_type_id", "")).strip()
            for content_id, row in current.items()
        }
    )
    if not candidates:
        return 0, True

    # 목록 조회는 계측 대상 트래픽이다 — 상태 조회와 달리 실제로 한도를 쓴다.
    async with create_external_client() as client:
        provider = RealBarrierFreeProvider(
            api_key=api_key,
            client=client,
            timeout_seconds=settings.external_api_timeout_seconds,
        )
        try:
            listed = await provider.list_barrier_free_content_ids(
                area_code, district_code
            )
        except AppError:
            return 0, False

    registered = [content_id for content_id in candidates if content_id in listed]
    if not registered:
        return 0, True

    async with status_client() as client:
        repository = SupabasePlaceRepository(
            supabase_url=url,
            secret_key=key,
            client=client,
            timeout_seconds=max(settings.external_api_timeout_seconds, 30.0),
        )
        already = await repository.list_barrier_free_fetched_at(registered)
    return len(
        barrier_free_stale_ids(
            registered,
            already,
            now=datetime.now(UTC),
            ttl=timedelta(days=settings.place_sync_detail_ttl_days),
        )
    ), True


async def _baseline_from_database(
    area_code: str, district_code: str
) -> tuple[dict[str, dict[str, str]], str]:
    """places에서 그 구의 활성 장소를 읽어 기준 스냅샷을 만든다.

    Supabase 자격증명은 여기서만 필요하다 — 파일 기준이 있는 대조는 DB를 아예
    건드리지 않으므로, 위에서 미리 요구하면 되던 일이 안 되게 만든다. 자격증명이
    없으면 "DB에 없다"가 아니라 "확인하지 못했다"로 돌려준다. 두 가지를 같은
    결과로 뭉개면 화면이 낭비되는 상세조회의 이유를 설명할 수 없다.

    비활성 장소는 넣지 않는다. 목록에서 사라져서 비활성이 된 것이라, 넣으면 대조할
    때마다 계속 "삭제"로 잡힌다.
    """
    url = settings.supabase_url.strip()
    key = settings.supabase_secret_key.strip()
    if not url or not key:
        return {}, "unavailable"

    async with status_client() as client:
        repository = SupabasePlaceRepository(
            supabase_url=url,
            secret_key=key,
            client=client,
            timeout_seconds=max(settings.external_api_timeout_seconds, 30.0),
        )
        rows = await repository.list_region_place_rows(
            area_code, district_code, place_snapshot.SNAPSHOT_COLUMNS
        )
    baseline = place_snapshot.snapshot_rows_from_db(rows)
    return baseline, "database" if baseline else "none"


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
    _require_snapshot_region(
        place_snapshot.load_snapshot(snapshot_path),
        snapshot_path.name,
        area,
        district,
    )
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
                # 무장애 정보(KorWithService2)는 같은 인증키를 쓰지만 다른
                # 서비스라 호출도 따로 나간다. 상세조회와 같은 실행에서 함께
                # 채워야 "스냅샷 반영은 됐는데 무장애만 비어 있는" 상태가 남지
                # 않는다.
                barrier_free_provider=RealBarrierFreeProvider(
                    api_key=api_key,
                    client=client,
                    timeout_seconds=settings.external_api_timeout_seconds,
                ),
                page_size=settings.place_sync_page_size,
                detail_concurrency=settings.place_sync_detail_concurrency,
                detail_ttl_days=settings.place_sync_detail_ttl_days,
                retry_count=settings.external_api_retry_count,
            )
            result = await service.sync(
                area,
                district,
                dry_run=request.dry_run,
                details_limit=request.details_limit,
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
                # 상한이 걸린 실행은 비활성화를 건너뛴다. 화면이 그 사실을 알려면
                # job 파라미터에 남아 있어야 한다.
                "details_limit": request.details_limit,
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
