"""미리 구축된 Supabase places 테이블에서 장소 상세·운영정보를 읽는 Provider.

역할: 후보별 TourAPI 상세 API 호출을 대체한다. 장소 후보 "검색"은 여전히
TourAPI(RealPlaceProvider)가 담당하고, 이 Provider는 검색으로 얻은 content_id의
상세·운영정보만 저장소에서 조회한다.

운영시간은 DB의 operating_schedule JSON을 읽지 않고 원문(operating_hours_raw,
rest_date_raw)을 normalize_operating_schedule()로 다시 정규화한다. TourAPI 경로와
같은 함수를 쓰므로 두 경로의 결과가 구조적으로 일치하고, 파서가 개선되면 재동기화
없이 즉시 반영된다. (DB의 operating_schedule 컬럼은 동기화 배치가 계속 채우지만
이 읽기 경로에서는 사용하지 않는다.)

입력: content_id 목록.
출력: content_id를 키로 하는 PlaceDetails dict.
호출 시점: PLACE_DETAILS_SOURCE=supabase일 때 NearbyPlaceDetailsTool이 호출한다.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from app.domain.models import PlaceDetails, StoredPlaceDetail
from app.domain.operating_hours import normalize_operating_schedule
from app.providers.contracts import (
    ProviderResult,
    ProviderSource,
    ProviderStatus,
    provider_result,
)
from app.repositories.protocols import PlaceRepository

_PROVIDER_NAME = "supabase_places"


class SupabasePlaceDetailsProvider:
    """PlaceDetailsProvider와 BatchPlaceDetailsProvider를 함께 구현한다."""

    def __init__(self, repository: PlaceRepository) -> None:
        self._repository = repository

    async def get_details_batch(
        self,
        content_ids: list[str],
    ) -> ProviderResult[dict[str, PlaceDetails]]:
        """여러 content_id의 상세정보를 한 번의 DB 조회로 가져온다."""
        if not content_ids:
            return provider_result(
                {},
                source=ProviderSource.SUPABASE_PLACES,
                status=ProviderStatus.NO_DATA,
            )

        # 중복 content_id가 있어도 조회는 한 번만 하도록 정리한다.
        unique_ids = list(dict.fromkeys(content_ids))
        rows = await self._repository.get_active_place_details(unique_ids)

        details = {
            content_id: _to_place_details(row) for content_id, row in rows.items()
        }
        return provider_result(
            details,
            source=ProviderSource.SUPABASE_PLACES,
            status=_batch_status(requested=len(unique_ids), found=len(details)),
            detail_fetched_at=_latest_detail_fetched_at(rows.values()),
        )

    async def get_details(
        self, content_id: str, content_type_id: str
    ) -> ProviderResult[PlaceDetails]:
        """단건 조회. 기존 PlaceDetailsProvider 계약 호환을 위해 유지한다.

        content_type_id는 저장소 행의 값을 우선하므로 조회 조건으로 쓰지 않는다.
        """
        rows = await self._repository.get_active_place_details([content_id])
        row = rows.get(content_id)
        if row is None:
            return provider_result(
                _empty_details(content_id, content_type_id),
                source=ProviderSource.SUPABASE_PLACES,
                status=ProviderStatus.NO_DATA,
            )
        return provider_result(
            _to_place_details(row),
            source=ProviderSource.SUPABASE_PLACES,
            status=ProviderStatus.SUCCESS,
            detail_fetched_at=row.detail_fetched_at,
        )


def _batch_status(*, requested: int, found: int) -> ProviderStatus:
    if found == 0:
        return ProviderStatus.NO_DATA
    if found < requested:
        return ProviderStatus.PARTIAL
    return ProviderStatus.SUCCESS


def _latest_detail_fetched_at(
    rows: Iterable[StoredPlaceDetail],
) -> datetime | None:
    """배치 안에서 가장 최근 동기화 시각을 대표값으로 사용한다.

    행마다 동기화 시각이 다르므로 Provider 단위 metadata로는 대표값만 담는다.
    """
    values = [row.detail_fetched_at for row in rows if row.detail_fetched_at is not None]
    return max(values) if values else None


def _to_place_details(row: StoredPlaceDetail) -> PlaceDetails:
    """저장소 행을 기존 PlaceDetails 계약으로 변환한다."""
    return PlaceDetails(
        content_id=row.content_id,
        content_type_id=row.content_type_id,
        title=row.title,
        address=row.address,
        # overview/homepage/telephone은 동기화 대상이 아니라 저장소에 없다.
        overview=None,
        homepage=None,
        telephone=None,
        operating_hours=row.operating_hours_raw,
        rest_date=row.rest_date_raw,
        raw_common={},
        raw_intro={},
        provider=_PROVIDER_NAME,
        operating_schedule=normalize_operating_schedule(
            content_type_id=row.content_type_id,
            operating_hours=row.operating_hours_raw,
            rest_date=row.rest_date_raw,
        ),
    )


def _empty_details(content_id: str, content_type_id: str) -> PlaceDetails:
    return PlaceDetails(
        content_id=content_id,
        content_type_id=content_type_id,
        title=None,
        address=None,
        overview=None,
        homepage=None,
        telephone=None,
        operating_hours=None,
        rest_date=None,
        raw_common={},
        raw_intro={},
        provider=_PROVIDER_NAME,
    )


__all__ = ["SupabasePlaceDetailsProvider"]
