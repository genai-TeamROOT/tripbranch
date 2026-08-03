"""Scoring v1 (domain/scoring.py) 고정 입력 테스트.

역할: 고정 `ScoringCandidate` 목록으로 하드 필터(폐점 최종 판정, 이전 노출/거절),
Feature 계산(날씨·남은 운영시간·거리), 가중치 재분배, 정렬 규칙을 검증한다.
Scoring v1은 카테고리를 가중치 계산에 사용하지 않고, 운영 유무는 boolean이
아니라 `now`와 `OperatingHours`를 비교해 남은 운영시간(분)으로 계산한다.
입력 데이터 주의: C-01 Tool 출력 초안이 아직 확정되지 않아, 실제 Tool 응답 대신
`ScoringCandidate` 계약에 맞춘 고정 Stub 값을 사용한다. Tool 계약이 나오면
"Tool 출력 → ScoringCandidate" 매퍼 테스트로 대체/보강한다.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.domain.models import OperatingHours, ScoringCandidate, WeatherCondition
from app.domain.scoring import (
    CONCENTRATION_WEIGHTS,
    DEFAULT_WEIGHTS,
    concentration_score,
    redistribute_weights,
    score_candidates,
)

# 고정 기준 시각 (모든 테스트가 공유): 14:00
NOW = datetime(2026, 7, 23, 14, 0, 0)

# 고정 후보 Stub (C-01 Tool 출력 확정 전까지 사용하는 임시 입력)
MUSEUM_OPEN = ScoringCandidate(
    place_id="p1",
    name="박물관A",
    category="museum",
    environment_type="indoor",
    distance_km=0.5,
    operating_hours=OperatingHours(time(9, 0), time(18, 0)),  # 마감까지 240분
)
CAFE_CLOSING_SOON = ScoringCandidate(
    place_id="p2",
    name="카페B",
    category="cafe",
    environment_type="indoor",
    distance_km=0.8,
    operating_hours=OperatingHours(time(9, 0), time(15, 0)),  # 마감까지 60분
)
PARK_CLOSED = ScoringCandidate(
    place_id="p3",
    name="공원C",
    category="park",
    environment_type="outdoor",
    distance_km=0.3,
    operating_hours=OperatingHours(time(9, 0), time(13, 0)),  # 14:00엔 이미 마감
)
GALLERY_UNKNOWN_HOURS = ScoringCandidate(
    place_id="p4",
    name="갤러리D",
    category="gallery",
    environment_type="indoor",
    distance_km=0.9,
    operating_hours=None,
)
RESTAURANT_FAR = ScoringCandidate(
    place_id="p5",
    name="맛집E",
    category="restaurant",
    environment_type="indoor",
    distance_km=1.2,
    operating_hours=OperatingHours(time(11, 0), time(23, 0)),  # 마감까지 540분(캡)
)


def test_scores_and_sorts_fixed_candidates() -> None:
    result = score_candidates(
        [MUSEUM_OPEN, CAFE_CLOSING_SOON, GALLERY_UNKNOWN_HOURS, RESTAURANT_FAR],
        now=NOW,
        weather_condition=WeatherCondition.BAD,
        max_distance_km=1.5,
    )

    # 날씨(모두 indoor라 동일)에 남은 운영시간과 거리가 함께 반영된다. 계산 근거는
    # recommendation-scoring.md 참고.
    place_ids = [item.place_id for item in result.ranked]
    assert place_ids == ["p1", "p5", "p4", "p2"]
    assert [item.rank for item in result.ranked] == [1, 2, 3, 4]
    scores = [item.score for item in result.ranked]
    assert scores == sorted(scores, reverse=True)


def test_closed_place_is_excluded() -> None:
    result = score_candidates(
        [MUSEUM_OPEN, PARK_CLOSED],
        now=NOW,
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=1.5,
    )

    assert "p3" not in [item.place_id for item in result.ranked]
    assert "p3" in result.excluded_place_ids


def test_timezone_aware_visit_time_is_supported() -> None:
    result = score_candidates(
        [MUSEUM_OPEN],
        now=datetime(2026, 7, 23, 14, tzinfo=ZoneInfo("Asia/Seoul")),
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=1.5,
    )

    assert result.ranked[0].place_id == "p1"


def test_unknown_hours_is_distinct_from_closed() -> None:
    result = score_candidates(
        [PARK_CLOSED, GALLERY_UNKNOWN_HOURS],
        now=NOW,
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=1.5,
    )

    # 폐점은 후보에서 제외되지만 운영시간 미확인은 제외되지 않는다.
    assert "p3" in result.excluded_place_ids
    assert "p3" not in [item.place_id for item in result.ranked]

    gallery = next(item for item in result.ranked if item.place_id == "p4")
    assert gallery.is_unverified is True
    assert gallery.warnings == ("방문 전에 운영 여부를 확인해주세요.",)
    assert gallery.feature_scores["remaining_operating_time"] is None
    assert "remaining_operating_time" not in gallery.weights_used
    assert gallery.weights_used["weather"] == pytest.approx(0.4 / 0.6)
    assert gallery.weights_used["distance"] == pytest.approx(0.2 / 0.6)


def test_shown_and_rejected_ids_are_excluded() -> None:
    result = score_candidates(
        [MUSEUM_OPEN, CAFE_CLOSING_SOON],
        now=NOW,
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=1.5,
        shown_place_ids=["p1"],
        rejected_place_ids=["p2"],
    )

    assert result.ranked == ()
    assert set(result.excluded_place_ids) == {"p1", "p2"}


def test_default_weights_used_when_all_features_present() -> None:
    result = score_candidates(
        [MUSEUM_OPEN],
        now=NOW,
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=1.5,
    )

    ranked = result.ranked[0]
    assert ranked.weights_used == DEFAULT_WEIGHTS
    assert ranked.feature_scores["weather"] is not None
    assert ranked.feature_scores["remaining_operating_time"] is not None


def test_weather_weight_is_redistributed_when_missing() -> None:
    result = score_candidates(
        [MUSEUM_OPEN],
        now=NOW,
        weather_condition=None,
        max_distance_km=1.5,
    )

    ranked = result.ranked[0]
    assert "weather" not in ranked.weights_used
    assert ranked.weights_used["remaining_operating_time"] == pytest.approx(0.4 / 0.6)
    assert ranked.weights_used["distance"] == pytest.approx(0.2 / 0.6)
    assert sum(ranked.weights_used.values()) == pytest.approx(1.0)
    assert ranked.feature_scores["weather"] is None


def test_both_weather_and_hours_missing_gives_distance_full_weight() -> None:
    result = score_candidates(
        [GALLERY_UNKNOWN_HOURS],
        now=NOW,
        weather_condition=None,
        max_distance_km=1.5,
    )

    ranked = result.ranked[0]
    assert ranked.weights_used == {"distance": pytest.approx(1.0)}
    assert ranked.feature_scores["weather"] is None
    assert ranked.feature_scores["remaining_operating_time"] is None


def test_tie_break_uses_distance_then_place_id() -> None:
    ample_hours = OperatingHours(time(9, 0), time(18, 0))
    tied_near_a = ScoringCandidate(
        place_id="z-near",
        name="Z",
        category="museum",
        environment_type="indoor",
        distance_km=0.5,
        operating_hours=ample_hours,
    )
    tied_near_b = ScoringCandidate(
        place_id="a-near",
        name="A",
        category="museum",
        environment_type="indoor",
        distance_km=0.5,
        operating_hours=ample_hours,
    )
    tied_far = ScoringCandidate(
        place_id="a-far",
        name="A-far",
        category="museum",
        environment_type="indoor",
        distance_km=1.0,
        operating_hours=ample_hours,
    )

    result = score_candidates(
        [tied_far, tied_near_a, tied_near_b],
        now=NOW,
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=1.5,
    )

    # 동점(같은 feature 값)일 때 거리 오름차순 → place_id 오름차순으로 정렬된다.
    assert [item.place_id for item in result.ranked] == ["a-near", "z-near", "a-far"]


# D-040: concentration_score()·CONCENTRATION_WEIGHTS (2차 Scoring 전용) 테스트.
# 1차 score_candidates()는 concentration을 전혀 모르므로 위 테스트들과는 분리한다.


def test_concentration_score_seek_rewards_high_rate() -> None:
    assert concentration_score(90.0, seek=True) == pytest.approx(0.9)
    assert concentration_score(10.0, seek=True) == pytest.approx(0.1)


def test_concentration_score_avoid_rewards_low_rate() -> None:
    assert concentration_score(90.0, seek=False) == pytest.approx(0.1)
    assert concentration_score(10.0, seek=False) == pytest.approx(0.9)


def test_concentration_score_clamps_out_of_range_rate() -> None:
    assert concentration_score(150.0, seek=True) == pytest.approx(1.0)
    assert concentration_score(150.0, seek=False) == pytest.approx(0.0)
    assert concentration_score(0.0, seek=True) == pytest.approx(0.0)
    assert concentration_score(0.0, seek=False) == pytest.approx(1.0)


def test_concentration_weights_redistribute_when_missing() -> None:
    # 5개 후보 중 1개만 concentration이 결측이면 그 후보만 재분배된다
    # (weather/remaining_operating_time과 동일한 개별 결측 패턴).
    weights_used = redistribute_weights(CONCENTRATION_WEIGHTS, ["concentration"])
    assert set(weights_used) == {"weather", "remaining_operating_time", "distance"}
    assert weights_used["weather"] == pytest.approx(0.35 / 0.85)
    assert weights_used["distance"] == pytest.approx(0.15 / 0.85)
    assert sum(weights_used.values()) == pytest.approx(1.0)
