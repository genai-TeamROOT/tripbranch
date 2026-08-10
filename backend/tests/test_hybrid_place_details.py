"""places 캐시 + detailCommon2 하이브리드 상세조회 Provider 테스트."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from app.agent_context.info_field_rules import extract_info_fields
from app.domain.models import (
    PlaceCommonDetails,
    StoredPlaceDetail,
    StoredPlaceLocation,
)
from app.errors import AppError
from app.providers.contracts import (
    ProviderResult,
    ProviderSource,
    ProviderStatus,
    provider_result,
)
from app.providers.hybrid_place_details import HybridPlaceDetailsProvider
from app.tools.contracts import ToolStatus
from app.tools.place_detail import GetPlaceDetailTool, PlaceDetailQuery

_FETCHED_AT = datetime(2026, 8, 10, 3, 0, tzinfo=UTC)


def _location(content_id: str = "126508") -> StoredPlaceLocation:
    return StoredPlaceLocation(
        content_id=content_id,
        title="경복궁",
        address="서울특별시 종로구 사직로 161",
        latitude=37.5788,
        longitude=126.9770,
    )


def _row(**overrides: object) -> StoredPlaceDetail:
    base: dict[str, object] = {
        "content_id": "126508",
        "content_type_id": "12",
        "title": "경복궁",
        "address": "서울특별시 종로구 사직로 161",
        "operating_hours_raw": "09:00~18:00",
        "rest_date_raw": "매주 화요일",
        "detail_fetch_status": "success",
        "detail_fetched_at": _FETCHED_AT,
        "source_modified_at": None,
        "lcls_systm1": "HS",
        "lcls_systm2": "HS01",
        "lcls_systm3": "HS010100",
        "parking_info_raw": "가능 (승용차 240대 / 버스 50대)",
        "parking_fee_raw": None,
        "use_fee_raw": "어른 3,000원",
        "info_center_raw": "02-3700-3900",
        "baby_carriage_raw": "없음",
        "pet_raw": "불가",
        "credit_card_raw": "가능",
        "restroom_raw": "있음",
        "first_image_url": "https://example.test/first.jpg",
        "thumbnail_url": "https://example.test/thumb.jpg",
    }
    base.update(overrides)
    return StoredPlaceDetail(**base)  # type: ignore[arg-type]


class _Locations:
    def __init__(self, matches: tuple[StoredPlaceLocation, ...]) -> None:
        self._matches = matches
        self.queries: list[str] = []

    async def find_active_places_by_name(
        self, name: str
    ) -> tuple[StoredPlaceLocation, ...]:
        self.queries.append(name)
        return self._matches


class _Details:
    def __init__(self, rows: dict[str, StoredPlaceDetail]) -> None:
        self._rows = rows

    async def get_active_place_details(
        self, content_ids: Sequence[str]
    ) -> dict[str, StoredPlaceDetail]:
        return {
            content_id: self._rows[content_id]
            for content_id in content_ids
            if content_id in self._rows
        }


class _Common:
    def __init__(
        self,
        overview: str | None = "조선왕조 제일의 법궁이다.",
        homepage: str | None = "https://royal.khs.go.kr/",
        telephone: str | None = None,
    ) -> None:
        self._details = PlaceCommonDetails(
            content_id="126508",
            overview=overview,
            homepage=homepage,
            telephone=telephone,
        )
        self.calls: list[str] = []

    async def get_common_details(
        self, content_id: str
    ) -> ProviderResult[PlaceCommonDetails]:
        self.calls.append(content_id)
        return provider_result(
            self._details,
            source=ProviderSource.TOUR_API_PLACE,
            status=ProviderStatus.SUCCESS,
        )


def _provider(
    *,
    matches: tuple[StoredPlaceLocation, ...] = (_location(),),
    rows: dict[str, StoredPlaceDetail] | None = None,
    common: _Common | None = None,
) -> tuple[HybridPlaceDetailsProvider, _Common]:
    common_provider = common or _Common()
    provider = HybridPlaceDetailsProvider(
        location_repository=_Locations(matches),
        details_repository=_Details(rows if rows is not None else {"126508": _row()}),
        common_provider=common_provider,
    )
    return provider, common_provider


@pytest.mark.asyncio
async def test_외부_호출은_detailCommon2_한_번뿐이다() -> None:
    """이 provider의 존재 이유다.

    TourAPI 직접 경로는 searchKeyword2 + detailCommon2 + detailIntro2로 3회를 쓴다.
    이름 대조와 intro 값이 모두 저장소에 있어 여기서는 1회로 끝난다.
    """
    provider, common = _provider()

    await provider.find_details_by_name("경복궁")

    assert common.calls == ["126508"]


@pytest.mark.asyncio
async def test_캐시와_common을_합쳐_채운다() -> None:
    provider, _ = _provider()

    details = (await provider.find_details_by_name("경복궁")).data

    # 저장소에서 온 값
    assert details.title == "경복궁"
    assert details.address == "서울특별시 종로구 사직로 161"
    assert details.operating_hours == "09:00~18:00"
    assert details.parking == "가능 (승용차 240대 / 버스 50대)"
    assert details.fee == "어른 3,000원"
    assert details.telephone == "02-3700-3900"
    # detailCommon2에서 온 값
    assert details.overview == "조선왕조 제일의 법궁이다."
    assert details.homepage == "https://royal.khs.go.kr/"


@pytest.mark.asyncio
async def test_운영시간을_원문에서_다시_정규화한다() -> None:
    provider, _ = _provider()

    details = (await provider.find_details_by_name("경복궁")).data

    assert details.operating_schedule is not None
    assert details.operating_schedule.cleaned_operating_hours == "09:00~18:00"


@pytest.mark.asyncio
async def test_안내처가_common의_tel보다_우선한다() -> None:
    """대부분의 유형에서 tel은 비어 있지만, 둘 다 있으면 안내처가 정확하다."""
    provider, _ = _provider(common=_Common(telephone="02-000-0000"))

    details = (await provider.find_details_by_name("경복궁")).data

    assert details.telephone == "02-3700-3900"


@pytest.mark.asyncio
async def test_안내처가_비면_common의_tel로_떨어진다() -> None:
    """축제(15)가 이 경로다 — infocenter 계열이 없고 tel만 채워진다."""
    provider, _ = _provider(
        rows={"126508": _row(info_center_raw=None)},
        common=_Common(telephone="02-3210-1645"),
    )

    details = (await provider.find_details_by_name("경복궁")).data

    assert details.telephone == "02-3210-1645"


@pytest.mark.asyncio
async def test_둘_다_없으면_전화번호는_None이다() -> None:
    """info_center_raw 적재 전 현재 상태다. 없는 값을 지어내지 않는다."""
    provider, _ = _provider(
        rows={"126508": _row(info_center_raw=None)}, common=_Common()
    )

    details = (await provider.find_details_by_name("경복궁")).data

    assert details.telephone is None


@pytest.mark.asyncio
async def test_주차_요금이_소비_측까지_도달한다() -> None:
    provider, _ = _provider()

    details = (await provider.find_details_by_name("경복궁")).data

    assert extract_info_fields("parking", details) == {
        "parking": "가능 (승용차 240대 / 버스 50대)"
    }
    assert extract_info_fields("fee", details) == {"fee": "어른 3,000원"}
    assert extract_info_fields("general_info", details) == {
        "overview": "조선왕조 제일의 법궁이다.",
        "homepage": "https://royal.khs.go.kr/",
    }


@pytest.mark.asyncio
async def test_편의시설도_캐시에서_답한다() -> None:
    """D-060에서 chk* 컬럼을 추가해 tour_api와 답할 수 있는 질문이 같아졌다.

    이게 성립해야 INFO 출처를 고르는 설정을 없앤 근거가 유지된다.
    """
    provider, _ = _provider()

    details = (await provider.find_details_by_name("경복궁")).data

    assert extract_info_fields("facility", details) == {
        "baby_carriage": "없음",
        "pet": "불가",
        "credit_card": "가능",
        "restroom": "있음",
    }


@pytest.mark.asyncio
async def test_썸네일이_카드용으로_실린다() -> None:
    provider, _ = _provider()

    details = (await provider.find_details_by_name("경복궁")).data

    assert details.thumbnail_url == "https://example.test/thumb.jpg"


@pytest.mark.asyncio
async def test_이름이_없으면_404를_던진다() -> None:
    """RealPlaceProvider와 같은 코드·상태여야 Tool이 no_data로 낮춘다."""
    provider, _ = _provider(matches=())

    with pytest.raises(AppError) as exc_info:
        await provider.find_details_by_name("없는장소")

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "place_not_found"


@pytest.mark.asyncio
async def test_상세_행이_없어도_404다() -> None:
    """이름 조회와 상세 조회 사이에 비활성화된 경우다. 장애가 아니다."""
    provider, _ = _provider(rows={})

    with pytest.raises(AppError) as exc_info:
        await provider.find_details_by_name("경복궁")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_Tool이_404를_no_data로_낮춘다() -> None:
    """계약이 실제로 맞물리는지 Tool까지 태워 확인한다."""
    provider, _ = _provider(matches=())
    tool = GetPlaceDetailTool(provider)

    result = await tool.execute(PlaceDetailQuery(place_name="없는장소"))

    assert result.status is ToolStatus.NO_DATA
    assert result.details is None


@pytest.mark.asyncio
async def test_Tool이_상세를_그대로_전달한다() -> None:
    provider, _ = _provider()
    tool = GetPlaceDetailTool(provider)

    result = await tool.execute(PlaceDetailQuery(place_name="경복궁"))

    assert result.status is ToolStatus.SUCCESS
    assert result.details is not None
    assert result.details.parking == "가능 (승용차 240대 / 버스 50대)"
