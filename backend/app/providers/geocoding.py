"""GeocodingProvider 계약과 구현체.

계약: 자유 텍스트(주소 또는 장소명)를 좌표로 변환한다. 결과가 없으면
AppError(code="location_not_found")를 던진다. 검색 결과가 여러 건이면 API가
반환한 순서(관련도/거리순) 중 첫 번째 결과를 채택한다 - 모호함을 사용자에게
되묻는 흐름은 이번 범위에 포함하지 않는다.
"""

from __future__ import annotations

import httpx

from app.domain.models import GeocodeResult
from app.errors import AppError
from app.providers.contracts import ProviderResult, ProviderSource, provider_result

_GEOCODE_URL = "https://maps.apigw.ntruss.com/map-geocode/v2/geocode"

# Naver Geocoding은 도로명/지번 주소와 행정동/법정동 이름은 인식하지만("인사동",
# "익선동"은 그대로 통함) 궁궐·공원·상가 같은 개별 장소명(POI)은 인식하지 못한다
# (실제 호출로 확인, backend/docs/api-samples.md 참고). MVP 범위를 서울 종로구로
# 한정하기로 해서, 종로구의 잘 알려진 장소명만 우선 formal 주소로 치환해 우회한다.
# 각 주소는 실제 Naver Geocoding 호출로 결과가 나오는 것을 확인한 값이다.
_JONGNO_LANDMARK_ADDRESS_ALIASES: dict[str, str] = {
    "경복궁": "서울특별시 종로구 사직로 161",
    "광화문": "서울특별시 종로구 사직로 161",  # 경복궁 정문
    "창덕궁": "서울특별시 종로구 율곡로 99",
    "종묘": "서울특별시 종로구 종로 157",
    "탑골공원": "서울특별시 종로구 종로 99",
    "북촌한옥마을": "서울특별시 종로구 계동길 37",
    "광장시장": "서울특별시 종로구 창경궁로 88",
    "청계광장": "서울특별시 종로구 청계천로 1",
    "종로구청": "서울특별시 종로구 삼봉로 43",
    "대학로": "서울특별시 종로구 대학로 100",
    "동묘": "서울특별시 종로구 종로 359",
    "낙원악기상가": "서울특별시 종로구 삼일대로 428",
    "낙원상가": "서울특별시 종로구 삼일대로 428",
}


def get_jongno_landmark_alias(normalized_query: str) -> str | None:
    for name, address in _JONGNO_LANDMARK_ADDRESS_ALIASES.items():
        if name in normalized_query:
            return address
    return None


def _apply_landmark_alias(normalized_query: str) -> str:
    return get_jongno_landmark_alias(normalized_query) or normalized_query


# 로컬 개발/테스트용 고정 지명 테이블. MVP 범위(서울 종로구)에 맞춰
# _JONGNO_LANDMARK_ADDRESS_ALIASES와 같은 장소들로 구성했다. substring 매칭으로 찾는다.
_KNOWN_LOCATIONS: dict[str, tuple[str, float, float]] = {
    "경복궁": ("경복궁", 37.5788, 126.9770),
    "광화문": ("광화문", 37.5788, 126.9770),
    "창덕궁": ("창덕궁", 37.5826, 126.9919),
    "종묘": ("종묘", 37.5739, 126.9945),
    "인사동": ("인사동", 37.5717, 126.9860),
}


