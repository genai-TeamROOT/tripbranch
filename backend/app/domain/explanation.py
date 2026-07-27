"""추천 Explainability Layer v1: Evidence를 Rule 기반 문장으로 변환한다 (D-06).

역할: `RecommendationEvidence.contributions`(Feature별 score/weight/contribution)를
바탕으로, 사용자가 이해할 수 있는 한국어 문장 목록을 생성한다. LLM을 호출하지
않는 Rule 기반·결정적 구조라 동일 입력에는 항상 동일한 문장이 나온다.
입력: `RecommendationEvidence` (`backend/app/domain/evidence.py`).
출력: `tuple[str, ...]` (0~3개, Feature 점수가 임계값 이상인 것만 포함).
호출 시점: 추천 파이프라인이 응답을 조립할 때 Evidence 계산 직후 호출한다.
설계 근거: `package_D/[D-06] Recommendation Explainability Layer.txt`.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.domain.evidence import FeatureContribution, RecommendationEvidence

# 이 점수 이상인 Feature만 "특별히 강조할 이유"로 문장화한다.
# 결측(None)이거나 애매한 점수(< 임계값)는 문장을 생략한다 — 결측은 이미
# warnings가 별도로 안내하므로 중복 설명하지 않는다.
_EXPLANATION_SCORE_THRESHOLD = 0.7

_EXPLANATION_SENTENCES: Mapping[str, str] = {
    "weather": "지금 날씨 조건에 잘 맞는 장소예요.",
    "remaining_operating_time": "운영 종료까지 시간 여유가 있어 방문하기 좋아요.",
    "distance": "현재 위치에서 가까운 장소예요.",
}


def _is_notable(contribution: FeatureContribution) -> bool:
    return (
        contribution.score is not None
        and contribution.score >= _EXPLANATION_SCORE_THRESHOLD
    )


def build_explanations(evidence: RecommendationEvidence) -> tuple[str, ...]:
    """기여도(score × weight)가 큰 순서로, 임계값 이상인 Feature만 문장화한다.

    기여도가 같으면 `contributions`에 이미 고정된 Feature 순서(weather →
    remaining_operating_time → distance)를 그대로 tie-break로 사용해
    결정적 순서를 보장한다.
    """
    notable = [
        (index, contribution)
        for index, contribution in enumerate(evidence.contributions)
        if _is_notable(contribution)
    ]
    notable.sort(key=lambda pair: (-(pair[1].contribution or 0.0), pair[0]))
    return tuple(_EXPLANATION_SENTENCES[contribution.feature] for _, contribution in notable)
