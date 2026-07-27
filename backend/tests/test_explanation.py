"""Explainability Layer v1(D-06)의 Rule 기반 문장 생성 검증.

D-02의 `scoring_fixture_v1.py` 시나리오를 그대로 재사용해, Feature 점수별로
어떤 문장이 몇 개·어떤 순서로 나오는지 손으로 계산한 값과 대조한다.
"""

from fixtures.scoring_fixture_v1 import (
    _CAFE_CLOSING_SOON,
    _GALLERY_UNKNOWN_HOURS,
    _MUSEUM_OPEN,
    _RESTAURANT_FAR,
    NOW,
)

from app.domain.evidence import build_evidence
from app.domain.explanation import build_explanations
from app.domain.models import WeatherCondition
from app.domain.scoring import score_candidates


def _explanations_by_place_id(candidates, **kwargs) -> dict[str, tuple[str, ...]]:
    result = score_candidates(candidates, now=NOW, **kwargs)
    return {
        ranked.place_id: build_explanations(build_evidence(ranked))
        for ranked in result.ranked
    }


def test_baseline_all_features_present_explanations() -> None:
    explanations = _explanations_by_place_id(
        (_MUSEUM_OPEN, _CAFE_CLOSING_SOON, _RESTAURANT_FAR),
        weather_condition=WeatherCondition.BAD,
        max_distance_km=1.5,
    )

    # p1(박물관A): weather=1.0, remaining=1.0(둘 다 임계값 이상, 기여도 동률
    # → weather가 고정 순서상 먼저), distance=0.667(임계값 미만이라 생략)
    assert explanations["p1"] == (
        "지금 날씨 조건에 잘 맞는 장소예요.",
        "운영 종료까지 시간 여유가 있어 방문하기 좋아요.",
    )
    # p5(맛집E): p1과 동일한 패턴(weather=1.0, remaining=1.0(캡), distance=0.2)
    assert explanations["p5"] == (
        "지금 날씨 조건에 잘 맞는 장소예요.",
        "운영 종료까지 시간 여유가 있어 방문하기 좋아요.",
    )
    # p2(카페B): weather=1.0(포함), remaining=0.5(임계값 미만, 생략),
    # distance=0.467(임계값 미만, 생략)
    assert explanations["p2"] == ("지금 날씨 조건에 잘 맞는 장소예요.",)


def test_weather_missing_can_produce_empty_explanations() -> None:
    explanations = _explanations_by_place_id(
        (_MUSEUM_OPEN, _CAFE_CLOSING_SOON, _RESTAURANT_FAR),
        weather_condition=None,
        max_distance_km=1.5,
    )

    assert explanations["p1"] == ("운영 종료까지 시간 여유가 있어 방문하기 좋아요.",)
    assert explanations["p5"] == ("운영 종료까지 시간 여유가 있어 방문하기 좋아요.",)
    # p2: remaining=0.5, distance=0.467 모두 임계값 미만이고 weather는 결측
    # → 강조할 이유가 하나도 없어 빈 튜플이 될 수 있다.
    assert explanations["p2"] == ()


def test_operating_hours_unknown_orders_by_contribution() -> None:
    explanations = _explanations_by_place_id(
        (_MUSEUM_OPEN, _GALLERY_UNKNOWN_HOURS),
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=1.5,
    )

    # p1: weather=0.70(기여도 0.28), remaining=1.0(기여도 0.4) → remaining이
    # 기여도가 더 커서 먼저 나온다.
    assert explanations["p1"] == (
        "운영 종료까지 시간 여유가 있어 방문하기 좋아요.",
        "지금 날씨 조건에 잘 맞는 장소예요.",
    )
    # p4(갤러리D, 운영시간 미확인): remaining_operating_time 결측 → 생략,
    # weather=0.70만 포함.
    assert explanations["p4"] == ("지금 날씨 조건에 잘 맞는 장소예요.",)


def test_explanations_are_deterministic_for_identical_input() -> None:
    kwargs = dict(weather_condition=WeatherCondition.BAD, max_distance_km=1.5)
    first = _explanations_by_place_id(
        (_MUSEUM_OPEN, _CAFE_CLOSING_SOON, _RESTAURANT_FAR), **kwargs
    )
    second = _explanations_by_place_id(
        (_MUSEUM_OPEN, _CAFE_CLOSING_SOON, _RESTAURANT_FAR), **kwargs
    )

    assert first == second