class FakeGeocodingProvider:
    """정해진 소수의 지명만 좌표로 변환하는 가짜 구현."""

    async def geocode(
        self, query: str, *, use_alias: bool = True
    ) -> ProviderResult[GeocodeResult]:
        normalized = query.strip()
        if not normalized:
            raise AppError(code="invalid_request", message="위치를 입력해주세요.")

        provider_query = (
            _apply_landmark_alias(normalized) if use_alias else normalized
        )
        alias_name = next(
            (
                name
                for name, address in _JONGNO_LANDMARK_ADDRESS_ALIASES.items()
                if address == provider_query and name in _KNOWN_LOCATIONS
            ),
            None,
        )
        if alias_name:
            resolved_name, lat, lon = _KNOWN_LOCATIONS[alias_name]
            return provider_result(
                GeocodeResult(
                    query=query,
                    resolved_name=resolved_name,
                    latitude=lat,
                    longitude=lon,
                    administrative_district="종로구",
                ),
                source=ProviderSource.FAKE_GEOCODING,
            )

        for name, (resolved_name, lat, lon) in _KNOWN_LOCATIONS.items():
            if name in provider_query:
                return provider_result(
                    GeocodeResult(
                        query=query,
                        resolved_name=resolved_name,
                        latitude=lat,
                        longitude=lon,
                        administrative_district="종로구",
                    ),
                    source=ProviderSource.FAKE_GEOCODING,
                )

        raise AppError(
            code="location_not_found",
            message=f"'{query}' 위치를 찾을 수 없어요.",
            status_code=404,
        )


class RealGeocodingProvider:
    """Naver Cloud Platform Geocoding API를 사용하는 실제 구현.

    이 API는 도로명/지번 주소 검색에 최적화되어 있어 개별 장소명(POI)은 인식하지
    못한다. 종로구 MVP 범위의 잘 알려진 장소명은 _JONGNO_LANDMARK_ADDRESS_ALIASES로
    formal 주소로 치환해서 우회하고, 그 외 지역/장소명은 아직 지원하지 않는다.
    """

    def __init__(
        self,
        api_key_id: str,
        api_key: str,
        client: httpx.AsyncClient,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._api_key_id = api_key_id
        self._api_key = api_key
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def geocode(
        self, query: str, *, use_alias: bool = True
    ) -> ProviderResult[GeocodeResult]:
        normalized = query.strip()
        if not normalized:
            raise AppError(code="invalid_request", message="위치를 입력해주세요.")

        request_headers = {
            "Accept": "application/json",
            "x-ncp-apigw-api-key-id": self._api_key_id,
            "x-ncp-apigw-api-key": self._api_key,
        }
        provider_query = (
            _apply_landmark_alias(normalized) if use_alias else normalized
        )
        params = {"query": provider_query, "count": "5"}

        try:
            response = await self._client.get(
                _GEOCODE_URL,
                params=params,
                headers=request_headers,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            # httpx 원인 예외에는 인증 헤더가 포함된 요청 정보가 남을 수 있다.
            request_headers.clear()
            response = None
            raise AppError(
                code="geocoding_unavailable",
                message="위치 검색 서비스를 사용할 수 없습니다.",
                status_code=502,
                retryable=True,
            ) from None

        if payload.get("status") != "OK":
            raise AppError(
                code="geocoding_unavailable",
                message="위치 검색 서비스를 사용할 수 없습니다.",
                status_code=502,
                retryable=True,
            )

        addresses = payload.get("addresses", [])
        if not addresses:
            raise AppError(
                code="location_not_found",
                message=f"'{query}' 위치를 찾을 수 없어요.",
                status_code=404,
            )

        top = addresses[0]
        resolved_name = top.get("roadAddress") or top.get("jibunAddress") or normalized
        meta = payload.get("meta")
        total_count = meta.get("totalCount") if isinstance(meta, dict) else None
        try:
            candidate_count = int(total_count)
        except (TypeError, ValueError):
            candidate_count = len(addresses)
        return provider_result(
            GeocodeResult(
                query=query,
                resolved_name=resolved_name,
                latitude=float(top["y"]),
                longitude=float(top["x"]),
                candidate_count=max(candidate_count, len(addresses)),
                administrative_district=_extract_district(top, resolved_name),
            ),
            source=ProviderSource.NAVER_GEOCODING,
        )


def _extract_district(address: dict, resolved_name: str) -> str | None:
    elements = address.get("addressElements")
    if isinstance(elements, list):
        for element in elements:
            if not isinstance(element, dict) or "SIGUGUN" not in element.get("types", []):
                continue
            district = element.get("shortName") or element.get("longName")
            if district:
                return str(district).strip()
    if "종로구" in resolved_name:
        return "종로구"
    return None
