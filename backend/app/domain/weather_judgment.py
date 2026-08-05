"""날씨 사실(precipitation/sky/temperature)과 사용자 의도로 WeatherCondition을 판정한다.

D-051: C는 기상청 코드를 도메인 용어로 번역한 사실만 전달하고(`WeatherForecast`의
precipitation/sky/temperature_celsius), 판정("이 날씨가 좋은가")은 D가 맡는다.
판정에는 weather_intent(AVOID/ENJOY)가 필요한데 그 값을 가진 쪽이 D이기 때문이다.

핵심 원칙: WeatherCondition(GOOD/NEUTRAL/BAD)은 "객관적으로 좋은 날씨"가 아니라
"이 사용자의 목적에 맞는 날씨"다. 그래서 같은 강수라도 AVOID면 BAD, ENJOY면
GOOD으로 판정될 수 있다. `_WEATHER_FIT_TABLE`(scoring.py)과 explanation.py의
라벨 텍스트는 이 모듈이 만든 WeatherCondition 값만 소비하므로 그대로 재사용된다.
"""

from __future__ import annotations

from typing import Literal

from app.domain.models import WeatherCondition
from app.schemas import StatedWeather, WeatherIntent

# 기상청 폭염주의보(33°C)·한파주의보(아침 최저기온 -12°C 이하) 기준을 차용했다.
# 공식 기준은 체감온도·2일 이상 지속을 요구하지만, 여기서는 단일 예보 시점의
# 기온만 본다 — 단순화라는 걸 인지하고 있어야 한다. 두 임계값 사이는 완충
# NEUTRAL 구간을 두지 않는다 — 근거 없는 값(예: 28°C/0°C)을 새로 만들지 않기
# 위해서다. 대신 그 구간은 하늘 상태로 판정한다(_classify_from_facts 참고).
_HEAT_BAD_THRESHOLD_CELSIUS = 33.0
_COLD_BAD_THRESHOLD_CELSIUS = -12.0

# C가 기상청 PTY 코드를 옮긴 강수형태(WeatherForecast.precipitation)와 동일한 값.
# C의 스키마 클래스는 import하지 않는다 — 값 타입만 공유하고 코드 의존은 없다.
Precipitation = Literal["none", "rain", "snow", "sleet", "shower"]
Sky = Literal["clear", "cloudy", "overcast"]

# 판정이 왜 그렇게 나왔는지(원인)를 함께 들고 다닌다 — ENJOY가 "강수라서 BAD"만
# 뒤집고 "기온이라서 BAD"는 그대로 두기 때문에, 판정값만으로는 이 재해석을 할 수 없다.
_Reason = Literal["precipitation", "temperature"] | None

_STATED_WEATHER_BASELINE: dict[StatedWeather, tuple[WeatherCondition, _Reason]] = {
    StatedWeather.RAIN: (WeatherCondition.BAD, "precipitation"),
    StatedWeather.SNOW: (WeatherCondition.BAD, "precipitation"),
    StatedWeather.HOT: (WeatherCondition.BAD, "temperature"),
    StatedWeather.COLD: (WeatherCondition.BAD, "temperature"),
    StatedWeather.GOOD: (WeatherCondition.GOOD, None),
}


def _classify_from_facts(
    precipitation: Precipitation | None,
    sky: Sky | None,
    temperature_celsius: float | None,
) -> tuple[WeatherCondition, _Reason]:
    """의도와 무관한 사실 기반 판정 + 원인 태깅.

    강수 > 기온(폭염/한파) > 하늘 순으로 확인한다 — 비가 오면서 기온도
    극단적이어도 강수 쪽이 체감에 더 크게 영향을 준다고 보고 강수를 우선한다.
    폭염·한파 기준을 넘지 않는 기온(예: 30°C, -5°C)은 그 자체로는 판정하지
    않고 하늘 상태로 넘어간다 — 근거 없는 "꽤 덥다/춥다" 구간을 만들지 않기
    위해서다.
    """
    if precipitation is not None and precipitation != "none":
        return WeatherCondition.BAD, "precipitation"

    if temperature_celsius is not None and (
        temperature_celsius >= _HEAT_BAD_THRESHOLD_CELSIUS
        or temperature_celsius <= _COLD_BAD_THRESHOLD_CELSIUS
    ):
        return WeatherCondition.BAD, "temperature"

    if sky == "clear":
        return WeatherCondition.GOOD, None
    if sky in ("cloudy", "overcast"):
        return WeatherCondition.NEUTRAL, None

    # precipitation/sky/temperature가 전부 결측이면 판단 근거가 없다 — 안전한
    # 중간값으로 취급한다(1차 Scoring의 _WEATHER_FIT_DEFAULT와 같은 태도).
    return WeatherCondition.NEUTRAL, None


def _classify_from_stated(stated: StatedWeather) -> tuple[WeatherCondition, _Reason]:
    return _STATED_WEATHER_BASELINE[stated]


def _apply_intent(
    condition: WeatherCondition,
    reason: _Reason,
    weather_intent: WeatherIntent | None,
) -> WeatherCondition:
    """AVOID/NO_MENTION/None은 기본 판정을 그대로 쓰고, ENJOY는 강수가 원인인
    BAD만 GOOD으로 뒤집는다. 기온이 원인인 BAD는 1차 범위에서 뒤집지 않는다 —
    "더워서 즐기고 싶다"류 케이스는 실제 사례가 나오면 확장 검토한다.
    """
    if (
        weather_intent is WeatherIntent.ENJOY
        and reason == "precipitation"
        and condition is WeatherCondition.BAD
    ):
        return WeatherCondition.GOOD
    return condition


def judge_weather_condition_from_facts(
    precipitation: Precipitation | None,
    sky: Sky | None,
    temperature_celsius: float | None,
    weather_intent: WeatherIntent | None,
) -> WeatherCondition:
    """C가 조회한 날씨 사실(`WeatherForecast.precipitation`/`sky`/`temperature_celsius`)로
    WeatherCondition을 판정한다. weather_intent가 NO_MENTION/None일 때 쓰인다 —
    AVOID/ENJOY는 사용자가 이미 발화에서 날씨를 말했다고 보고
    `judge_weather_condition_from_stated()`를 대신 쓴다(호출부 책임).
    """
    condition, reason = _classify_from_facts(precipitation, sky, temperature_celsius)
    return _apply_intent(condition, reason, weather_intent)


def judge_weather_condition_from_stated(
    stated_weather: StatedWeather,
    weather_intent: WeatherIntent | None,
) -> WeatherCondition:
    """사용자가 발화에서 직접 말한 날씨(`StatedWeather`)로 WeatherCondition을
    판정한다. weather_intent가 AVOID/ENJOY일 때 쓰인다.
    """
    condition, reason = _classify_from_stated(stated_weather)
    return _apply_intent(condition, reason, weather_intent)


__all__ = [
    "Precipitation",
    "Sky",
    "judge_weather_condition_from_facts",
    "judge_weather_condition_from_stated",
]
