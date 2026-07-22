from __future__ import annotations

from datetime import datetime

import pytest

from app.domain.models import WeatherCondition
from app.providers.weather import map_sky_pty_to_condition, resolve_base_date_time


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
