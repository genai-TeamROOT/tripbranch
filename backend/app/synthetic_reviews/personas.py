"""TourAPI 장소 속성으로 리뷰 작성자용 복합 페르소나를 결정적으로 생성한다.

여행 구성·방문 목적·중요 조건·방문 스타일을 조합한다. 이 단계는 감정이나 리뷰
문장을 만들지 않으며, 이후 생성기가 평가할 수 있는 공식 근거의 경계만 제공한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TravelPartyTrait(StrEnum):
    SOLO = "SOLO"
    COMPANION = "COMPANION"


class VisitPurposeTrait(StrEnum):
    ATTRACTION = "ATTRACTION"
    CULTURE = "CULTURE"
    FESTIVAL = "FESTIVAL"
    LEISURE = "LEISURE"
    ACCOMMODATION = "ACCOMMODATION"
    SHOPPING = "SHOPPING"
    FOOD = "FOOD"
    GENERAL_EXPLORATION = "GENERAL_EXPLORATION"


class PriorityTrait(StrEnum):
    SCHEDULE = "SCHEDULE"
    PARKING = "PARKING"
    BUDGET = "BUDGET"
    PET = "PET"
    STROLLER = "STROLLER"
    CARD_PAYMENT = "CARD_PAYMENT"
    RESTROOM = "RESTROOM"
    INFORMATION = "INFORMATION"
    GENERAL = "GENERAL"


class VisitStyleTrait(StrEnum):
    FIRST_TIME = "FIRST_TIME"
    RETURN_CONSIDERING = "RETURN_CONSIDERING"
    SPONTANEOUS = "SPONTANEOUS"
    RELAXED = "RELAXED"
    MULTI_STOP = "MULTI_STOP"


@dataclass(frozen=True)
class PlacePersonaInput:
    content_id: str
    content_type_id: str
    operating_hours_raw: str | None = None
    rest_date_raw: str | None = None
    parking_info_raw: str | None = None
    parking_fee_raw: str | None = None
    use_fee_raw: str | None = None
    discount_info_raw: str | None = None
    info_center_raw: str | None = None
    baby_carriage_raw: str | None = None
    pet_raw: str | None = None
    credit_card_raw: str | None = None
    restroom_raw: str | None = None

    def __post_init__(self) -> None:
        if not self.content_id.strip():
            raise ValueError("content_id가 필요합니다.")
        if not self.content_type_id.strip():
            raise ValueError("content_type_id가 필요합니다.")


@dataclass(frozen=True)
class CompositePersona:
    persona_id: str
    description: str
    travel_party: TravelPartyTrait
    visit_purpose: VisitPurposeTrait
    priority: PriorityTrait
    visit_style: VisitStyleTrait
    evidence_fields: tuple[str, ...]
    allowed_evaluation_axes: tuple[str, ...]


@dataclass(frozen=True)
class _PriorityRule:
    trait: PriorityTrait
    fields: tuple[str, ...]
    axes: tuple[str, ...]


_PRIORITY_RULES = (
    _PriorityRule(
        PriorityTrait.SCHEDULE,
        ("operating_hours_raw", "rest_date_raw"),
        ("OPERATING_HOURS", "REST_DATE"),
    ),
    _PriorityRule(
        PriorityTrait.PARKING,
        ("parking_info_raw", "parking_fee_raw"),
        ("PARKING_AVAILABILITY", "PARKING_FEE"),
    ),
    _PriorityRule(
        PriorityTrait.BUDGET,
        ("use_fee_raw", "discount_info_raw"),
        ("USE_FEE", "DISCOUNT"),
    ),
    _PriorityRule(PriorityTrait.PET, ("pet_raw",), ("PET_POLICY",)),
    _PriorityRule(
        PriorityTrait.STROLLER, ("baby_carriage_raw",), ("STROLLER_POLICY",)
    ),
    _PriorityRule(
        PriorityTrait.CARD_PAYMENT, ("credit_card_raw",), ("CARD_PAYMENT",)
    ),
    _PriorityRule(PriorityTrait.RESTROOM, ("restroom_raw",), ("RESTROOM",)),
    _PriorityRule(
        PriorityTrait.INFORMATION, ("info_center_raw",), ("INFORMATION_CONTACT",)
    ),
)

_TYPE_PURPOSES = {
    "12": VisitPurposeTrait.ATTRACTION,
    "14": VisitPurposeTrait.CULTURE,
    "15": VisitPurposeTrait.FESTIVAL,
    "28": VisitPurposeTrait.LEISURE,
    "32": VisitPurposeTrait.ACCOMMODATION,
    "38": VisitPurposeTrait.SHOPPING,
    "39": VisitPurposeTrait.FOOD,
}

_PARTIES = (TravelPartyTrait.SOLO, TravelPartyTrait.COMPANION)
_STYLES = (
    VisitStyleTrait.FIRST_TIME,
    VisitStyleTrait.RETURN_CONSIDERING,
    VisitStyleTrait.SPONTANEOUS,
    VisitStyleTrait.RELAXED,
    VisitStyleTrait.MULTI_STOP,
)

_PARTY_LABELS = {
    TravelPartyTrait.SOLO: "혼자",
    TravelPartyTrait.COMPANION: "동행자와",
}
_PURPOSE_LABELS = {
    VisitPurposeTrait.ATTRACTION: "관광지를 둘러보는",
    VisitPurposeTrait.CULTURE: "문화 공간을 탐방하는",
    VisitPurposeTrait.FESTIVAL: "축제를 찾는",
    VisitPurposeTrait.LEISURE: "레포츠를 즐기려는",
    VisitPurposeTrait.ACCOMMODATION: "숙박을 고려하는",
    VisitPurposeTrait.SHOPPING: "쇼핑을 계획하는",
    VisitPurposeTrait.FOOD: "음식을 경험하려는",
    VisitPurposeTrait.GENERAL_EXPLORATION: "새로운 장소를 둘러보는",
}
_PRIORITY_LABELS = {
    PriorityTrait.SCHEDULE: "운영 일정",
    PriorityTrait.PARKING: "주차",
    PriorityTrait.BUDGET: "비용",
    PriorityTrait.PET: "반려동물 동반",
    PriorityTrait.STROLLER: "유모차 이용",
    PriorityTrait.CARD_PAYMENT: "카드 결제",
    PriorityTrait.RESTROOM: "화장실 정보",
    PriorityTrait.INFORMATION: "공식 안내 정보",
    PriorityTrait.GENERAL: "전체 일정과의 조화",
}
_STYLE_LABELS = {
    VisitStyleTrait.FIRST_TIME: "처음 방문하며",
    VisitStyleTrait.RETURN_CONSIDERING: "재방문을 고려하며",
    VisitStyleTrait.SPONTANEOUS: "즉흥적으로",
    VisitStyleTrait.RELAXED: "여유 있게",
    VisitStyleTrait.MULTI_STOP: "여러 장소를 잇는 일정으로",
}


def _present(value: str | None) -> bool:
    return value is not None and bool(value.strip())


def _available_priorities(
    place: PlacePersonaInput,
) -> tuple[tuple[PriorityTrait, tuple[str, ...], tuple[str, ...]], ...]:
    available: list[tuple[PriorityTrait, tuple[str, ...], tuple[str, ...]]] = []
    for rule in _PRIORITY_RULES:
        evidence_fields = tuple(
            field for field in rule.fields if _present(getattr(place, field))
        )
        if not evidence_fields:
            continue
        axes = tuple(
            axis
            for field, axis in zip(rule.fields, rule.axes, strict=True)
            if field in evidence_fields
        )
        available.append((rule.trait, evidence_fields, axes))
    return tuple(available)


def _description(
    party: TravelPartyTrait,
    purpose: VisitPurposeTrait,
    priority: PriorityTrait,
    style: VisitStyleTrait,
) -> str:
    priority_label = _PRIORITY_LABELS[priority]
    return (
        f"{_STYLE_LABELS[style]} {_PARTY_LABELS[party]} "
        f"{_PURPOSE_LABELS[purpose]} 여행자. "
        f"{priority_label}{_object_particle(priority_label)} 중요하게 본다."
    )


def _object_particle(label: str) -> str:
    """마지막 한글 음절의 받침 유무에 따라 목적격 조사를 고른다."""
    last = label[-1]
    codepoint = ord(last)
    if 0xAC00 <= codepoint <= 0xD7A3:
        return "을" if (codepoint - 0xAC00) % 28 else "를"
    return "를"


def generate_personas(
    place: PlacePersonaInput, *, target_count: int = 4
) -> tuple[CompositePersona, ...]:
    """장소별로 서로 다른 복합 페르소나 3~5개를 생성한다."""
    if not 3 <= target_count <= 5:
        raise ValueError("target_count는 3~5여야 합니다.")

    purpose = _TYPE_PURPOSES.get(
        place.content_type_id.strip(), VisitPurposeTrait.GENERAL_EXPLORATION
    )
    priorities = list(_available_priorities(place))
    priorities.extend(
        (PriorityTrait.GENERAL, (), ("PERSONAL_PREFERENCE", "ITINERARY_FIT"))
        for _ in range(max(0, target_count - len(priorities)))
    )

    personas: list[CompositePersona] = []
    for index, (priority, priority_fields, priority_axes) in enumerate(
        priorities[:target_count]
    ):
        party = _PARTIES[index % len(_PARTIES)]
        style = _STYLES[index]
        known_purpose = purpose is not VisitPurposeTrait.GENERAL_EXPLORATION
        evidence_fields = (
            ("content_type_id", *priority_fields) if known_purpose else priority_fields
        )
        axes = ("PLACE_TYPE_FIT", *priority_axes) if known_purpose else priority_axes
        persona_id = "_".join((party.value, purpose.value, priority.value, style.value))
        personas.append(
            CompositePersona(
                persona_id=persona_id,
                description=_description(party, purpose, priority, style),
                travel_party=party,
                visit_purpose=purpose,
                priority=priority,
                visit_style=style,
                evidence_fields=evidence_fields,
                allowed_evaluation_axes=axes,
            )
        )
    return tuple(personas)


__all__ = [
    "CompositePersona",
    "PlacePersonaInput",
    "PriorityTrait",
    "TravelPartyTrait",
    "VisitPurposeTrait",
    "VisitStyleTrait",
    "generate_personas",
]
