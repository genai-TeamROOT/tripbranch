"""TourAPI searchFestival2로 행사·축제 목록을 조회하는 Provider.

역할: INFO(question_type=event)가 "지금 이 근처에서 뭐 하나"에 답할 수 있도록
지역 단위 행사 목록을 정규화해서 돌려준다. 장소별 조회 API가 아니라 지역+기간
조회 API라, 대상 장소와의 연결은 상위 Tool·Service가 좌표로 판단한다.

**지역 필터는 lDongRegnCd/lDongSignguCd를 쓴다(D-055).** areaCode/sigunguCode는
응답 항목의 상당수가 비워둔 채 내려와 서버 필터에서 통째로 탈락한다 — 2026-08-07
실측에서 종로구가 `sigunguCode=23`으로는 14건(전부 2025년, 진행 중 0건),
`lDongSignguCd=110`으로는 25건(진행 중 6건)이었다. 장소 검색이 이미 같은 이유로
법정동 코드를 쓰고 있다(place_search_policy.PLACE_SEARCH_LDONG_*).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

import httpx

from app.errors import ProviderTimeoutError, ProviderUnavailableError
from app.providers.contracts import (
    ProviderResult,
    ProviderSource,
    ProviderStatus,
    provider_result,
)
from app.providers.upstream_errors import upstream_error_detail

logger = logging.getLogger(__name__)

_BASE_URL = "https://apis.data.go.kr/B551011/KorService2"
_SEARCH_FESTIVAL_PATH = "/searchFestival2"
# 조회 시작일. 진행 중 판정은 응답의 기간으로 다시 하므로 넉넉히 잡는다 —
# 장기 행사(예: 20260101~20261231)가 시작일 필터에서 빠지지 않게 해야 한다.
_SEARCH_START_DATE_OFFSET_YEARS = 2


@dataclass(frozen=True)
class FestivalEvent:
    """TourAPI 행사 응답을 정규화한 한 건.

    PlaceDetails와 달리 app/domain에 두지 않는다 — INFO event 경로에서만 쓰는
    C 내부 모델이라 패키지 경계를 넘길 이유가 없다.
    """

    content_id: str
    title: str
    start_date: date
    end_date: date
    address: str | None
    latitude: float | None
    longitude: float | None

    def is_ongoing(self, reference_date: date) -> bool:
        return self.start_date <= reference_date <= self.end_date


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _parse_date(value: object) -> date | None:
    """TourAPI의 YYYYMMDD를 date로. 형식이 깨진 행은 버린다."""
    raw = _text(value)
    if raw is None or len(raw) != 8 or not raw.isdigit():
        return None
    try:
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    except ValueError:
        return None


def _parse_coordinate(value: object) -> float | None:
    raw = _text(value)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _items(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    response = payload.get("response")
    body = response.get("body") if isinstance(response, Mapping) else None
    items = body.get("items") if isinstance(body, Mapping) else None
    if not isinstance(items, Mapping):
        return []
    item = items.get("item")
    if isinstance(item, Mapping):
        return [item]
    if isinstance(item, list):
        return [entry for entry in item if isinstance(entry, Mapping)]
    return []


def map_festival_items(
    items: list[Mapping[str, object]],
) -> list[FestivalEvent]:
    """응답 항목을 FestivalEvent로 옮긴다. 기간이 없는 행은 버린다.

    기간이 없으면 "지금 진행 중인가"를 판정할 수 없어 event 질의에 쓸모가 없다.
    좌표는 없어도 남긴다 — 거리 정렬에서만 빠지고 목록에는 실릴 수 있다.
    """

    events: list[FestivalEvent] = []
    for item in items:
        content_id = _text(item.get("contentid"))
        title = _text(item.get("title"))
        start_date = _parse_date(item.get("eventstartdate"))
        end_date = _parse_date(item.get("eventenddate"))
        if content_id is None or title is None or start_date is None or end_date is None:
            continue
        if end_date < start_date:
            continue
        events.append(
            FestivalEvent(
                content_id=content_id,
                title=title,
                start_date=start_date,
                end_date=end_date,
                address=_text(item.get("addr1")),
                latitude=_parse_coordinate(item.get("mapy")),
                longitude=_parse_coordinate(item.get("mapx")),
            )
        )
    return events


class RealFestivalProvider:
    """TourAPI searchFestival2를 호출하는 Provider."""

    def __init__(
        self,
        api_key: str,
        client: httpx.AsyncClient,
        timeout_seconds: float,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def search_festivals(
        self,
        region_code: str,
        district_code: str,
        reference_date: date,
        limit: int = 100,
    ) -> ProviderResult[list[FestivalEvent]]:
        start_date = reference_date.replace(
            year=reference_date.year - _SEARCH_START_DATE_OFFSET_YEARS
        )
        payload = await self._request_json(
            _SEARCH_FESTIVAL_PATH,
            {
                "MobileOS": "ETC",
                "MobileApp": "TripBranch",
                "_type": "json",
                "eventStartDate": start_date.strftime("%Y%m%d"),
                "lDongRegnCd": region_code,
                "lDongSignguCd": district_code,
                "numOfRows": max(1, min(limit, 100)),
            },
        )
        events = map_festival_items(_items(payload))
        return provider_result(
            events,
            source=ProviderSource.TOUR_API_FESTIVAL,
            status=ProviderStatus.SUCCESS if events else ProviderStatus.NO_DATA,
        )

    async def _request_json(
        self, path: str, params: dict[str, object]
    ) -> dict[str, object]:
        """real_place.py와 같은 예외 처리 규약을 따른다.

        request_params.clear()는 traceback·로그에 serviceKey가 남지 않게 하려는
        것이다(backend/.env의 실제 키가 노출되면 안 된다).
        """
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
            request_params.clear()
            logger.error("TourAPI 행사 조회 타임아웃 (path=%s)", path)
            raise ProviderTimeoutError("TourAPI") from None
        except httpx.HTTPStatusError as exc:
            detail = f"HTTP {exc.response.status_code}, {upstream_error_detail(exc.response)}"
            request_params.clear()
            logger.error("TourAPI 행사 조회 실패 (%s, path=%s)", detail, path)
            raise ProviderUnavailableError("TourAPI", detail=detail) from None
        except httpx.HTTPError as exc:
            name = type(exc).__name__
            request_params.clear()
            logger.error("TourAPI 행사 조회 실패 (%s, path=%s)", name, path)
            raise ProviderUnavailableError("TourAPI") from None
        except ValueError:
            request_params.clear()
            logger.error("TourAPI 행사 조회 실패 (non-JSON response, path=%s)", path)
            raise ProviderUnavailableError(
                "TourAPI", detail="non-JSON response"
            ) from None

        header = payload.get("response", {}).get("header", {})
        result_code = str(header.get("resultCode", ""))
        if result_code not in {"", "00", "0000"}:
            logger.error(
                "TourAPI 행사 응답 오류 (resultCode=%s, resultMsg=%s)",
                result_code,
                header.get("resultMsg", ""),
            )
            raise ProviderUnavailableError(
                "TourAPI",
                detail=f"{result_code}: {header.get('resultMsg', '')}",
            )
        return payload


class FakeFestivalProvider:
    """종로구 행사를 고정 목록으로 돌려주는 fake provider.

    좌표·기간·명칭 모두 2026-08-07 실측 응답에서 가져왔다. 값을 임의로 만들면
    "eventplace가 장소명과 안 붙는다"는 실제 특성이 사라져, 근접 매칭 경로가
    한 번도 실행되지 않은 채 테스트가 통과한다.

    reference_date 기준으로 진행 중/종료/예정이 각각 존재하도록 구성했다 —
    상위 Service가 진행 중만 걸러내는지 fake로도 확인할 수 있어야 한다.
    """

    # 기준일을 어디로 잡든 진행 중/종료/예정이 모두 나오도록 상대 오프셋으로 만든다.
    async def search_festivals(
        self,
        region_code: str,
        district_code: str,
        reference_date: date,
        limit: int = 100,
    ) -> ProviderResult[list[FestivalEvent]]:
        from datetime import timedelta

        events = [
            # 진행 중 — 이름이 장소와 안 붙는다(실측의 다수 사례).
            FestivalEvent(
                content_id="3419040",
                title="서울썸머비치",
                start_date=reference_date - timedelta(days=18),
                end_date=reference_date + timedelta(days=2),
                address="서울특별시 종로구 세종대로 175 (세종로)",
                latitude=37.5718478585,
                longitude=126.9761682759,
            ),
            # 진행 중 — 제목에 장소명이 들어가 직접 매칭이 되는 사례.
            FestivalEvent(
                content_id="2648460",
                title="경복궁 별빛야행",
                start_date=reference_date - timedelta(days=3),
                end_date=reference_date + timedelta(days=20),
                address="서울특별시 종로구 사직로 161 (세종로)",
                latitude=37.5796,
                longitude=126.9770,
            ),
            # 종료됨 — 걸러져야 한다.
            FestivalEvent(
                content_id="3312721",
                title="북촌의 날",
                start_date=reference_date - timedelta(days=300),
                end_date=reference_date - timedelta(days=290),
                address="서울특별시 종로구 계동길 37",
                latitude=37.5826,
                longitude=126.9850,
            ),
            # 예정 — 걸러져야 한다.
            FestivalEvent(
                content_id="3401928",
                title="서울국제작가축제",
                start_date=reference_date + timedelta(days=35),
                end_date=reference_date + timedelta(days=40),
                address="서울특별시 종로구 동숭길 122",
                latitude=37.5820,
                longitude=127.0030,
            ),
        ]
        return provider_result(
            events[:limit],
            source=ProviderSource.FAKE_FESTIVAL,
            status=ProviderStatus.SUCCESS,
        )


__all__ = [
    "FakeFestivalProvider",
    "FestivalEvent",
    "RealFestivalProvider",
    "map_festival_items",
]
