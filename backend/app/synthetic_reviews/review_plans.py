"""복합 페르소나에 장소별 합성 리뷰 작성 계획을 결정적으로 배분한다."""

from __future__ import annotations

from dataclasses import dataclass

from app.synthetic_reviews.personas import CompositePersona

DEFAULT_REVIEWS_PER_PLACE = 8

_CONTEXT_TEMPLATES = (
    "공식 장소 정보를 확인하고 방문 여부를 계획하는 상황",
    "다른 일정과 함께 방문 순서를 조정하는 상황",
    "같은 목적의 방문 후보와 비교해 선택을 검토하는 상황",
)

# 장소 유형은 모든 복합 페르소나에 공통으로 붙는다. 구체적인 공식 속성이 있으면
# 먼저 평가하고, 같은 페르소나의 다음 리뷰에서 유형 적합성을 다루게 한다.
_SECONDARY_AXES = frozenset({"PLACE_TYPE_FIT", "PERSONAL_PREFERENCE", "ITINERARY_FIT"})


@dataclass(frozen=True)
class ReviewPlan:
    review_index: int
    persona_id: str
    persona_description: str
    visit_context: str
    focus_axes: tuple[str, ...]
    evidence_fields: tuple[str, ...]


def _ordered_axes(persona: CompositePersona) -> tuple[str, ...]:
    specific = tuple(
        axis for axis in persona.allowed_evaluation_axes if axis not in _SECONDARY_AXES
    )
    secondary = tuple(
        axis for axis in persona.allowed_evaluation_axes if axis in _SECONDARY_AXES
    )
    return (*specific, *secondary)


def generate_review_plans(
    personas: tuple[CompositePersona, ...],
    *,
    review_count: int = DEFAULT_REVIEWS_PER_PLACE,
) -> tuple[ReviewPlan, ...]:
    """3~5개 페르소나에 리뷰를 round-robin으로 배분한다.

    모든 페르소나에 한 건씩 먼저 배정하고 앞에서부터 추가 배정하므로 기본 8건은
    3명일 때 3·3·2, 4명일 때 2·2·2·2, 5명일 때 2·2·2·1·1이 된다.
    """
    if not 3 <= len(personas) <= 5:
        raise ValueError("페르소나는 3~5개여야 합니다.")
    if review_count < len(personas):
        raise ValueError("review_count는 페르소나 수 이상이어야 합니다.")
    if review_count > len(personas) * len(_CONTEXT_TEMPLATES):
        raise ValueError("페르소나별 고유 visitContext는 최대 3개입니다.")
    persona_ids = [persona.persona_id for persona in personas]
    if len(set(persona_ids)) != len(persona_ids):
        raise ValueError("persona_id는 중복될 수 없습니다.")

    occurrence_counts = [0] * len(personas)
    plans: list[ReviewPlan] = []
    for review_index in range(review_count):
        persona_index = review_index % len(personas)
        persona = personas[persona_index]
        occurrence = occurrence_counts[persona_index]
        occurrence_counts[persona_index] += 1
        axes = _ordered_axes(persona)
        focus_axes = (axes[occurrence % len(axes)],) if axes else ()
        plans.append(
            ReviewPlan(
                review_index=review_index,
                persona_id=persona.persona_id,
                persona_description=persona.description,
                visit_context=_CONTEXT_TEMPLATES[occurrence],
                focus_axes=focus_axes,
                evidence_fields=persona.evidence_fields,
            )
        )
    return tuple(plans)


__all__ = ["DEFAULT_REVIEWS_PER_PLACE", "ReviewPlan", "generate_review_plans"]
