"""build_tool_execution_debug()가 C 응답의 관측 정보를 빠짐없이 옮기는지 검증한다.

이 값은 /dev-chat 감사 패널에만 쓰이지만, 소비 측이 실제로 읽는 필드(특히
providers[].source)가 비면 "Fake Provider가 조용히 답했다"를 화면에서 못 잡는다.
그래서 빈 껍데기가 아니라 실제 값이 실린다는 것까지 못 박는다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.agent_context.schemas import (
    AgentContextResponse,
    Clarification,
    ContextError,
    ContextValue,
    ContextWarning,
    Coordinates,
    HolidayInfo,
    ProviderMetadata,
    RecommendationContext,
    ResolvedLocation,
    ResponseMetadata,
    WeatherForecast,
)
from app.services.runtime.tool_debug import build_tool_execution_debug

RETRIEVED_AT = datetime(2026, 8, 7, 3, 0, tzinfo=UTC)


def _location_value(source: str = "kakao") -> ContextValue[ResolvedLocation]:
    return ContextValue(
        status="success",
        data=ResolvedLocation(
            requested_query="경복궁",
            resolved_name="경복궁",
            location=Coordinates(latitude=37.5788, longitude=126.9770),
            address="서울 종로구 사직로 161",
        ),
        provider_metadata=[
            ProviderMetadata(source=source, status="success", retrieved_at=RETRIEVED_AT)
        ],
    )


def test_성공_응답의_provider와_항목_상태를_그대로_옮긴다() -> None:
    response = AgentContextResponse(
        request_id="req-1",
        intent="RECOMMEND",
        status="success",
        context=RecommendationContext(
            location=_location_value(),
            holidays=ContextValue(
                status="success",
                data=[HolidayInfo(date="2026-08-15", name="광복절")],
            ),
        ),
        metadata=ResponseMetadata(
            rule_versions={"tool_execution": "v1"},
            provider_metadata=[
                ProviderMetadata(source="kma", status="success", retrieved_at=RETRIEVED_AT)
            ],
        ),
    )

    debug = build_tool_execution_debug(response, latency_ms=330)

    assert debug is not None
    assert debug.request_id == "req-1"
    assert debug.status == "success"
    assert debug.latency_ms == 330
    assert debug.rule_versions == {"tool_execution": "v1"}
    assert debug.resolved_location_name == "경복궁"
    assert debug.resolved_location_address == "서울 종로구 사직로 161"
    # 최상위 metadata와 항목별 provider_metadata를 모두 모은다 — 어느 한쪽만 보면
    # 실제 호출한 Provider가 화면에서 누락된다.
    assert {provider.source for provider in debug.providers} == {"kakao", "kma"}


def test_조회하지_않은_항목과_실패한_항목을_구분한다() -> None:
    response = AgentContextResponse(
        request_id="req-2",
        intent="RECOMMEND",
        status="partial",
        context=RecommendationContext(
            location=_location_value(),
            # weather는 아예 조회하지 않았다(발화에 날씨가 이미 있는 경우).
            places=ContextValue(
                status="unavailable",
                error=ContextError(code="upstream_timeout", message="시간 초과", retryable=True),
            ),
        ),
        metadata=ResponseMetadata(),
    )

    debug = build_tool_execution_debug(response)

    assert debug is not None
    items = {item.key: item for item in debug.context_items}
    assert items["weather"].fetched is False
    assert items["weather"].status is None
    assert items["places"].fetched is True
    assert items["places"].status == "unavailable"
    assert items["places"].error_code == "upstream_timeout"
    assert debug.latency_ms is None


def test_목록형_항목의_후보_수를_센다() -> None:
    """D Scoring 탭의 결과 수와 비교해 어디서 후보가 줄었는지 보기 위한 값이다."""

    response = AgentContextResponse(
        request_id="req-3",
        intent="RECOMMEND",
        status="success",
        context=RecommendationContext(
            location=_location_value(),
            weather=ContextValue(
                status="success",
                data=WeatherForecast(
                    forecast_for=RETRIEVED_AT,
                    precipitation="none",
                    sky="clear",
                    temperature_celsius=28.0,
                ),
                warnings=[ContextWarning(code="stale_forecast", message="예보가 오래됨")],
            ),
            holidays=ContextValue(status="no_data", data=[]),
        ),
        metadata=ResponseMetadata(),
    )

    debug = build_tool_execution_debug(response)

    assert debug is not None
    items = {item.key: item for item in debug.context_items}
    assert items["holidays"].item_count == 0
    assert items["weather"].warning_codes == ["stale_forecast"]
    # 단건형 항목은 개수를 세지 않는다.
    assert items["weather"].item_count is None
    assert items["location"].item_count is None


def test_되묻기_응답의_코드를_남긴다() -> None:
    response = AgentContextResponse(
        request_id="req-4",
        intent="RECOMMEND",
        status="needs_clarification",
        clarification=Clarification(code="location_required", missing_fields=["search_center"]),
        metadata=ResponseMetadata(),
    )

    debug = build_tool_execution_debug(response)

    assert debug is not None
    assert debug.clarification_code == "location_required"
    assert debug.error_code is None
    # context가 없어도 항목 목록은 "조회 안 함"으로 채워진다.
    assert all(item.fetched is False for item in debug.context_items)
