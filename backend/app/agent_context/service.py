"""A의 조건 요청을 받아 필요한 C Tool을 실행하고 공통 Context를 반환한다."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from zoneinfo import ZoneInfo

from app.agent_context.assembler import (
    ContextAssemblyInput,
    assemble_agent_context_response,
)
from app.agent_context.category_rules import (
    CategoryQueryPlan,
    build_category_query_plan,
)
from app.agent_context.schemas import (
    AgentContextRequest,
    AgentContextResponse,
    ContextError,
    ResponseMetadata,
)
from app.tools.contracts import ToolError, ToolStatus
from app.tools.holiday import GetHolidaysTool, HolidayQuery
from app.tools.nearby_place_details import (
    EnrichedPlace,
    NearbyPlaceDetailsQuery,
    NearbyPlaceDetailsResult,
    NearbyPlaceDetailsTool,
)
from app.tools.resolve_location import (
    ResolveLocationQuery,
    ResolveLocationTool,
)
from app.tools.weather_forecast import (
    GetWeatherForecastTool,
    WeatherForecastQuery,
)

_KST = ZoneInfo("Asia/Seoul")
_CATEGORY_RULE_VERSION = "tour-category-v1"
_SEARCH_RADIUS_RULE_VERSION = "walking-radius-v1"
_WALKING_KM_PER_MINUTE = 0.07
_MIN_SEARCH_RADIUS_KM = 0.3
_MAX_SEARCH_RADIUS_KM = 20.0


@dataclass(frozen=True)
class ContextTools:
    """Context 수집에 필요한 Tool 묶음."""

    location: ResolveLocationTool
    places: NearbyPlaceDetailsTool
    weather: GetWeatherForecastTool
    holidays: GetHolidaysTool


class ContextService:
    """A가 지정한 조건으로 C의 Tool 실행 계획을 만들고 결과를 조립한다."""

    def __init__(
        self,
        tools: ContextTools,
        *,
        clock: Callable[[], datetime] | None = None,
        search_radius_km: float = 2.0,
        candidate_limit: int = 10,
    ) -> None:
        self._tools = tools
        self._clock = clock or (lambda: datetime.now(_KST))
        self._search_radius_km = search_radius_km
        self._candidate_limit = candidate_limit

    async def fetch_context(
        self,
        request: AgentContextRequest,
    ) -> AgentContextResponse:
        conditions = request.conditions
        location_query = conditions.search_center or conditions.current_location
        if location_query is None:
            return assemble_agent_context_response(
                ContextAssemblyInput(request=request, location_result=None),
                rule_versions=_rule_versions(),
            )

        category_plan = build_category_query_plan(
            conditions.place_types,
            conditions.place_tags,
        )
        if category_plan.has_unsupported_conditions or category_plan.has_conflicts:
            return _unsupported_category_response(request, category_plan)

        location_result = await self._tools.location.execute(ResolveLocationQuery(location_query))
        if location_result.status is not ToolStatus.SUCCESS or location_result.location is None:
            return assemble_agent_context_response(
                ContextAssemblyInput(
                    request=request,
                    location_result=location_result,
                ),
                rule_versions=_rule_versions(),
            )

        visit_at = _as_kst(self._clock())
        location = location_result.location
        weather_task = self._tools.weather.execute(
            WeatherForecastQuery(
                latitude=location.latitude,
                longitude=location.longitude,
                visit_at=visit_at,
            )
        )
        holidays_task = self._tools.holidays.execute(
            HolidayQuery(year=visit_at.year, month=visit_at.month)
        )
        places_task = self._collect_places(
            category_plan,
            latitude=location.latitude,
            longitude=location.longitude,
            search_radius_km=_resolve_search_radius_km(
                conditions.max_travel_time,
                default_radius_km=self._search_radius_km,
            ),
        )
        weather_result, holidays_result, places_result = await asyncio.gather(
            weather_task,
            holidays_task,
            places_task,
        )

        return assemble_agent_context_response(
            ContextAssemblyInput(
                request=request,
                location_result=location_result,
                weather_result=weather_result,
                places_result=places_result,
                holidays_result=holidays_result,
            ),
            rule_versions=_rule_versions(),
        )

    async def _collect_places(
        self,
        plan: CategoryQueryPlan,
        *,
        latitude: float,
        longitude: float,
        search_radius_km: float,
    ) -> NearbyPlaceDetailsResult:
        """분류별 장소 조회를 병렬 실행하고 중복 후보를 제거해 한 결과로 합친다."""

        started_at = perf_counter()
        results = await asyncio.gather(
            *(
                self._tools.places.execute(
                    NearbyPlaceDetailsQuery(
                        latitude=latitude,
                        longitude=longitude,
                        search_radius_km=search_radius_km,
                        limit=self._candidate_limit,
                        preferred_categories=plan.resolved_place_tags,
                        category_filter=category_filter,
                    )
                )
                for category_filter in plan.filters
            )
        )
        return _merge_place_results(
            results,
            limit=self._candidate_limit,
            started_at=started_at,
        )


def _resolve_search_radius_km(
    max_travel_time: int | None,
    *,
    default_radius_km: float,
) -> float:
    """최대 이동시간을 MVP 도보 속도로 환산한 후보 수집 반경으로 변환한다."""

    if max_travel_time is None:
        return default_radius_km
    estimated_radius = max_travel_time * _WALKING_KM_PER_MINUTE
    return min(
        max(estimated_radius, _MIN_SEARCH_RADIUS_KM),
        _MAX_SEARCH_RADIUS_KM,
    )


def _merge_place_results(
    results: list[NearbyPlaceDetailsResult],
    *,
    limit: int,
    started_at: float,
) -> NearbyPlaceDetailsResult:
    if not results:
        return NearbyPlaceDetailsResult(
            places=(),
            status=ToolStatus.UNSUPPORTED,
            source="agent_context_service",
            retrieved_at=datetime.now(UTC),
            elapsed_ms=(perf_counter() - started_at) * 1000,
            error=ToolError(
                code="unsupported_category",
                message="지원하는 장소 분류를 찾지 못했습니다.",
                cause="unsupported_category",
                retryable=False,
            ),
        )

    places: list[EnrichedPlace] = []
    seen_place_ids: set[str] = set()
    for result in results:
        for place in result.places:
            place_id = place.candidate.place_id
            if place_id not in seen_place_ids:
                seen_place_ids.add(place_id)
                places.append(place)
                if len(places) == limit:
                    break
        if len(places) == limit:
            break

    statuses = tuple(result.status for result in results)
    if places:
        status = (
            ToolStatus.PARTIAL
            if any(item in {ToolStatus.PARTIAL, ToolStatus.UNAVAILABLE} for item in statuses)
            else ToolStatus.SUCCESS
        )
        error = None
    elif all(item is ToolStatus.NO_DATA for item in statuses):
        status = ToolStatus.NO_DATA
        error = None
    elif all(item is ToolStatus.UNSUPPORTED for item in statuses):
        status = ToolStatus.UNSUPPORTED
        error = next((result.error for result in results if result.error), None)
    else:
        status = ToolStatus.UNAVAILABLE
        error = next((result.error for result in results if result.error), None)

    return NearbyPlaceDetailsResult(
        places=tuple(places),
        status=status,
        source="agent_context_service",
        retrieved_at=max(result.retrieved_at for result in results),
        elapsed_ms=(perf_counter() - started_at) * 1000,
        error=error,
        warnings=("partial_data",) if status is ToolStatus.PARTIAL else (),
        provider_metadata=tuple(
            metadata for result in results for metadata in result.provider_metadata
        ),
    )


def _unsupported_category_response(
    request: AgentContextRequest,
    plan: CategoryQueryPlan,
) -> AgentContextResponse:
    details = [
        *plan.unsupported_place_types,
        *plan.unsupported_place_tags,
        *plan.conflicting_place_tags,
    ]
    message = "지원하지 않거나 서로 맞지 않는 장소 분류입니다."
    if details:
        message = f"{message} ({', '.join(details)})"
    return AgentContextResponse(
        request_id=request.request_id,
        intent=request.intent,
        status="unsupported",
        context=None,
        error=ContextError(
            code="unsupported_category",
            message=message,
            retryable=False,
        ),
        metadata=ResponseMetadata(rule_versions=_rule_versions()),
    )


def _rule_versions() -> dict[str, str]:
    return {
        "category": _CATEGORY_RULE_VERSION,
        "search_radius": _SEARCH_RADIUS_RULE_VERSION,
    }


def _as_kst(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=_KST)
    return value.astimezone(_KST)


__all__ = ["ContextService", "ContextTools"]
