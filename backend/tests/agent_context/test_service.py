"""실제 C ContextService가 조건에 따라 Tool을 조합하는 흐름을 검증한다."""

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.agent_context.factory import get_context_provider
from app.agent_context.schemas import AgentContextRequest
from app.agent_context.service import ContextService, ContextTools
from app.providers.geocoding import FakeGeocodingProvider
from app.providers.holiday import FakeHolidayProvider
from app.providers.stub import FakePlaceProvider, FakeWeatherProvider
from app.tools.holiday import GetHolidaysTool
from app.tools.nearby_place_details import NearbyPlaceDetailsTool
from app.tools.resolve_location import ResolveLocationTool
from app.tools.weather_forecast import GetWeatherForecastTool

KST = ZoneInfo("Asia/Seoul")


def _service() -> ContextService:
    place_provider = FakePlaceProvider()
    return ContextService(
        ContextTools(
            location=ResolveLocationTool(FakeGeocodingProvider()),
            places=NearbyPlaceDetailsTool(place_provider, place_provider),
            weather=GetWeatherForecastTool(FakeWeatherProvider()),
            holidays=GetHolidaysTool(FakeHolidayProvider()),
        ),
        # FakeWeatherProvider도 현재 시각 기준 슬롯을 생성하므로 같은 기준을 쓴다.
        clock=lambda: datetime.now(KST),
    )


def _request(
    *,
    search_center: str | None = "경복궁",
    place_types: list[str] | None = None,
    place_tags: list[str] | None = None,
) -> AgentContextRequest:
    return AgentContextRequest(
        request_id="request-1",
        intent="RECOMMEND",
        conditions={
            "search_center": search_center,
            "place_types": place_types or [],
            "place_tags": place_tags or [],
        },
    )


@pytest.mark.asyncio
async def test_collects_real_context_with_fake_external_providers() -> None:
    response = await _service().fetch_context(
        _request(place_types=["restaurant"], place_tags=["카페"])
    )

    assert response.status == "success"
    assert response.context is not None
    assert response.context.location is not None
    assert response.context.weather is not None
    assert response.context.holidays is not None
    assert response.context.places is not None
    assert [item.place_id for item in response.context.places.data or []] == ["fake-cafe-1"]
    assert response.metadata.rule_versions == {"category": "tour-category-v1"}


@pytest.mark.asyncio
async def test_missing_location_requests_clarification_without_calling_tools() -> None:
    response = await _service().fetch_context(_request(search_center=None))

    assert response.status == "needs_clarification"
    assert response.clarification is not None
    assert response.clarification.code == "location_required"


@pytest.mark.asyncio
async def test_unsupported_category_stops_before_external_calls() -> None:
    response = await _service().fetch_context(_request(place_types=["unknown"]))

    assert response.status == "unsupported"
    assert response.error is not None
    assert response.error.code == "unsupported_category"


@pytest.mark.asyncio
async def test_multiple_categories_are_merged_without_duplicate_places() -> None:
    response = await _service().fetch_context(
        _request(place_types=["cultural_facility", "restaurant"])
    )

    assert response.context is not None
    assert response.context.places is not None
    assert [item.place_id for item in response.context.places.data or []] == [
        "fake-museum-1",
        "fake-cafe-1",
    ]


@pytest.mark.asyncio
async def test_factory_wires_fake_providers_into_common_context() -> None:
    """설정 기반 Factory도 수동 조립과 동일한 A–C 응답 계약을 사용한다."""

    async with httpx.AsyncClient() as client:
        response = await get_context_provider(client).fetch_context(
            _request(place_types=["restaurant"], place_tags=["카페"])
        )

    assert response.status == "success"
    assert response.context is not None
    assert response.context.places is not None
    assert [item.place_id for item in response.context.places.data or []] == [
        "fake-cafe-1"
    ]
    assert {
        metadata.source for metadata in response.metadata.provider_metadata
    } == {
        "fake_geocoding",
        "fake_weather",
        "fake_place",
        "fake_holiday",
    }
