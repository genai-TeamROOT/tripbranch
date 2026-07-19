# WeatherProvider 계약: 좌표의 현재 날씨를 good/neutral/bad 중 하나로 반환.
# 실제 API의 세부 날씨 코드(맑음/흐림/눈/비 등)를 이 세 단계로 매핑하는 책임은
# 구현체(providers/real/weather.py)에 있다 - 도메인 점수 계산은 이 세 값만 안다.

from __future__ import annotations

from typing import Protocol

from app.domain.models import WeatherCondition


class WeatherProvider(Protocol):
    async def get_current_condition(self, latitude: float, longitude: float) -> WeatherCondition:
        """Return the current coarse weather condition at a location."""
        ...
