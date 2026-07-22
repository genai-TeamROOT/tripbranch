"""TourAPI(한국관광공사) 기반 실제 장소 Provider.

역할: TourAPI locationBasedList2를 호출해 좌표 기준 장소 후보를 조회하고,
      mapper를 통해 공통 PlaceCandidate 모델로 변환해 반환한다.
입력: 위도, 경도, 선호 카테고리, 검색 반경(km).
출력: PlaceCandidate 리스트 (빈 리스트 가능, 예외적 상황에서만 AppError 계열 발생).
호출 시점: PLACE_PROVIDER=real일 때 providers/factory.get_place_provider()가 반환한다.
TODO: detailIntro2 연동으로 operating_hours 채우기.
      contentTypeId를 preferred_categories 기준으로 필터링해 요청 자체를 줄이기.
"""

from __future__ import annotations

import httpx

from app.errors import ProviderTimeoutError, ProviderUnavailableError
from app.providers.mappers import map_tour_api_response
from app.schemas import PlaceCandidate

_LOCATION_BASED_LIST_PATH = "/locationBasedList2"


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

    async def search_places(
        self,
        latitude: float,
        longitude: float,
        preferred_categories: list[str],
        search_radius_km: float,
    ) -> list[PlaceCandidate]:
        radius_m = min(int(search_radius_km * 1000), 20000)  # TourAPI 최대 반경 20km

        params = {
            "serviceKey": self._api_key,
            "MobileOS": "ETC",
            "MobileApp": "TripBranch",
            "_type": "json",
            "mapX": longitude,
            "mapY": latitude,
            "radius": radius_m,
            "arrange": "E",  # 거리순 정렬
            "numOfRows": 20,
            "pageNo": 1,
        }

        url = "http://apis.data.go.kr/B551011/KorService2" + _LOCATION_BASED_LIST_PATH

        try:
            response = await self._client.get(
                url,
                params=params,
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("TourAPI") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError("TourAPI", detail=str(exc)) from exc

        if response.status_code >= 500:
            raise ProviderUnavailableError("TourAPI", detail=f"status={response.status_code}")

        if response.status_code >= 400:
            # 4xx는 재시도해도 소용없는 경우가 많음 (키 오류, 파라미터 오류 등)
            raise ProviderUnavailableError("TourAPI", detail=f"status={response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            # TourAPI는 인증키 오류 시 JSON 대신 XML을 반환하는 경우가 있음
            raise ProviderUnavailableError("TourAPI", detail="non-JSON response") from exc

        result_code = payload.get("response", {}).get("header", {}).get("resultCode")
        if result_code not in (None, "0000"):
            # 결과 코드가 있는데 정상(0000)이 아니면 provider 오류로 취급
            result_msg = payload.get("response", {}).get("header", {}).get("resultMsg", "")
            raise ProviderUnavailableError("TourAPI", detail=f"{result_code}: {result_msg}")

        # 여기 도달하면 응답 자체는 정상. 결과가 0건이어도 그냥 빈 리스트 반환 (에러 아님)
        return map_tour_api_response(payload)
