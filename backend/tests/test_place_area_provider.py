from __future__ import annotations

import httpx
import pytest

from app.errors import ProviderUnavailableError
from app.providers.real_place import RealPlaceProvider


def _payload(
    item: object,
    *,
    page_no: object = 1,
    num_of_rows: object = 100,
    total_count: object = 1,
) -> dict[str, object]:
    return {
        "response": {
            "header": {"resultCode": "0000", "resultMsg": "OK"},
            "body": {
                "items": item,
                "pageNo": page_no,
                "numOfRows": num_of_rows,
                "totalCount": total_count,
            },
        }
    }


@pytest.mark.asyncio
async def test_list_places_by_area_maps_page_and_place_fields() -> None:
    seen_params: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/areaBasedList2")
        seen_params.update(dict(request.url.params))
        return httpx.Response(
            200,
            json=_payload(
                {
                    "item": [
                        {
                            "contentid": "126508",
                            "contenttypeid": "12",
                            "title": "경복궁",
                            "addr1": "서울특별시 종로구 사직로 161",
                            "addr2": "(세종로)",
                            "mapx": "126.9770162",
                            "mapy": "37.5788222",
                            "areacode": "11",
                            "sigungucode": "110",
                            "lclsSystm1": "VE",
                            "lclsSystm2": "VE01",
                            "lclsSystm3": "VE010100",
                            "modifiedtime": "20260723153045",
                        }
                    ]
                },
                total_count=882,
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await RealPlaceProvider(
            api_key="dummy", client=client
        ).list_places_by_area("11", "110", page_no=1)

    assert seen_params["lDongRegnCd"] == "11"
    assert seen_params["lDongSignguCd"] == "110"
    assert seen_params["pageNo"] == "1"
    assert seen_params["numOfRows"] == "100"
    assert result.total_count == 882
    assert len(result.places) == 1
    place = result.places[0]
    assert place.content_id == "126508"
    assert place.title == "경복궁"
    assert place.address == "서울특별시 종로구 사직로 161 (세종로)"
    assert place.latitude == pytest.approx(37.5788222)
    assert place.longitude == pytest.approx(126.9770162)
    assert place.lcls_systm3 == "VE010100"
    assert place.source_modified_at is not None
    assert place.source_modified_at.isoformat() == "2026-07-23T15:30:45"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("items_value", "expected_count"),
    [
        ("", 0),
        ({"item": {}}, 0),
        (
            {
                "item": {
                    "contentid": "1",
                    "contenttypeid": "12",
                    "title": "한 장소",
                }
            },
            1,
        ),
    ],
)
async def test_list_places_by_area_handles_tour_api_item_shapes(
    items_value: object,
    expected_count: int,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload(items_value, total_count=expected_count),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await RealPlaceProvider(
            api_key="dummy", client=client
        ).list_places_by_area("11", "110", page_no=1)

    assert len(result.places) == expected_count


@pytest.mark.asyncio
async def test_list_places_by_area_rejects_missing_required_identifier() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload({"item": {"contenttypeid": "12", "title": "경복궁"}}),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderUnavailableError) as exc_info:
            await RealPlaceProvider(
                api_key="dummy", client=client
            ).list_places_by_area("11", "110", page_no=1)

    assert exc_info.value.details == {
        "upstream_detail": "areaBasedList2 item missing contentid"
    }


@pytest.mark.asyncio
async def test_list_places_by_area_validates_pagination_before_request() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = RealPlaceProvider(api_key="dummy", client=client)
        with pytest.raises(ValueError, match="page_no"):
            await provider.list_places_by_area("11", "110", page_no=0)
        with pytest.raises(ValueError, match="num_of_rows"):
            await provider.list_places_by_area("11", "110", page_no=1, num_of_rows=101)

    assert calls == 0


@pytest.mark.asyncio
async def test_get_operating_details_calls_only_detail_intro() -> None:
    seen_paths: list[str] = []
    seen_params: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        seen_params.update(dict(request.url.params))
        return httpx.Response(
            200,
            json={
                "response": {
                    "header": {"resultCode": "0000", "resultMsg": "OK"},
                    "body": {
                        "items": {
                            "item": {
                                "contentid": "126508",
                                "contenttypeid": "12",
                                "usetime": "09:00~18:00",
                                "restdate": "매주 화요일",
                            }
                        }
                    },
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await RealPlaceProvider(
            api_key="dummy", client=client
        ).get_operating_details("126508", "12")

    assert seen_paths == ["/B551011/KorService2/detailIntro2"]
    assert seen_params["contentId"] == "126508"
    assert seen_params["contentTypeId"] == "12"
    assert result.operating_hours_raw == "09:00~18:00"
    assert result.rest_date_raw == "매주 화요일"


@pytest.mark.asyncio
async def test_get_operating_details_selects_content_type_specific_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "response": {
                    "header": {"resultCode": "0000", "resultMsg": "OK"},
                    "body": {
                        "items": {
                            "item": {
                                "opentimefood": "11:00~21:00",
                                "restdatefood": "매주 월요일",
                            }
                        }
                    },
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await RealPlaceProvider(
            api_key="dummy", client=client
        ).get_operating_details("food-1", "39")

    assert result.operating_hours_raw == "11:00~21:00"
    assert result.rest_date_raw == "매주 월요일"


@pytest.mark.asyncio
async def test_get_operating_details_accepts_empty_normal_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "response": {
                    "header": {"resultCode": "0000", "resultMsg": "OK"},
                    "body": {"items": ""},
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await RealPlaceProvider(
            api_key="dummy", client=client
        ).get_operating_details("empty-1", "12")

    assert result.operating_hours_raw is None
    assert result.rest_date_raw is None
