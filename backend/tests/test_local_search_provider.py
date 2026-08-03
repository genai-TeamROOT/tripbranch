from __future__ import annotations

import httpx
import pytest

from app.errors import AppError
from app.providers.contracts import ProviderSource, ProviderStatus
from app.providers.local_search import RealLocalSearchProvider


@pytest.mark.asyncio
async def test_real_local_search_maps_place_name_address_and_wgs84_coordinates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search/v1/local"
        assert request.url.params["query"] == "쌈지길"
        assert request.url.params["display"] == "5"
        assert request.headers["x-ncp-apigw-api-key-id"] == "test-id"
        assert request.headers["x-ncp-apigw-api-key"] == "test-secret"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "title": "<b>쌈지길</b>",
                        "category": "쇼핑,유통>전통시장",
                        "address": "서울특별시 종로구 관훈동 38",
                        "roadAddress": "서울특별시 종로구 인사동길 44",
                        "mapx": "126.9848674428",
                        "mapy": "37.5743062352",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = RealLocalSearchProvider("test-id", "test-secret", client)
        result = await provider.search_places_by_name("쌈지길")

    assert result.metadata.source is ProviderSource.NAVER_LOCAL_SEARCH
    assert result.metadata.status is ProviderStatus.SUCCESS
    assert result.data[0].name == "쌈지길"
    assert result.data[0].longitude == 126.9848674428
    assert result.data[0].latitude == 37.5743062352


@pytest.mark.asyncio
async def test_real_local_search_converts_http_failure_to_app_error() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(401, request=request))
    ) as client:
        provider = RealLocalSearchProvider("test-id", "test-secret", client)
        with pytest.raises(AppError, match="연동에 문제가"):
            await provider.search_places_by_name("쌈지길")
