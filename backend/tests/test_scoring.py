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
    ExcludedCandidate,
    ExclusionReason,
    PreparedCandidate,
    PrepareResult,
    concentration_score,
    prepare_candidates,
    redistribute_weights,
    score_candidates,
    score_prepared_candidates,
)
from app.domain.travel_route import RouteSource, RouteStatus, TravelRoute

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


def test_prepare_result_exposes_eligible_count_and_excluded_ids() -> None:
    prepared = PreparedCandidate(
        candidate=MUSEUM_OPEN,
        remaining_minutes=240.0,
        is_unverified=False,
    )
    excluded = ExcludedCandidate(
        candidate=PARK_CLOSED,
        reason=ExclusionReason.CLOSED,
    )

    result = PrepareResult(
        eligible_candidates=(prepared,),
        excluded_candidates=(excluded,),
        input_count=2,
    )

    assert result.eligible_count == 1
    assert result.excluded_place_ids == ("p3",)
    assert result.excluded_candidates[0].reason.value == "closed"


def test_prepare_candidates_returns_eligible_and_excluded_with_reasons() -> None:
    result = prepare_candidates(
        [MUSEUM_OPEN, PARK_CLOSED, CAFE_CLOSING_SOON, RESTAURANT_FAR],
        now=NOW,
        shown_place_ids=["p2"],
        rejected_place_ids=["p5"],
    )

    assert [item.candidate.place_id for item in result.eligible_candidates] == ["p1"]
    assert [
        (item.place_id, item.reason)
        for item in result.excluded_candidates
    ] == [
        ("p3", ExclusionReason.CLOSED),
        ("p2", ExclusionReason.ALREADY_SHOWN),
        ("p5", ExclusionReason.REJECTED),
    ]
    assert result.input_count == 4


def test_prepare_candidates_keeps_unknown_hours_as_unverified() -> None:
    result = prepare_candidates([GALLERY_UNKNOWN_HOURS], now=NOW)

    prepared = result.eligible_candidates[0]
    assert prepared.remaining_minutes is None
    assert prepared.is_unverified is True
    assert prepared.warnings == ("방문 전에 운영 여부를 확인해주세요.",)


def test_prepare_candidates_can_include_closed_place_with_override_warning() -> None:
    result = prepare_candidates(
        [PARK_CLOSED],
        now=NOW,
        ignore_operating_hours=True,
    )

    prepared = result.eligible_candidates[0]
    assert prepared.remaining_minutes is None
    assert prepared.is_unverified is True
    assert prepared.warnings == (
        "지금은 운영시간이 아니에요. 방문 전에 다시 확인해주세요.",
    )


def test_prepare_candidates_prioritizes_history_reason_over_closed() -> None:
    result = prepare_candidates(
        [PARK_CLOSED],
        now=NOW,
        shown_place_ids=["p3"],
    )

    assert result.excluded_candidates[0].reason is ExclusionReason.ALREADY_SHOWN


def test_score_prepared_candidates_matches_compatibility_wrapper() -> None:
    candidates = [MUSEUM_OPEN, CAFE_CLOSING_SOON, GALLERY_UNKNOWN_HOURS]
    prepared = prepare_candidates(candidates, now=NOW)

    direct = score_prepared_candidates(
        prepared.eligible_candidates,
        weather_condition=WeatherCondition.BAD,
        max_distance_km=1.5,
    )
    compatible = score_candidates(
        candidates,
        now=NOW,
        weather_condition=WeatherCondition.BAD,
        max_distance_km=1.5,
    )

    assert direct.ranked == compatible.ranked
    assert direct.excluded_place_ids == ()


def test_score_prepared_candidates_uses_remaining_minutes_from_prepare() -> None:
    prepared = PreparedCandidate(
        candidate=MUSEUM_OPEN,
        remaining_minutes=30.0,
        is_unverified=False,
    )

    result = score_prepared_candidates(
        [prepared],
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=1.5,
    )

    assert result.ranked[0].remaining_minutes == 30.0
    assert result.ranked[0].feature_scores["remaining_operating_time"] == 0.25


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


