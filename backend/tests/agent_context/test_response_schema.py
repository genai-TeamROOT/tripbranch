from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.agent_context.schemas import (
    AgentContextResponse,
    Clarification,
    ContextError,
    ContextValue,
    Coordinates,
    HolidayInfo,
    ProviderMetadata,
    RecommendationContext,
    ResolvedLocation,
    ResponseMetadata,
    WeatherForecast,
)

RETRIEVED_AT = datetime(2026, 7, 24, 1, tzinfo=UTC)


def _metadata(source: str = "fake") -> ProviderMetadata:
    return ProviderMetadata(
        source=source,
        status="success",
        retrieved_at=RETRIEVED_AT,
    )


def _location_context() -> ContextValue[ResolvedLocation]:
    return ContextValue[ResolvedLocation](
        status="success",
        data=ResolvedLocation(
            requested_query="경복궁",
            resolved_name="경복궁",
            location=Coordinates(latitude=37.5796, longitude=126.977),
            address="서울특별시 종로구",
        ),
        provider_metadata=[_metadata("fake_geocoding")],
    )


def _response_metadata() -> ResponseMetadata:
    return ResponseMetadata(
        rule_versions={"location_resolution": "v1"},
        provider_metadata=[_metadata("fake_geocoding")],
    )


def test_success_response_requires_context() -> None:
    response = AgentContextResponse(
        request_id="request-1",
        intent="RECOMMEND",
        status="success",
        context=RecommendationContext(location=_location_context()),
        metadata=_response_metadata(),
    )

    assert response.contract_version == "draft-v0"
    assert response.context is not None


def test_partial_response_keeps_success_and_unavailable_contexts() -> None:
    weather_error = ContextError(
        code="weather_unavailable",
        message="날씨 정보를 가져오지 못했습니다.",
        retryable=True,
    )
    response = AgentContextResponse(
        request_id="request-1",
        intent="RECOMMEND",
        status="partial",
        context=RecommendationContext(
            location=_location_context(),
            weather=ContextValue[WeatherForecast](
                status="unavailable",
                error=weather_error,
            ),
        ),
        metadata=_response_metadata(),
    )

    assert response.context is not None
    assert response.context.location is not None
    assert response.context.weather is not None
    assert response.context.weather.error == weather_error


def test_no_data_allows_empty_list_or_null_by_data_shape() -> None:
    holidays = ContextValue[list[HolidayInfo]](status="no_data", data=[])
    location = ContextValue[ResolvedLocation](status="no_data", data=None)

    assert holidays.data == []
    assert location.data is None


@pytest.mark.parametrize("status", ["success", "partial"])
def test_usable_context_requires_data(status: str) -> None:
    with pytest.raises(ValidationError):
        ContextValue[ResolvedLocation](status=status)


@pytest.mark.parametrize("status", ["unsupported", "unavailable"])
def test_blocked_context_requires_error_and_rejects_data(status: str) -> None:
    with pytest.raises(ValidationError):
        ContextValue[ResolvedLocation](status=status)

    with pytest.raises(ValidationError):
        ContextValue[ResolvedLocation](
            status=status,
            data=_location_context().data,
            error=ContextError(code="blocked", message="사용 불가", retryable=False),
        )


def test_needs_clarification_has_structured_reason_without_error() -> None:
    response = AgentContextResponse(
        request_id="request-1",
        intent="RECOMMEND",
        status="needs_clarification",
        clarification=Clarification(
            code="location_required",
            missing_fields=["current_location", "search_center"],
        ),
        metadata=ResponseMetadata(),
    )

    assert response.context is None
    assert response.error is None
    assert response.clarification is not None


def test_rejects_naive_provider_retrieved_at() -> None:
    with pytest.raises(ValidationError):
        ProviderMetadata(
            source="fake",
            status="success",
            retrieved_at=datetime(2026, 7, 24, 10),
        )


def test_request_weather_and_response_weather_have_separate_vocabularies() -> None:
    forecast = WeatherForecast(
        condition="neutral",
        forecast_for=RETRIEVED_AT,
    )

    assert forecast.condition == "neutral"
    with pytest.raises(ValidationError):
        WeatherForecast(condition="rain", forecast_for=RETRIEVED_AT)


def test_rejects_invalid_top_level_state_combinations() -> None:
    with pytest.raises(ValidationError):
        AgentContextResponse(
            request_id="request-1",
            intent="RECOMMEND",
            status="success",
            metadata=ResponseMetadata(),
        )

    with pytest.raises(ValidationError):
        AgentContextResponse(
            request_id="request-1",
            intent="RECOMMEND",
            status="needs_clarification",
            metadata=ResponseMetadata(),
        )
