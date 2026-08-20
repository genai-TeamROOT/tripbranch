"""취향 Feature 채점 테스트 — 정규화 구간과 요청 단위 켜기/끄기."""

from __future__ import annotations

from datetime import time

import pytest

from app.domain.models import (
    OperatingHours,
    PlaceEvidenceMatch,
    ScoringCandidate,
    WeatherCondition,
)
from app.domain.scoring import (
    DEFAULT_WEIGHTS,
    TASTE_WEIGHTS,
    PreparedCandidate,
    score_prepared_candidates,
)

_HOURS = OperatingHours(time(9, 0), time(22, 0))


def _prepared(place_id: str, distance_km: float = 0.5) -> PreparedCandidate:
    return PreparedCandidate(
        candidate=ScoringCandidate(
            place_id=place_id,
            name=f"장소 {place_id}",
            category="카페",
            environment_type="indoor",
            distance_km=distance_km,
            operating_hours=_HOURS,
        ),
        remaining_minutes=240.0,
        is_unverified=False,
    )


def _match(place_id: str, avg: float) -> PlaceEvidenceMatch:
    return PlaceEvidenceMatch(
        content_id=place_id,
        place_title=f"장소 {place_id}",
        avg_similarity=avg,
        snippets=(),
    )


def _score(candidates, taste_matches=None):
    return score_prepared_candidates(
        candidates,
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=2.0,
        taste_matches=taste_matches,
    )


def test_taste_feature_is_off_when_no_matches_are_passed() -> None:
    """취향을 말하지 않은 요청은 기존 3축 그대로여야 한다."""
    result = _score([_prepared("a")])

    ranked = result.ranked[0]
    assert "taste" not in ranked.feature_scores
    assert set(ranked.weights_used) == set(DEFAULT_WEIGHTS)


def test_taste_feature_is_on_for_every_candidate_once_enabled() -> None:
    """일부만 Feature를 가지면 한 순위 안에서 자가 둘이 된다 — 도보에서 순위가 뒤집혔다."""
    result = _score(
        [_prepared("a"), _prepared("b")],
        taste_matches={"a": _match("a", 0.60)},
    )

    for ranked in result.ranked:
        assert "taste" in ranked.feature_scores
        assert set(ranked.weights_used) == set(TASTE_WEIGHTS)


def test_candidate_without_evidence_scores_zero_not_missing() -> None:
    """근거 없음은 "계산 못 함"이 아니라 "안 맞음"이다 — 재분배하지 않는다."""
    result = _score(
        [_prepared("a"), _prepared("b")],
        taste_matches={"a": _match("a", 0.60)},
    )

    by_id = {r.place_id: r for r in result.ranked}
    assert by_id["b"].feature_scores["taste"] == 0.0
    assert by_id["b"].weights_used["taste"] == TASTE_WEIGHTS["taste"]


@pytest.mark.parametrize(
    ("avg_similarity", "expected"),
    [
        (0.43, 0.0),    # 컷값 = 0점
        (0.54, 0.5),    # 구간 중앙
        (0.65, 1.0),    # 관측 상한 = 만점
        (0.813, 1.0),   # 관측 최대 — clipping (의도된 대가)
        (0.30, 0.0),    # 컷 미만 (검색이 돌려주지 않는 값이지만 방어)
    ],
)
def test_similarity_is_stretched_over_the_measured_range(
    avg_similarity: float, expected: float
) -> None:
    """1.0으로 나누면 1등 후보조차 0.22점이다 — 실측 상한 0.65로 편다."""
    result = _score(
        [_prepared("a")], taste_matches={"a": _match("a", avg_similarity)}
    )

    assert result.ranked[0].feature_scores["taste"] == pytest.approx(
        expected
    )


def test_taste_can_flip_ranking_between_equal_candidates() -> None:
    """같은 조건이면 취향 근거가 순위를 가른다 — 이 Feature의 존재 이유다."""
    result = _score(
        [_prepared("far", 0.9), _prepared("near", 0.8)],
        taste_matches={"far": _match("far", 0.65)},
    )

    # 거리는 near가 유리한데, 취향 만점이 그것을 뒤집는다.
    assert [r.place_id for r in result.ranked] == ["far", "near"]


def test_all_zero_taste_does_not_change_ranking() -> None:
    """전 후보가 0점이어도 순위는 그대로다 — 모두 같은 만큼 낮아진다."""
    without = _score([_prepared("a", 0.4), _prepared("b", 0.9)])
    with_empty = _score([_prepared("a", 0.4), _prepared("b", 0.9)], taste_matches={})

    assert [r.place_id for r in without.ranked] == [
        r.place_id for r in with_empty.ranked
    ]


def test_empty_mapping_still_enables_the_feature() -> None:
    """빈 dict는 "취향을 말했는데 근거를 못 찾았다"다. None과 구분해야 한다."""
    result = _score([_prepared("a")], taste_matches={})

    assert result.ranked[0].feature_scores["taste"] == 0.0
    assert set(result.ranked[0].weights_used) == set(TASTE_WEIGHTS)
