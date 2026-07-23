"""TourAPI 지역 장소를 Supabase에 동기화하는 명령행 진입점."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from dataclasses import asdict

import httpx

from app.config import Settings
from app.providers.real_place import RealPlaceProvider
from app.repositories.supabase_places import SupabasePlaceRepository
from app.services.place_sync import PlaceSyncService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="지역별 TourAPI 장소 동기화")
    parser.add_argument("--area-code", help="TourAPI 광역 행정구역 코드")
    parser.add_argument("--district-code", help="TourAPI 시·군·구 코드")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="외부 API와 DB 조회만 수행하고 DB를 수정하지 않음",
    )
    parser.add_argument(
        "--details-limit",
        type=int,
        help="상세조회 대상을 지정한 건수로 제한하며 비활성화도 수행하지 않음",
    )
    parser.add_argument(
        "--force-details",
        action="store_true",
        help="수정 시각과 TTL에 관계없이 상세정보를 다시 조회",
    )
    return parser


async def run(args: argparse.Namespace, settings: Settings) -> int:
    area_code = args.area_code or settings.place_sync_area_code
    district_code = args.district_code or settings.place_sync_district_code
    if not settings.tour_api_service_key:
        raise ValueError("TOUR_API_SERVICE_KEY가 필요합니다.")
    if not settings.supabase_url:
        raise ValueError("SUPABASE_URL이 필요합니다.")
    if not settings.supabase_secret_key:
        raise ValueError("SUPABASE_SECRET_KEY가 필요합니다.")

    async with httpx.AsyncClient() as client:
        provider = RealPlaceProvider(
            api_key=settings.tour_api_service_key,
            client=client,
            timeout_seconds=settings.external_api_timeout_seconds,
        )
        repository = SupabasePlaceRepository(
            supabase_url=settings.supabase_url,
            secret_key=settings.supabase_secret_key,
            client=client,
            timeout_seconds=settings.external_api_timeout_seconds,
        )
        service = PlaceSyncService(
            provider,
            repository,
            page_size=settings.place_sync_page_size,
            detail_concurrency=settings.place_sync_detail_concurrency,
            detail_ttl_days=settings.place_sync_detail_ttl_days,
            retry_count=settings.external_api_retry_count,
        )
        result = await service.sync(
            area_code,
            district_code,
            dry_run=args.dry_run,
            details_limit=args.details_limit,
            force_details=args.force_details,
        )

    print(json.dumps(asdict(result), ensure_ascii=False, default=str, indent=2))
    return 0 if result.status == "success" else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(run(args, Settings()))


if __name__ == "__main__":
    raise SystemExit(main())
