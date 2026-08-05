"""weather_judgment.judge_weather_condition_from_facts/_from_stated() 판정 규칙 고정.

판정 근거: package_D/feature-weather-judgment-role-split_설계.md §4 (D-051).
의도(AVOID/ENJOY/IGNORE/NO_MENTION/None) × 원인(precipitation/temperature/맑음/
흐림/결측) 조합을 전수 검증한다. 핵심 회귀 케이스는
test_enjoy_precipitation_bad_flips_to_good다 — D-051 문제 1(ENJOY 반전)의
직접적인 재현·검증이다.
"""

from __future__ import annotations

import pytest

from app.domain.models import WeatherCondition
from app.domain.weather_judgment import (
    judge_weather_condition_from_facts,
    judge_weather_condition_from_stated,
)
from app.schemas import StatedWeather, WeatherIntent

_NON_FLIPPING_INTENTS = (WeatherIntent.AVOID, WeatherIntent.NO_MENTION, None)


# --- judge_weather_condition_from_facts() -----------------------------------


@pytest.mark.parametrize("weather_intent", _NON_FLIPPING_INTENTS)
def test_facts_precipitation_is_bad_regardless_of_intent_except_enjoy(
    weather_intent: WeatherIntent | None,
) -> None:
    assert (
        judge_weather_condition_from_facts("rain", "overcast", 15.0, weather_intent)
        is WeatherCondition.BAD
    )


@pytest.mark.parametrize("precipitation", ["rain", "snow", "sleet", "shower"])
def test_enjoy_precipitation_bad_flips_to_good(precipitation: str) -> None:
    """D-051 문제 1의 회귀 테스트: "비 오는 날 산책하고 싶어"(ENJOY)가
    outdoor를 우대해야 한다 — BAD가 아니라 GOOD으로 판정돼야 한다.
    """
    result = judge_weather_condition_from_facts(
        precipitation, "overcast", 15.0, WeatherIntent.ENJOY
    )
    assert result is WeatherCondition.GOOD


def test_facts_precipitation_none_is_not_bad() -> None:
    result = judge_weather_condition_from_facts("none", "clear", 15.0, WeatherIntent.AVOID)
    assert result is WeatherCondition.GOOD


@pytest.mark.parametrize("weather_intent", [*_NON_FLIPPING_INTENTS, WeatherIntent.ENJOY])
def test_facts_extreme_heat_is_bad_and_enjoy_does_not_flip(
    weather_intent: WeatherIntent | None,
) -> None:
    """기온이 원인인 BAD는 ENJOY여도 뒤집지 않는다(1차 범위 제외)."""
    result = judge_weather_condition_from_facts("none", "clear", 35.0, weather_intent)
    assert result is WeatherCondition.BAD


@pytest.mark.parametrize("weather_intent", [*_NON_FLIPPING_INTENTS, WeatherIntent.ENJOY])
def test_facts_extreme_cold_is_bad_and_enjoy_does_not_flip(
    weather_intent: WeatherIntent | None,
) -> None:
    result = judge_weather_condition_from_facts("none", "clear", -15.0, weather_intent)
    assert result is WeatherCondition.BAD


@pytest.mark.parametrize("temperature_celsius", [28.0, 30.0, 33.0 - 0.01, -12.0 + 0.01, 0.0])
def test_facts_below_threshold_temperature_is_not_bad(temperature_celsius: float) -> None:
    """폭염·한파 기준 미만 기온은 그 자체로 BAD를 만들지 않는다 — 완충 NEUTRAL
    구간(예: 28°C)을 별도로 두지 않기로 했다(근거 없는 임의값 배제)."""
    result = judge_weather_condition_from_facts(
        "none", "clear", temperature_celsius, WeatherIntent.AVOID
    )
    assert result is not WeatherCondition.BAD