def test_closed_place_is_tracked_in_excluded_closed_place_ids() -> None:
    result = score_candidates(
        [MUSEUM_OPEN, PARK_CLOSED],
        now=NOW,
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=1.5,
    )

    assert result.excluded_closed_place_ids == ("p3",)


def test_shown_place_is_not_counted_as_closed_exclusion() -> None:
    result = score_candidates(
        [MUSEUM_OPEN, PARK_CLOSED],
        now=NOW,
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=1.5,
        shown_place_ids=["p3"],
    )

    # p3는 폐점이기도 하지만 이미 노출된 후보라, "폐점 때문에 제외됨" 집계에는
    # 넣지 않는다 — 결과 0건의 원인 판정이 이 집계를 근거로 하므로 이중 집계를
    # 막아야 "전부 폐점 탓"을 잘못 True로 판정하지 않는다.
    assert result.excluded_closed_place_ids == ()


def test_ignore_operating_hours_includes_closed_place_with_warning() -> None:
    result = score_candidates(
        [PARK_CLOSED],
        now=NOW,
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=1.5,
        ignore_operating_hours=True,
    )

    assert [item.place_id for item in result.ranked] == ["p3"]
    ranked = result.ranked[0]
    assert ranked.is_unverified is True
    assert ranked.warnings == ("지금은 운영시간이 아니에요. 방문 전에 다시 확인해주세요.",)
    assert ranked.feature_scores["remaining_operating_time"] is None
    assert result.excluded_closed_place_ids == ()


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


# --- 요청 환경(conditions.environment) 채점 -------------------------------
#
# 사용자가 실내/실외를 명시했는데 날씨 언급이 없으면 날씨 대신 요청 환경으로
# 같은 자리를 채점한다. 거리·운영시간을 동일하게 맞춘 한 쌍으로 비교해서
# 순위 차이가 오직 환경에서만 나오게 한다.
_SAME_HOURS = OperatingHours(time(9, 0), time(18, 0))
INDOOR_TWIN = ScoringCandidate(
    place_id="in",
    name="실내쌍둥이",
    category="museum",
    environment_type="indoor",
    distance_km=0.5,
    operating_hours=_SAME_HOURS,
)
OUTDOOR_TWIN = ScoringCandidate(
    place_id="out",
    name="야외쌍둥이",
    category="park",
    environment_type="outdoor",
    distance_km=0.5,
    operating_hours=_SAME_HOURS,
)
UNKNOWN_TWIN = ScoringCandidate(
    place_id="unknown",
    name="미상쌍둥이",
    category="etc",
    environment_type="unknown",
    distance_km=0.5,
    operating_hours=_SAME_HOURS,
)


def test_requested_indoor_replaces_weather_feature() -> None:
    result = score_candidates(
        [INDOOR_TWIN, OUTDOOR_TWIN],
        now=NOW,
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=1.5,
        requested_environment="indoor",
    )

    ranked = {item.place_id: item for item in result.ranked}
    assert ranked["in"].feature_scores["environment"] == 1.00
    assert ranked["out"].feature_scores["environment"] == 0.30
    # 날씨는 이번 실행에 존재하지 않는 Feature다 — 결측(None)이 아니라 키가 없다.
    assert "weather" not in ranked["in"].feature_scores
    # 가중치 숫자는 그대로고 키만 옮겨간다.
    assert ranked["in"].weights_used["environment"] == DEFAULT_WEIGHTS["weather"]
    assert sum(ranked["in"].weights_used.values()) == pytest.approx(1.0)


def test_requested_indoor_wins_over_good_weather_outdoor_preference() -> None:
    """맑은 날엔 날씨 표가 야외에 만점(1.00)/실내에 0.70을 주지만, 사용자가
    실내를 명시하면 그 선호가 순위를 결정해야 한다 — 이 역전이 원래 증상이었다.
    """
    weather_only = score_candidates(
        [INDOOR_TWIN, OUTDOOR_TWIN],
        now=NOW,
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=1.5,
    )
    assert [item.place_id for item in weather_only.ranked] == ["out", "in"]

    requested_indoor = score_candidates(
        [INDOOR_TWIN, OUTDOOR_TWIN],
        now=NOW,
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=1.5,
        requested_environment="indoor",
    )
    assert [item.place_id for item in requested_indoor.ranked] == ["in", "out"]


