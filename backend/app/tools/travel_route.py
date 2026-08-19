"""이동수단별 실제 경로를 조회하고 누락 결과를 직선거리 추정으로 보완하는 Tool."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from app.domain.travel_route import (
    GeoCoordinate,
    RouteDestination,
    RouteStatus,
    TravelMode,
    TravelRoute,
)
from app.errors import AppError
from app.providers.contracts import ProviderMetadata
from app.providers.protocols import TravelRouteProvider
from app.providers.walking_route import MAX_TRAVEL_ROUTE_DESTINATIONS
from app.tools.contracts import ToolError, ToolStatus

logger = logging.getLogger(__name__)

TRAVEL_ROUTE_FALLBACK_WARNING = "travel_route_straight_line_fallback"
TRAVEL_ROUTE_FALLBACK_FAILED_WARNING = "travel_route_fallback_failed"
TRAVEL_ROUTE_MODE_UNSUPPORTED_WARNING = "travel_route_mode_unsupported"


@dataclass(frozen=True)
class TravelRouteQuery:
    """조회 요청. `mode`는 기본값을 두지 않는다.

    기본값을 두면 mode를 넘기지 않은 호출부가 조용히 도보를 조회한다 — 이 카드가
    고친 문제가 정확히 그것이었다(자동차 요청에도 도보를 20건씩 조회하고 D가
    결과를 버렸다).
    """

    origin: GeoCoordinate
    destinations: tuple[RouteDestination, ...]
    mode: TravelMode
    radius_m: int | None = None

    def __post_init__(self) -> None:
        if len(self.destinations) > MAX_TRAVEL_ROUTE_DESTINATIONS:
            raise ValueError(
                f"destinations는 최대 {MAX_TRAVEL_ROUTE_DESTINATIONS}개까지 허용됩니다."
            )
        if self.radius_m is not None and self.radius_m <= 0:
            raise ValueError("radius_m는 0보다 커야 합니다.")
        place_ids = tuple(destination.place_id for destination in self.destinations)
        if len(place_ids) != len(set(place_ids)):
            raise ValueError("destinations의 place_id는 중복될 수 없습니다.")


@dataclass(frozen=True)
class TravelRouteToolResult:
    status: ToolStatus
    routes: tuple[TravelRoute, ...]
    error: ToolError | None = None
    warnings: tuple[str, ...] = ()
    provider_metadata: tuple[ProviderMetadata, ...] = ()


@dataclass(frozen=True)
class TravelRouteProviders:
    """한 이동수단의 실측 Provider와 그 실패를 메울 추정 Provider."""

    primary: TravelRouteProvider
    fallback: TravelRouteProvider | None = None


class TravelRouteTool:
    """등록된 이동수단만 조회한다.

    미등록 이동수단은 호출 없이 NO_DATA로 답한다. 추정으로 메우지 않는 이유는
    도보 속도 추정값을 자동차 실측인 척 내보내는 것이 D-042("Real 실패 시 Fake로
    자동 전환하지 않는다")가 막으려던 그 상황이기 때문이다. 소비 측은 값이
    없으면 직선거리로 돌아가므로, 없는 것이 틀린 것보다 안전하다.
    """

    def __init__(self, providers: Mapping[TravelMode, TravelRouteProviders]) -> None:
        if not providers:
            raise ValueError("이동수단이 하나도 등록되지 않았습니다.")
        self._providers = dict(providers)

    async def execute(self, query: TravelRouteQuery) -> TravelRouteToolResult:
        if not query.destinations:
            return TravelRouteToolResult(status=ToolStatus.NO_DATA, routes=())

        providers = self._providers.get(query.mode)
        if providers is None:
            logger.info(
                "경로 조회를 지원하지 않는 이동수단 (mode=%s, 등록=%s)",
                query.mode,
                sorted(self._providers),
            )
            return TravelRouteToolResult(
                status=ToolStatus.NO_DATA,
                routes=(),
                warnings=(TRAVEL_ROUTE_MODE_UNSUPPORTED_WARNING,),
            )

        try:
            primary_result = await providers.primary.get_routes(
                query.origin,
                query.destinations,
                mode=query.mode,
                radius_m=query.radius_m,
            )
        except AppError as exc:
            logger.warning(
                "경로 Provider 실패 (mode=%s, code=%s, provider=%s)",
                query.mode,
                exc.code,
                exc.provider,
            )
            return await self._fallback_all(query, providers.fallback, exc)

        failed_ids = frozenset(
            route.place_id
            for route in primary_result.data.routes
            if route.status is not RouteStatus.SUCCESS
        )
        if not failed_ids or providers.fallback is None:
            return TravelRouteToolResult(
                status=_tool_status(primary_result.data.routes),
                routes=primary_result.data.routes,
                provider_metadata=(primary_result.metadata,),
            )

        fallback_destinations = tuple(
            destination for destination in query.destinations if destination.place_id in failed_ids
        )
        try:
            fallback_result = await providers.fallback.get_routes(
                query.origin,
                fallback_destinations,
                mode=query.mode,
                radius_m=query.radius_m,
            )
        except AppError as exc:
            logger.warning(
                "경로 부분 fallback 실패 (mode=%s, code=%s, provider=%s)",
                query.mode,
                exc.code,
                exc.provider,
            )
            return TravelRouteToolResult(
                status=_tool_status(primary_result.data.routes),
                routes=primary_result.data.routes,
                error=_tool_error(exc),
                warnings=(TRAVEL_ROUTE_FALLBACK_FAILED_WARNING,),
                provider_metadata=(primary_result.metadata,),
            )

        fallback_by_id = {route.place_id: route for route in fallback_result.data.routes}
        routes = tuple(
            fallback_by_id.get(route.place_id, route)
            if route.status is not RouteStatus.SUCCESS
            else route
            for route in primary_result.data.routes
        )
        # D-042의 "조용한 폴백 금지". 예외가 난 경로는 위에서 로그를 남기지만,
        # 목적지별 실패는 예외 없이 여기로 오기 때문에 이 분기만 무로그였다 —
        # 카카오가 한 건도 못 풀어도 추정값이 조용히 D까지 흘러갔다.
        replaced_ids = frozenset(
            route.place_id
            for route in primary_result.data.routes
            if route.status is not RouteStatus.SUCCESS and route.place_id in fallback_by_id
        )
        if replaced_ids:
            causes = Counter(
                route.error_code or "unknown"
                for route in primary_result.data.routes
                if route.place_id in replaced_ids
            )
            logger.warning(
                "%s 경로 %d/%d건을 직선거리 추정으로 대체 (원인=%s)",
                query.mode,
                len(replaced_ids),
                len(primary_result.data.routes),
                dict(sorted(causes.items())),
            )
        return TravelRouteToolResult(
            # 실제값과 추정값이 섞였으므로 모두 채워졌어도 degraded 결과다.
            status=ToolStatus.PARTIAL,
            routes=routes,
            warnings=(TRAVEL_ROUTE_FALLBACK_WARNING,),
            provider_metadata=(primary_result.metadata, fallback_result.metadata),
        )

    async def _fallback_all(
        self,
        query: TravelRouteQuery,
        fallback_provider: TravelRouteProvider | None,
        primary_error: AppError,
    ) -> TravelRouteToolResult:
        if fallback_provider is None:
            return TravelRouteToolResult(
                status=ToolStatus.UNAVAILABLE,
                routes=(),
                error=_tool_error(primary_error),
            )
        try:
            fallback_result = await fallback_provider.get_routes(
                query.origin,
                query.destinations,
                mode=query.mode,
                radius_m=query.radius_m,
            )
        except AppError as fallback_error:
            logger.warning(
                "경로 전체 fallback 실패 (mode=%s, code=%s, provider=%s)",
                query.mode,
                fallback_error.code,
                fallback_error.provider,
            )
            return TravelRouteToolResult(
                status=ToolStatus.UNAVAILABLE,
                routes=(),
                error=_tool_error(fallback_error),
                warnings=(TRAVEL_ROUTE_FALLBACK_FAILED_WARNING,),
            )
        return TravelRouteToolResult(
            status=ToolStatus.PARTIAL,
            routes=fallback_result.data.routes,
            warnings=(TRAVEL_ROUTE_FALLBACK_WARNING,),
            provider_metadata=(fallback_result.metadata,),
        )


def _tool_status(routes: tuple[TravelRoute, ...]) -> ToolStatus:
    successful_count = sum(route.status is RouteStatus.SUCCESS for route in routes)
    if successful_count == len(routes) and routes:
        return ToolStatus.SUCCESS
    if successful_count:
        return ToolStatus.PARTIAL
    if routes and all(route.status is RouteStatus.NO_DATA for route in routes):
        return ToolStatus.NO_DATA
    return ToolStatus.UNAVAILABLE


def _tool_error(error: AppError) -> ToolError:
    return ToolError(
        code="unavailable",
        message="이동 경로 정보를 가져오지 못했습니다.",
        cause="timeout" if error.code == "provider_timeout" else "upstream_error",
        retryable=error.retryable,
    )


__all__ = [
    "TRAVEL_ROUTE_FALLBACK_FAILED_WARNING",
    "TRAVEL_ROUTE_FALLBACK_WARNING",
    "TRAVEL_ROUTE_MODE_UNSUPPORTED_WARNING",
    "TravelRouteProviders",
    "TravelRouteQuery",
    "TravelRouteTool",
    "TravelRouteToolResult",
]
