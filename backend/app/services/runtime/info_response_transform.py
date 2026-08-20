"""C의 INFO 장소 카드 묶음을 A의 최종 응답 계약으로 변환한다."""

from __future__ import annotations

from app.agent_context.info_schemas import (
    ConcentrationInfoResult,
    EventInfoResult,
    InfoContextResponse,
    PlaceCard,
    PlaceInfoResult,
)
from app.schemas import InfoPlaceCard, QuestionType
from app.services.runtime.info_display import format_parking_for_display


def to_info_place_card(response: InfoContextResponse) -> InfoPlaceCard | None:
    """장소가 확인된 모든 INFO 결과를 카드 묶음으로 AgentResponse에 전달한다.

    C의 ``location_info``·혼잡도·행사 경로는 비용을 아끼기 위해 PlaceDetails를
    조회하지 않아 ``place_card``가 비어 있을 수 있다. 이 경우에도 사용자가 INFO
    답변 아래에서 같은 장소 맥락을 확인할 수 있도록, C가 이미 확정한 장소명과
    답변 사실만으로 최소 카드를 만든다. Overview·썸네일 같은 상세는 C가 제공한
    경우에만 채운다.
    """

    result = response.result
    if isinstance(result, PlaceInfoResult):
        return _to_place_info_card(result)
    if isinstance(result, ConcentrationInfoResult):
        return _to_concentration_card(result)
    if isinstance(result, EventInfoResult):
        return _to_event_card(result)
    return None


def _to_place_info_card(result: PlaceInfoResult) -> InfoPlaceCard:
    """상세 조회 유무와 관계없이 장소 정보 INFO 카드를 만든다."""

    card = result.place_card or PlaceCard(
        place_id=result.place_id,
        place_name=result.resolved_place_name or result.requested_place_name,
    )
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


def _to_concentration_card(result: ConcentrationInfoResult) -> InfoPlaceCard | None:
    """혼잡도 결과도 장소가 확인됐을 때 최소 카드로 보여준다."""

    place_name = result.requested_place_name or result.resolved_place_name
    if place_name is None:
        return None

    value_parts = [part for part in (result.forecast_date, result.concentration_label) if part]
    return InfoPlaceCard(
        question_type=QuestionType.CONCENTRATION,
        answer_fields={"concentration": " · ".join(value_parts)} if value_parts else {},
        place_name=place_name,
    )


def _to_event_card(result: EventInfoResult) -> InfoPlaceCard | None:
    """행사 INFO도 확정된 장소명을 중심으로 최소 카드를 보여준다."""

    place_name = result.resolved_place_name or result.requested_place_name
    if place_name is None:
        return None

    event_lines = [
        f"{event.title} ({event.start_date}~{event.end_date})" for event in result.events
    ]
    return InfoPlaceCard(
        question_type=QuestionType.EVENT,
        answer_fields={"event": "\n".join(event_lines)} if event_lines else {},
        place_name=place_name,
    )