def test_requested_outdoor_is_symmetric() -> None:
    result = score_candidates(
        [INDOOR_TWIN, OUTDOOR_TWIN],
        now=NOW,
        weather_condition=WeatherCondition.BAD,
        max_distance_km=1.5,
        requested_environment="outdoor",
    )

    assert [item.place_id for item in result.ranked] == ["out", "in"]
    ranked = {item.place_id: item for item in result.ranked}
    assert ranked["out"].feature_scores["environment"] == 1.00
    assert ranked["in"].feature_scores["environment"] == 0.30


def test_unknown_environment_type_scores_between_match_and_mismatch() -> None:
    result = score_candidates(
        [INDOOR_TWIN, OUTDOOR_TWIN, UNKNOWN_TWIN],
        now=NOW,
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=1.5,
        requested_environment="indoor",
    )

    assert [item.place_id for item in result.ranked] == ["in", "unknown", "out"]
    ranked = {item.place_id: item for item in result.ranked}
    assert ranked["unknown"].feature_scores["environment"] == 0.60


@pytest.mark.parametrize("requested", [None, "any"])
def test_no_environment_preference_keeps_weather_feature(requested: str | None) -> None:
    """`any`는 "실내외 무관"이라 기존 날씨 판정을 그대로 쓴다(D-053의 되묻기
    기본값이 ANY라, 이 구분이 없으면 되묻기 답변 경로 전체가 환경 채점으로 샌다).
    """
    result = score_candidates(
        [INDOOR_TWIN, OUTDOOR_TWIN],
        now=NOW,
        weather_condition=WeatherCondition.GOOD,
        max_distance_km=1.5,
        requested_environment=requested,
    )

    ranked = {item.place_id: item for item in result.ranked}
    assert "environment" not in ranked["in"].feature_scores
    assert ranked["in"].feature_scores["weather"] == 0.70
    assert ranked["out"].feature_scores["weather"] == 1.00
    assert ranked["in"].weights_used == DEFAULT_WEIGHTS


def test_requested_environment_is_scored_when_weather_is_missing() -> None:
    """날씨를 못 구해도 요청 환경은 그대로 채점된다 — 이 자리를 결측으로 두면
    "날씨 조회 실패 → 실내 요청 무시"로 같은 증상이 남는다.
    """
    result = score_candidates(
        [INDOOR_TWIN, OUTDOOR_TWIN],
        now=NOW,
        weather_condition=None,
        max_distance_km=1.5,
        requested_environment="indoor",
    )

    ranked = {item.place_id: item for item in result.ranked}
    assert ranked["in"].feature_scores["environment"] == 1.00
    assert ranked["in"].weights_used["environment"] == DEFAULT_WEIGHTS["weather"]
    assert sum(ranked["in"].weights_used.values()) == pytest.approx(1.0)


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


# --- 실측 도보 시간 반영 (feat/walking-duration-scoring) --------------------
#
# 거리 Feature는 실측 도보 소요시간이 있으면 그걸 쓰고, 없으면 직선거리로
# 돌아간다. 분모는 검색 반경을 도보 속도로 되돌린 예산(분)이다.


def _walking_route(
    place_id: str,
    duration_seconds: int | None,
    *,
    status: RouteStatus = RouteStatus.SUCCESS,
) -> TravelRoute:
    return TravelRoute(
        place_id=place_id,
        status=status,
        source=RouteSource.KAKAO_WALKING,
        distance_m=None if duration_seconds is None else duration_seconds * 1,
        duration_seconds=duration_seconds,
    )


def _distance_feature_score(candidate: ScoringCandidate, **kwargs: object) -> float:
    prepared = prepare_candidates([candidate], now=NOW)
    result = score_prepared_candidates(
        prepared.eligible_candidates,
        weather_condition=None,
        max_distance_km=2.0,
        **kwargs,  # type: ignore[arg-type]
    )
    score = result.ranked[0].feature_scores["distance"]
    assert score is not None
    return score


