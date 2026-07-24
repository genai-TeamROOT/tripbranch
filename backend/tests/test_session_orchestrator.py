"""session_orchestrator.ensure_current_context()의 GPS/날씨 최신화 회귀 테스트."""

from __future__ import annotations

import pytest

from app.domain.models import WeatherCondition
from app.providers.stub import FakeWeatherProvider
from app.services.interpret.session_orchestrator import ensure_current_context
from app.state.service import StateApplyRequest, apply
from app.state.store import InMemoryStateStore


@pytest.fixture
def store() -> InMemoryStateStore:
    return InMemoryStateStore()


def _existing_session(store: InMemoryStateStore) -> str:
    return apply(
        StateApplyRequest(session_id=None, intent="RECOMMEND", confirmed=True),
        store=store,
    ).session_id


@pytest.mark.asyncio
async def test_no_session_yet_skips_gps_seeding_even_with_device_location(
    store: InMemoryStateStore,
) -> None:
    """session_id=None인 최초 턴은 세션이 없어 GPS를 심을 수 없다(알려진 한계)."""
    weather = FakeWeatherProvider(WeatherCondition.GOOD)

    context = await ensure_current_context(None, "37.5788,126.9770", weather, store=store)

    assert context.session_exists is False
    assert context.api_context.gps_expired is True
    assert context.api_context.gps_location is None


@pytest.mark.asyncio
async def test_existing_session_gps_expired_seeds_gps_and_refreshes_weather(
    store: InMemoryStateStore,
) -> None:
    session_id = _existing_session(store)
    weather = FakeWeatherProvider(WeatherCondition.BAD)

    context = await ensure_current_context(
        session_id, "37.5788,126.9770", weather, store=store
    )

    assert context.api_context.gps_location == "37.5788,126.9770"
    assert context.api_context.gps_expired is False
    assert context.api_context.api_weather == "bad"
    assert context.api_context.weather_expired is False


@pytest.mark.asyncio
async def test_existing_session_without_device_location_stays_gps_missing(
    store: InMemoryStateStore,
) -> None:
    session_id = _existing_session(store)
    weather = FakeWeatherProvider(WeatherCondition.GOOD)

    context = await ensure_current_context(session_id, None, weather, store=store)

    assert context.api_context.gps_location is None
    assert context.api_context.gps_expired is True
    # GPS가 없으면 날씨 조회 자체를 시도하지 않는다.
    assert context.api_context.api_weather is None


@pytest.mark.asyncio
async def test_already_fresh_gps_and_weather_are_not_refetched(
    store: InMemoryStateStore,
) -> None:
    session_id = _existing_session(store)
    weather = FakeWeatherProvider(WeatherCondition.GOOD)

    first = await ensure_current_context(session_id, "37.5788,126.9770", weather, store=store)
    second = await ensure_current_context(session_id, "9.9999,9.9999", weather, store=store)

    # 두 번째 호출은 device_location이 달라도 이미 신선하므로 갱신하지 않는다.
    assert second.api_context.gps_location == first.api_context.gps_location == "37.5788,126.9770"
