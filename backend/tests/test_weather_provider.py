from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from app.domain.models import WeatherCondition
from app.errors import AppError
from app.providers.weather import (
    RealWeatherProvider,
    map_items_to_forecast_slots,
    map_sky_pty_to_condition,
    resolve_base_date_time,
)


def test_resolve_base_date_time_before_45_uses_previous_hour() -> None:
    now = datetime(2026, 7, 22, 10, 20)
    assert resolve_base_date_time(now) == ("20260722", "0930")


def test_resolve_base_date_time_after_45_uses_current_hour() -> None:
    now = datetime(2026, 7, 22, 10, 50)
    assert resolve_base_date_time(now) == ("20260722", "1030")


def test_resolve_base_date_time_crosses_midnight() -> None:
    now = datetime(2026, 7, 22, 0, 10)
    assert resolve_base_date_time(now) == ("20260721", "2330")


@pytest.mark.parametrize(
    ("sky", "pty", "expected"),
    [
        ("1", "0", WeatherCondition.GOOD),
        ("3", "0", WeatherCondition.NEUTRAL),
        ("4", "0", WeatherCondition.NEUTRAL),
        ("1", "1", WeatherCondition.BAD),
        ("1", "3", WeatherCondition.BAD),
    ],
)
def test_map_sky_pty_to_condition(sky: str, pty: str, expected: WeatherCondition) -> None:
    assert map_sky_pty_to_condition(sky, pty) == expected


def test_map_sky_pty_to_condition_missing_data_raises_weather_no_data() -> None:
    with pytest.raises(AppError) as exc_info:
        map_sky_pty_to_condition(None, None)
    assert exc_info.value.code == "weather_no_data"


def _fcst_item(category: str, fcst_time: str, value: str) -> dict:
    return {
        "baseDate": "20260722",
        "baseTime": "1030",
        "category": category,
        "fcstDate": "20260722",
        "fcstTime": fcst_time,
        "fcstValue": value,
        "nx": 60,
        "ny": 127,
    }


def test_maps_items_to_time_aware_forecast_slots() -> None:
    slots = map_items_to_forecast_slots(
        [
            _fcst_item("SKY", "1100", "1"),
            _fcst_item("PTY", "1100", "0"),
            _fcst_item("SKY", "1200", "4"),
            _fcst_item("PTY", "1200", "1"),
        ]
    )

    assert [slot.forecast_for.hour for slot in slots] == [11, 12]
    assert slots[0].forecast_for.tzinfo is not None
    assert slots[0].condition is WeatherCondition.GOOD
    assert slots[1].condition is WeatherCondition.BAD
    assert slots[1].sky_code == "4"
    assert slots[1].precipitation_type == "1"


@pytest.mark.asyncio
async def test_real_weather_provider_picks_earliest_forecast_slot() -> None:
    items = [
        _fcst_item("SKY", "1300", "4"),
        _fcst_item("SKY", "1100", "1"),
        _fcst_item("PTY", "1300", "1"),
        _fcst_item("PTY", "1100", "0"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "response": {
                    "header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
                    "body": {"dataType": "JSON", "items": {"item": items}},
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = RealWeatherProvider(api_key="dummy", client=client)

    condition = await provider.get_current_condition(37.5636, 126.9976)

    assert condition == WeatherCondition.GOOD
    await client.aclose()


@pytest.mark.asyncio
async def test_real_weather_provider_returns_all_forecast_slots() -> None:
    items = [
        _fcst_item("SKY", "1100", "1"),
        _fcst_item("PTY", "1100", "0"),
        _fcst_item("SKY", "1200", "4"),
        _fcst_item("PTY", "1200", "1"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "response": {
                    "header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
                    "body": {"items": {"item": items}},
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await RealWeatherProvider(
            api_key="dummy",
            client=client,
        ).get_forecast_slots(37.5636, 126.9976)

    assert result.grid_x > 0
    assert result.grid_y > 0
    assert len(result.slots) == 2
    assert result.provider == "kma_ultra_short_forecast"


@pytest.mark.asyncio
async def test_real_weather_provider_raises_on_failed_result_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "response": {
                    "header": {"resultCode": "03", "resultMsg": "NODATA_ERROR"},
                    "body": {},
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = RealWeatherProvider(api_key="dummy", client=client)

    with pytest.raises(AppError) as exc_info:
        await provider.get_current_condition(37.5636, 126.9976)

    assert exc_info.value.code == "weather_unavailable"
    await client.aclose()


@pytest.mark.asyncio
async def test_real_weather_provider_does_not_chain_sensitive_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = RealWeatherProvider(api_key="sensitive-key", client=client)
        with pytest.raises(AppError) as exc_info:
            await provider.get_current_condition(37.5636, 126.9976)

    assert exc_info.value.code == "weather_unavailable"
    assert exc_info.value.__cause__ is None
