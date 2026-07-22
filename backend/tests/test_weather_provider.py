from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from app.domain.models import WeatherCondition
from app.providers.weather import (
    RealWeatherProvider,
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
