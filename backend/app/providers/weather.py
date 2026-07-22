"""WeatherProvider 계약과 구현체.

계약: 좌표의 현재 날씨를 good/neutral/bad 중 하나로 반환한다. 업스트림(KMA)의
세부 날씨 코드를 이 세 단계로 매핑하는 책임은 구현체가 진다 - 이 셋 이외의
값은 provider 밖으로 노출되지 않는다.
"""

from __future__ import annotations

from typing import Protocol

from app.domain.models import WeatherCondition


class WeatherProvider(Protocol):
    async def get_current_condition(self, latitude: float, longitude: float) -> WeatherCondition:
        """좌표의 현재(가장 가까운 예보 시각) 날씨를 반환한다."""
        ...


class FakeWeatherProvider:
    """설정된 고정 날씨를 반환하는 테스트/로컬 개발용 구현."""

    def __init__(self, condition: WeatherCondition = WeatherCondition.NEUTRAL) -> None:
        self._condition = condition

    async def get_current_condition(self, latitude: float, longitude: float) -> WeatherCondition:
        return self._condition
