"""Scoring v1: Candidate 목록에 하드 필터와 가중치 점수를 적용해 정렬한다.

역할: `ScoringCandidate` 목록을 받아 폐점/이전 노출/거절 후보를 제외하고,
운영 유무·날씨·거리 Feature로 가중치 점수를 계산해 정렬한다.
입력: `ScoringCandidate` 목록과 실행 조건(날씨, 검색 반경, 이전 노출·거절 ID).
출력: `ScoringResult` (정렬된 `RankedCandidate` 목록, 사용된 가중치, 제외 ID).
호출 시점: 추천 파이프라인이 후보 조회를 마친 뒤 순위를 매길 때 호출한다.
설계 근거: `docs/design/recommendation-scoring.md` 참고.
TODO: 혼잡도 Feature, 실제 이동시간 기반 거리, 예산/동행 하드 필터는 v2 이후.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.domain.models import PlaceStatus, ScoringCandidate, WeatherCondition

DEFAULT_WEIGHTS: Mapping[str, float] = {
    "weather": 0.4,
    "operating": 0.4,
    "distance": 0.2,
}

_OPERATING_OPEN_SCORE = 1.0
_OPERATING_UNKNOWN_SCORE = 0.5

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
    is_unverified: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ScoringResult:
    """Scoring v1의 최종 출력."""

    ranked: tuple[RankedCandidate, ...]
    weights_used: Mapping[str, float]
    excluded_place_ids: tuple[str, ...]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _is_excluded(
    candidate: ScoringCandidate,
    shown_place_ids: frozenset[str],
    rejected_place_ids: frozenset[str],
) -> bool:
    if candidate.place_status is PlaceStatus.CLOSED:
        return True
    return candidate.place_id in shown_place_ids or candidate.place_id in rejected_place_ids


def _operating_score(candidate: ScoringCandidate) -> float:
    if candidate.place_status is PlaceStatus.OPEN:
        return _OPERATING_OPEN_SCORE
    # CLOSED는 하드필터에서 이미 제외되므로 여기 도달하면 UNKNOWN이다.
    return _OPERATING_UNKNOWN_SCORE


def _weather_fit_score(candidate: ScoringCandidate, weather_condition: WeatherCondition) -> float:
    return _WEATHER_FIT_TABLE.get(
        (weather_condition, candidate.environment_type), _WEATHER_FIT_DEFAULT
    )


def _distance_score(distance_km: float, max_distance_km: float) -> float:
    if max_distance_km <= 0:
        return 1.0 if distance_km <= 0 else 0.0
    return _clamp(1.0 - distance_km / max_distance_km, 0.0, 1.0)


def redistribute_weights(
    weights: Mapping[str, float], missing_feature: str
) -> dict[str, float]:
    """`missing_feature`를 제외하고 나머지 가중치를 기존 비중에 비례해 재분배한다."""
    remaining = {
        feature: weight for feature, weight in weights.items() if feature != missing_feature
    }
    total_remaining = sum(remaining.values())
    if total_remaining <= 0:
        return remaining
    return {feature: weight / total_remaining for feature, weight in remaining.items()}


def score_candidates(
    candidates: Sequence[ScoringCandidate],
    *,
    weather_condition: WeatherCondition | None,
    max_distance_km: float,
    shown_place_ids: Iterable[str] = (),
    rejected_place_ids: Iterable[str] = (),
    weights: Mapping[str, float] | None = None,
) -> ScoringResult:
    """Candidate 목록에 하드 필터와 가중치 점수를 적용해 정렬한다.

    1. 폐점/이전 노출/거절 후보 제외 (운영시간 미확인은 제외하지 않음)
    2. 날씨 정보 유무에 따라 기본 가중치 또는 재분배 가중치 결정
    3. Feature별 점수 계산 후 가중합 (운영 유무, 날씨, 거리)
    4. score 내림차순 → distance_km 오름차순 → place_id 오름차순으로 정렬
    """
    base_weights = dict(weights) if weights is not None else dict(DEFAULT_WEIGHTS)
    weights_used = (
        base_weights
        if weather_condition is not None
        else redistribute_weights(base_weights, "weather")
    )

    shown = frozenset(shown_place_ids)
    rejected = frozenset(rejected_place_ids)

    excluded_ids: list[str] = []
    scored: list[tuple[ScoringCandidate, float, dict[str, float | None]]] = []

    for candidate in candidates:
        if _is_excluded(candidate, shown, rejected):
            excluded_ids.append(candidate.place_id)
            continue

        feature_scores: dict[str, float | None] = {
            "operating": _operating_score(candidate),
            "distance": _distance_score(candidate.distance_km, max_distance_km),
        }
        feature_scores["weather"] = (
            _weather_fit_score(candidate, weather_condition)
            if weather_condition is not None
            else None
        )

        score = sum(
            feature_scores[feature] * weight  # type: ignore[operator]
            for feature, weight in weights_used.items()
            if feature_scores.get(feature) is not None
        )
        scored.append((candidate, score, feature_scores))

    scored.sort(key=lambda entry: (-entry[1], entry[0].distance_km, entry[0].place_id))

    ranked = tuple(
        RankedCandidate(
            place_id=candidate.place_id,
            name=candidate.name,
            category=candidate.category,
            rank=index + 1,
            score=round(score, 4),
            feature_scores=feature_scores,
            is_unverified=candidate.place_status is PlaceStatus.UNKNOWN,
            warnings=(_UNVERIFIED_WARNING,)
            if candidate.place_status is PlaceStatus.UNKNOWN
            else (),
        )
        for index, (candidate, score, feature_scores) in enumerate(scored)
    )

    return ScoringResult(
        ranked=ranked,
        weights_used=weights_used,
        excluded_place_ids=tuple(excluded_ids),
    )
