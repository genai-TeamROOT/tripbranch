import pytest
from pydantic import ValidationError

from app.agent_context.schemas import AgentContextRequest


def _request_payload() -> dict[str, object]:
    return {
        "request_id": "req_01JABC",
        "intent": "RECOMMEND",
        "conditions": {
            "current_location": "경복궁",
            "search_center": None,
            "place_types": ["restaurant"],
            "place_tags": ["카페"],
            "weather": "rain",
            "weather_intent": "AVOID",
            "transport": "walk",
            "max_travel_time": 20,
            "time_available": 120,
            "environment": "indoor",
            "companion": "friend",
            "budget": None,
            "exclude_tags": [],
            "special_requirements": [],
        },
    }


def test_validates_recommend_context_request() -> None:
    request = AgentContextRequest.model_validate(_request_payload())

    assert request.request_id == "req_01JABC"
    assert request.conditions.current_location == "경복궁"
    assert request.conditions.weather == "rain"


def test_allows_missing_location_for_service_clarification() -> None:
    payload = _request_payload()
    conditions = payload["conditions"]
    assert isinstance(conditions, dict)
    conditions["current_location"] = None
    conditions["search_center"] = None

    request = AgentContextRequest.model_validate(payload)

    assert request.conditions.current_location is None
    assert request.conditions.search_center is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("current_location", " "),
        ("place_types", ["restaurant", " "]),
        ("max_travel_time", 0),
        ("time_available", -1),
    ],
)
def test_rejects_invalid_condition_values(field: str, value: object) -> None:
    payload = _request_payload()
    conditions = payload["conditions"]
    assert isinstance(conditions, dict)
    conditions[field] = value

    with pytest.raises(ValidationError):
        AgentContextRequest.model_validate(payload)


def test_rejects_unknown_fields() -> None:
    payload = _request_payload()
    payload["tool_type"] = "get_weather_forecast"

    with pytest.raises(ValidationError):
        AgentContextRequest.model_validate(payload)


def test_serializes_with_snake_case_fields() -> None:
    dumped = AgentContextRequest.model_validate(_request_payload()).model_dump()

    assert "request_id" in dumped
    assert "current_location" in dumped["conditions"]
    assert "requestId" not in dumped
