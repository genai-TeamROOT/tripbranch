"""개발자 Ops 패널 전용 API 라우터.

역할: 프론트 `/dev-ops` 화면이 쓰는 외부 API 호출량 집계와 장소 DB 상태를 낸다.
입력: GET /api/dev/api-usage, GET /api/dev/db-status 등.
출력: 관측용 JSON. 추천 판정에는 어떤 영향도 주지 않는다.
호출 시점: 개발자가 /dev-ops 화면을 열거나 폴링할 때.

이 라우터는 `APP_ENV=local`일 때만 main.py가 등록한다 — 배포 환경에서는 경로
자체가 존재하지 않는다(404). DB 쓰기 엔드포인트가 붙을 자리라 노출 범위를
설정이 아니라 등록 여부로 끊는다.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter

from app.config import settings
from app.errors import AppError
from app.observability.api_usage import get_usage_snapshot, reset_usage
from app.repositories.supabase_places import SupabasePlaceRepository

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
