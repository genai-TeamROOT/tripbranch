"""외부 호출 없이 직선거리 기반 도보 이동을 추정하는 Provider."""

from __future__ import annotations

import logging
import math

import httpx

from app.domain.travel_route import (
    GeoCoordinate,
    RouteDestination,
    RouteSource,
    RouteStatus,
    WalkingRoute,
    WalkingRouteBatch,
)
from app.errors import ProviderTimeoutError, ProviderUnavailableError
from app.geo import haversine_km
from app.providers.contracts import (
    ProviderResult,
    ProviderSource,
    ProviderStatus,
    provider_result,
)
from app.providers.upstream_errors import upstream_error_detail

logger = logging.getLogger(__name__)

KAKAO_WALKING_DESTINATIONS_URL = (
    "https://apis-navi.kakaomobility.com/affiliate/walking/v1/destinations/directions"
)
MAX_WALKING_DESTINATIONS = 100
MAX_WALKING_RADIUS_M = 12_000


class FakeWalkingRouteProvider:
    """카카오 미연동 환경과 향후 장애 fallback에서 사용할 직선거리 추정기."""

    def __init__(self, walking_speed_mps: float) -> None:
        if walking_speed_mps <= 0:
            raise ValueError("walking_speed_mps는 0보다 커야 합니다.")
        self._walking_speed_mps = walking_speed_mps

    async def get_routes(
        self,
        origin: GeoCoordinate,
        destinations: tuple[RouteDestination, ...],
        *,
        radius_m: int | None = None,
    ) -> ProviderResult[WalkingRouteBatch]:
        _validate_request(destinations, radius_m)

        routes = tuple(self._estimate_route(origin, destination) for destination in destinations)
        status = ProviderStatus.SUCCESS if routes else ProviderStatus.NO_DATA
        return provider_result(
            WalkingRouteBatch(routes=routes),
            source=ProviderSource.FAKE_WALKING_ROUTE,
            status=status,
        )

    def _estimate_route(
        self,
        origin: GeoCoordinate,
        destination: RouteDestination,
    ) -> WalkingRoute:
        distance_m = round(
            haversine_km(
                origin.latitude,
                origin.longitude,
                destination.coordinate.latitude,
                destination.coordinate.longitude,
            )
            * 1000
        )
        return WalkingRoute(
            place_id=destination.place_id,
            status=RouteStatus.SUCCESS,
            source=RouteSource.STRAIGHT_LINE_ESTIMATE,
            distance_m=distance_m,
            duration_seconds=math.ceil(distance_m / self._walking_speed_mps),
        )


