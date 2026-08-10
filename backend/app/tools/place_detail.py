"""장소 1건의 상세정보를 이름으로 조회하는 내부 Tool.

NearbyPlaceDetailsTool과 나누는 이유는 조회 대상이 다르기 때문이다 — 그쪽은
좌표 주변 후보 N건을 검색해 상세를 보강하고, 이쪽은 이미 특정된 장소 1건만 본다.

**PLACE_DETAILS_SOURCE와 무관하게 PlaceProvider(TourAPI)를 쓴다(D-054).** Supabase 상세
캐시는 동기화 대상이 operating_hours_raw/rest_date_raw뿐이라 overview·요금·주차·
편의시설이 전부 비어 있다(supabase_place_details.py의 _to_place_details 참고).
캐시를 둔 이유는 추천 후보 N건의 상세조회를 없애려는 것이었고, INFO는 장소 1건이라
그 근거가 적용되지 않는다. 여기서 캐시를 쓰면 질문 유형 대부분이 조용히 no_data로
떨어진다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.domain.models import PlaceDetails
from app.errors import AppError
from app.place_search_policy import (
    PLACE_SEARCH_LDONG_DISTRICT_CODE,
    PLACE_SEARCH_LDONG_REGION_CODE,
)
from app.providers.contracts import ProviderMetadata, ProviderStatus
from app.providers.protocols import PlaceProvider
from app.tools.contracts import ToolError, ToolStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlaceDetailQuery:
    """이미 해석된 장소명으로 상세정보를 조회한다.

    place_name은 ResolveLocationTool이 돌려준 resolved_name을 쓴다 — 사용자 발화
    그대로가 아니라 저장소·API 기준 명칭이라야 provider의 정확 일치 검색에 걸린다.
    """

    place_name: str
    region_code: str = PLACE_SEARCH_LDONG_REGION_CODE
    district_code: str = PLACE_SEARCH_LDONG_DISTRICT_CODE

    def __post_init__(self) -> None:
        if not self.place_name.strip():
            raise ValueError("place_name은 비어 있을 수 없습니다.")


@dataclass(frozen=True)
class PlaceDetailResult:
    status: ToolStatus
    details: PlaceDetails | None
    error: ToolError | None = None
    provider_metadata: tuple[ProviderMetadata, ...] = ()


class GetPlaceDetailTool:
    """장소명으로 상세정보 1건을 조회하고 실패를 ToolStatus로 정규화한다."""

    def __init__(self, place_provider: PlaceProvider) -> None:
        self._place_provider = place_provider

    async def execute(self, query: PlaceDetailQuery) -> PlaceDetailResult:
        try:
            result = await self._place_provider.find_details_by_name(
                query.place_name.strip(),
                region_code=query.region_code,
                district_code=query.district_code,
            )
        except AppError as exc:
            # 여기서 삼킨 오류는 200 응답으로 나가므로 로그가 유일한 흔적이다.
            logger.warning(
                "장소 상세 조회 실패 (place=%s, code=%s, provider=%s, details=%s)",
                query.place_name,
                exc.code,
                exc.provider,
                exc.details,
            )
            # provider는 이름이 정확히 일치하지 않으면 place_not_found(404)를 던진다.
            # 장애가 아니라 "그 장소를 못 찾았다"이므로 no_data로 낮춘다.
            if exc.status_code == 404:
                return PlaceDetailResult(
                    status=ToolStatus.NO_DATA,
                    details=None,
                    error=ToolError(
                        code="no_data",
                        message="장소 상세정보를 찾지 못했습니다.",
                        cause="place_not_found",
                        retryable=False,
                    ),
                )
            return PlaceDetailResult(
                status=ToolStatus.UNAVAILABLE,
                details=None,
                error=ToolError(
                    code="unavailable",
                    message="장소 상세정보를 가져오지 못했습니다.",
                    cause=(
                        "timeout" if exc.code == "provider_timeout" else "upstream_error"
                    ),
                    retryable=exc.retryable,
                ),
            )

        status = (
            ToolStatus.NO_DATA
            if result.metadata.status is ProviderStatus.NO_DATA
            else ToolStatus.SUCCESS
        )
        return PlaceDetailResult(
            status=status,
            details=result.data,
            error=None,
            provider_metadata=(result.metadata,),
        )


__all__ = [
    "GetPlaceDetailTool",
    "PlaceDetailQuery",
    "PlaceDetailResult",
]
