"""추천 Evidence: RankedCandidate를 설명 가능한 근거 구조로 변환한다.

역할: Scoring v1(`RankedCandidate`)의 feature_scores/weights_used를 그대로
버리지 않고, Feature별 기여도(score * weight)를 더해 "왜 이 순위인지" 확인할
수 있는 형태로 재구성한다. 자연어 문장(reason)은 만들지 않는다 — 이는
Response Generator(LLM) 영역이며 D-02 범위 밖이다.
입력: `ScoringResult`/`RankedCandidate` (모두 `backend/app/domain/scoring.py`).
출력: `RecommendationEvidence` (직렬화 가능한 순수 데이터).
설계 근거: `docs/design/recommendation-evidence-fixture.md` 참고.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import WeatherCondition
from app.domain.scoring import RankedCandidate, ScoringResult

# feature_scores/weights_used에 항상 존재하는 Feature 순서 (scoring.py와 동일).
_FEATURE_ORDER: tuple[str, ...] = ("weather", "remaining_operating_time", "distance")


@dataclass(frozen=True)
class FeatureContribution:
    """Feature 1개가 최종 점수에 기여한 정도."""

    feature: str
    score: float | None
    weight: float | None
    contribution: float | None  # score * weight; 둘 중 하나라도 결측이면 None


@dataclass(frozen=True)
class RecommendationEvidence:
    """추천 결과 1건의 점수 근거."""

    place_id: str
    name: str
    category: str
    rank: int
    score: float
    contributions: tuple[FeatureContribution, ...]
    is_unverified: bool
    warnings: tuple[str, ...]
    # 문장 조립(explanation.py)에 필요한 원본 값. contributions는 정렬용
    # 정규화 점수만 담으므로 별도로 보존한다.
    distance_km: float
    remaining_minutes: float | None
    weather_condition: WeatherCondition | None
    environment_type: str


def _build_contributions(candidate: RankedCandidate) -> tuple[FeatureContribution, ...]:
    contributions = []
    for feature in _FEATURE_ORDER:
        score = candidate.feature_scores.get(feature)
        weight = candidate.weights_used.get(feature)
        contribution = score * weight if score is not None and weight is not None else None
        contributions.append(
            FeatureContribution(
                feature=feature,
                score=score,
                weight=weight,
                contribution=contribution,
            )
        )
    return tuple(contributions)


def build_evidence(candidate: RankedCandidate) -> RecommendationEvidence:
    """`RankedCandidate` 1건을 `RecommendationEvidence`로 변환한다."""
    return RecommendationEvidence(
        place_id=candidate.place_id,
        name=candidate.name,
        category=candidate.category,
        rank=candidate.rank,
        score=candidate.score,
        contributions=_build_contributions(candidate),
        is_unverified=candidate.is_unverified,
        warnings=candidate.warnings,
        distance_km=candidate.distance_km,
        remaining_minutes=candidate.remaining_minutes,
        weather_condition=candidate.weather_condition,
        environment_type=candidate.environment_type,
    )


def build_evidence_list(result: ScoringResult) -> tuple[RecommendationEvidence, ...]:
    """`ScoringResult.ranked` 전체를 순서 그대로 `RecommendationEvidence` 목록으로 변환한다."""
    return tuple(build_evidence(candidate) for candidate in result.ranked)
