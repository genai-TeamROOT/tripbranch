"""C의 INFO 장소 카드 묶음을 A의 최종 응답 계약으로 변환한다."""

from __future__ import annotations

from app.agent_context.info_schemas import InfoContextResponse, PlaceInfoResult
from app.schemas import InfoPlaceCard, QuestionType
from app.services.runtime.info_display import format_parking_for_display


def to_info_place_card(response: InfoContextResponse) -> InfoPlaceCard | None:
    """장소 상세 결과의 카드 묶음만 AgentResponse로 전달한다.

    ``fields``가 비어 ``no_data``인 경우에도 C가 ``place_card``를 제공했다면
    카드는 반환한다. 예를 들어 주차 정보는 없지만 장소 개요·운영시간은 있을 수
    있기 때문이다. 사용자 답변의 "정보 없음" 판정은 여전히 ``fields``가 맡는다.
    """

    result = response.result
    if not isinstance(result, PlaceInfoResult) or result.place_card is None:
        return None

    card = result.place_card
    return InfoPlaceCard(
        question_type=QuestionType(result.question_type),
        answer_fields={
            key: format_parking_for_display(value) if key == "parking" else value
            for key, value in result.fields.items()
        },
        place_id=card.place_id,
        place_name=card.place_name,
        thumbnail_url=card.thumbnail_url,
        overview=card.overview,
        operating_hours=card.operating_hours,
        rest_date=card.rest_date,
        parking=format_parking_for_display(card.parking),
        parking_fee=card.parking_fee,
        fee=card.fee,
        baby_carriage=card.baby_carriage,
        pet=card.pet,
        credit_card=card.credit_card,
        restroom=card.restroom,
        homepage=card.homepage,
    )
