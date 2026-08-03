"""to_agent_context_request() 단위 테스트.

concentration-conditions.md §2.2/§4.2 관련: A의 UserConditions에
concentration_intent가 추가된 뒤에도, C의 ContextUserConditions(StrictModel,
extra="forbid")가 아직 그 필드를 모르는 과도기에 ValidationError 없이 안전하게
넘어가는지 확인한다.
"""

from __future__ import annotations

from app.schemas import ConcentrationIntent, PlaceTag, PlaceType, UserConditions, WeatherIntent
from app.services.runtime.context_transform import to_agent_context_request


class TestToAgentContextRequest:
    def test_round_trips_existing_fields(self) -> None:
        conditions = UserConditions(
            current_location="홍대",
            search_center="경복궁",
            place_types=[PlaceType.RESTAURANT],
            place_tags=[PlaceTag.CAFE],
            weather_intent=WeatherIntent.AVOID,
        )

        request = to_agent_context_request("req-1", conditions)

        assert request.request_id == "req-1"
        assert request.intent == "RECOMMEND"
        assert request.conditions.current_location == "홍대"
        assert request.conditions.search_center == "경복궁"
        assert request.conditions.place_types == ["restaurant"]
        assert request.conditions.place_tags == ["카페"]
        assert request.conditions.weather_intent == "AVOID"

    def test_concentration_intent_does_not_raise_before_c_adds_field(self) -> None:
        """C의 ContextUserConditions가 concentration_intent를 아직 모르는 상태를
        가정한다 — extra="forbid"라 그대로 넘기면 ValidationError가 난다.
        to_agent_context_request()가 C가 모르는 필드를 걸러내는지 확인한다.
        """
        conditions = UserConditions(concentration_intent=ConcentrationIntent.AVOID)

        request = to_agent_context_request("req-2", conditions)

        assert not hasattr(request.conditions, "concentration_intent")

    def test_no_conditions_still_builds_valid_request(self) -> None:
        request = to_agent_context_request("req-3", UserConditions())

        assert request.conditions.current_location is None
        assert request.conditions.place_types == []

    def test_converts_gps_string_to_coordinates(self) -> None:
        request = to_agent_context_request(
            "req-4", UserConditions(), gps_location="37.5796,126.9770"
        )

        assert request.gps_location is not None
        assert request.gps_location.latitude == 37.5796
        assert request.gps_location.longitude == 126.9770

    def test_invalid_gps_is_omitted(self) -> None:
        request = to_agent_context_request(
            "req-5", UserConditions(), gps_location="91.0,126.9770"
        )

        assert request.gps_location is None