class RealKakaoWalkingRouteProvider:
    """카카오모빌리티 제휴 다중 목적지 도보 길찾기 Provider."""

    def __init__(
        self,
        api_key: str,
        client: httpx.AsyncClient,
        walking_speed_mps: float,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not api_key:
            raise ValueError("KAKAO_MOBILITY_REST_API_KEY가 필요합니다.")
        if walking_speed_mps <= 0:
            raise ValueError("walking_speed_mps는 0보다 커야 합니다.")
        self._api_key = api_key
        self._client = client
        self._walking_speed_kph = walking_speed_mps * 3.6
        self._timeout_seconds = timeout_seconds

    async def get_routes(
        self,
        origin: GeoCoordinate,
        destinations: tuple[RouteDestination, ...],
        *,
        radius_m: int | None = None,
    ) -> ProviderResult[WalkingRouteBatch]:
        _validate_request(destinations, radius_m)
        if not destinations:
            return provider_result(
                WalkingRouteBatch(routes=()),
                source=ProviderSource.KAKAO_WALKING_ROUTE,
                status=ProviderStatus.NO_DATA,
            )

        headers = {
            "Authorization": f"KakaoAK {self._api_key}",
            "Content-Type": "application/json",
        }
        request_body: dict[str, object] = {
            "origin": {"x": origin.longitude, "y": origin.latitude},
            "destinations": [
                {
                    "x": destination.coordinate.longitude,
                    "y": destination.coordinate.latitude,
                }
                for destination in destinations
            ],
            "summary": True,
            # 카카오는 km/h, 내부 설정과 Fake Provider는 m/s를 사용한다.
            "default_speed": self._walking_speed_kph,
        }
        if radius_m is not None:
            request_body["radius"] = radius_m

        try:
            response = await self._client.post(
                KAKAO_WALKING_DESTINATIONS_URL,
                headers=headers,
                json=request_body,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException:
            headers.clear()
            logger.error("Kakao Walking Route 호출 타임아웃")
            raise ProviderTimeoutError("Kakao Walking Route") from None
        except httpx.HTTPStatusError as exc:
            detail = f"HTTP {exc.response.status_code}, {upstream_error_detail(exc.response)}"
            headers.clear()
            logger.error("Kakao Walking Route 호출 실패 (%s)", detail)
            raise ProviderUnavailableError("Kakao Walking Route", detail=detail) from None
        except (httpx.HTTPError, ValueError):
            headers.clear()
            logger.error("Kakao Walking Route 응답을 처리하지 못했습니다")
            raise ProviderUnavailableError("Kakao Walking Route") from None

        routes_payload = payload.get("routes") if isinstance(payload, dict) else None
        if not isinstance(routes_payload, list) or len(routes_payload) != len(destinations):
            logger.error(
                "Kakao Walking Route 응답 개수 불일치 (requested=%s, returned=%s)",
                len(destinations),
                len(routes_payload) if isinstance(routes_payload, list) else "invalid",
            )
            raise ProviderUnavailableError("Kakao Walking Route")

        routes = tuple(
            _map_kakao_route(destination.place_id, raw_route)
            for destination, raw_route in zip(destinations, routes_payload, strict=True)
        )
        successful_count = sum(route.status is RouteStatus.SUCCESS for route in routes)
        status = (
            ProviderStatus.SUCCESS
            if successful_count == len(routes)
            else ProviderStatus.PARTIAL
            if successful_count
            else ProviderStatus.NO_DATA
        )
        transaction_id = payload.get("trans_id")
        return provider_result(
            WalkingRouteBatch(
                routes=routes,
                transaction_id=(str(transaction_id) if transaction_id is not None else None),
            ),
            source=ProviderSource.KAKAO_WALKING_ROUTE,
            status=status,
        )


def _validate_request(destinations: tuple[RouteDestination, ...], radius_m: int | None) -> None:
    if len(destinations) > MAX_WALKING_DESTINATIONS:
        raise ValueError(f"destinations는 최대 {MAX_WALKING_DESTINATIONS}개까지 허용됩니다.")
    if radius_m is not None and not 0 < radius_m <= MAX_WALKING_RADIUS_M:
        raise ValueError(f"radius_m는 0 초과 {MAX_WALKING_RADIUS_M} 이하여야 합니다.")


def _map_kakao_route(place_id: str, raw_route: object) -> WalkingRoute:
    if not isinstance(raw_route, dict):
        raise ProviderUnavailableError("Kakao Walking Route")
    try:
        result_code = int(raw_route.get("result_code"))
    except (TypeError, ValueError):
        raise ProviderUnavailableError("Kakao Walking Route") from None

    if result_code != 0:
        return WalkingRoute(
            place_id=place_id,
            status=RouteStatus.NO_DATA,
            source=RouteSource.KAKAO_WALKING,
            error_code=f"kakao_result_{result_code}",
        )

    summary = raw_route.get("summary")
    if not isinstance(summary, dict):
        raise ProviderUnavailableError("Kakao Walking Route")
    try:
        distance_m = int(summary["distance"])
        duration_seconds = int(summary["duration"])
    except (KeyError, TypeError, ValueError):
        raise ProviderUnavailableError("Kakao Walking Route") from None
    if distance_m < 0 or duration_seconds < 0:
        raise ProviderUnavailableError("Kakao Walking Route")
    return WalkingRoute(
        place_id=place_id,
        status=RouteStatus.SUCCESS,
        source=RouteSource.KAKAO_WALKING,
        distance_m=distance_m,
        duration_seconds=duration_seconds,
    )


__all__ = [
    "FakeWalkingRouteProvider",
    "KAKAO_WALKING_DESTINATIONS_URL",
    "MAX_WALKING_DESTINATIONS",
    "MAX_WALKING_RADIUS_M",
    "RealKakaoWalkingRouteProvider",
]
