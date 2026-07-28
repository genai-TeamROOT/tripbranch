"""실제 C ContextService가 조건에 따라 Tool을 조합하는 흐름을 검증한다."""

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.agent_context.factory import get_context_provider
from app.agent_context.schemas import AgentContextRequest, UserConditions
from app.agent_context.service import ContextService, ContextTools
from app.config import settings
from app.domain.models import PlaceCategoryFilter, WeatherForecastResult
from app.place_search_policy import DEFAULT_PLACE_SEARCH_RADIUS_KM
from app.providers.contracts import ProviderResult
from app.providers.geocoding import FakeGeocodingProvider
from app.providers.holiday import FakeHolidayProvider
from app.providers.protocols import WeatherProvider
from app.providers.stub import FakePlaceProvider, FakeWeatherProvider
from app.schemas import PlaceCandidate
from app.tools.holiday import GetHolidaysTool
from app.tools.nearby_place_details import NearbyPlaceDetailsTool
from app.tools.resolve_location import ResolveLocationTool
from app.tools.weather_forecast import GetWeatherForecastTool

KST = ZoneInfo("Asia/Seoul")


def _service(weather_provider: WeatherProvider | None = None) -> ContextService:
    place_provider = FakePlaceProvider()
    return ContextService(
        ContextTools(
            location=ResolveLocationTool(FakeGeocodingProvider()),
            places=NearbyPlaceDetailsTool(place_provider, place_provider),
            weather=GetWeatherForecastTool(weather_provider or FakeWeatherProvider()),
            holidays=GetHolidaysTool(FakeHolidayProvider()),
        ),
        candidate_limit=10,
        # FakeWeatherProvider도 현재 시각 기준 슬롯을 생성하므로 같은 기준을 쓴다.
        clock=lambda: datetime.now(KST),
    )


def _request(
    *,
    search_center: str | None = "경복궁",
    place_types: list[str] | None = None,
    place_tags: list[str] | None = None,
    max_travel_time: int | None = None,
    weather_intent: Literal["AVOID", "ENJOY", "IGNORE"] | None = None,
) -> AgentContextRequest:
    return AgentContextRequest(
        request_id="request-1",
        intent="RECOMMEND",
        conditions=UserConditions(
            search_center=search_center,
            place_types=place_types or [],
            place_tags=place_tags or [],
            max_travel_time=max_travel_time,
            weather_intent=weather_intent,
        ),
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
    assert response.metadata.rule_versions == {
        "category": "tour-category-v1",
        "search_radius": "walking-radius-v1",
        "tool_execution": "context-tool-plan-v1",
    }


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


@pytest.mark.asyncio
async def test_factory_uses_recommendation_candidate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "recommendation_candidate_limit", 1)

    async with httpx.AsyncClient() as client:
        response = await get_context_provider(client).fetch_context(
            _request(place_types=["cultural_facility", "restaurant"])
        )

    assert response.context is not None
    assert response.context.places is not None
    assert len(response.context.places.data or []) == 1


class _RecordingPlaceProvider(FakePlaceProvider):
    def __init__(self) -> None:
        self.search_radii: list[float] = []

    async def search_places(
        self,
        latitude: float,
        longitude: float,
        preferred_categories: list[str],
        search_radius_km: float,
        category_filter: PlaceCategoryFilter | None = None,
        limit: int = 20,
    ) -> ProviderResult[list[PlaceCandidate]]:
        self.search_radii.append(search_radius_km)
        return await super().search_places(
            latitude=latitude,
            longitude=longitude,
            preferred_categories=preferred_categories,
            search_radius_km=search_radius_km,
            category_filter=category_filter,
            limit=limit,
        )


class _RecordingWeatherProvider(FakeWeatherProvider):
    def __init__(self) -> None:
        super().__init__()
        self.forecast_calls = 0

    async def get_forecast_slots(
        self,
        latitude: float,
        longitude: float,
    ) -> ProviderResult[WeatherForecastResult]:
        self.forecast_calls += 1
        return await super().get_forecast_slots(latitude, longitude)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("max_travel_time", "expected_radius_km"),
    [
        (None, DEFAULT_PLACE_SEARCH_RADIUS_KM),
        (1, 0.3),
        (5, 0.35),
        (30, 2.1),
        (300, 20.0),
    ],
)
async def test_max_travel_time_controls_place_search_radius(
    max_travel_time: int | None,
    expected_radius_km: float,
) -> None:
    """최대 이동시간이 실제 장소 Tool Query의 검색 반경으로 전달되는지 검증한다."""

    place_provider = _RecordingPlaceProvider()
    service = ContextService(
        ContextTools(
            location=ResolveLocationTool(FakeGeocodingProvider()),
            places=NearbyPlaceDetailsTool(place_provider, place_provider),
            weather=GetWeatherForecastTool(FakeWeatherProvider()),
            holidays=GetHolidaysTool(FakeHolidayProvider()),
        ),
        candidate_limit=10,
        clock=lambda: datetime.now(KST),
    )

    response = await service.fetch_context(
        _request(
            place_types=["restaurant"],
            place_tags=["카페"],
            max_travel_time=max_travel_time,
        )
    )

    assert response.status == "success"
    # 이후 기록되는 1km 호출은 Fake 상세정보 구현의 내부 후보 재조회다.
    assert place_provider.search_radii[0] == pytest.approx(expected_radius_km)


@pytest.mark.asyncio
async def test_weather_ignore_returns_success_without_weather_context() -> None:
    weather_provider = _RecordingWeatherProvider()
    response = await _service(weather_provider).fetch_context(
        _request(
            place_types=["restaurant"],
            place_tags=["카페"],
            weather_intent="IGNORE",
        )
    )

    assert response.status == "success"
    assert response.context is not None
    assert response.context.weather is None
    assert weather_provider.forecast_calls == 0
    assert all(warning.code != "weather_missing" for warning in response.warnings)
