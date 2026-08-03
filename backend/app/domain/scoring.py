"""Scoring v1: Candidate 목록에 하드 필터와 가중치 점수를 적용해 정렬한다.

역할: `ScoringCandidate` 목록을 받아 이전 노출/거절 후보와 폐점 후보(운영 유무
최종 판정)를 제외하고, 날씨·거리·남은 운영시간 Feature로 가중치 점수를 계산해
정렬한다. 카테고리(place_type/place_tag) 하드 필터는 Scoring 이전 단계에서
이미 처리됐다고 전제한다.
입력: `ScoringCandidate` 목록과 실행 조건(기준 시각, 날씨, 검색 반경, 이전
노출·거절 ID).
출력: `ScoringResult` (정렬된 `RankedCandidate` 목록, 후보별 사용 가중치,
제외 ID).
호출 시점: 추천 파이프라인이 카테고리 필터를 마친 뒤 순위를 매길 때 호출한다.
설계 근거: `docs/design/recommendation-scoring.md` 참고.
TODO: 혼잡도 Feature, 실제 이동시간 기반 거리, 예산/동행 하드 필터는 v2 이후.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.concentration_policy import ConcentrationLevel
from app.domain.models import OperatingHours, ScoringCandidate, WeatherCondition

DEFAULT_WEIGHTS: Mapping[str, float] = {
    "weather": 0.4,
    "remaining_operating_time": 0.4,
    "distance": 0.2,
}

# D-040: concentration_intent가 AVOID/SEEK일 때만 쓰는 2차 Scoring 기본 가중치.
# 1차 Scoring(DEFAULT_WEIGHTS)은 이 이름 자체를 모른다 — concentration은 1차에
# "결측"이 아니라 "존재하지 않는 Feature"다(concentration-conditions.md §2.3).
CONCENTRATION_WEIGHTS: Mapping[str, float] = {
    "weather": 0.35,
    "remaining_operating_time": 0.35,
    "distance": 0.15,
    "concentration": 0.15,
}

# 남은 운영시간이 이 값(분) 이상이면 만점(1.0)으로 취급한다.
_REMAINING_TIME_FULL_SCORE_MINUTES = 120.0

_WEATHER_FIT_TABLE: Mapping[tuple[WeatherCondition, str], float] = {
    (WeatherCondition.GOOD, "indoor"): 0.70,
    (WeatherCondition.GOOD, "outdoor"): 1.00,
    (WeatherCondition.GOOD, "unknown"): 0.85,
    (WeatherCondition.NEUTRAL, "indoor"): 0.80,
    (WeatherCondition.NEUTRAL, "outdoor"): 0.80,
    (WeatherCondition.NEUTRAL, "unknown"): 0.80,
    (WeatherCondition.BAD, "indoor"): 1.00,
    (WeatherCondition.BAD, "outdoor"): 0.30,
    (WeatherCondition.BAD, "unknown"): 0.60,
}
_WEATHER_FIT_DEFAULT = 0.80

_UNVERIFIED_WARNING = "방문 전에 운영 여부를 확인해주세요."


@dataclass(frozen=True)
class RankedCandidate:
    """점수 계산 후 정렬된 후보 1건."""

    place_id: str
    name: str
    category: str
    rank: int
    score: float
    feature_scores: Mapping[str, float | None]
    weights_used: Mapping[str, float]
    is_unverified: bool
    warnings: tuple[str, ...]
    # 정규화 점수(feature_scores)만으로는 "직선거리 약 400m" 같은 구체적인
    # 문장을 만들 수 없어, Explainability Layer(D-06)가 쓸 원본 값을 보존한다.
    distance_km: float
    remaining_minutes: float | None
    weather_condition: WeatherCondition | None
    environment_type: str
    # D-040: 2차 Scoring(rerank_with_concentration())에서만 채워진다. 1차 Scoring
    # 결과는 concentration 자체를 모르므로 항상 None이다 — explanation.py가 문장을
    # "한적함/보통/다소 혼잡/혼잡" 중 무엇으로 쓸지 고르는 데 필요하다(direction이
    # 이미 반영된 concentration_score만으로는 실제 붐빔 정도를 알 수 없다).
    concentration_level: ConcentrationLevel | None = None


@dataclass(frozen=True)
class ScoringResult:
    """Scoring v1의 최종 출력."""

    ranked: tuple[RankedCandidate, ...]
    excluded_place_ids: tuple[str, ...]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _remaining_minutes(now: datetime, hours: OperatingHours) -> float | None:
    """`now`가 영업시간 안이면 마감까지 남은 분을, 밖이면 `None`(폐점)을 반환한다."""
    current_time = now.time()
    if not (hours.open_time <= current_time < hours.close_time):
        return None
    close_at = datetime.combine(
        now.date(),
        hours.close_time,
        tzinfo=now.tzinfo,
    )
    return (close_at - now).total_seconds() / 60.0


def _remaining_time_score(remaining_minutes: float) -> float:
    return _clamp(remaining_minutes / _REMAINING_TIME_FULL_SCORE_MINUTES, 0.0, 1.0)


def _weather_fit_score(candidate: ScoringCandidate, weather_condition: WeatherCondition) -> float:
    return _WEATHER_FIT_TABLE.get(
        (weather_condition, candidate.environment_type), _WEATHER_FIT_DEFAULT
    )


def _distance_score(distance_km: float, max_distance_km: float) -> float:
    if max_distance_km <= 0:
        return 1.0 if distance_km <= 0 else 0.0
    return _clamp(1.0 - distance_km / max_distance_km, 0.0, 1.0)


def concentration_score(concentration_rate: float, *, seek: bool) -> float:
    """혼잡률(평시 대비 0~100대 상대 비율)을 0~1 점수로 선형 정규화한다.

    `seek`(concentration_intent=SEEK, 붐비는 곳 선호)이면 혼잡률이 높을수록
    점수가 높고, `seek=False`(AVOID, 한적한 곳 선호)면 그 반대다. distance/
    remaining_operating_time과 같은 연속값 스타일을 따른다 — 4단계 구간
    (quiet/normal/slightly_crowded/crowded) 매핑 대신 선형 정규화를 택해
    정보 손실을 피한다.
    """
    normalized = _clamp(concentration_rate / 100.0, 0.0, 1.0)
    return normalized if seek else 1.0 - normalized


def redistribute_weights(
    weights: Mapping[str, float], missing_features: Iterable[str]
) -> dict[str, float]:
    """결측 Feature들을 제외하고 나머지 가중치를 기존 비중에 비례해 재분배한다."""
    missing = set(missing_features)
    remaining = {feature: weight for feature, weight in weights.items() if feature not in missing}
    total_remaining = sum(remaining.values())
    if total_remaining <= 0:
        return remaining
    return {feature: weight / total_remaining for feature, weight in remaining.items()}


def _is_closed(candidate: ScoringCandidate, now: datetime) -> bool:
    if candidate.operating_hours is None:
        return False  # 운영시간 미확인은 폐점이 아니다.
    return _remaining_minutes(now, candidate.operating_hours) is None


def _is_excluded(
    candidate: ScoringCandidate,
    now: datetime,
    shown_place_ids: frozenset[str],
    rejected_place_ids: frozenset[str],
) -> bool:
    if _is_closed(candidate, now):
        return True
    return candidate.place_id in shown_place_ids or candidate.place_id in rejected_place_ids


def score_candidates(
    candidates: Sequence[ScoringCandidate],
    *,
    now: datetime,
    weather_condition: WeatherCondition | None,
    max_distance_km: float,
    shown_place_ids: Iterable[str] = (),
    rejected_place_ids: Iterable[str] = (),
    weights: Mapping[str, float] | None = None,
) -> ScoringResult:
    """Candidate 목록에 하드 필터와 가중치 점수를 적용해 정렬한다.

    1. 이전 노출/거절 후보 제외, 운영 유무 최종 판정으로 폐점 후보 제외
       (운영시간 미확인은 폐점과 달리 제외하지 않음)
    2. 후보별로 날씨·남은 운영시간 결측 여부를 확인해 기본 가중치 또는
       재분배 가중치를 적용 (두 Feature 모두 결측일 수도 있음)
    3. Feature별 점수 계산 후 가중합 (날씨, 남은 운영시간, 거리)
    4. score 내림차순 → distance_km 오름차순 → place_id 오름차순으로 정렬
    """
    base_weights = dict(weights) if weights is not None else dict(DEFAULT_WEIGHTS)
    shown = frozenset(shown_place_ids)
    rejected = frozenset(rejected_place_ids)

    excluded_ids: list[str] = []
    scored: list[
        tuple[
            ScoringCandidate,
            float,
            dict[str, float | None],
            dict[str, float],
            bool,
            float | None,
        ]
    ] = []

    for candidate in candidates:
        if _is_excluded(candidate, now, shown, rejected):
            excluded_ids.append(candidate.place_id)
            continue

        missing_features: list[str] = []

        weather_score: float | None
        if weather_condition is None:
            weather_score = None
            missing_features.append("weather")
        else:
            weather_score = _weather_fit_score(candidate, weather_condition)

        remaining_minutes = (
            _remaining_minutes(now, candidate.operating_hours)
            if candidate.operating_hours is not None
            else None
        )
        remaining_time_score: float | None
        if remaining_minutes is None:
            remaining_time_score = None
            missing_features.append("remaining_operating_time")
        else:
            remaining_time_score = _remaining_time_score(remaining_minutes)

        weights_used = (
            redistribute_weights(base_weights, missing_features)
            if missing_features
            else dict(base_weights)
        )

        feature_scores: dict[str, float | None] = {
            "weather": weather_score,
            "remaining_operating_time": remaining_time_score,
            "distance": _distance_score(candidate.distance_km, max_distance_km),
        }

        score = sum(
            feature_scores[feature] * weight  # type: ignore[operator]
            for feature, weight in weights_used.items()
        )

        is_unverified = candidate.operating_hours is None
        scored.append(
            (candidate, score, feature_scores, weights_used, is_unverified, remaining_minutes)
        )

    scored.sort(key=lambda entry: (-entry[1], entry[0].distance_km, entry[0].place_id))

    ranked = tuple(
        RankedCandidate(
            place_id=candidate.place_id,
            name=candidate.name,
            category=candidate.category,
            rank=index + 1,
            score=round(score, 4),
            feature_scores=feature_scores,
            weights_used=weights_used,
            is_unverified=is_unverified,
            warnings=(_UNVERIFIED_WARNING,) if is_unverified else (),
            distance_km=candidate.distance_km,
            remaining_minutes=remaining_minutes,
            weather_condition=weather_condition,
            environment_type=candidate.environment_type,
        )
        for index, (
            candidate,
            score,
            feature_scores,
            weights_used,
            is_unverified,
            remaining_minutes,
        ) in enumerate(scored)
    )

    return ScoringResult(
        ranked=ranked,
        excluded_place_ids=tuple(excluded_ids),
    )
