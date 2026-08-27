"""INFO 응답의 장소 카드(PlaceCard) 계약 테스트.

카드는 질문 유형과 무관하게 채우고 status 판정에는 관여하지 않는다. 두 값이 섞이면
"주차 정보는 없어요" 같은 안내의 근거가 사라진다.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.agent_context.info_schemas import (
    InfoContextRequest,
    InfoContextResponse,
    InfoQuestionType,
    PlaceInfoResult,
)
from app.agent_context.service import ContextService, ContextTools
from app.domain.models import PlaceDetails
from app.providers.concentration import FakeConcentrationProvider
from app.providers.contracts import (
    ProviderResult,
    ProviderSource,
    ProviderStatus,
    provider_result,
)
from app.providers.geocoding import FakeGeocodingProvider
from app.providers.holiday import FakeHolidayProvider
from app.providers.stub import FakePlaceProvider, FakeWeatherProvider
from app.repositories.fake_places import FakePlaceLocationRepository
from app.tools.concentration import GetConcentrationTool
from app.tools.holiday import GetHolidaysTool
from app.tools.nearby_place_details import NearbyPlaceDetailsTool
from app.tools.place_detail import GetPlaceDetailTool
from app.tools.resolve_location import ResolveLocationTool
from app.tools.weather_forecast import GetWeatherForecastTool

KST = ZoneInfo("Asia/Seoul")


def _details(**overrides: object) -> PlaceDetails:
    base: dict[str, object] = {
        "content_id": "126508",
        "content_type_id": "12",
        "title": "경복궁",
        "address": "서울특별시 종로구 사직로 161",
        "overview": None,
        "homepage": None,
        "telephone": None,
        "operating_hours": None,
        "rest_date": None,
        "raw_common": {},
        "raw_intro": {},
        "provider": "hybrid_places",
        "thumbnail_url": "https://example.test/thumb.jpg",
    }
    base.update(overrides)
    return PlaceDetails(**base)  # type: ignore[arg-type]


class _Provider(FakePlaceProvider):
    def __init__(self, details: PlaceDetails) -> None:
        self._details = details

    async def find_details_by_name(
        self,
        name: str,
        region_code: str | None = None,
        district_code: str | None = None,
    ) -> ProviderResult[PlaceDetails]:
        return provider_result(
            self._details,
            source=ProviderSource.TOUR_API_PLACE,
            status=ProviderStatus.SUCCESS,
        )


def _service(details: PlaceDetails) -> ContextService:
    search_provider = FakePlaceProvider()
    return ContextService(
        ContextTools(
            location=ResolveLocationTool(
                FakeGeocodingProvider(),
                place_repository=FakePlaceLocationRepository(),
            ),
            places=NearbyPlaceDetailsTool(search_provider, search_provider),
            weather=GetWeatherForecastTool(FakeWeatherProvider()),
            holidays=GetHolidaysTool(FakeHolidayProvider()),
            concentration=GetConcentrationTool(FakeConcentrationProvider()),
            place_detail=GetPlaceDetailTool(_Provider(details)),
        ),
        candidate_limit=10,
        clock=lambda: datetime.now(KST),
    )


def _request(question_type: InfoQuestionType) -> InfoContextRequest:
    return InfoContextRequest(
        request_id="request-info-card-1",
        place_name="경복궁",
        place_context="explicit",
        question_type=question_type,
    )


def _result(response: InfoContextResponse) -> PlaceInfoResult:
    assert isinstance(response.result, PlaceInfoResult)
    return response.result


@pytest.mark.asyncio
async def test_질문_유형과_무관하게_전체를_채운다() -> None:
    """주차를 물어도 카드에는 운영시간·요금·개요가 함께 담긴다."""
    service = _service(
        _details(
            parking="가능 (240대)",
            fee="어른 3,000원",
            overview="조선왕조 제일의 법궁이다.",
            operating_hours="09:00~18:00",
        )
    )

    response = await service.fetch_info_context(_request("parking"))

    card = _result(response).place_card
    assert card is not None
    assert card.parking == "가능 (240대)"
    assert card.fee == "어른 3,000원"
    assert card.overview == "조선왕조 제일의 법궁이다."
    assert card.operating_hours == "09:00~18:00"
    assert card.place_name == "경복궁"


@pytest.mark.asyncio
async def test_카드가_차도_no_data_판정은_그대로다() -> None:
    """이 테스트가 이 설계의 전부다.

    카드를 fields에 합치면 overview가 거의 항상 있어 fields가 비지 않고,
    "경복궁 요금 정보는 없어요"가 영영 나오지 않는다.

    질문 유형이 parking이 아니라 fee인 이유는 D-099다 — 주차는 상세정보에
    parking/parking_fee가 없으면 주변 공영주차장 현황으로 대체하므로
    PlaceInfoResult로 돌아오지 않는다(그 경로는
    test_info_realtime_commercial.py가 본다). 여기서 보려는 것은 대체 경로가
    없는 질문 유형에서 카드와 fields가 서로 다른 값으로 남는지다.
    """
    service = _service(
        _details(overview="조선왕조 제일의 법궁이다.", operating_hours="09:00~18:00")
    )

    response = await service.fetch_info_context(_request("fee"))

    result = _result(response)
    # 물어본 요금 정보가 없으므로 no_data다.
    assert response.status == "no_data"
    assert result.status == "no_data"
    assert result.fields == {}
    # 그래도 카드는 채워져 펼칠 수 있다.
    assert result.place_card is not None
    assert result.place_card.overview == "조선왕조 제일의 법궁이다."


@pytest.mark.asyncio
async def test_fields와_카드가_같은_정제_결과를_쓴다() -> None:
    """HTML 정리가 두 곳에서 갈리면 같은 값이 다르게 보인다."""
    service = _service(_details(parking="가능<br>요금 (30분 1,500원)"))

    response = await service.fetch_info_context(_request("parking"))

    result = _result(response)
    assert result.fields["parking"] == "가능 요금 (30분 1,500원)"
    assert result.place_card is not None
    assert result.place_card.parking == result.fields["parking"]


@pytest.mark.asyncio
async def test_없는_값은_None으로_두고_문구를_지어내지_않는다() -> None:
    service = _service(_details(parking="가능"))

    response = await service.fetch_info_context(_request("parking"))

    card = _result(response).place_card
    assert card is not None
    assert card.overview is None
    assert card.homepage is None
    assert card.restroom is None


@pytest.mark.asyncio
async def test_편의시설은_네_항목으로_따로_담는다() -> None:
    """하나로 합치면 어느 항목이 빠졌는지 구분되지 않는다."""
    service = _service(
        _details(baby_carriage="없음", credit_card="가능", restroom="있음")
    )

    response = await service.fetch_info_context(_request("facility"))

    card = _result(response).place_card
    assert card is not None
    assert card.baby_carriage == "없음"
    assert card.credit_card == "가능"
    assert card.restroom == "있음"
    # 값이 없는 항목은 None이며, "없다고 답한" 없음과 구분된다.
    assert card.pet is None


@pytest.mark.asyncio
async def test_썸네일이_없으면_None이다() -> None:
    """실측 844건 중 169건(20%)이 여기 해당한다. 소비 측이 이미지 영역을 숨긴다."""
    service = _service(_details(parking="가능", thumbnail_url=None))

    response = await service.fetch_info_context(_request("parking"))

    card = _result(response).place_card
    assert card is not None
    assert card.thumbnail_url is None


@pytest.mark.asyncio
async def test_상세조회를_하지_않는_경로는_카드가_없다() -> None:
    """location_info는 상세 조회 전에 응답한다 — 카드를 지어내지 않는다."""
    service = _service(_details(parking="가능"))

    response = await service.fetch_info_context(_request("location_info"))

    assert _result(response).place_card is None
