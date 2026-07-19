# 추천 점수 계산에 쓰이는 모든 상수(가중치, 임계값, 날씨x환경 점수표)를 한곳에 모아둠.
# PRD에 명시된 숫자를 그대로 옮겨놓은 것이므로, 기획/실험으로 수치를 바꿀 때는
# 이 파일만 수정하면 된다(도메인 로직 코드는 건드릴 필요 없음).
# TODO: 나중에 A/B 테스트나 사용자별 가중치 커스터마이징이 필요해지면, 이 상수들을
# 설정 파일(core/config.py)이나 DB로 옮기는 걸 고려 - 지금은 배포 단위로만 바뀌는 걸 전제로 함.

"""Recommendation scoring configuration.

Kept as plain Python constants (no YAML/config-file parsing) so the domain
layer has zero I/O dependencies. If these need to become user-tunable later,
load them once at startup (core/config.py) and pass values in, rather than
importing this module's constants from deep inside scoring logic.
"""

from __future__ import annotations

from app.domain.models import EnvironmentType, WeatherCondition

DEFAULT_SEARCH_RADIUS_KM = 1.0
MINIMUM_RECOMMENDATION_COUNT = 3
MAXIMUM_RECOMMENDATION_COUNT = 5

RECOMMENDATION_WEIGHTS: dict[str, float] = {
    "category": 0.40,
    "remaining_open_time": 0.30,
    "weather": 0.20,
    "distance": 0.10,
}

RECOMMENDATION_WEIGHTS_WITHOUT_WEATHER: dict[str, float] = {
    "category": 0.50,
    "remaining_open_time": 0.375,
    "distance": 0.125,
}

CATEGORY_RANK_SCORES: dict[int, float] = {
    1: 1.00,
    2: 0.85,
    3: 0.70,
}
CATEGORY_RANK_FALLBACK_SCORE = CATEGORY_RANK_SCORES[3]

# (lower_bound_minutes_inclusive, score), evaluated from the top down.
REMAINING_TIME_SCORE_THRESHOLDS: list[tuple[int, float]] = [
    (180, 1.00),
    (120, 0.85),
    (60, 0.65),
    (30, 0.35),
    (0, 0.10),
]

# (max_ratio_of_radius_inclusive, score), evaluated from the top down.
DISTANCE_SCORE_THRESHOLDS: list[tuple[float, float]] = [
    (0.25, 1.00),
    (0.50, 0.80),
    (0.75, 0.60),
    (1.00, 0.40),
]

WEATHER_ENVIRONMENT_SCORE_TABLE: dict[WeatherCondition, dict[EnvironmentType, float]] = {
    WeatherCondition.GOOD: {
        EnvironmentType.INDOOR: 0.8,
        EnvironmentType.MIXED: 0.9,
        EnvironmentType.OUTDOOR: 1.0,
        EnvironmentType.UNKNOWN: 0.7,
    },
    WeatherCondition.NEUTRAL: {
        EnvironmentType.INDOOR: 1.0,
        EnvironmentType.MIXED: 0.9,
        EnvironmentType.OUTDOOR: 0.8,
        EnvironmentType.UNKNOWN: 0.7,
    },
    WeatherCondition.BAD: {
        EnvironmentType.INDOOR: 1.0,
        EnvironmentType.MIXED: 0.7,
        EnvironmentType.OUTDOOR: 0.3,
        EnvironmentType.UNKNOWN: 0.5,
    },
}
