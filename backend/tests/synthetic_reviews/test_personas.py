import pytest

from app.synthetic_reviews.personas import (
    CompanionTypeTrait,
    PlacePersonaInput,
    PriorityTrait,
    TravelPartyTrait,
    VisitPurposeTrait,
    VisitStyleTrait,
    generate_personas,
)


def _place(**overrides: object) -> PlacePersonaInput:
    values: dict[str, object] = {
        "content_id": "126508",
        "content_type_id": "14",
    }
    values.update(overrides)
    return PlacePersonaInput(**values)  # type: ignore[arg-type]


def test_네_가지_축을_조합해_복합_페르소나를_생성한다() -> None:
    personas = generate_personas(
        _place(
            operating_hours_raw="09:00~18:00",
            parking_info_raw="불가능",
            use_fee_raw="3,000원",
            pet_raw="불가",
        )
    )

    assert len(personas) == 5
    assert personas[0].travel_party is TravelPartyTrait.SOLO
    assert personas[0].companion_type is CompanionTypeTrait.NONE
    assert personas[0].visit_purpose is VisitPurposeTrait.CULTURE
    assert personas[0].priority is PriorityTrait.SCHEDULE
    assert personas[0].visit_style is VisitStyleTrait.FIRST_TIME
    assert personas[0].persona_id == "SOLO_NONE_CULTURE_SCHEDULE_FIRST_TIME"
    assert "혼자" in personas[0].description
    assert "운영 일정" in personas[0].description


def test_공식_정보가_있는_중요_조건만_근거와_함께_쓴다() -> None:
    personas = generate_personas(
        _place(parking_info_raw="가능", parking_fee_raw="무료")
    )

    parking = personas[0]
    assert parking.priority is PriorityTrait.PARKING
    assert "주차를 중요하게" in parking.description
    assert parking.evidence_fields == ("parking_info_raw", "parking_fee_raw")
    assert parking.allowed_evaluation_axes == (
        "PARKING_AVAILABILITY",
        "PARKING_FEE",
    )


def test_빈_공식_정보는_중요_조건으로_선정하지_않는다() -> None:
    personas = generate_personas(
        _place(parking_info_raw="  ", pet_raw="", use_fee_raw=None)
    )

    assert all(persona.priority is PriorityTrait.GENERAL for persona in personas)
    assert all(persona.evidence_fields == () for persona in personas)
    assert all(
        persona.allowed_evaluation_axes == ("PERSONAL_PREFERENCE", "ITINERARY_FIT")
        for persona in personas
    )


def test_알_수_없는_장소_유형은_일반_탐색_목적으로_안전하게_대체한다() -> None:
    personas = generate_personas(_place(content_type_id="999"), target_count=5)

    assert len(personas) == 5
    assert all(
        persona.visit_purpose is VisitPurposeTrait.GENERAL_EXPLORATION
        for persona in personas
    )
    assert all("content_type_id" not in persona.evidence_fields for persona in personas)


def test_페르소나마다_조합과_id가_중복되지_않는다() -> None:
    personas = generate_personas(
        _place(
            operating_hours_raw="09:00~18:00",
            parking_info_raw="가능",
            use_fee_raw="무료",
            pet_raw="불가",
            baby_carriage_raw="없음",
        ),
        target_count=5,
    )

    assert len({persona.persona_id for persona in personas}) == 5
    assert [persona.priority for persona in personas] == [
        PriorityTrait.SCHEDULE,
        PriorityTrait.PARKING,
        PriorityTrait.BUDGET,
        PriorityTrait.PET,
        PriorityTrait.STROLLER,
    ]
    assert [persona.travel_party for persona in personas] == [
        TravelPartyTrait.SOLO,
        TravelPartyTrait.COMPANION,
        TravelPartyTrait.SOLO,
        TravelPartyTrait.COMPANION,
        TravelPartyTrait.SOLO,
    ]
    assert [persona.companion_type for persona in personas] == [
        CompanionTypeTrait.NONE,
        CompanionTypeTrait.CHILD,
        CompanionTypeTrait.NONE,
        CompanionTypeTrait.OLDER_ADULT,
        CompanionTypeTrait.NONE,
    ]


def test_동행자_유형은_content_id에_따라_결정적으로_다양화한다() -> None:
    first = generate_personas(_place(content_id="1"), target_count=4)
    second = generate_personas(_place(content_id="2"), target_count=4)

    first_companions = [
        persona.companion_type
        for persona in first
        if persona.travel_party is TravelPartyTrait.COMPANION
    ]
    second_companions = [
        persona.companion_type
        for persona in second
        if persona.travel_party is TravelPartyTrait.COMPANION
    ]
    assert first_companions != second_companions
    assert all(item is not CompanionTypeTrait.NONE for item in first_companions)


def test_같은_입력은_항상_같은_페르소나를_만든다() -> None:
    place = _place(operating_hours_raw="09:00~18:00", parking_info_raw="가능")

    assert generate_personas(place) == generate_personas(place)


@pytest.mark.parametrize("target_count", [2, 6])
def test_페르소나_수는_3개에서_5개_사이만_허용한다(target_count: int) -> None:
    with pytest.raises(ValueError, match="3~5"):
        generate_personas(_place(), target_count=target_count)


@pytest.mark.parametrize("field", ["content_id", "content_type_id"])
def test_장소_식별자는_필수다(field: str) -> None:
    values = {"content_id": "1", "content_type_id": "14", field: " "}
    with pytest.raises(ValueError, match=field):
        PlacePersonaInput(**values)
