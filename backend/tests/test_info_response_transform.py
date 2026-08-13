"""INFO 장소 상세 카드의 C→A 최종 응답 변환을 검증한다."""

from app.agent_context.info_schemas import InfoContextResponse, PlaceCard, PlaceInfoResult
from app.services.runtime.info_response_transform import to_info_place_card


def _response(
    *, status: str = "success", fields: dict[str, str] | None = None
) -> InfoContextResponse:
    return InfoContextResponse(
        request_id="info-card-test",
        status="success",
        result=PlaceInfoResult(
            status=status,  # type: ignore[arg-type]
            question_type="parking",
            fields=fields or {},
            place_card=PlaceCard(
                place_id="126508",
                place_name="경복궁",
                thumbnail_url="https://example.test/gyeongbokgung.jpg",
                overview="조선 왕조의 법궁이다.",
                operating_hours="09:00~18:00",
                parking="가능",
                parking_fee="무료",
                fee="성인 3,000원",
            ),
        ),
    )


def test_transforms_answer_fields_and_full_card_separately() -> None:
    card = to_info_place_card(
        _response(fields={"parking": "가능", "parking_fee": "무료"})
    )

    assert card is not None
    assert card.question_type.value == "parking"
    assert card.answer_fields == {"parking": "가능", "parking_fee": "무료"}
    assert card.overview == "조선 왕조의 법궁이다."
    assert card.operating_hours == "09:00~18:00"
    assert card.thumbnail_url == "https://example.test/gyeongbokgung.jpg"


def test_parking_hides_bus_capacity_from_answer_and_card() -> None:
    response = _response(fields={"parking": "가능 (승용차 240대 / 버스 50대)"})
    result = response.result
    assert isinstance(result, PlaceInfoResult)
    assert result.place_card is not None
    result.place_card.parking = "가능 (승용차 240대 / 버스 50대)"

    card = to_info_place_card(response)

    assert card is not None
    assert card.answer_fields["parking"] == "가능 (승용차 240대)"
    assert card.parking == "가능 (승용차 240대)"


def test_keeps_card_when_requested_field_has_no_data() -> None:
    """질문한 주차 정보가 없더라도 개요 등이 있으면 카드는 보여줄 수 있다."""
    card = to_info_place_card(_response(status="no_data"))

    assert card is not None
    assert card.answer_fields == {}
    assert card.place_name == "경복궁"


def test_returns_none_when_info_result_has_no_card() -> None:
    response = InfoContextResponse(
        request_id="no-card",
        status="success",
        result=PlaceInfoResult(
            status="success",
            question_type="location_info",
            fields={"address": "서울특별시 종로구 사직로 161"},
        ),
    )

    assert to_info_place_card(response) is None
