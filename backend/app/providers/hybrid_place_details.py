"""places 캐시와 detailCommon2를 합쳐 장소 상세정보 1건을 만드는 Provider.

역할: INFO 상세 질의(`GetPlaceDetailTool`)가 쓰는 이름 기반 상세조회를, 외부 호출
1회로 끝낸다.

출처 분담:
  places 캐시 — 장소명·주소·운영시간·휴무일·주차·요금·안내처·편의시설
  detailCommon2 — overview·homepage (+ 축제의 tel)

호출 수가 3회에서 1회로 준다. RealPlaceProvider.find_details_by_name()은
searchKeyword2로 이름을 맞추고(1) detailCommon2(2) + detailIntro2(3)를 부른다.
여기서는 이름 대조와 intro 값이 모두 저장소에 있어 detailCommon2만 남는다.

**D-054를 대체하는 경로다.** 그 결정은 "Supabase 캐시에는 INFO가 답할 데이터가
없다"가 전제였고, 당시 places의 동기화 대상은 operating_hours_raw/rest_date_raw
뿐이었다. D-056 이후 주차·요금이, D-060에서 안내처와 편의시설이 캐시에 들어와
question_type 전부를 덮게 됐다. overview/homepage만 detailCommon2에 남아 있어
그 1회를 부른다.
"""

from __future__ import annotations

from app.domain.models import PlaceCommonDetails, PlaceDetails, StoredPlaceDetail
from app.domain.operating_hours import normalize_operating_schedule
from app.errors import AppError
from app.providers.contracts import (
    ProviderResult,
    ProviderSource,
    ProviderStatus,
    provider_result,
)
from app.providers.protocols import PlaceCommonDetailsProvider
from app.repositories.protocols import (
    PlaceDetailsReadRepository,
    PlaceLocationRepository,
)

_PROVIDER_NAME = "hybrid_places"


class HybridPlaceDetailsProvider:
    """저장소에서 장소를 확정하고 detailCommon2로 서술 정보만 보탠다."""

    def __init__(
        self,
        location_repository: PlaceLocationRepository,
        details_repository: PlaceDetailsReadRepository,
        common_provider: PlaceCommonDetailsProvider,
    ) -> None:
        self._locations = location_repository
        self._details = details_repository
        self._common = common_provider

    async def find_details_by_name(
        self,
        name: str,
        region_code: str | None = None,
        district_code: str | None = None,
    ) -> ProviderResult[PlaceDetails]:
        """저장소에 정확히 일치하는 장소가 없으면 404를 던진다.

        region_code/district_code는 받기만 한다 — 저장소가 이미 종로구 한 지역만
        담고 있어 좁힐 대상이 없다. RealPlaceProvider와 시그니처를 맞춰 호출부가
        provider를 바꿔 끼울 수 있게 남긴다.
        """
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("name은 비어 있을 수 없습니다.")

        matches = await self._locations.find_active_places_by_name(normalized_name)
        if not matches:
            # RealPlaceProvider와 같은 코드·상태를 쓴다. GetPlaceDetailTool이 404를
            # no_data로 낮추므로 여기서 형태가 달라지면 장애로 잘못 보고된다.
            raise AppError(
                code="place_not_found",
                message=f"'{normalized_name}' 장소를 정확히 찾을 수 없어요.",
                status_code=404,
                details={"source": _PROVIDER_NAME},
            )

        content_id = matches[0].content_id
        rows = await self._details.get_active_place_details([content_id])
        row = rows.get(content_id)
        if row is None:
            # 이름 조회에는 걸렸는데 상세 행이 없다 — 두 조회 사이에 비활성화된
            # 경우다. 장애가 아니므로 같은 404 경로로 보낸다.
            raise AppError(
                code="place_not_found",
                message=f"'{normalized_name}' 장소를 정확히 찾을 수 없어요.",
                status_code=404,
                details={"source": _PROVIDER_NAME},
            )

        common_result = await self._common.get_common_details(content_id)
        return provider_result(
            _to_place_details(row, common_result.data),
            source=ProviderSource.TOUR_API_PLACE,
            status=ProviderStatus.SUCCESS,
            detail_fetched_at=row.detail_fetched_at,
        )


def _to_place_details(
    row: StoredPlaceDetail, common: PlaceCommonDetails
) -> PlaceDetails:
    return PlaceDetails(
        content_id=row.content_id,
        content_type_id=row.content_type_id,
        title=row.title,
        address=row.address,
        overview=common.overview,
        homepage=common.homepage,
        # 안내처가 먼저다. common의 tel은 축제(15)에만 채워지므로 대부분의 유형에서
        # 이 순서가 뒤바뀌어도 결과는 같지만, 축제는 저장소 쪽이 항상 비어 있어
        # 순서를 지켜야 tel이 살아난다.
        telephone=row.info_center_raw or common.telephone,
        operating_hours=row.operating_hours_raw,
        rest_date=row.rest_date_raw,
        raw_common={},
        # 저장소가 유형별 키를 한 컬럼으로 눌러 담아 원본 키를 복원할 수 없다.
        # 값은 아래 정규화 필드가 나르고, 소비 측도 raw_intro를 읽지 않는다(D-060).
        raw_intro={},
        provider=_PROVIDER_NAME,
        operating_schedule=normalize_operating_schedule(
            content_type_id=row.content_type_id,
            operating_hours=row.operating_hours_raw,
            rest_date=row.rest_date_raw,
        ),
        parking=row.parking_info_raw,
        parking_fee=row.parking_fee_raw,
        fee=row.use_fee_raw,
        baby_carriage=row.baby_carriage_raw,
        pet=row.pet_raw,
        credit_card=row.credit_card_raw,
        restroom=row.restroom_raw,
    )


__all__ = ["HybridPlaceDetailsProvider"]
