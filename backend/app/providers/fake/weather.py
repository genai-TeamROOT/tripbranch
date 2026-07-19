# FakeWeatherProvider - 항상 고정된 날씨(good/neutral/bad)를 반환하는 가짜 구현.
# 사용법: 생성자 인자 또는 backend/.env의 FAKE_WEATHER_CONDITION으로 값을 바꿀 수 있음
# (api/deps.py에서 Settings.fake_weather_condition을 읽어 주입).
# TODO: RealWeatherProvider(providers/real/weather.py)로 교체될 대상.

from __future__ import annotations

from app.domain.models import WeatherCondition


class FakeWeatherProvider:
    """Returns a fixed weather condition, configurable via settings
    (FAKE_WEATHER_CONDITION env var) so teammates can exercise each
    branch of the weather scoring table without a real API."""

    def __init__(self, condition: WeatherCondition = WeatherCondition.NEUTRAL) -> None:
        self._condition = condition

    async def get_current_condition(self, latitude: float, longitude: float) -> WeatherCondition:
        return self._condition
