"""WeatherProvider 계약과 구현체.

계약: 좌표의 현재 날씨를 good/neutral/bad 중 하나로 반환한다. 업스트림(KMA)의
세부 날씨 코드를 이 세 단계로 매핑하는 책임은 구현체가 진다 - 이 셋 이외의
값은 provider 밖으로 노출되지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

import httpx

from app.domain.models import WeatherCondition
from app.providers.kma_grid import latlon_to_grid

_KST = ZoneInfo("Asia/Seoul")
_ULTRA_SRT_FCST_URL = (
    "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtFcst"
)

# PTY(강수형태): 0 없음 외에는 모두 강수 상황 -> bad로 취급.
_PRECIPITATION_PTY_CODES = {"1", "2", "3", "4", "5", "6", "7"}

# SKY(하늘상태): 1 맑음, 3 구름많음, 4 흐림. 흐림은 강수는 아니므로 neutral로 취급.
_SKY_TO_CONDITION = {
    "1": WeatherCondition.GOOD,
    "3": WeatherCondition.NEUTRAL,
    "4": WeatherCondition.NEUTRAL,
}


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


def resolve_base_date_time(now: datetime) -> tuple[str, str]:
    """주어진 시각 기준으로 조회 가능한 가장 최신 초단기예보 base_date/base_time을 구한다.

    발표는 매시 30분, API 제공은 발표 후 10분 뒤(매시 40분)부터 시작되므로
    45분 이전이면 직전 시각의 30분 발표분을 사용한다.
    """
    base_dt = now if now.minute >= 45 else now - timedelta(hours=1)
    return base_dt.strftime("%Y%m%d"), base_dt.strftime("%H30")


def map_sky_pty_to_condition(sky: str | None, pty: str | None) -> WeatherCondition:
    if pty is not None and pty in _PRECIPITATION_PTY_CODES:
        return WeatherCondition.BAD
    if sky is not None and sky in _SKY_TO_CONDITION:
        return _SKY_TO_CONDITION[sky]
    # sky/pty 값을 아직 못 구한 경우의 처리는 에러 처리 단계에서 다룬다.
    return WeatherCondition.NEUTRAL


def _earliest_sky_and_pty(items: list[dict]) -> tuple[str | None, str | None]:
    """응답 항목 중 가장 이른 fcstDate/fcstTime의 SKY, PTY 값을 찾는다."""
    sky_items = [item for item in items if item.get("category") == "SKY"]
    pty_items = [item for item in items if item.get("category") == "PTY"]

    def _earliest_value(candidates: list[dict]) -> str | None:
        if not candidates:
            return None
        earliest = min(candidates, key=lambda item: (item["fcstDate"], item["fcstTime"]))
        return earliest["fcstValue"]

    return _earliest_value(sky_items), _earliest_value(pty_items)


class RealWeatherProvider:
    """KMA 단기예보 조회서비스(getUltraSrtFcst)를 사용하는 실제 구현.

    초단기실황(getUltraSrtNcst)과 달리 SKY(하늘상태)와 PTY(강수형태)를 한 번의
    호출로 함께 제공해서 good/neutral/bad 판정에 필요한 값을 모두 얻을 수 있다.
    """

    def __init__(
        self,
        api_key: str,
        client: httpx.AsyncClient,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def get_current_condition(self, latitude: float, longitude: float) -> WeatherCondition:
        nx, ny = latlon_to_grid(latitude, longitude)
        base_date, base_time = resolve_base_date_time(datetime.now(_KST))

        params = {
            "serviceKey": self._api_key,
            "pageNo": "1",
            "numOfRows": "100",
            "dataType": "JSON",
            "base_date": base_date,
            "base_time": base_time,
            "nx": str(nx),
            "ny": str(ny),
        }

        response = await self._client.get(
            _ULTRA_SRT_FCST_URL, params=params, timeout=self._timeout_seconds
        )
        response.raise_for_status()
        payload = response.json()

        items = payload["response"]["body"]["items"]["item"]
        sky_value, pty_value = _earliest_sky_and_pty(items)
        return map_sky_pty_to_condition(sky_value, pty_value)
