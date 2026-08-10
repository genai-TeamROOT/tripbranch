"""TourAPI 기반 좌표·키워드 검색과 장소 상세정보 Provider."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from app.domain.models import (
    PlaceCategoryFilter,
    PlaceDetails,
    PlaceOperatingDetails,
    TourPlacePage,
    TourPlaceRecord,
)
from app.domain.operating_hours import normalize_operating_schedule
from app.errors import AppError, ProviderTimeoutError, ProviderUnavailableError
from app.place_search_policy import (
    DEFAULT_PLACE_PROVIDER_RESULT_LIMIT,
    MAX_PLACE_SEARCH_RADIUS_KM,
)
from app.providers.contracts import (
    ProviderResult,
    ProviderSource,
    ProviderStatus,
    provider_result,
)
from app.providers.mappers import map_tour_api_response
from app.providers.upstream_errors import upstream_error_detail
from app.schemas import PlaceCandidate

logger = logging.getLogger(__name__)

_BASE_URL = "https://apis.data.go.kr/B551011/KorService2"
_AREA_BASED_LIST_PATH = "/areaBasedList2"
_LOCATION_BASED_LIST_PATH = "/locationBasedList2"
_SEARCH_KEYWORD_PATH = "/searchKeyword2"
_DETAIL_COMMON_PATH = "/detailCommon2"
_DETAIL_INTRO_PATH = "/detailIntro2"

# 목록 조회 numOfRows 상한. TourAPI가 실제로 받아주는 값이다.
_MAX_LIST_ROWS = 1000
_OPERATING_HOURS_KEYS = (
    "usetime",
    "usetimeculture",
    "playtime",
    "usetimeleports",
    "opentime",
    "opentimefood",
    "checkintime",
    "openperiod",
)
_REST_DATE_KEYS = (
    "restdate",
    "restdateculture",
    "restdateleports",
    "restdateshopping",
    "restdatefood",
)

# 아래 네 묶음은 detailIntro2의 주차·요금 필드다(D-056, 2026-08-08 실측).
# contenttypeid마다 이름이 달라 _first_text로 먼저 걸리는 값을 쓴다.
#
# 축제(15)에는 주차 필드 자체가 없다. 종로구 844건 중 38건이 해당한다.
_PARKING_KEYS = (
    "parking",  # 12 관광지
    "parkingculture",  # 14 문화시설
    "parkinglodging",  # 32 숙박
    "parkingshopping",  # 38 쇼핑
    "parkingfood",  # 39 음식점
    "parkingleports",  # 28 레포츠
)
_PARKING_FEE_KEYS = (
    "parkingfee",  # 14 문화시설
    "parkingfeeleports",  # 28 레포츠
)

# 축제의 이용요금 필드명이 usetimefestival이다. 이름은 시간처럼 보이지만 내용은
# 요금이라, 이 키를 _OPERATING_HOURS_KEYS에 넣으면 영업시간 자리에 "5,000원"이
# 들어간다. 축제 운영시간은 playtime이 담당한다 — 두 목록을 섞지 않는다.
_USE_FEE_KEYS = (
    "usefee",  # 14 문화시설
    "usefeeleports",  # 28 레포츠
    "usetimefestival",  # 15 축제 (이름과 달리 요금)
)
_DISCOUNT_INFO_KEYS = (
    "discountinfo",  # 14 문화시설
    "discountinfofestival",  # 15 축제
    "discountinfofood",  # 39 음식점
)
_TOUR_API_TIMEZONE = ZoneInfo("Asia/Seoul")


def _first_item(payload: Mapping[str, object]) -> dict[str, object]:
    response = payload.get("response")
    body = response.get("body") if isinstance(response, Mapping) else None
    items = body.get("items") if isinstance(body, Mapping) else None
    raw_items = items.get("item", []) if isinstance(items, Mapping) else []
    if isinstance(raw_items, Mapping):
        return dict(raw_items)
    if isinstance(raw_items, list) and raw_items and isinstance(raw_items[0], Mapping):
        return dict(raw_items[0])
    return {}


def _first_text(item: Mapping[str, object], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _body(payload: Mapping[str, object]) -> Mapping[str, object]:
    response = payload.get("response")
    body = response.get("body") if isinstance(response, Mapping) else None
    return body if isinstance(body, Mapping) else {}


def _items(payload: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    items = _body(payload).get("items")
    raw_items = items.get("item", []) if isinstance(items, Mapping) else []
    if isinstance(raw_items, Mapping):
        return (raw_items,) if raw_items else ()
    if isinstance(raw_items, list):
        return tuple(item for item in raw_items if isinstance(item, Mapping))
    return ()


def _required_text(item: Mapping[str, object], key: str) -> str:
    value = item.get(key)
    if value is None or not str(value).strip():
        raise ProviderUnavailableError(
            "TourAPI", detail=f"areaBasedList2 item missing {key}"
        )
    return str(value).strip()


def _optional_float(item: Mapping[str, object], key: str) -> float | None:
    value = item.get(key)
    if value in (None, ""):
        return None
    try:
        return float(str(value))
    except ValueError:
        raise ProviderUnavailableError(
            "TourAPI", detail=f"areaBasedList2 item has invalid {key}"
        ) from None


def _optional_modified_at(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.strptime(str(value), "%Y%m%d%H%M%S").replace(
            tzinfo=_TOUR_API_TIMEZONE
        )
    except ValueError:
        raise ProviderUnavailableError(
            "TourAPI", detail="areaBasedList2 item has invalid modifiedtime"
        ) from None


def _non_negative_int(value: object, field: str) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        raise ProviderUnavailableError(
            "TourAPI", detail=f"areaBasedList2 response has invalid {field}"
        ) from None
    if parsed < 0:
        raise ProviderUnavailableError(
            "TourAPI", detail=f"areaBasedList2 response has invalid {field}"
        )
    return parsed


def _map_area_place(
    item: Mapping[str, object],
    *,
    requested_area_code: str,
    requested_district_code: str,
) -> TourPlaceRecord:
    address_parts = (item.get("addr1"), item.get("addr2"))
    address = " ".join(str(part).strip() for part in address_parts if part).strip() or None
    return TourPlaceRecord(
        content_id=_required_text(item, "contentid"),
        content_type_id=_required_text(item, "contenttypeid"),
        title=_required_text(item, "title"),
        address=address,
        latitude=_optional_float(item, "mapy"),
        longitude=_optional_float(item, "mapx"),
        area_code=requested_area_code,
        district_code=requested_district_code,
        lcls_systm1=_first_text(item, ("lclsSystm1",)),
        lcls_systm2=_first_text(item, ("lclsSystm2",)),
        lcls_systm3=_first_text(item, ("lclsSystm3",)),
        source_modified_at=_optional_modified_at(item.get("modifiedtime")),
        first_image_url=_first_text(item, ("firstimage",)),
        thumbnail_url=_first_text(item, ("firstimage2",)),
    )


class RealPlaceProvider:
    def __init__(
        self,
        api_key: str,
        client: httpx.AsyncClient,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._timeout_seconds = timeout_seconds

    def _base_params(self) -> dict[str, object]:
        return {
            "MobileOS": "ETC",
            "MobileApp": "TripBranch",
            "_type": "json",
        }

    async def _request_json(self, path: str, params: dict[str, object]) -> dict[str, object]:
        request_params = {"serviceKey": self._api_key, **params}
        try:
            response = await self._client.get(
                _BASE_URL + path,
                params=request_params,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException:
            # httpx 예외와 traceback에는 ServiceKey가 포함된 전체 URL이 남을 수 있다.
            request_params.clear()
            response = None
            logger.error("TourAPI 호출 타임아웃 (path=%s)", path)
            raise ProviderTimeoutError("TourAPI") from None
        except httpx.HTTPStatusError as exc:
            # 상태 코드만으로는 인증 실패·쿼터 초과·기간 만료가 구분되지 않는다.
            detail = f"HTTP {exc.response.status_code}, {upstream_error_detail(exc.response)}"
            request_params.clear()
            response = None
            exc = None
            logger.error("TourAPI 호출 실패 (%s, path=%s)", detail, path)
            raise ProviderUnavailableError("TourAPI", detail=detail) from None
        except httpx.HTTPError as exc:
            request_params.clear()
            response = None
            logger.error(
                "TourAPI 호출 실패 (%s, path=%s)", type(exc).__name__, path
            )
            raise ProviderUnavailableError("TourAPI") from None
        except ValueError:
            request_params.clear()
            response = None
            logger.error("TourAPI 호출 실패 (non-JSON response, path=%s)", path)
            raise ProviderUnavailableError(
                "TourAPI", detail="non-JSON response"
            ) from None

        header = payload.get("response", {}).get("header", {})
        result_code = str(header.get("resultCode", ""))
        if result_code not in {"", "00", "0000"}:
            logger.error(
                "TourAPI 응답 오류 (resultCode=%s, resultMsg=%s, path=%s)",
                result_code,
                header.get("resultMsg", ""),
                path,
            )
            raise ProviderUnavailableError(
                "TourAPI",
                detail=f"{result_code}: {header.get('resultMsg', '')}",
            )
        return payload

    async def search_places(
        self,
        latitude: float,
        longitude: float,
        preferred_categories: list[str],
        search_radius_km: float,
        region_code: str | None = None,
        district_code: str | None = None,
        category_filter: PlaceCategoryFilter | None = None,
        limit: int = DEFAULT_PLACE_PROVIDER_RESULT_LIMIT,
    ) -> ProviderResult[list[PlaceCandidate]]:
        radius_m = min(
            int(search_radius_km * 1000),
            int(MAX_PLACE_SEARCH_RADIUS_KM * 1000),
        )
        params = {
            **self._base_params(),
            "mapX": longitude,
            "mapY": latitude,
            "radius": radius_m,
            "arrange": "E",
            "numOfRows": max(1, min(limit, 100)),
            "pageNo": 1,
        }
        if district_code and not region_code:
            raise ValueError("district_code 사용 시 region_code가 필요합니다.")
        if region_code:
            params["lDongRegnCd"] = region_code
        if district_code:
            params["lDongSignguCd"] = district_code
        if category_filter is not None:
            optional_filters = {
                "contentTypeId": category_filter.content_type_id,
                "lclsSystm1": category_filter.lcls_systm1,
                "lclsSystm2": category_filter.lcls_systm2,
                "lclsSystm3": category_filter.lcls_systm3,
            }
            params.update(
                {
                    key: value
                    for key, value in optional_filters.items()
                    if value is not None
                }
            )
        payload = await self._request_json(_LOCATION_BASED_LIST_PATH, params)
        candidates = map_tour_api_response(payload)
        return provider_result(
            candidates,
            source=ProviderSource.TOUR_API_PLACE,
            status=ProviderStatus.SUCCESS if candidates else ProviderStatus.NO_DATA,
        )

    async def list_places_by_area(
        self,
        area_code: str,
        district_code: str,
        page_no: int,
        num_of_rows: int = 100,
    ) -> TourPlacePage:
        normalized_area_code = area_code.strip()
        normalized_district_code = district_code.strip()
        if not normalized_area_code or not normalized_district_code:
            raise ValueError("area_code와 district_code가 필요합니다.")
        if page_no < 1:
            raise ValueError("page_no는 1 이상이어야 합니다.")
        # TourAPI 목록 조회는 numOfRows 1000까지 그대로 반환한다(2026-08-08 확인).
        # 상한을 100으로 두면 종로구 전량 스냅샷에 9회가 필요한데, areaBasedList2는
        # 오퍼레이션 단위 일일 한도가 있어 호출 수를 줄일 수 있어야 한다.
        if not 1 <= num_of_rows <= _MAX_LIST_ROWS:
            raise ValueError(f"num_of_rows는 1 이상 {_MAX_LIST_ROWS} 이하여야 합니다.")

        payload = await self._request_json(
            _AREA_BASED_LIST_PATH,
            {
                **self._base_params(),
                "lDongRegnCd": normalized_area_code,
                "lDongSignguCd": normalized_district_code,
                "arrange": "A",
                "pageNo": page_no,
                "numOfRows": num_of_rows,
            },
        )
        body = _body(payload)
        return TourPlacePage(
            page_no=_non_negative_int(body.get("pageNo"), "pageNo"),
            num_of_rows=_non_negative_int(body.get("numOfRows"), "numOfRows"),
            total_count=_non_negative_int(body.get("totalCount"), "totalCount"),
            places=tuple(
                _map_area_place(
                    item,
                    requested_area_code=normalized_area_code,
                    requested_district_code=normalized_district_code,
                )
                for item in _items(payload)
            ),
        )

    async def get_operating_details(
        self,
        content_id: str,
        content_type_id: str,
    ) -> PlaceOperatingDetails:
        normalized_content_id = content_id.strip()
        normalized_content_type_id = content_type_id.strip()
        if not normalized_content_id or not normalized_content_type_id:
            raise ValueError("content_id와 content_type_id가 필요합니다.")

        payload = await self._request_json(
            _DETAIL_INTRO_PATH,
            {
                **self._base_params(),
                "contentId": normalized_content_id,
                "contentTypeId": normalized_content_type_id,
            },
        )
        intro = _first_item(payload)
        return PlaceOperatingDetails(
            content_id=normalized_content_id,
            content_type_id=normalized_content_type_id,
            operating_hours_raw=_first_text(intro, _OPERATING_HOURS_KEYS),
            rest_date_raw=_first_text(intro, _REST_DATE_KEYS),
            parking_info_raw=_first_text(intro, _PARKING_KEYS),
            parking_fee_raw=_first_text(intro, _PARKING_FEE_KEYS),
            use_fee_raw=_first_text(intro, _USE_FEE_KEYS),
            discount_info_raw=_first_text(intro, _DISCOUNT_INFO_KEYS),
        )

    async def search_by_keyword(
        self,
        keyword: str,
        region_code: str | None = None,
        district_code: str | None = None,
        limit: int = DEFAULT_PLACE_PROVIDER_RESULT_LIMIT,
    ) -> ProviderResult[list[PlaceCandidate]]:
        normalized_keyword = keyword.strip()
        if not normalized_keyword:
            raise ValueError("keyword는 비어 있을 수 없습니다.")
        if district_code and not region_code:
            raise ValueError("district_code 사용 시 region_code가 필요합니다.")

        params = {
            **self._base_params(),
            "keyword": normalized_keyword,
            "arrange": "A",
            "numOfRows": max(1, min(limit, 100)),
            "pageNo": 1,
        }
        if region_code:
            params["lDongRegnCd"] = region_code
        if district_code:
            params["lDongSignguCd"] = district_code

        payload = await self._request_json(_SEARCH_KEYWORD_PATH, params)
        candidates = map_tour_api_response(payload)
        return provider_result(
            candidates,
            source=ProviderSource.TOUR_API_PLACE,
            status=ProviderStatus.SUCCESS if candidates else ProviderStatus.NO_DATA,
        )

    async def get_details(
        self, content_id: str, content_type_id: str
    ) -> ProviderResult[PlaceDetails]:
        if not content_id or not content_type_id:
            raise ValueError("content_id와 content_type_id가 필요합니다.")

        common_payload = await self._request_json(
            _DETAIL_COMMON_PATH,
            {**self._base_params(), "contentId": content_id},
        )
        intro_payload = await self._request_json(
            _DETAIL_INTRO_PATH,
            {
                **self._base_params(),
                "contentId": content_id,
                "contentTypeId": content_type_id,
            },
        )
        common = _first_item(common_payload)
        intro = _first_item(intro_payload)
        address_parts = [common.get("addr1"), common.get("addr2")]
        address = " ".join(str(part) for part in address_parts if part) or None

        operating_hours = _first_text(intro, _OPERATING_HOURS_KEYS)
        rest_date = _first_text(intro, _REST_DATE_KEYS)
        details = PlaceDetails(
            content_id=content_id,
            content_type_id=content_type_id,
            title=_first_text(common, ("title",)),
            address=address,
            overview=_first_text(common, ("overview",)),
            homepage=_first_text(common, ("homepage",)),
            telephone=_first_text(common, ("tel",)) or _first_text(intro, ("infocenter",)),
            operating_hours=operating_hours,
            rest_date=rest_date,
            raw_common=common,
            raw_intro=intro,
            provider="tour_api",
            operating_schedule=normalize_operating_schedule(
                content_type_id=content_type_id,
                operating_hours=operating_hours,
                rest_date=rest_date,
            ),
        )
        has_data = any(
            (
                details.title,
                details.address,
                details.overview,
                details.homepage,
                details.telephone,
                details.operating_hours,
                details.rest_date,
                details.raw_common,
                details.raw_intro,
            )
        )
        return provider_result(
            details,
            source=ProviderSource.TOUR_API_PLACE,
            status=ProviderStatus.SUCCESS if has_data else ProviderStatus.NO_DATA,
        )

    async def find_details_by_name(
        self,
        name: str,
        region_code: str | None = None,
        district_code: str | None = None,
    ) -> ProviderResult[PlaceDetails]:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("name은 비어 있을 수 없습니다.")

        candidates = (await self.search_by_keyword(
            normalized_name,
            region_code=region_code,
            district_code=district_code,
            limit=100,
        )).data
        exact = next(
            (
                candidate
                for candidate in candidates
                if candidate.name.strip().casefold() == normalized_name.casefold()
            ),
            None,
        )
        if exact is None:
            raise AppError(
                code="place_not_found",
                message=f"'{normalized_name}' 장소를 정확히 찾을 수 없어요.",
                status_code=404,
                details={"candidate_names": [item.name for item in candidates[:5]]},
            )
        if not exact.content_type_id:
            raise ProviderUnavailableError(
                "TourAPI", detail="matched place has no contentTypeId"
            )
        return await self.get_details(exact.place_id, exact.content_type_id)
