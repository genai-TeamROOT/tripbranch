from __future__ import annotations

import json

import httpx
import pytest

from app.domain.travel_route import (
    GeoCoordinate,
    RouteDestination,
    RouteSource,
    RouteStatus,
)
from app.errors import ProviderTimeoutError, ProviderUnavailableError
from app.providers.contracts import ProviderSource, ProviderStatus
from app.providers.walking_route import (
    KAKAO_WALKING_DESTINATIONS_URL,
    RealKakaoWalkingRouteProvider,
)


def _destinations() -> tuple[RouteDestination, ...]:
    return (
        RouteDestination("first", GeoCoordinate(37.571, 126.981)),
        RouteDestination("second", GeoCoordinate(37.572, 126.982)),
    )


@pytest.mark.asyncio
async def test_kakao_walking_route_sends_official_batch_request_and_maps_routes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == KAKAO_WALKING_DESTINATIONS_URL
        assert request.method == "POST"
        assert request.headers["Authorization"] == "KakaoAK test-key"
        payload = json.loads(request.content)
        assert payload == {
            "origin": {"x": 126.98, "y": 37.57},
            "destinations": [
                {"x": 126.981, "y": 37.571},
                {"x": 126.982, "y": 37.572},
            ],
            "summary": True,
            # 내부 1.2m/s를 공식 API 단위인 km/h로 변환한다.
            "default_speed": pytest.approx(4.32),
            "radius": 2_000,
        }
        return httpx.Response(
            200,
            json={
                "trans_id": "transaction-1",
                "routes": [
                    {
                        "result_code": 0,
                        "result_message": "길찾기 성공",
                        "summary": {"distance": 342, "duration": 345},
                    },
                    {
                        "result_code": 0,
                        "result_message": "길찾기 성공",
                        "summary": {"distance": 532, "duration": 514},
                    },
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await RealKakaoWalkingRouteProvider(
            "test-key", client, walking_speed_mps=1.2
        ).get_routes(
            GeoCoordinate(37.57, 126.98),
            _destinations(),
            radius_m=2_000,
        )

    assert result.data.transaction_id == "transaction-1"
    assert [route.place_id for route in result.data.routes] == ["first", "second"]
    assert [route.distance_m for route in result.data.routes] == [342, 532]
    assert [route.duration_seconds for route in result.data.routes] == [345, 514]
    assert all(route.source is RouteSource.KAKAO_WALKING for route in result.data.routes)
    assert result.metadata.source is ProviderSource.KAKAO_WALKING_ROUTE
    assert result.metadata.status is ProviderStatus.SUCCESS


@pytest.mark.asyncio
async def test_kakao_walking_route_preserves_per_destination_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "routes": [
                    {"result_code": 0, "summary": {"distance": 100, "duration": 90}},
                    {"result_code": 104, "result_message": "경로를 찾을 수 없음"},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await RealKakaoWalkingRouteProvider(
            "test-key", client, walking_speed_mps=1.2
        ).get_routes(GeoCoordinate(37.57, 126.98), _destinations())

    failed = result.data.routes[1]
    assert failed.place_id == "second"
    assert failed.status is RouteStatus.NO_DATA
    assert failed.error_code == "kakao_result_104"
    assert result.metadata.status is ProviderStatus.PARTIAL


@pytest.mark.asyncio
async def test_kakao_walking_route_rejects_mismatched_response_count() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"routes": []}))
    ) as client:
        provider = RealKakaoWalkingRouteProvider("test-key", client, walking_speed_mps=1.2)
        with pytest.raises(ProviderUnavailableError):
            await provider.get_routes(GeoCoordinate(37.57, 126.98), _destinations())


@pytest.mark.parametrize("status_code", [401, 429, 500])
@pytest.mark.asyncio
async def test_kakao_walking_route_converts_http_failure(status_code: int) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                status_code,
                json={"errorCode": "UpstreamError"},
                request=request,
            )
        )
    ) as client:
        provider = RealKakaoWalkingRouteProvider("test-key", client, walking_speed_mps=1.2)
        with pytest.raises(ProviderUnavailableError):
            await provider.get_routes(GeoCoordinate(37.57, 126.98), _destinations())


@pytest.mark.asyncio
async def test_kakao_walking_route_converts_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = RealKakaoWalkingRouteProvider("test-key", client, walking_speed_mps=1.2)
        with pytest.raises(ProviderTimeoutError):
            await provider.get_routes(GeoCoordinate(37.57, 126.98), _destinations())


@pytest.mark.asyncio
async def test_kakao_walking_route_skips_http_for_empty_destinations() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("빈 목적지 요청은 HTTP를 호출하면 안 됩니다.")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await RealKakaoWalkingRouteProvider(
            "test-key", client, walking_speed_mps=1.2
        ).get_routes(GeoCoordinate(37.57, 126.98), ())

    assert result.data.routes == ()
    assert result.metadata.status is ProviderStatus.NO_DATA


@pytest.mark.asyncio
async def test_kakao_walking_route_enforces_official_batch_and_radius_limits() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("유효하지 않은 요청은 HTTP를 호출하면 안 됩니다.")

    destinations = tuple(
        RouteDestination(str(index), GeoCoordinate(37.57, 126.98)) for index in range(101)
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = RealKakaoWalkingRouteProvider("test-key", client, walking_speed_mps=1.2)
        with pytest.raises(ValueError, match="최대 100개"):
            await provider.get_routes(GeoCoordinate(37.57, 126.98), destinations)
        with pytest.raises(ValueError, match="12000"):
            await provider.get_routes(
                GeoCoordinate(37.57, 126.98), _destinations(), radius_m=12_001
            )
