"""A의 조건 요청을 받아 필요한 C Tool을 실행하고 공통 Context를 반환한다."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
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
from app.agent_context.enrichment_service import (
    JONGNO_CONCENTRATION_AREA_CODE,
    JONGNO_CONCENTRATION_DISTRICT_CODE,
    select_concentration_forecast,
)
from app.agent_context.info_schemas import (
    ConcentrationInfoResult,
    InfoContextRequest,
    InfoContextResponse,
)
from app.agent_context.schemas import (
    AgentContextRequest,
    AgentContextResponse,
    Clarification,
    ContextError,
    ResponseMetadata,
)
from app.agent_context.tool_rules import (
    TOOL_EXECUTION_RULE_VERSION,
    ContextTool,
    build_tool_execution_plan,
)
from app.concentration_policy import is_valid_concentration_rate, normalize_concentration
from app.place_search_policy import (
    DEFAULT_PLACE_SEARCH_RADIUS_KM,
    MAX_PLACE_SEARCH_RADIUS_KM,
    MIN_PLACE_SEARCH_RADIUS_KM,
    WALKING_SPEED_KM_PER_MINUTE,
)
from app.providers.contracts import ProviderMetadata, ProviderSource, ProviderStatus
from app.recommendation_limits import (
    MAX_RECOMMENDATION_CANDIDATE_LIMIT,
    MIN_RECOMMENDATION_LIMIT,
)
from app.tools.concentration import ConcentrationQuery, GetConcentrationTool
from app.tools.contracts import ToolError, ToolStatus
from app.tools.holiday import GetHolidaysTool, HolidayQuery
from app.tools.nearby_place_details import (
    EnrichedPlace,
    NearbyPlaceDetailsQuery,
    NearbyPlaceDetailsResult,
    NearbyPlaceDetailsTool,
)
from app.tools.resolve_location import (
    ResolutionConfidence,
    ResolutionMethod,
    ResolvedLocation,
    ResolveLocationQuery,
    ResolveLocationResult,
    ResolveLocationTool,
)
from app.tools.weather_forecast import (
    GetWeatherForecastTool,
    WeatherForecastQuery,
)

_KST = ZoneInfo("Asia/Seoul")
_CATEGORY_RULE_VERSION = "tour-category-v1"
_SEARCH_RADIUS_RULE_VERSION = "walking-radius-v1"


@dataclass(frozen=True)
class ContextTools:
    """Context 수집에 필요한 Tool 묶음."""

    location: ResolveLocationTool
    places: NearbyPlaceDetailsTool
    weather: GetWeatherForecastTool
    holidays: GetHolidaysTool
    # INFO 혼잡도는 RECOMMEND Context와 별도 경로다. 기존 RECOMMEND 조립 코드와
    # 테스트의 호환을 위해 선택적으로 두고, Factory에서는 항상 실제 Tool을 주입한다.
    concentration: GetConcentrationTool | None = None


class ContextService:
    """A가 지정한 조건으로 C의 Tool 실행 계획을 만들고 결과를 조립한다."""

    def __init__(
        self,
        tools: ContextTools,
        *,
        candidate_limit: int,
        clock: Callable[[], datetime] | None = None,
        search_radius_km: float = DEFAULT_PLACE_SEARCH_RADIUS_KM,
    ) -> None:
        if not (
            MIN_RECOMMENDATION_LIMIT
            <= candidate_limit
            <= MAX_RECOMMENDATION_CANDIDATE_LIMIT
        ):
            raise ValueError(
                "candidate_limit은 "
                f"{MIN_RECOMMENDATION_LIMIT} 이상 "
                f"{MAX_RECOMMENDATION_CANDIDATE_LIMIT} 이하여야 합니다."
            )
        self._tools = tools
        self._clock = clock or (lambda: datetime.now(_KST))
        self._search_radius_km = search_radius_km
        self._candidate_limit = candidate_limit

    async def fetch_context(
        self,
        request: AgentContextRequest,
    ) -> AgentContextResponse:
        conditions = request.conditions
        execution_plan = build_tool_execution_plan(conditions)
        location_query = conditions.search_center or conditions.current_location
        if location_query is None and request.gps_location is None:
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

        location_result = (
            await self._tools.location.execute(ResolveLocationQuery(location_query))
            if location_query is not None
            else _gps_location_result(request, self._clock())
        )
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
        weather_task = (
            asyncio.create_task(
                self._tools.weather.execute(
                    WeatherForecastQuery(
                        latitude=location.latitude,
                        longitude=location.longitude,
                        visit_at=visit_at,
                    )
                )
            )
            if execution_plan.requires(ContextTool.GET_WEATHER)
            else None
        )
        holidays_task = (
            asyncio.create_task(
                self._tools.holidays.execute(
                    HolidayQuery(year=visit_at.year, month=visit_at.month)
                )
            )
            if execution_plan.requires(ContextTool.GET_HOLIDAYS)
            else None
        )
        places_task = asyncio.create_task(
            self._collect_places(
                category_plan,
                latitude=location.latitude,
                longitude=location.longitude,
                search_radius_km=_resolve_search_radius_km(
                    conditions.max_travel_time,
                    default_radius_km=self._search_radius_km,
                ),
            )
        )
        weather_result = await weather_task if weather_task is not None else None
        holidays_result = await holidays_task if holidays_task is not None else None
        places_result = await places_task

        return assemble_agent_context_response(
            ContextAssemblyInput(
                request=request,
                location_result=location_result,
                weather_result=weather_result,
                places_result=places_result,
                holidays_result=holidays_result,
                weather_requested=execution_plan.requires(ContextTool.GET_WEATHER),
                holidays_requested=execution_plan.requires(ContextTool.GET_HOLIDAYS),
            ),
            rule_versions=_rule_versions(),
        )

    async def fetch_info_context(
        self,
        request: InfoContextRequest,
    ) -> InfoContextResponse:
        """INFO 단일 장소의 직접 집중률을 조회해 공통 응답으로 반환한다.

        이번 단계는 대상 장소의 직접 조회까지만 담당한다. 직접 데이터가 없을 때
        인근 관광지를 재조회하는 D-036 fallback은 별도 단계에서 추가한다.
        """

        if request.place_name is None:
            return InfoContextResponse(
                request_id=request.request_id,
                status="needs_clarification",
                clarification=Clarification(
                    code="place_required",
                    missing_fields=["place_name"],
                    candidates=[],
                ),
            )

        location_result = await self._tools.location.execute(
            ResolveLocationQuery(request.place_name)
        )
        if location_result.status is ToolStatus.NO_DATA:
            cause = location_result.error.cause if location_result.error else None
            if cause == "ambiguous_location":
                return InfoContextResponse(
                    request_id=request.request_id,
                    status="needs_clarification",
                    clarification=Clarification(
                        code="place_ambiguous",
                        missing_fields=[],
                        candidates=[],
                    ),
                )
            return _info_no_data_response(request)
        if location_result.status is ToolStatus.UNSUPPORTED:
            return _info_error_response(
                request,
                status="unsupported",
                error=_context_error_from_tool(
                    location_result.error,
                    fallback_code="unsupported",
                    fallback_message="현재 지원하지 않는 위치입니다.",
                    retryable=False,
                ),
            )
        if location_result.status is ToolStatus.UNAVAILABLE:
            return _info_error_response(
                request,
                status="unavailable",
                error=_context_error_from_tool(
                    location_result.error,
                    fallback_code="location_unavailable",
                    fallback_message="위치 정보를 가져오지 못했습니다.",
                    retryable=True,
                ),
            )

        reference_date = _info_reference_date(request.visit_time, self._clock())
        if self._tools.concentration is None:
            return _info_error_response(
                request,
                status="unavailable",
                error=ContextError(
                    code="concentration_not_configured",
                    message="집중률 조회 기능을 사용할 수 없습니다.",
                    retryable=False,
                ),
            )

        concentration_result = await self._tools.concentration.execute(
            ConcentrationQuery(
                area_code=JONGNO_CONCENTRATION_AREA_CODE,
                district_code=JONGNO_CONCENTRATION_DISTRICT_CODE,
                place_name=request.place_name,
            )
        )
        if concentration_result.status is ToolStatus.UNAVAILABLE:
            return _info_error_response(
                request,
                status="unavailable",
                error=_context_error_from_tool(
                    concentration_result.error,
                    fallback_code="concentration_unavailable",
                    fallback_message="집중률 정보를 가져오지 못했습니다.",
                    retryable=True,
                ),
            )

        forecast = select_concentration_forecast(
            concentration_result.concentration,
            candidate_name=request.place_name,
            reference_date=reference_date,
        )
        rate = forecast.concentration_rate if forecast is not None else None
        if forecast is None or not is_valid_concentration_rate(rate):
            return _info_no_data_response(request)

        normalized = normalize_concentration(rate)
        return InfoContextResponse(
            request_id=request.request_id,
            status="success",
            result=ConcentrationInfoResult(
                status="success",
                is_proxy=False,
                requested_place_name=request.place_name,
                resolved_place_name=forecast.place_name,
                forecast_date=reference_date.isoformat(),
                concentration_rate=rate,
                concentration_level=normalized.level,
                concentration_label=normalized.label,
            ),
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


def _gps_location_result(
    request: AgentContextRequest, retrieved_at: datetime
) -> ResolveLocationResult:
    """장소명이 없을 때 A가 전달한 기기 GPS를 위치 Tool 성공 결과로 정규화한다."""

    gps = request.gps_location
    if gps is None:
        raise ValueError("gps_location이 필요합니다.")
    return ResolveLocationResult(
        status=ToolStatus.SUCCESS,
        location=ResolvedLocation(
            requested_query="gps_location",
            provider_query="device_gps",
            resolved_name="기기 GPS 위치",
            latitude=gps.latitude,
            longitude=gps.longitude,
            resolution_method=ResolutionMethod.DIRECT,
            confidence=ResolutionConfidence.EXACT,
        ),
        error=None,
        provider_metadata=(
            ProviderMetadata(
                source=ProviderSource.DEVICE_GPS,
                status=ProviderStatus.SUCCESS,
                retrieved_at=_as_kst(retrieved_at).astimezone(UTC),
            ),
        ),
    )


def _info_reference_date(visit_time: str | None, clock_value: datetime) -> date:
    """INFO 요청의 방문일이 없으면 C 조회 시각의 한국 날짜를 사용한다."""

    if visit_time is not None:
        return date.fromisoformat(visit_time)
    return _as_kst(clock_value).date()


def _info_no_data_response(request: InfoContextRequest) -> InfoContextResponse:
    """직접 조회 결과가 없을 때의 INFO 응답을 한 형태로 유지한다."""

    return InfoContextResponse(
        request_id=request.request_id,
        status="no_data",
        result=ConcentrationInfoResult(
            status="no_data",
            requested_place_name=request.place_name,
        ),
    )


def _info_error_response(
    request: InfoContextRequest,
    *,
    status: str,
    error: ContextError,
) -> InfoContextResponse:
    return InfoContextResponse(
        request_id=request.request_id,
        status=status,
        error=error,
    )


def _context_error_from_tool(
    error: ToolError | None,
    *,
    fallback_code: str,
    fallback_message: str,
    retryable: bool,
) -> ContextError:
    """Tool 오류 세부 정보는 유지하되 INFO 계약의 오류 모델로 변환한다."""

    return ContextError(
        code=error.code if error is not None else fallback_code,
        message=error.message if error is not None else fallback_message,
        retryable=error.retryable if error is not None else retryable,
    )


def _resolve_search_radius_km(
    max_travel_time: int | None,
    *,
    default_radius_km: float,
) -> float:
    """최대 이동시간을 MVP 도보 속도로 환산한 후보 수집 반경으로 변환한다."""

    if max_travel_time is None:
        return default_radius_km
    estimated_radius = max_travel_time * WALKING_SPEED_KM_PER_MINUTE
    return min(
        max(estimated_radius, MIN_PLACE_SEARCH_RADIUS_KM),
        MAX_PLACE_SEARCH_RADIUS_KM,
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
        "tool_execution": TOOL_EXECUTION_RULE_VERSION,
    }


def _as_kst(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=_KST)
    return value.astimezone(_KST)


__all__ = ["ContextService", "ContextTools"]
