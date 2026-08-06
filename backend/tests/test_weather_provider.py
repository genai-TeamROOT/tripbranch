from __future__ import annotations

import logging
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


def test_parses_temperature_into_forecast_slots() -> None:
    """T1H(기온)를 버리지 않는다.

    폭염일 때 SKY=맑음이면 condition은 GOOD이 되어 야외가 우대된다. 기온을 함께
    넘겨야 D가 그 경우를 판정할 수 있다(D-051 제안).
    """
    slots = map_items_to_forecast_slots(
        [
            _fcst_item("SKY", "1100", "1"),
            _fcst_item("PTY", "1100", "0"),
            _fcst_item("T1H", "1100", "35.0"),
        ]
    )

    assert len(slots) == 1
    assert slots[0].temperature_celsius == 35.0


def test_ignores_non_numeric_temperature() -> None:
    """결측·비정상 값이 와도 슬롯 자체를 버리지 않는다."""
    slots = map_items_to_forecast_slots(
        [
            _fcst_item("SKY", "1100", "1"),
            _fcst_item("PTY", "1100", "0"),
            _fcst_item("T1H", "1100", "-"),
        ]
    )

    assert len(slots) == 1
    assert slots[0].temperature_celsius is None


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

    condition = (await provider.get_current_condition(37.5636, 126.9976)).data

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
        result = result.data

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


@pytest.mark.asyncio
async def test_real_weather_provider_logs_gateway_reason_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """403은 인증·기간만료·쿼터를 모두 뭉뚱그리므로 errMsg가 로그에 남아야 한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "OpenAPI_ServiceResponse": {
                    "cmmMsgHeader": {
                        "errMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
                        "returnAuthMsg": "등록되지 않은 서비스키",
                        "returnReasonCode": "30",
                    }
                }
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = RealWeatherProvider(api_key="sensitive-key", client=client)
        with caplog.at_level(logging.ERROR, logger="app.providers.weather"):
            with pytest.raises(AppError):
                await provider.get_current_condition(37.5636, 126.9976)

    logged = caplog.text
    assert "http_status=403" in logged
    assert "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" in logged
    assert "returnReasonCode=30" in logged
    assert "sensitive-key" not in logged


@pytest.mark.asyncio
async def test_real_weather_provider_logs_result_code_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "response": {
                    "header": {
                        "resultCode": "22",
                        "resultMsg": "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR",
                    },
                    "body": {},
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = RealWeatherProvider(api_key="sensitive-key", client=client)
        with caplog.at_level(logging.ERROR, logger="app.providers.weather"):
            with pytest.raises(AppError):
                await provider.get_current_condition(37.5636, 126.9976)

    assert "resultCode=22" in caplog.text
    assert "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR" in caplog.text
