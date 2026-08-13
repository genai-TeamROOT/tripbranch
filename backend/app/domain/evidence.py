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

from collections.abc import Mapping
from dataclasses import dataclass

from app.concentration_policy import ConcentrationLevel
from app.domain.models import WeatherCondition
from app.domain.scoring import RankedCandidate, ScoringResult
from app.domain.weather_judgment import WeatherReason

# 1차 Scoring 결과의 Feature 순서 (scoring.py DEFAULT_WEIGHTS와 동일).
_FEATURE_ORDER: tuple[str, ...] = ("weather", "remaining_operating_time", "distance")

# 요청 환경으로 채점된 실행(scoring.py::uses_environment_feature)의 순서. 날씨와
# 환경은 같은 자리를 나눠 쓰므로 Feature 개수는 그대로 3개다.
_ENVIRONMENT_FEATURE_ORDER: tuple[str, ...] = (
    "environment",
    "remaining_operating_time",
    "distance",
)

# 2차 Scoring(rerank_with_concentration(), D-040) 결과의 Feature 순서. concentration은
# 1차 결과의 feature_scores에는 키 자체가 없다(결측이 아니라 "존재하지 않음" —
# concentration-conditions.md §2.3) — 그래서 1차용 _FEATURE_ORDER에는 넣지 않고,
# 이 상수를 별도로 둔다.
CONCENTRATION_FEATURE_ORDER: tuple[str, ...] = (*_FEATURE_ORDER, "concentration")
ENVIRONMENT_CONCENTRATION_FEATURE_ORDER: tuple[str, ...] = (
    *_ENVIRONMENT_FEATURE_ORDER,
    "concentration",
)


def resolve_feature_order(feature_scores: Mapping[str, float | None]) -> tuple[str, ...]:
    """실제로 채점된 Feature 키를 보고 순서를 고른다.

    날씨/환경 중 어느 쪽으로 채점됐는지는 호출부가 다시 판단하지 않는다 —
    `feature_scores`에 들어 있는 키가 그대로 답이다.
    """
    environment_driven = "environment" in feature_scores
    with_concentration = "concentration" in feature_scores
    if environment_driven:
        return (
            ENVIRONMENT_CONCENTRATION_FEATURE_ORDER
            if with_concentration
            else _ENVIRONMENT_FEATURE_ORDER
        )
    return CONCENTRATION_FEATURE_ORDER if with_concentration else _FEATURE_ORDER


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
    # D-040: 2차 Scoring에서만 채워진다(scoring.py::RankedCandidate.concentration_level
    # 참고) — concentration_score(direction 반영됨)만으로는 실제 붐빔 정도를 알 수
    # 없어서, 문장 조립에 원본 4단계 구간을 그대로 보존한다.
    concentration_level: ConcentrationLevel | None = None
    # weather_condition만으로는 "왜"(비/눈/폭염/한파)를 알 수 없어서 문장 조립에
    # 따로 필요하다(scoring.py::RankedCandidate.weather_reason 참고).
    weather_reason: WeatherReason = None


def _build_contributions(
    candidate: RankedCandidate, feature_order: tuple[str, ...]
) -> tuple[FeatureContribution, ...]:
    contributions = []
    for feature in feature_order:
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


def build_evidence(
    candidate: RankedCandidate, *, feature_order: tuple[str, ...] | None = None
) -> RecommendationEvidence:
    """`RankedCandidate` 1건을 `RecommendationEvidence`로 변환한다.

    `feature_order`를 생략하면 `candidate.feature_scores`에 실제로 들어 있는
    키로 순서를 정한다(`resolve_feature_order()`) — 2차 Scoring(D-040)의
    `"concentration"`과 요청 환경 채점의 `"environment"`가 모두 여기서 갈린다.
    """
    resolved_order = feature_order or resolve_feature_order(candidate.feature_scores)
    return RecommendationEvidence(
        place_id=candidate.place_id,
        name=candidate.name,
        category=candidate.category,
        rank=candidate.rank,
        score=candidate.score,
        contributions=_build_contributions(candidate, resolved_order),
        is_unverified=candidate.is_unverified,
        warnings=candidate.warnings,
        distance_km=candidate.distance_km,
        remaining_minutes=candidate.remaining_minutes,
        weather_condition=candidate.weather_condition,
        environment_type=candidate.environment_type,
        concentration_level=candidate.concentration_level,
        weather_reason=candidate.weather_reason,
    )


def build_evidence_list(result: ScoringResult) -> tuple[RecommendationEvidence, ...]:
    """`ScoringResult.ranked` 전체를 순서 그대로 `RecommendationEvidence` 목록으로 변환한다."""
    return tuple(build_evidence(candidate) for candidate in result.ranked)
