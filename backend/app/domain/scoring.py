# 카테고리/남은운영시간/거리/날씨 개별 점수 함수와, 이를 가중합하는 weighted_total_score.
# 숫자 임계값과 가중치 자체는 weights.py에 상수로 분리되어 있으니, 점수 "기준"을 바꿀 땐
# weights.py만 고치면 되고, 점수 "계산 로직 구조"를 바꿀 땐 이 파일을 고친다.
# 사용법: recommendation_service가 후보 장소 하나당 이 함수들을 호출해 ScoreBreakdown을 만든다.

"""Individual scoring functions and weighted-sum aggregation.

Each function is intentionally small and independent so that team members
can own/tune one score dimension without touching the others.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import EnvironmentType, WeatherCondition
from app.domain.weights import (
    CATEGORY_RANK_FALLBACK_SCORE,
    CATEGORY_RANK_SCORES,
    DISTANCE_SCORE_THRESHOLDS,
    RECOMMENDATION_WEIGHTS,
    RECOMMENDATION_WEIGHTS_WITHOUT_WEATHER,
    REMAINING_TIME_SCORE_THRESHOLDS,
    WEATHER_ENVIRONMENT_SCORE_TABLE,
)


def category_score(rank: int) -> float:
    """rank is the 1-based position of this place's category within the
    user's preferred category order (rank 1 = first preference)."""
    return CATEGORY_RANK_SCORES.get(rank, CATEGORY_RANK_FALLBACK_SCORE)


def remaining_open_time_score(remaining_minutes: int) -> float:
    for lower_bound, score in REMAINING_TIME_SCORE_THRESHOLDS:
        if remaining_minutes >= lower_bound:
            return score
    return REMAINING_TIME_SCORE_THRESHOLDS[-1][1]


def distance_score(distance_km: float, search_radius_km: float) -> float:
    if search_radius_km <= 0:
        return DISTANCE_SCORE_THRESHOLDS[-1][1]

    ratio = distance_km / search_radius_km
    for max_ratio, score in DISTANCE_SCORE_THRESHOLDS:
        if ratio <= max_ratio:
            return score
    return 0.0


def weather_score(weather_condition: WeatherCondition, environment_type: EnvironmentType) -> float:
    return WEATHER_ENVIRONMENT_SCORE_TABLE[weather_condition][environment_type]


@dataclass(frozen=True)
class ScoreBreakdown:
    category: float
    remaining_open_time: float
    distance: float
    weather: float | None = None

    def as_dict(self) -> dict[str, float]:
        data = {
            "category": self.category,
            "remaining_open_time": self.remaining_open_time,
            "distance": self.distance,
        }
        if self.weather is not None:
            data["weather"] = self.weather
        return data


def weighted_total_score(breakdown: ScoreBreakdown) -> float:
    """Weighted sum. Uses the no-weather weight set when weather is absent
    (e.g. WeatherProvider unavailable)."""
    if breakdown.weather is None:
        weights = RECOMMENDATION_WEIGHTS_WITHOUT_WEATHER
        return (
            breakdown.category * weights["category"]
            + breakdown.remaining_open_time * weights["remaining_open_time"]
            + breakdown.distance * weights["distance"]
        )

    weights = RECOMMENDATION_WEIGHTS
    return (
        breakdown.category * weights["category"]
        + breakdown.remaining_open_time * weights["remaining_open_time"]
        + breakdown.weather * weights["weather"]
        + breakdown.distance * weights["distance"]
    )
