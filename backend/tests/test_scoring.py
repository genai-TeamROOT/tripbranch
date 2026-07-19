# domain/scoring.py의 개별 점수 함수(카테고리/운영시간/거리/날씨)와 가중합 로직 검증.
# weights.py에 정의된 임계값 표와 정확히 일치하는지 확인하는 회귀 테스트 성격이 강하다 -
# weights.py의 숫자를 바꾸면 이 테스트도 같이 갱신해야 한다.

from __future__ import annotations

import math

from app.domain.models import EnvironmentType, WeatherCondition
from app.domain.scoring import (
    ScoreBreakdown,
    category_score,
    distance_score,
    remaining_open_time_score,
    weather_score,
    weighted_total_score,
)


def test_category_score_uses_rank_table() -> None:
    assert category_score(1) == 1.00
    assert category_score(2) == 0.85
    assert category_score(3) == 0.70


def test_category_score_falls_back_beyond_rank_3() -> None:
    assert category_score(4) == category_score(3)


def test_remaining_open_time_score_buckets() -> None:
    assert remaining_open_time_score(200) == 1.00
    assert remaining_open_time_score(150) == 0.85
    assert remaining_open_time_score(90) == 0.65
    assert remaining_open_time_score(45) == 0.35
    assert remaining_open_time_score(10) == 0.10


def test_distance_score_ratio_buckets() -> None:
    assert distance_score(0.2, 1.0) == 1.00
    assert distance_score(0.5, 1.0) == 0.80
    assert distance_score(0.75, 1.0) == 0.60
    assert distance_score(1.0, 1.0) == 0.40


def test_weather_score_table_lookup() -> None:
    assert weather_score(WeatherCondition.BAD, EnvironmentType.OUTDOOR) == 0.3
    assert weather_score(WeatherCondition.BAD, EnvironmentType.INDOOR) == 1.0
    assert weather_score(WeatherCondition.GOOD, EnvironmentType.OUTDOOR) == 1.0


def test_weighted_total_score_with_weather() -> None:
    breakdown = ScoreBreakdown(category=1.0, remaining_open_time=1.0, distance=1.0, weather=1.0)

    assert math.isclose(weighted_total_score(breakdown), 1.0)


def test_weighted_total_score_without_weather_uses_alternate_weights() -> None:
    breakdown = ScoreBreakdown(category=1.0, remaining_open_time=1.0, distance=1.0, weather=None)

    assert math.isclose(weighted_total_score(breakdown), 1.0)