@pytest.mark.parametrize("temperature_celsius", [28.0, 30.0, -5.0, 0.0])
def test_facts_below_threshold_temperature_follows_sky(temperature_celsius: float) -> None:
    """폭염·한파 기준에 못 미치면 기온은 판정에서 빠지고 하늘 상태로 결정된다."""
    assert (
        judge_weather_condition_from_facts(
            "none", "clear", temperature_celsius, WeatherIntent.AVOID
        )
        is WeatherCondition.GOOD
    )
    assert (
        judge_weather_condition_from_facts(
            "none", "overcast", temperature_celsius, WeatherIntent.AVOID
        )
        is WeatherCondition.NEUTRAL
    )


def test_facts_heat_threshold_boundary_is_bad() -> None:
    assert (
        judge_weather_condition_from_facts("none", "clear", 33.0, WeatherIntent.AVOID)
        is WeatherCondition.BAD
    )


def test_facts_cold_threshold_boundary_is_bad() -> None:
    assert (
        judge_weather_condition_from_facts("none", "clear", -12.0, WeatherIntent.AVOID)
        is WeatherCondition.BAD
    )


def test_facts_clear_sky_comfortable_temperature_is_good() -> None:
    result = judge_weather_condition_from_facts("none", "clear", 15.0, WeatherIntent.AVOID)
    assert result is WeatherCondition.GOOD


@pytest.mark.parametrize("sky", ["cloudy", "overcast"])
def test_facts_cloudy_or_overcast_comfortable_temperature_is_neutral(sky: str) -> None:
    result = judge_weather_condition_from_facts("none", sky, 15.0, WeatherIntent.AVOID)
    assert result is WeatherCondition.NEUTRAL


def test_facts_all_missing_defaults_to_neutral() -> None:
    result = judge_weather_condition_from_facts(None, None, None, WeatherIntent.AVOID)
    assert result is WeatherCondition.NEUTRAL


def test_facts_ignore_intent_does_not_change_baseline() -> None:
    """IGNORE는 실제로는 A가 이 함수까지 안 넘긴다(호출부 책임) — 그래도 이
    함수 자체는 방어적으로 기본 판정을 그대로 반환해야 한다."""
    result = judge_weather_condition_from_facts("rain", "overcast", 15.0, WeatherIntent.IGNORE)
    assert result is WeatherCondition.BAD


# --- judge_weather_condition_from_stated() -----------------------------------


@pytest.mark.parametrize("stated_weather", [StatedWeather.RAIN, StatedWeather.SNOW])
@pytest.mark.parametrize("weather_intent", _NON_FLIPPING_INTENTS)
def test_stated_precipitation_is_bad_when_not_enjoy(
    stated_weather: StatedWeather, weather_intent: WeatherIntent | None
) -> None:
    result = judge_weather_condition_from_stated(stated_weather, weather_intent)
    assert result is WeatherCondition.BAD


@pytest.mark.parametrize("stated_weather", [StatedWeather.RAIN, StatedWeather.SNOW])
def test_stated_precipitation_flips_to_good_when_enjoy(stated_weather: StatedWeather) -> None:
    result = judge_weather_condition_from_stated(stated_weather, WeatherIntent.ENJOY)
    assert result is WeatherCondition.GOOD


@pytest.mark.parametrize("stated_weather", [StatedWeather.HOT, StatedWeather.COLD])
@pytest.mark.parametrize("weather_intent", [*_NON_FLIPPING_INTENTS, WeatherIntent.ENJOY])
def test_stated_temperature_is_bad_and_enjoy_does_not_flip(
    stated_weather: StatedWeather, weather_intent: WeatherIntent | None
) -> None:
    result = judge_weather_condition_from_stated(stated_weather, weather_intent)
    assert result is WeatherCondition.BAD


@pytest.mark.parametrize("weather_intent", [*_NON_FLIPPING_INTENTS, WeatherIntent.ENJOY])
def test_stated_good_is_always_good(weather_intent: WeatherIntent | None) -> None:
    result = judge_weather_condition_from_stated(StatedWeather.GOOD, weather_intent)
    assert result is WeatherCondition.GOOD
