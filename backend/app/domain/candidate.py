# 추천 후보 하나를 표현하는 ScoredCandidate 데이터클래스.
# recommendation_service가 Place + 계산된 거리/남은시간/점수/추천사유/경고를 묶어서 만들고,
# api/routes/recommendations.py가 이걸 RecommendationItem(응답 스키마)로 변환한다.
# 사용법: 새 필드가 필요하면 여기 추가하고, recommendation_service._build_candidate()와
# routes/recommendations.py의 _to_item()도 같이 수정해야 한다(두 군데가 짝을 이룸).

"""Intermediate representation of a scored recommendation candidate,
produced by domain scoring and consumed by services/sorting."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import EnvironmentType, Place
from app.domain.scoring import ScoreBreakdown


@dataclass(frozen=True)
class ScoredCandidate:
    place: Place
    distance_km: float
    remaining_minutes: int | None
    environment_type: EnvironmentType
    score_breakdown: ScoreBreakdown
    total_score: float
    recommendation_reason: str
    warnings: list[str]