def test_distance_feature_uses_measured_walking_duration() -> None:
    """반경 2.0km면 예산은 2.0/0.07 = 약 28.57분. 14.28분이면 절반이 남는다."""
    score = _distance_feature_score(
        MUSEUM_OPEN,
        travel_routes=[_walking_route("p1", duration_seconds=857)],
    )

    assert score == pytest.approx(0.5, abs=0.01)


def test_distance_feature_falls_back_to_straight_line_without_route() -> None:
    """도보 경로가 아예 없으면 기존 직선거리 점수(1 - 0.5/2.0)를 그대로 쓴다."""
    assert _distance_feature_score(MUSEUM_OPEN) == pytest.approx(0.75)


def test_distance_feature_falls_back_when_route_lookup_failed() -> None:
    """조회 실패(no_data)는 결측이 아니라 직선거리 폴백이다 — 재분배를 태우면
    조회에 실패한 후보만 거리 Feature가 빠져 오히려 유리해진다."""
    score = _distance_feature_score(
        MUSEUM_OPEN,
        travel_routes=[
            _walking_route("p1", duration_seconds=None, status=RouteStatus.NO_DATA)
        ],
    )

    assert score == pytest.approx(0.75)


def test_distance_feature_keeps_distance_weight_when_route_missing() -> None:
    """폴백 후보의 가중치 구성은 실측 후보와 같아야 한다(결측 재분배 금지)."""
    prepared = prepare_candidates([MUSEUM_OPEN], now=NOW)
    result = score_prepared_candidates(
        prepared.eligible_candidates,
        weather_condition=WeatherCondition.NEUTRAL,
        max_distance_km=2.0,
    )

    assert "distance" in result.ranked[0].weights_used


def test_walking_duration_beyond_budget_scores_zero() -> None:
    """예산(약 28.57분)을 넘으면 0으로 클램프된다."""
    score = _distance_feature_score(
        MUSEUM_OPEN,
        travel_routes=[_walking_route("p1", duration_seconds=3600)],
    )

    assert score == 0.0


def test_walking_route_of_other_place_is_ignored() -> None:
    """place_id가 다른 경로는 이 후보에 적용되지 않는다."""
    score = _distance_feature_score(
        MUSEUM_OPEN,
        travel_routes=[_walking_route("other", duration_seconds=60)],
    )

    assert score == pytest.approx(0.75)


def test_measured_route_is_exposed_on_ranked_candidate() -> None:
    """채점에 쓴 실측 값은 응답 조립·근거 문장이 쓸 수 있게 보존된다."""
    prepared = prepare_candidates([MUSEUM_OPEN], now=NOW)
    result = score_prepared_candidates(
        prepared.eligible_candidates,
        weather_condition=None,
        max_distance_km=2.0,
        travel_routes=[
            TravelRoute(
                place_id="p1",
                status=RouteStatus.SUCCESS,
                source=RouteSource.KAKAO_WALKING,
                distance_m=620,
                duration_seconds=530,
            )
        ],
    )

    ranked = result.ranked[0]
    assert ranked.walking_distance_m == 620
    assert ranked.walking_duration_seconds == 530


def test_fallback_candidate_exposes_no_measured_route() -> None:
    """직선거리로 폴백한 후보는 도보 값을 내보내지 않는다 — 표기가 실측인 척하면 안 된다."""
    prepared = prepare_candidates([MUSEUM_OPEN], now=NOW)
    result = score_prepared_candidates(
        prepared.eligible_candidates,
        weather_condition=None,
        max_distance_km=2.0,
        travel_routes=[
            _walking_route("p1", duration_seconds=None, status=RouteStatus.UNAVAILABLE)
        ],
    )

    ranked = result.ranked[0]
    assert ranked.walking_distance_m is None
    assert ranked.walking_duration_seconds is None


def test_partial_measurement_falls_back_to_straight_line_for_every_candidate() -> None:
    """실측과 직선거리를 한 순위표에 섞으면 실측 후보만 손해를 본다.

    실거리는 직선거리보다 항상 크거나 같아 두 기준의 낙관도가 다르기 때문이다.
    하나라도 실측이 없으면 전부 직선거리로 내려서 같은 자로 잰다.
    """
    prepared = prepare_candidates([MUSEUM_OPEN, RESTAURANT_FAR], now=NOW)
    result = score_prepared_candidates(
        prepared.eligible_candidates,
        weather_condition=None,
        max_distance_km=2.0,
        travel_routes=[_walking_route("p1", duration_seconds=530)],
    )

    assert [ranked.walking_duration_seconds for ranked in result.ranked] == [None, None]
    # 직선거리 기준이므로 더 가까운 p1이 위에 온다.
    assert [ranked.place_id for ranked in result.ranked] == ["p1", "p5"]


