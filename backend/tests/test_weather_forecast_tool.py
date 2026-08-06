from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.domain.models import (
    WeatherCondition,
    WeatherForecastResult,
    WeatherForecastSlot,
)
from app.errors import AppError, ProviderTimeoutError
from app.providers.contracts import (
    ProviderResult,
    ProviderSource,
    ProviderStatus,
    provider_result,
)
from app.tools.weather_forecast import (
    ForecastSelectionMethod,
    GetWeatherForecastTool,
    WeatherForecastQuery,
    WeatherToolStatus,
)

KST = ZoneInfo("Asia/Seoul")
FIXED_NOW = datetime(2026, 7, 23, 6, 20, tzinfo=UTC)


def _slot(hour: int, condition: WeatherCondition) -> WeatherForecastSlot:
    return WeatherForecastSlot(
        forecast_for=datetime(2026, 7, 23, hour, tzinfo=KST),
        condition=condition,
        sky_code="1" if condition is WeatherCondition.GOOD else "4",
        precipitation_type="1" if condition is WeatherCondition.BAD else "0",
    )


class ForecastProvider:
    def __init__(
        self,
        slots: tuple[WeatherForecastSlot, ...] = (),
        error: AppError | None = None,
    ) -> None:
        self.slots = slots
        self.error = error

    async def get_forecast_slots(
        self, latitude: float, longitude: float
    ) -> ProviderResult[WeatherForecastResult]:
        if self.error:
            raise self.error
        return provider_result(
            WeatherForecastResult(
                latitude=latitude,
                longitude=longitude,
                grid_x=60,
                grid_y=127,
                slots=self.slots,
                provider="test",
            ),
            source=ProviderSource.FAKE_WEATHER,
        )


@pytest.mark.asyncio
async def test_selects_nearest_forecast_and_assumes_kst_for_naive_visit_at() -> None:
    provider = ForecastProvider(
        (
            _slot(14, WeatherCondition.GOOD),
            _slot(15, WeatherCondition.NEUTRAL),
            _slot(16, WeatherCondition.BAD),
        )
    )
    tool = GetWeatherForecastTool(provider, clock=lambda: FIXED_NOW)

    result = await tool.execute(
        WeatherForecastQuery(
            37.5788,
            126.9770,
            visit_at=datetime(2026, 7, 23, 15, 10),
        )
    )

    assert result.status is WeatherToolStatus.SUCCESS
    assert result.forecast is not None
    assert result.forecast.forecast_for.hour == 15
    assert result.forecast.timezone == "Asia/Seoul"
    assert result.forecast.timezone_assumed is True
    assert result.forecast.data_type == "forecast"
    assert result.forecast.observed_at is None
    assert result.forecast.retrieved_at == FIXED_NOW
    assert result.provider_metadata[0].source is ProviderSource.FAKE_WEATHER


@pytest.mark.asyncio
async def test_tie_prefers_future_forecast() -> None:
    provider = ForecastProvider(
        (
            _slot(15, WeatherCondition.GOOD),
            _slot(16, WeatherCondition.BAD),
        )
    )

    result = await GetWeatherForecastTool(
        provider,
        clock=lambda: FIXED_NOW,
    ).execute(
        WeatherForecastQuery(
            37.5788,
            126.9770,
            visit_at=datetime(2026, 7, 23, 15, 30, tzinfo=KST),
        )
    )

    assert result.forecast is not None
    assert result.forecast.forecast_for.hour == 16
    assert result.forecast.timezone_assumed is False


@pytest.mark.asyncio
async def test_immediate_visit_uses_earliest_future_slot() -> None:
    provider = ForecastProvider(
        (
            _slot(16, WeatherCondition.GOOD),
            _slot(17, WeatherCondition.BAD),
        )
    )

    result = await GetWeatherForecastTool(
        provider,
        clock=lambda: FIXED_NOW,
    ).execute(WeatherForecastQuery(37.5788, 126.9770))

    assert result.forecast is not None
    assert result.forecast.forecast_for.hour == 16
    assert (
        result.forecast.selection_method
        is ForecastSelectionMethod.EARLIEST_AVAILABLE
    )
    assert result.forecast.timezone_assumed is False


@pytest.mark.asyncio
async def test_explicit_visit_outside_forecast_range_is_unsupported() -> None:
    result = await GetWeatherForecastTool(
        ForecastProvider((_slot(15, WeatherCondition.GOOD),)),
        clock=lambda: FIXED_NOW,
    ).execute(
        WeatherForecastQuery(
            37.5788,
            126.9770,
            visit_at=datetime(2026, 7, 24, 15, tzinfo=KST),
        )
    )

    assert result.status is WeatherToolStatus.UNSUPPORTED
    assert result.error is not None
    assert result.error.cause == "outside_forecast_range"
    assert result.provider_metadata[0].source is ProviderSource.FAKE_WEATHER
    assert result.provider_metadata[0].status is ProviderStatus.SUCCESS
    assert result.provider_metadata[0].retrieved_at.tzinfo is not None


@pytest.mark.asyncio
async def test_empty_slots_are_no_data() -> None:
    result = await GetWeatherForecastTool(
        ForecastProvider(),
        clock=lambda: FIXED_NOW,
    ).execute(WeatherForecastQuery(37.5788, 126.9770))

    assert result.status is WeatherToolStatus.NO_DATA
    assert result.error is not None
    assert result.error.cause == "forecast_not_found"
    assert result.provider_metadata[0].source is ProviderSource.FAKE_WEATHER
    assert result.provider_metadata[0].status is ProviderStatus.SUCCESS
    assert result.provider_metadata[0].retrieved_at.tzinfo is not None


@pytest.mark.asyncio
async def test_provider_timeout_is_unavailable() -> None:
    result = await GetWeatherForecastTool(
        ForecastProvider(error=ProviderTimeoutError("KMA")),
        clock=lambda: FIXED_NOW,
    ).execute(WeatherForecastQuery(37.5788, 126.9770))

    assert result.status is WeatherToolStatus.UNAVAILABLE
    assert result.error is not None
    assert result.error.cause == "timeout"
    assert result.error.retryable is True


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(91, 127), (-91, 127), (37.5, 181), (37.5, -181)],
)
def test_validates_coordinates(latitude: float, longitude: float) -> None:
    with pytest.raises(ValueError):
        WeatherForecastQuery(latitude, longitude)
