from __future__ import annotations

import httpx
import pytest

from app.domain.models import GeocodeResult
from app.errors import AppError
from app.providers.geocoding import FakeGeocodingProvider, RealGeocodingProvider


@pytest.mark.asyncio
async def test_fake_geocoding_provider_resolves_known_location() -> None:
    provider = FakeGeocodingProvider()

    result = await provider.geocode("경복궁 근처")

    assert result == GeocodeResult(
        query="경복궁 근처", resolved_name="경복궁", latitude=37.5788, longitude=126.9770
    )


@pytest.mark.asyncio
async def test_fake_geocoding_provider_raises_not_found_for_unknown_location() -> None:
    provider = FakeGeocodingProvider()

    with pytest.raises(AppError) as exc_info:
        await provider.geocode("아무도 모르는 동네")

    assert exc_info.value.code == "location_not_found"


@pytest.mark.asyncio
async def test_fake_geocoding_provider_raises_invalid_request_for_blank_query() -> None:
    provider = FakeGeocodingProvider()

    with pytest.raises(AppError) as exc_info:
        await provider.geocode("   ")

    assert exc_info.value.code == "invalid_request"


@pytest.mark.asyncio
async def test_real_geocoding_provider_maps_top_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "meta": {"totalCount": 1, "page": 1, "count": 1},
                "addresses": [
                    {
                        "roadAddress": "서울특별시 종로구 사직로 161",
                        "jibunAddress": "서울특별시 종로구 세종로 1-1",
                        "x": "126.9770",
                        "y": "37.5796",
                        "distance": 0,
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = RealGeocodingProvider(api_key_id="id", api_key="key", client=client)

    result = await provider.geocode("경복궁")

    assert result.resolved_name == "서울특별시 종로구 사직로 161"
    assert result.latitude == pytest.approx(37.5796)
    assert result.longitude == pytest.approx(126.9770)
    await client.aclose()


@pytest.mark.asyncio
async def test_real_geocoding_provider_substitutes_jongno_landmark_alias() -> None:
    seen_queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_queries.append(request.url.params["query"])
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "meta": {"totalCount": 1, "count": 1},
                "addresses": [
                    {
                        "roadAddress": "서울특별시 종로구 사직로 161 경복궁",
                        "x": "126.9770162",
                        "y": "37.5788408",
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = RealGeocodingProvider(api_key_id="id", api_key="key", client=client)

    result = await provider.geocode("경복궁")

    assert seen_queries == ["서울특별시 종로구 사직로 161"]
    assert result.query == "경복궁"
    assert result.resolved_name == "서울특별시 종로구 사직로 161 경복궁"
    await client.aclose()


@pytest.mark.asyncio
async def test_real_geocoding_provider_raises_not_found_on_empty_addresses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": "OK", "meta": {"totalCount": 0}, "addresses": []}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = RealGeocodingProvider(api_key_id="id", api_key="key", client=client)

    with pytest.raises(AppError) as exc_info:
        await provider.geocode("존재하지않는주소12345")

    assert exc_info.value.code == "location_not_found"
    await client.aclose()


@pytest.mark.asyncio
async def test_real_geocoding_provider_raises_unavailable_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"status": "ERROR"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = RealGeocodingProvider(api_key_id="bad", api_key="bad", client=client)

    with pytest.raises(AppError) as exc_info:
        await provider.geocode("서울역")

    assert exc_info.value.code == "geocoding_unavailable"
    await client.aclose()
