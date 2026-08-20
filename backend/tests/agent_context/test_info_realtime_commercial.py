"""INFO 실시간 카페 상권 경로의 위치·상권 대체 계약을 검증한다."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.agent_context.info_schemas import (
    InfoContextRequest,
    RealtimeCommercialInfoResult,
)
from app.agent_context.service import ContextService, ContextTools
from app.domain.models import GeocodeResult, LocalSearchPlace
from app.providers.contracts import ProviderSource, provider_result
from app.providers.holiday import FakeHolidayProvider
from app.providers.seoul_citydata import (
    FakeRealtimeCityDataProvider,
    FakeRealtimeCommercialProvider,
)
from app.providers.stub import FakePlaceProvider, FakeWeatherProvider
from app.tools.holiday import GetHolidaysTool
from app.tools.nearby_place_details import NearbyPlaceDetailsTool
from app.tools.realtime_citydata import GetRealtimeCityDataTool
from app.tools.realtime_commercial import GetRealtimeCommercialTool
from app.tools.resolve_location import ResolveLocationTool
from app.tools.weather_forecast import GetWeatherForecastTool


class _FixedGeocodingProvider:
    def __init__(self, *, latitude: float, longitude: float) -> None:
        self._latitude = latitude
        self._longitude = longitude

    async def geocode(self, location_query: str, *, use_alias: bool = True):
        del use_alias
        return provider_result(
            GeocodeResult(
                query=location_query,
                resolved_name=location_query,
                latitude=self._latitude,
                longitude=self._longitude,
            ),
            source=ProviderSource.FAKE_GEOCODING,
        )


class _CafeLocalSearchProvider:
    async def search_places_by_name(self, query: str, *, display: int = 5):
        del query, display
        return provider_result(
            (
                LocalSearchPlace(
                    name="노우즈 창덕",
                    address="서울 종로구 율곡로 99",
                    road_address="서울 종로구 율곡로 99",
                    category="음식점>카페>디저트카페",
                    latitude=37.5795,
                    longitude=126.9901,
                ),
            ),
            source=ProviderSource.FAKE_LOCAL_SEARCH,
        )


def _service(
    *, latitude: float, longitude: float, with_cafe_local_search: bool = False
) -> ContextService:
    place_provider = FakePlaceProvider()
    return ContextService(
        ContextTools(
            location=ResolveLocationTool(
                _FixedGeocodingProvider(latitude=latitude, longitude=longitude),
                local_search_provider=(
                    _CafeLocalSearchProvider() if with_cafe_local_search else None
                ),
            ),
            places=NearbyPlaceDetailsTool(place_provider, place_provider),
            weather=GetWeatherForecastTool(FakeWeatherProvider()),
            holidays=GetHolidaysTool(FakeHolidayProvider()),
            realtime_commercial=GetRealtimeCommercialTool(FakeRealtimeCommercialProvider()),
            realtime_citydata=GetRealtimeCityDataTool(FakeRealtimeCityDataProvider()),
        ),
        candidate_limit=10,
        clock=lambda: datetime.now(ZoneInfo("Asia/Seoul")),
    )


def _request(place_name: str = "용리단길 카페") -> InfoContextRequest:
    return InfoContextRequest(
        request_id="realtime-commercial",
        place_name=place_name,
        place_context="explicit",
        question_type="realtime_commercial",
        specific_question=f"{place_name} 지금 사람 많아?",
    )


@pytest.mark.asyncio
async def test_external_commercial_area_bypasses_jongno_recommendation_boundary() -> None:
    # 용리단길은 종로구 밖이다. 그러나 서울시 상권 제공 지역이므로 위치 단계에서
    # 종로구 정책으로 막히지 않고, 카페 업종의 대체 상권 결과가 나와야 한다.
    response = await _service(latitude=37.5311, longitude=126.9715).fetch_info_context(_request())

    assert response.status == "success"
    assert isinstance(response.result, RealtimeCommercialInfoResult)
    assert response.result.is_proxy is True
    assert response.result.area_name == "용리단길"
    assert response.result.commercial_level == "바쁜 시간대"
    assert response.metadata.provider_metadata[-1].source == "fake_seoul_citydata"


@pytest.mark.asyncio
async def test_location_outside_citydata_coverage_is_explicitly_unsupported() -> None:
    response = await _service(latitude=35.1796, longitude=129.0756).fetch_info_context(
        _request("부산 카페")
    )

    assert response.status == "unsupported"
    assert response.error is not None
    assert response.error.code == "realtime_commercial_unsupported_region"


@pytest.mark.asyncio
async def test_current_cafe_question_reroutes_after_category_resolution() -> None:
    response = await _service(
        latitude=37.5795,
        longitude=126.9901,
        with_cafe_local_search=True,
    ).fetch_info_context(
        InfoContextRequest(
            request_id="cafe-reroute",
            place_name="노우즈 창덕",
            place_context="explicit",
            question_type="concentration",
            specific_question="노우즈 창덕 지금 사람 많아?",
        )
    )

    assert response.status == "success"
    assert isinstance(response.result, RealtimeCommercialInfoResult)
    assert response.result.population_forecasts
