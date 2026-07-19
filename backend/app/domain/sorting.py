# 추천 후보 정렬(동점 처리)과 이미 보여준 장소 제외 로직.
# 정렬 기준: total_score -> category -> remaining_open_time -> weather -> distance -> 이름
# (모두 내림차순, 이름만 오름차순) 순서로 tie-break. 사용법: recommendation_service에서
# sort_candidates() 후 exclude_shown()을 적용한다(순서를 바꾸면 "다른 장소 보기"가
# 이미 정렬된 결과에서 제외만 하는 대신 재정렬까지 해버릴 수 있으니 주의).

"""Tie-break ordering and shown-place exclusion for recommendation candidates."""

from __future__ import annotations

from app.domain.candidate import ScoredCandidate


def sort_candidates(candidates: list[ScoredCandidate]) -> list[ScoredCandidate]:
    """Sort by total_score desc, then tie-break in order:
    category score -> remaining_open_time score -> weather score
    -> distance score -> place name (asc).
    """

    def sort_key(candidate: ScoredCandidate) -> tuple:
        breakdown = candidate.score_breakdown
        return (
            -candidate.total_score,
            -breakdown.category,
            -breakdown.remaining_open_time,
            -(breakdown.weather if breakdown.weather is not None else 0.0),
            -breakdown.distance,
            candidate.place.name,
        )

    return sorted(candidates, key=sort_key)


def exclude_shown(
    candidates: list[ScoredCandidate], shown_place_ids: set[str]
) -> list[ScoredCandidate]:
    return [c for c in candidates if c.place.id not in shown_place_ids]
