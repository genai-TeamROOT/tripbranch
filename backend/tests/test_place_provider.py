from __future__ import annotations

import httpx
import pytest

from app.providers.real_place import RealPlaceProvider


def _payload(item: dict) -> dict:
    return {
        "response": {
            "header": {"resultCode": "0000", "resultMsg": "OK"},
            "body": {"items": {"item": item}},
        }
    }


@pytest.mark.asyncio
async def test_search_by_keyword_returns_content_identifiers() -> None:
    seen_params: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/searchKeyword2")
        seen_params.update(dict(request.url.params))
        return httpx.Response(
            200,
            json=_payload(
                {
                    "contentid": "126508",
                    "contenttypeid": "12",
                    "title": "경복궁",
                    "mapx": "126.9770",
                    "mapy": "37.5788",
                    "addr1": "서울특별시 종로구 사직로 161",
                }
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = RealPlaceProvider(api_key="dummy", client=client)
        result = await provider.search_by_keyword(
            "경복궁", region_code="11", district_code="110"
        )

    assert seen_params["keyword"] == "경복궁"
    assert seen_params["lDongRegnCd"] == "11"
    assert seen_params["lDongSignguCd"] == "110"
    assert result[0].place_id == "126508"
    assert result[0].content_type_id == "12"


@pytest.mark.asyncio
async def test_get_details_combines_common_and_intro_responses() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path.endswith("/detailCommon2"):
            return httpx.Response(
                200,
                json=_payload(
                    {
                        "contentid": "126508",
                        "title": "경복궁",
                        "addr1": "서울특별시 종로구 사직로 161",
                        "overview": "조선 왕조의 법궁",
                        "homepage": "https://example.test",
                        "tel": "02-000-0000",
                    }
                ),
            )
        return httpx.Response(
            200,
            json=_payload(
                {
                    "contentid": "126508",
                    "contenttypeid": "12",
                    "usetime": "09:00~18:00",
                }
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = RealPlaceProvider(api_key="dummy", client=client)
        result = await provider.get_details("126508", "12")

    assert seen_paths[0].endswith("/detailCommon2")
    assert seen_paths[1].endswith("/detailIntro2")
    assert result.title == "경복궁"
    assert result.operating_hours == "09:00~18:00"
    assert result.overview == "조선 왕조의 법궁"


@pytest.mark.asyncio
async def test_search_by_keyword_requires_region_for_district() -> None:
    async with httpx.AsyncClient() as client:
        provider = RealPlaceProvider(api_key="dummy", client=client)
        with pytest.raises(ValueError, match="region_code"):
            await provider.search_by_keyword("경복궁", district_code="110")
