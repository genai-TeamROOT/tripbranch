"""INFO 장소 상세 카드의 C→A 최종 응답 변환을 검증한다."""

from app.agent_context.info_schemas import (
    ConcentrationInfoResult,
    EventInfoResult,
    EventItem,
    InfoContextResponse,
    PlaceCard,
    PlaceInfoResult,
    RealtimeCommercialInfoResult,
)
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
    card = to_info_place_card(_response(fields={"parking": "가능", "parking_fee": "무료"}))

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


def test_location_info_without_c_place_card_still_returns_minimum_card() -> None:
    """C가 주소 조회에서 상세 API를 생략해도 INFO 카드 자체는 항상 보인다."""
    response = InfoContextResponse(
        request_id="no-card",
        status="success",
        result=PlaceInfoResult(
            status="success",
            question_type="location_info",
            requested_place_name="건청궁",
            resolved_place_name="건청궁",
            place_id="126508",
            fields={"address": "서울특별시 종로구 사직로 161"},
        ),
    )

    card = to_info_place_card(response)

    assert card is not None
    assert card.question_type.value == "location_info"
    assert card.place_name == "건청궁"
    assert card.place_id == "126508"
    assert card.answer_fields == {"address": "서울특별시 종로구 사직로 161"}
    assert card.thumbnail_url is None
    assert card.overview is None


def test_concentration_and_event_results_also_return_minimum_cards() -> None:
    concentration = to_info_place_card(
        InfoContextResponse(
            request_id="concentration-card",
            status="success",
            result=ConcentrationInfoResult(
                status="success",
                requested_place_name="경복궁",
                resolved_place_name="경복궁",
                forecast_date="2026-08-19",
                concentration_label="보통",
            ),
        )
    )
    event = to_info_place_card(
        InfoContextResponse(
            request_id="event-card",
            status="success",
            result=EventInfoResult(
                status="success",
                requested_place_name="경복궁",
                resolved_place_name="경복궁",
                events=[
                    EventItem(
                        title="경복궁 별빛야행",
                        start_date="2026-08-19",
                        end_date="2026-08-20",
                    )
                ],
            ),
        )
    )

    assert concentration is not None
    assert concentration.answer_fields == {"concentration": "2026-08-19 · 보통"}
    assert event is not None
    assert event.answer_fields == {"event": "경복궁 별빛야행 (2026-08-19~2026-08-20)"}


def test_realtime_commercial_result_returns_proxy_card() -> None:
    card = to_info_place_card(
        InfoContextResponse(
            request_id="commercial-card",
            status="success",
            result=RealtimeCommercialInfoResult(
                status="success",
                requested_place_name="테스트 카페",
                area_name="용리단길",
                category_label="음식·음료 · 커피·음료",
                commercial_level="바쁜 시간대",
                observed_at="2026-08-20 14:00",
            ),
        )
    )

    assert card is not None
    assert card.question_type.value == "realtime_commercial"
    assert card.place_name == "테스트 카페"
    assert card.answer_fields["상권 지역"] == "용리단길"
    assert card.answer_fields["실시간 활동"] == "바쁜 시간대"
    assert card.answer_fields["기준 시각"] == "8월 20일 14:00"


def test_realtime_commercial_area_overall_card_discloses_scope() -> None:
    card = to_info_place_card(
        InfoContextResponse(
            request_id="commercial-area-card",
            status="success",
            result=RealtimeCommercialInfoResult(
                status="success",
                requested_place_name="테스트 카페",
                area_name="용리단길",
                commercial_level="한산한",
                commercial_scope="area_overall",
            ),
        )
    )

    assert card is not None
    assert card.answer_fields["상권 기준"] == "지역 전체 상권 (카페 업종 세부값 미제공)"
