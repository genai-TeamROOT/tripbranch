"""D의 RecommendationItem을 사용자에게 보여줄 자연어 문장으로 조립한다.

역할: D가 만든 explanations(근거 문장)와 warnings(경고 문장)를 D님과 협의한
순서(근거 먼저, 경고는 "다만~"으로 마지막)로 이어붙인다. 문장 내용 자체는
재작문하지 않고 D가 만든 그대로 쓴다 — 특정 문자열을 검사하는 조건 분기를
넣지 않는다(날씨 결측/임계값 미달 등 warnings 문구가 나중에 추가·변경돼도
이 함수는 손댈 필요가 없어야 한다).
"""

from __future__ import annotations

from app.schemas import RecommendationItem


def compose_recommendation_message(item: RecommendationItem) -> str:
    """explanations를 먼저, warnings는 "다만, ~" 형태로 마지막에 붙인다.

    explanations/warnings 둘 다 이미 완결된 문장(마침표 포함)이라 공백으로
    이어붙인다. explanations는 빈 배열일 수 있다(임계값 미달 등) — 그 경우
    warnings만 "다만, ~"으로 반환한다.
    """
    parts: list[str] = []
    if item.explanations:
        parts.append(" ".join(item.explanations))
    if item.warnings:
        parts.append(f"다만, {' '.join(item.warnings)}")
    return " ".join(parts)


__all__ = ["compose_recommendation_message"]
