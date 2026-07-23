"""Scoring v1 (domain/scoring.py) 고정 입력 테스트.

역할: 고정 `ScoringCandidate` 목록으로 하드 필터, Feature 계산, 가중치 재분배,
정렬 규칙을 검증한다.
입력 데이터 주의: C-01 Tool 출력 초안이 아직 확정되지 않아, 실제 Tool 응답 대신
`ScoringCandidate` 계약에 맞춘 고정 Stub 값을 사용한다. Tool 계약이 나오면
"Tool 출력 → ScoringCandidate" 매퍼 테스트로 대체/보강한다.
"""

from __future__ import annotations

import pytest

from app.domain.models import PlaceStatus, ScoringCandidate, WeatherCondition
from app.domain.scoring import DEFAULT_WEIGHTS, score_candidates

# 고정 후보 Stub (C-01 Tool 출력 확정 전까지 사용하는 임시 입력)
MUSEUM_OPEN = ScoringCandidate(
    place_id="p1",
    name="박물관A",
    category="museum",
    environment_type="indoor",
    distance_km=0.5,
    place_status=PlaceStatus.OPEN,
    remaining_open_minutes=150,
)
CAFE_OPEN_SOON_CLOSING = ScoringCandidate(
    place_id="p2",
    name="카페B",
    category="cafe",
    environment_type="indoor",
    distance_km=0.8,
    place_status=PlaceStatus.OPEN,
    remaining_open_minutes=30,
)
PARK_CLOSED = ScoringCandidate(
    place_id="p3",
    name="공원C",
    category="park",
    environment_type="outdoor",
    distance_km=0.3,
    place_status=PlaceStatus.CLOSED,
    remaining_open_minutes=None,
)
GALLERY_UNKNOWN_HOURS = ScoringCandidate(
    place_id="p4",
    name="갤러리D",
    category="gallery",
    environment_type="indoor",
    distance_km=0.9,
    place_status=PlaceStatus.UNKNOWN,
    remaining_open_minutes=None,
)
RESTAURANT_FAR = ScoringCandidate(
    place_id="p5",
    name="맛집E",
    category="restaurant",
    environment_type="indoor",
    distance_km=1.2,
    place_status=PlaceStatus.OPEN,
    remaining_open_minutes=200,
)


def test_scores_and_sorts_fixed_candidates() -> None:
    result = score_candidates(
        [MUSEUM_OPEN, CAFE_OPEN_SOON_CLOSING, GALLERY_UNKNOWN_HOURS, RESTAURANT_FAR],
        preferred_categories=["museum", "cafe"],
        weather_condition=WeatherCondition.BAD,
        max_distance_km=1.5,
    )

    # p1(박물관, rank_1 카테고리+영업시간 넉넉)이 최상위, p4(갤러리, 카테고리 불일치+
    # 운영시간 미확인 중립값)가 최하위. 계산 근거는 recommendation-scoring.md 참고.
    place_ids = [item.place_id for item in result.ranked]
    assert place_ids == ["p1", "p5", "p2", "p4"]
    assert [item.rank for item in result.ranked] == [1, 2, 3, 4]
    # score는 내림차순으로 정렬되어 있어야 한다.
    scores = [item.score for item in result.ranked]
    assert scores == sorted(scores, reverse=True)


def test_closed_place_is_excluded() -> None:
    result = score_candidates(
        [MUSEUM_OPEN, PARK_CLOSED],
        preferred_categories=[],
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=1.5,
    )

    assert "p3" not in [item.place_id for item in result.ranked]
    assert "p3" in result.excluded_place_ids


def test_unknown_hours_is_distinct_from_closed() -> None:
    result = score_candidates(
        [PARK_CLOSED, GALLERY_UNKNOWN_HOURS],
        preferred_categories=[],
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=1.5,
    )

    # 폐점은 후보에서 제외되지만 운영시간 미확인은 제외되지 않는다.
    assert "p3" in result.excluded_place_ids
    assert "p3" not in [item.place_id for item in result.ranked]

    gallery = next(item for item in result.ranked if item.place_id == "p4")
    assert gallery.is_unverified is True
    assert gallery.warnings == ("방문 전에 운영 여부를 확인해주세요.",)


def test_shown_and_rejected_ids_are_excluded() -> None:
    result = score_candidates(
        [MUSEUM_OPEN, CAFE_OPEN_SOON_CLOSING],
        preferred_categories=[],
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=1.5,
        shown_place_ids=["p1"],
        rejected_place_ids=["p2"],
    )

    assert result.ranked == ()
    assert set(result.excluded_place_ids) == {"p1", "p2"}


def test_default_weights_used_when_weather_present() -> None:
    result = score_candidates(
        [MUSEUM_OPEN],
        preferred_categories=[],
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=1.5,
    )

    assert result.weights_used == DEFAULT_WEIGHTS
    assert result.ranked[0].feature_scores["weather"] is not None


def test_weather_weight_is_redistributed_when_missing() -> None:
    result = score_candidates(
        [MUSEUM_OPEN],
        preferred_categories=[],
        weather_condition=None,
        max_distance_km=1.5,
    )

    assert "weather" not in result.weights_used
    assert result.weights_used["category"] == pytest.approx(0.35 / 0.75)
    assert result.weights_used["remaining_time"] == pytest.approx(0.25 / 0.75)
    assert result.weights_used["distance"] == pytest.approx(0.15 / 0.75)
    assert sum(result.weights_used.values()) == pytest.approx(1.0)
    assert result.ranked[0].feature_scores["weather"] is None


def test_tie_break_uses_distance_then_place_id() -> None:
    tied_near_a = ScoringCandidate(
        place_id="z-near",
        name="Z",
        category="museum",
        environment_type="indoor",
        distance_km=0.5,
        place_status=PlaceStatus.OPEN,
        remaining_open_minutes=150,
    )
    tied_near_b = ScoringCandidate(
        place_id="a-near",
        name="A",
        category="museum",
        environment_type="indoor",
        distance_km=0.5,
        place_status=PlaceStatus.OPEN,
        remaining_open_minutes=150,
    )
    tied_far = ScoringCandidate(
        place_id="a-far",
        name="A-far",
        category="museum",
        environment_type="indoor",
        distance_km=1.0,
        place_status=PlaceStatus.OPEN,
        remaining_open_minutes=150,
    )

    result = score_candidates(
        [tied_far, tied_near_a, tied_near_b],
        preferred_categories=[],
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=1.5,
    )

    # 동점(같은 feature 값)일 때 거리 오름차순 → place_id 오름차순으로 정렬된다.
    assert [item.place_id for item in result.ranked] == ["a-near", "z-near", "a-far"]