def test_closer_place_is_not_demoted_by_having_a_measurement() -> None:
    """회귀 방지: 실측이 있다는 이유로 더 가까운 장소가 밀려나면 안 된다."""
    prepared = prepare_candidates([MUSEUM_OPEN, RESTAURANT_FAR], now=NOW)
    partial = score_prepared_candidates(
        prepared.eligible_candidates,
        weather_condition=None,
        max_distance_km=2.0,
        travel_routes=[_walking_route("p1", duration_seconds=530)],
    )
    none_measured = score_prepared_candidates(
        prepared.eligible_candidates,
        weather_condition=None,
        max_distance_km=2.0,
    )

    assert [r.place_id for r in partial.ranked] == [r.place_id for r in none_measured.ranked]


def test_all_measured_candidates_keep_their_routes() -> None:
    """전원 실측이면 그대로 실측으로 채점한다."""
    prepared = prepare_candidates([MUSEUM_OPEN, RESTAURANT_FAR], now=NOW)
    result = score_prepared_candidates(
        prepared.eligible_candidates,
        weather_condition=None,
        max_distance_km=2.0,
        travel_routes=[
            _walking_route("p1", duration_seconds=300),
            _walking_route("p5", duration_seconds=900),
        ],
    )

    assert [ranked.walking_duration_seconds for ranked in result.ranked] == [300, 900]


def _estimated_route(place_id: str, duration_seconds: int) -> TravelRoute:
    """TravelRouteTool의 폴백과 fake Provider가 내보내는 직선거리 추정값."""
    return TravelRoute(
        place_id=place_id,
        status=RouteStatus.SUCCESS,  # 추정값도 SUCCESS로 온다 — 상태로는 구분 못 한다
        source=RouteSource.STRAIGHT_LINE_ESTIMATE,
        distance_m=duration_seconds,
        duration_seconds=duration_seconds,
    )


def test_straight_line_estimate_is_not_treated_as_measurement() -> None:
    """직선거리 추정은 status가 SUCCESS여도 실측이 아니다.

    이걸 실측으로 쓰면 응답의 walking_duration_seconds에 추정값이 실려
    "걸어서 약 N분"이라는 거짓 문구가 나간다.
    """
    score = _distance_feature_score(
        MUSEUM_OPEN,
        travel_routes=[_estimated_route("p1", duration_seconds=857)],
    )

    assert score == pytest.approx(0.75)  # 직선거리 폴백 점수


def test_estimate_is_not_exposed_as_measured_route() -> None:
    prepared = prepare_candidates([MUSEUM_OPEN], now=NOW)
    result = score_prepared_candidates(
        prepared.eligible_candidates,
        weather_condition=None,
        max_distance_km=2.0,
        travel_routes=[_estimated_route("p1", duration_seconds=857)],
    )

    ranked = result.ranked[0]
    assert ranked.walking_distance_m is None
    assert ranked.walking_duration_seconds is None


def test_estimate_mixed_with_measurement_falls_back_for_every_candidate() -> None:
    """실측과 추정이 섞이면 낙관도가 달라 순위가 왜곡된다.

    둘 다 status=SUCCESS라 상태만 보는 일관성 검사는 그냥 통과한다 —
    source까지 봐야 이 케이스가 잡힌다.
    """
    prepared = prepare_candidates([MUSEUM_OPEN, RESTAURANT_FAR], now=NOW)
    result = score_prepared_candidates(
        prepared.eligible_candidates,
        weather_condition=None,
        max_distance_km=2.0,
        travel_routes=[
            _walking_route("p1", duration_seconds=300),  # 실측
            _estimated_route("p5", duration_seconds=900),  # 추정
        ],
    )

    assert [ranked.walking_duration_seconds for ranked in result.ranked] == [None, None]
