"""기존 Tool 결과를 A–C 상위 RecommendationContext 값으로 변환한다."""

from __future__ import annotations

from datetime import UTC
from typing import Any, TypeVar

from app.agent_context.schemas import (
    ContextError,
    ContextValue,
    ContextWarning,
    Coordinates,
    HolidayInfo,
    PlaceCandidate,
    ProviderMetadata,
    ResolvedLocation,
    WeatherForecast,
)
from app.domain.operating_hours import OperatingSchedule
from app.providers.contracts import ProviderMetadata as DomainProviderMetadata
from app.tools.contracts import ToolError, ToolStatus
from app.tools.holiday import HolidayToolResult
from app.tools.nearby_place_details import NearbyPlaceDetailsResult
from app.tools.resolve_location import ResolveLocationResult
from app.tools.weather_forecast import WeatherForecastToolResult

T = TypeVar("T")

_WARNING_MESSAGES = {
    "partial_data": "일부 데이터를 확인하지 못했습니다.",
    "stale_data": "최신성이 보장되지 않는 데이터를 사용했습니다.",
    "fallback_used": "대체 조회 방식으로 결과를 찾았습니다.",
}
_WEEKDAY_NAMES = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def map_location_context(
    result: ResolveLocationResult,
) -> ContextValue[ResolvedLocation]:
    """위치 Tool 결과를 좌표 중심의 A–C Context로 변환한다."""

    data = None
    if result.location is not None:
        data = ResolvedLocation(
            requested_query=result.location.requested_query,
            resolved_name=result.location.resolved_name,
            location=Coordinates(
                latitude=result.location.latitude,
                longitude=result.location.longitude,
            ),
            # 현재 위치 Tool 도메인에는 주소 필드가 없다.
            address=None,
        )
    return _context_value(
        status=result.status,
        data=data,
        empty_data=None,
        error=result.error,
        warnings=result.warnings,
        provider_metadata=result.provider_metadata,
    )


def map_weather_context(
    result: WeatherForecastToolResult,
) -> ContextValue[WeatherForecast]:
    """선택된 초단기예보를 A–C의 3단계 날씨 Context로 변환한다."""

    data = None
    if result.forecast is not None:
        data = WeatherForecast(
            condition=result.forecast.condition.value,
            forecast_for=result.forecast.forecast_for,
            # 현재 Weather Tool은 기온을 결과 모델에 포함하지 않는다.
            temperature_celsius=None,
        )
    return _context_value(
        status=result.status,
        data=data,
        empty_data=None,
        error=result.error,
        warnings=result.warnings,
        provider_metadata=result.provider_metadata,
    )


def map_places_context(
    result: NearbyPlaceDetailsResult,
) -> ContextValue[list[PlaceCandidate]]:
    """검색 후보를 유지하면서 확인 가능한 상세·운영정보만 보완한다."""

    places = [
        PlaceCandidate(
            place_id=item.candidate.place_id,
            name=item.candidate.name,
            category=item.candidate.category,
            location=Coordinates(
                latitude=item.candidate.latitude,
                longitude=item.candidate.longitude,
            ),
            operating_hours_raw=(
                item.details.operating_hours
                if item.details is not None
                else item.candidate.operating_hours
            ),
            rest_date_raw=(
                item.details.rest_date if item.details is not None else None
            ),
            operating_schedule=_operating_schedule(
                item.details.operating_schedule
                if item.details is not None
                else None
            ),
        )
        for item in result.places
    ]
    return _context_value(
        status=result.status,
        data=places or None,
        empty_data=[],
        error=result.error,
        warnings=result.warnings,
        provider_metadata=result.provider_metadata,
    )


def map_holidays_context(
    result: HolidayToolResult,
) -> ContextValue[list[HolidayInfo]]:
    """공휴일 Provider 결과에서 실제 공휴일 항목만 전달한다."""

    holidays = (
        [
            HolidayInfo(date=item.date, name=item.name)
            for item in result.holidays.holidays
        ]
        if result.holidays is not None
        else []
    )
    return _context_value(
        status=result.status,
        data=holidays or None,
        empty_data=[],
        error=result.error,
        warnings=result.warnings,
        provider_metadata=result.provider_metadata,
    )


def _context_value(
    *,
    status: ToolStatus,
    data: T | None,
    empty_data: T | None,
    error: ToolError | None,
    warnings: tuple[str, ...],
    provider_metadata: tuple[DomainProviderMetadata, ...],
) -> ContextValue[T]:
    mapped_error = _error(error)
    if status is ToolStatus.NO_DATA:
        data = empty_data
        # A–C 계약은 no_data를 정상적인 빈 결과로 표현한다.
        mapped_error = None
    elif status in {ToolStatus.UNSUPPORTED, ToolStatus.UNAVAILABLE}:
        data = None

    return ContextValue[T](
        status=status.value,
        data=data,
        error=mapped_error,
        warnings=_warnings(warnings),
        provider_metadata=_metadata(provider_metadata),
    )


def _metadata(
    values: tuple[DomainProviderMetadata, ...],
) -> list[ProviderMetadata]:
    return [
        ProviderMetadata(
            source=value.source.value,
            status=value.status.value,
            retrieved_at=value.retrieved_at.astimezone(UTC),
        )
        for value in values
    ]


def _error(error: ToolError | None) -> ContextError | None:
    if error is None:
        return None
    return ContextError(
        code=error.code,
        message=error.message,
        retryable=error.retryable,
    )


def _warnings(values: tuple[str, ...]) -> list[ContextWarning]:
    return [
        ContextWarning(
            code=value,
            message=_WARNING_MESSAGES.get(value, value),
        )
        for value in values
    ]


def _operating_schedule(
    schedule: OperatingSchedule | None,
) -> dict[str, Any] | None:
    if schedule is None:
        return None
    return {
        "availability": schedule.availability.value,
        "time_ranges": [
            {
                "open_time": time_range.start.strftime("%H:%M"),
                "close_time": time_range.end.strftime("%H:%M"),
                "crosses_midnight": time_range.crosses_midnight,
            }
            for rule in schedule.rules
            for time_range in rule.time_ranges
        ],
        "closure_rules": [
            {
                "weekdays": [
                    _WEEKDAY_NAMES[index] for index in sorted(rule.weekdays)
                ],
                "source_text": rule.source_text,
            }
            for rule in schedule.closure_rules
        ],
        "parse_status": schedule.parse_status.value,
        "assumption_reason": schedule.assumption_reason,
        "warnings": list(schedule.warnings),
    }
