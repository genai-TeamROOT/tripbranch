# RealWeatherProvider placeholder - 실제 날씨 API(예: OpenWeather, 기상청) 연동 위치.
# TODO: get_current_condition() 구현. 업스트림 날씨 코드를 good/neutral/bad 3단계로
# 매핑하는 규칙을 이 클래스 안에서 결정할 것(도메인 쪽에는 3단계만 노출).

from __future__ import annotations

from app.domain.models import WeatherCondition


class RealWeatherProvider:
    """TODO: implement against a real weather API (e.g. OpenWeather,
    KMA). Map the upstream forecast/condition code onto our coarse
    good/neutral/bad scale in this class -- keep that mapping out of
    domain code."""

    def __init__(self, api_key: str | None, timeout_seconds: float) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    async def get_current_condition(self, latitude: float, longitude: float) -> WeatherCondition:
        raise NotImplementedError("RealWeatherProvider is not implemented yet.")
