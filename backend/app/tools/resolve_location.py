"""사용자 위치 표현을 지원 지역 안의 좌표로 해석하는 내부 Tool."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from itertools import combinations

from app.domain.models import GeocodeResult, LocalSearchPlace
from app.errors import AppError
from app.geo import haversine_km
from app.providers.contracts import (
    ProviderMetadata,
    ProviderSource,
    ProviderStatus,
)
from app.providers.geocoding import get_landmark_alias
from app.providers.protocols import GeocodingProvider, LocalSearchProvider
from app.repositories.protocols import PlaceLocationRepository
from app.service_area import is_within_service_area, supported_district_label
from app.tools.contracts import ToolError, ToolStatus

ResolveLocationStatus = ToolStatus

# 도로명 주소와 지번 주소를 보수적으로 감지한다. 장소명에 "길"이 포함돼도
# 번지수가 없으면 장소명 검색 흐름을 유지한다.
_ROAD_ADDRESS_PATTERN = re.compile(r"(?:로|길)\s*\d+(?:-\d+)?(?:\s|$)")
_LOT_ADDRESS_PATTERN = re.compile(r"(?:동|읍|면|리)\s*\d+(?:-\d+)?(?:\s|$)")
_ADMIN_ADDRESS_PATTERN = re.compile(
    r"(?:서울(?:특별시)?|부산(?:광역시)?|대구(?:광역시)?|인천(?:광역시)?|"
    r"광주(?:광역시)?|대전(?:광역시)?|울산(?:광역시)?|세종(?:특별자치시)?|"
    r"경기(?:도)?|강원(?:특별자치도|도)?|충북|충청북도|충남|충청남도|전북|"
    r"전라북도|전남|전라남도|경북|경상북도|경남|경상남도|제주(?:특별자치도)?)"
    r"\s+\S+(?:시|군|구)"
)


# 위치를 가리키는 수식어. 장소명 뒤에 붙어도 검색 대상은 앞의 장소다
# ("안국역 근처" → "안국역"). 실측(2026-08-03): "안국역 근처"로 지역 검색하면
# 엘리베이터·모텔·돈까스집이 나와 정답인 "안국역 3호선"이 후보에 없었다.
# 이 목록은 보수적으로 유지한다 — 단어를 늘릴수록 실제 장소명을 잘라낼 위험이 커진다.
_LOCATION_MODIFIER_TOKENS = frozenset({"근처", "주변", "인근", "부근"})


# 같은 역을 노선별로 나눠 반환하는 경우를 한 장소로 묶기 위한 기준.
#
# 지역 검색은 "종로3가역"에 1·3·5호선을 각각 돌려준다. 이름이 달라 정확 일치가 안 되고
# 첫 토큰은 셋 다 같아 못 좁히므로 되묻기로 빠지는데, 사용자에게 몇 호선인지 물어도
# 답이 될 수 없다 — 카페를 찾는 사람에게 무의미하고, 검색 반경이 2km라 어느 출입구를
# 골라도 결과가 같다.
#
# 실측(2026-08-04) 역별 후보 간 최대 거리: 청량리역 381m, 서울역 341m, 종로3가역 291m,
# 시청역 267m, 김포공항역 248m, 공덕역 187m, 왕십리역 137m, 충무로역 47m. 노선 수가
# 아니라 역사 구조가 거리를 결정한다(5개 노선인 왕십리역이 가장 좁다).
_SAME_PLACE_RADIUS_KM = 0.5

# 카테고리도 함께 본다. 거리만 보면 "종각역 김밥천국"처럼 역명을 그대로 앞에 붙인 상호가
# 섞여도 묶이고, 그러면 "첫 후보를 임의로 고르지 않는다"는 원칙이 깨진다(쌈지길 검색에서
# 정답이 3번째였다). 실측한 표기는 4종이었다 — 지하철·전철·기차역·정차역.
_TRANSIT_CATEGORY_MARKERS = ("지하철", "전철", "기차", "철도", "정차역")


def strip_location_modifiers(value: str) -> str:
    """장소명 뒤의 위치 수식어를 떼어낸다. 남는 게 없으면 원문을 유지한다.

    공백으로 구분된 토큰 단위로만 지운다 — "역근처식당"처럼 이름에 붙어 있는
    경우는 건드리지 않는다. "근처 추천해줘"처럼 수식어만 있는 입력은 애초에
    장소 조건이 비어 A가 이 Tool을 호출하지 않지만, 방어적으로 원문을 돌려준다.
    """
    tokens = value.split()
    kept = [token for token in tokens if token not in _LOCATION_MODIFIER_TOKENS]
    if not kept:
        return value
    return " ".join(kept)


def is_address_query(value: str) -> bool:
    """주소 형태의 입력이면 장소명 검색보다 Geocoding을 먼저 사용한다."""
    normalized = " ".join(value.split())
    return bool(
        _ROAD_ADDRESS_PATTERN.search(normalized)
        or _LOT_ADDRESS_PATTERN.search(normalized)
        or _ADMIN_ADDRESS_PATTERN.search(normalized)
    )


def _normalize_name(value: str) -> str:
    return value.casefold().replace(" ", "")


def _head_token(name: str) -> str:
    """공백으로 구분된 첫 토큰. 정규화 전에 잘라야 토큰 경계가 남는다."""
    tokens = name.split()
    return _normalize_name(tokens[0] if tokens else name)


def _select_local_search_candidate(
    candidates: tuple[LocalSearchPlace, ...], requested_query: str
) -> LocalSearchPlace | None:
    """이름으로 유일하게 특정되는 후보만 고른다. 못 좁히면 None(재질문).

    Local Search는 연관도 순으로 주변 상호까지 함께 반환하므로 순위를 판정에 쓰지
    않는다 — 실제로 "쌈지길" 검색에서 정답이 3번째였다. 임의로 첫 후보를 고르면
    엉뚱한 음식점이 검색 중심이 된다.
    """
    normalized_query = _normalize_name(requested_query)

    # 1) 정확 일치. 동명 후보가 2건 이상이면 첫 토큰으로도 못 좁히므로 바로 재질문한다.
    exact = tuple(item for item in candidates if _normalize_name(item.name) == normalized_query)
    if exact:
        return exact[0] if len(exact) == 1 else None

    # 2) 첫 토큰 일치. "안국역 3호선"은 잡고 "안국역사거리"는 배제하기 위해
    #    startswith가 아니라 토큰 단위로 비교한다.
    head_matched = tuple(item for item in candidates if _head_token(item.name) == normalized_query)
    if len(head_matched) == 1:
        return head_matched[0]

    # 3) 같은 역의 노선별 후보라면 하나로 본다. 전부 교통 시설이고 서로 붙어 있을 때만
    #    묶으므로, 상호가 하나라도 섞이면 여기서 걸러져 재질문으로 남는다.
    if len(head_matched) > 1 and _is_same_transit_place(head_matched):
        return head_matched[0]

    return None


# 되묻기 버튼 개수를 UI에서 감당할 만큼으로 제한한다(A2 종로구 대표 스팟 버튼도
# 4개 — docs/design/clarification-options.md 7절과 결을 맞춘다).
_MAX_LOCATION_CANDIDATES = 4


def _join_candidate_names(names: object) -> str:
    """되묻기 버튼용 후보 이름을 "|" 구분 문자열로 합친다.

    ToolError.details가 dict[str, str]라 리스트를 그대로 못 담아, agent_context/
    assembler.py가 다시 split("|")로 푼다. 중복은 순서를 지키며 제거하고 최대
    _MAX_LOCATION_CANDIDATES개까지만 남긴다.
    """
    return "|".join(list(dict.fromkeys(names))[:_MAX_LOCATION_CANDIDATES])


def _is_transit_place(place: LocalSearchPlace) -> bool:
    category = place.category or ""
    return any(marker in category for marker in _TRANSIT_CATEGORY_MARKERS)


# 되묻기 후보로는 지하철역/명소류만 적절하다 — 지역 검색은 주변 상호(식당·카페 등)도
# 같이 돌려주는데, "종각"에 "숙썽수산 종로본점"/"어망집" 같은 식당이 위치 후보로
# 뜨면 사용자가 혼란스럽다(실사용 피드백, 2026-08-13). 사용자가 실제로 궁금한 건
# 지역/랜드마크 이름이지 특정 가게가 아니다.
_LANDMARK_CATEGORY_MARKERS = ("관광", "명소")


def _is_location_pickable(place: LocalSearchPlace) -> bool:
    category = place.category or ""
    return _is_transit_place(place) or any(
        marker in category for marker in _LANDMARK_CATEGORY_MARKERS
    )


def _is_same_transit_place(places: tuple[LocalSearchPlace, ...]) -> bool:
    """모든 후보가 교통 시설이고 서로 _SAME_PLACE_RADIUS_KM 안이면 True."""
    if not all(_is_transit_place(place) for place in places):
        return False
    located = [
        place for place in places if place.latitude is not None and place.longitude is not None
    ]
    if len(located) != len(places):
        # 좌표가 없으면 거리를 확인할 수 없다. 묶지 않고 재질문한다.
        return False
    return all(
        haversine_km(first.latitude, first.longitude, second.latitude, second.longitude)
        <= _SAME_PLACE_RADIUS_KM
        for first, second in combinations(located, 2)
    )


class ResolutionMethod(StrEnum):
    DIRECT = "direct"
    ALIAS = "alias"
    FALLBACK = "fallback"
    DATABASE = "database"
    LOCAL_SEARCH = "local_search"


class ResolutionConfidence(StrEnum):
    EXACT = "exact"
    APPROXIMATE = "approximate"
    UNKNOWN = "unknown"


class LocationSource(StrEnum):
    """이 좌표가 어디서 왔는지. 판정이 아니라 사실이다(D-051).

    기준점을 사용자에게 뭐라고 부를지는 D가 이 값으로 정한다 — QUERY면 사용자가
    말한 이름을 쓰고, DEVICE_GPS면 "현재 위치"라고 한다. C는 출처만 싣고 문구를
    고르지 않는다.
    """

    QUERY = "query"
    DEVICE_GPS = "device_gps"


class LocationPurpose(StrEnum):
    """이 해석이 무엇에 쓰이는지. 사다리 순서를 가른다.

    두 목적이 필요로 하는 것이 다르다.

    - SEARCH_CENTER: 반경 검색의 기준 좌표만 있으면 된다. 사용자가 말한 곳이
      우리 코퍼스의 어느 장소인지는 알 필요가 없다.
    - PLACE_IDENTITY: "여기 혼잡해?"에 답하려면 좌표가 아니라 **집중률 매핑이
      걸린 그 장소**를 확정해야 한다. 좌표 최근접으로 고르면 틀린다 — 북촌
      한옥마을 좌표의 최근접은 가회민화박물관(27m)이고 정작 북촌한옥마을은
      293m로 밀린다(D-043 실측).

    세 목적 모두 저장소를 먼저 본다. 한때 SEARCH_CENTER만 건너뛰었는데(cc3da0ed),
    코퍼스에 없는 이름은 조회가 반드시 실패하는 데다 필터 사다리를 한 칸씩 던지느라
    `places`를 4회 버렸기 때문이다. 필터를 or= 하나로 합쳐 그 비용이 제목 1회 +
    별칭 1회로 줄면서 전제가 사라졌다. REALTIME_CITYDATA만 예외다(아래).
    """

    SEARCH_CENTER = "search_center"
    PLACE_IDENTITY = "place_identity"
    # 서울시 실시간 상권은 TourAPI 코퍼스 밖의 서울 주요 지역도 제공한다. 이 목적은
    # 상호 좌표만 찾고, 이후 C가 서울시 제공 지역 반경을 따로 판정한다. 추천의 지원
    # 지역 제한을 여기서 재사용하면 용리단길 같은 정상 상권 질문이 위치 단계에서
    # 막힌다. 저장소 조회도 건너뛴다 — 권역명("광화문·덕수궁")이나 코퍼스 밖 지명이
    # 대상이라 실패가 정상이다.
    REALTIME_CITYDATA = "realtime_citydata"


@dataclass(frozen=True)
class ResolveLocationQuery:
    location_query: str
    # 기존 호출부와 CLI가 그대로 동작하도록 정체성 확정을 기본으로 둔다.
    purpose: LocationPurpose = LocationPurpose.PLACE_IDENTITY

    def __post_init__(self) -> None:
        normalized = self.location_query.strip()
        if not normalized:
            raise ValueError("location_query는 비어 있을 수 없습니다.")
        if len(normalized) > 200:
            raise ValueError("location_query는 200자 이하여야 합니다.")


@dataclass(frozen=True)
class ResolvedLocation:
    requested_query: str
    provider_query: str
    resolved_name: str
    latitude: float
    longitude: float
    resolution_method: ResolutionMethod
    confidence: ResolutionConfidence
    # 이 Tool은 언제나 사용자가 말한 문자열을 푼다. 기기 GPS로 만든 결과는 Tool을
    # 거치지 않고 service.py::_gps_location_result()가 직접 만들며 거기서만 뒤집는다.
    source: LocationSource = LocationSource.QUERY
    place_id: str | None = None
    address: str | None = None
    # Naver Local Search의 업종. INFO 현재 혼잡 질문에서 관광지 예측과 상권 활동을
    # 구분할 때만 사용하며, 없으면 기존 위치 해석 동작을 유지한다.
    place_category: str | None = None
    # 집중률 응답에서 장소를 골라낼 때 대조할 정식 명칭.
    concentration_name: str | None = None
    # tAtsNm에 넣을 검색어 목록. 앞에서부터 시도한다. 비어 있으면
    # concentration_name을 그대로 쓴다(D-057).
    concentration_search_keys: tuple[str, ...] = ()


ResolveLocationError = ToolError


@dataclass(frozen=True)
class ResolveLocationResult:
    status: ResolveLocationStatus
    location: ResolvedLocation | None
    error: ResolveLocationError | None
    warnings: tuple[str, ...] = ()
    provider_metadata: tuple[ProviderMetadata, ...] = ()


class ResolveLocationTool:
    def __init__(
        self,
        provider: GeocodingProvider,
        place_repository: PlaceLocationRepository | None = None,
        local_search_provider: LocalSearchProvider | None = None,
    ) -> None:
        self._provider = provider
        self._place_repository = place_repository
        self._local_search_provider = local_search_provider

    async def execute(self, query: ResolveLocationQuery) -> ResolveLocationResult:
        # 수식어를 먼저 떼고 조회한다. 주소 판별도 정리된 값으로 해야 "인사동길 44
        # 근처"가 주소로 잡힌다.
        requested_query = strip_location_modifiers(query.location_query.strip())
        enforce_service_area = query.purpose is not LocationPurpose.REALTIME_CITYDATA
        if is_address_query(requested_query):
            return await self._resolve_address(
                requested_query, enforce_service_area=enforce_service_area
            )

        # 검색 중심점도 저장소를 먼저 본다. 예전에는 "코퍼스에 없는 이름은
        # 그 조회가 반드시 실패하므로 왕복만 버린다"는 이유로 건너뛰었는데, 지원
        # 지역이 네 구로 늘면서 그 전제가 깨졌다 — "명동성당 근처"처럼 저장소에
        # 있는 장소를 검색 중심으로 쓰는 요청이 실제로 들어온다. 지역 검색은 그런
        # 이름을 못 좁혀 되묻기로 끝난다("르빵 명동성당점" 같은 주변 상호가 섞인다).
        #
        # 실시간 도시데이터는 그대로 건너뛴다. 그쪽은 코퍼스 밖의 서울 주요
        # 지역을 대상으로 해서 저장소 조회가 실패하는 게 정상이다.
        if query.purpose is not LocationPurpose.REALTIME_CITYDATA:
            stored_result = await self._lookup_stored_place(requested_query)
            if stored_result is not None:
                return stored_result

        local_search_result = await self._lookup_local_search(
            requested_query,
            purpose=query.purpose,
            enforce_service_area=enforce_service_area,
        )
        if local_search_result is not None:
            return local_search_result

        alias = get_landmark_alias(requested_query)

        if alias:
            first = await self._lookup(alias)
            if isinstance(first, ResolveLocationResult):
                if first.status is not ResolveLocationStatus.NO_DATA:
                    return first
                fallback = await self._lookup(requested_query, use_alias=False)
                if isinstance(fallback, ResolveLocationResult):
                    return fallback
                fallback_data, fallback_metadata = fallback
                return self._success_or_policy_result(
                    result=fallback_data,
                    requested_query=requested_query,
                    provider_query=requested_query,
                    method=ResolutionMethod.FALLBACK,
                    warnings=("fallback_used",),
                    provider_metadata=(fallback_metadata,),
                    enforce_service_area=enforce_service_area,
                )
            first_data, first_metadata = first
            return self._success_or_policy_result(
                result=first_data,
                requested_query=requested_query,
                provider_query=alias,
                method=ResolutionMethod.ALIAS,
                provider_metadata=(first_metadata,),
                enforce_service_area=enforce_service_area,
            )

        direct = await self._lookup(requested_query, use_alias=False)
        if isinstance(direct, ResolveLocationResult):
            return direct
        direct_data, direct_metadata = direct
        return self._success_or_policy_result(
            result=direct_data,
            requested_query=requested_query,
            provider_query=requested_query,
            method=ResolutionMethod.DIRECT,
            provider_metadata=(direct_metadata,),
            enforce_service_area=enforce_service_area,
        )

    async def _resolve_address(
        self, requested_query: str, *, enforce_service_area: bool = True
    ) -> ResolveLocationResult:
        """주소는 DB·지역 검색을 건너뛰고 Geocoding으로 바로 해석한다."""
        direct = await self._lookup(requested_query, use_alias=False)
        if isinstance(direct, ResolveLocationResult):
            return direct
        direct_data, direct_metadata = direct
        return self._success_or_policy_result(
            result=direct_data,
            requested_query=requested_query,
            provider_query=requested_query,
            method=ResolutionMethod.DIRECT,
            provider_metadata=(direct_metadata,),
            enforce_service_area=enforce_service_area,
        )

    async def _lookup_local_search(
        self,
        requested_query: str,
        *,
        purpose: LocationPurpose = LocationPurpose.PLACE_IDENTITY,
        enforce_service_area: bool = True,
    ) -> ResolveLocationResult | None:
        """DB에 없는 상호명은 지역 검색으로 좌표를 보완한다."""
        if self._local_search_provider is None:
            return None
        try:
            result = await self._local_search_provider.search_places_by_name(requested_query)
        except AppError:
            # Local Search 장애가 주소 Geocoding fallback을 막지 않게 한다.
            return None
        candidates = tuple(
            item for item in result.data if item.latitude is not None and item.longitude is not None
        )
        if not candidates:
            return None
        selected = _select_local_search_candidate(candidates, requested_query)
        if selected is None:
            # 후보를 못 좁혔는데 찾은 것이 전부 지역 밖이면 되묻기가 아니라 지역 문제다.
            # "부산 해운대"에 "지원 구 안에서 어느 장소인지" 되묻는 일을 막는다.
            if enforce_service_area and not any(
                is_within_service_area(item.latitude, item.longitude)
                for item in candidates
                if item.latitude is not None and item.longitude is not None
            ):
                return self._error_result(
                    status=ResolveLocationStatus.UNSUPPORTED,
                    code="unsupported_region",
                    cause="outside_supported_region",
                    retryable=False,
                    details={"reason": "outside_supported_region"},
                    provider_metadata=(result.metadata,),
                )
            in_area = [
                item
                for item in candidates
                if item.latitude is not None
                and item.longitude is not None
                and is_within_service_area(item.latitude, item.longitude)
            ]
            # 지하철역/명소류로만 좁힌다. 식당·상점은 위치 후보로 부적절하니 안
            # 좁혀진 전체로 폴백하지 않는다 — 여기서 비어 있으면(전부 식당·상점뿐)
            # agent_runtime.py가 A2 종로구 대표 스팟 고정 버튼으로 대신한다
            # (실사용 피드백, 2026-08-13: "그냥 지하철역으로만 가자").
            names_source = [item for item in in_area if _is_location_pickable(item)]
            return self._error_result(
                status=ResolveLocationStatus.NO_DATA,
                code="no_data",
                cause="ambiguous_location",
                retryable=False,
                details={
                    "reason": "ambiguous_location",
                    "candidate_names": _join_candidate_names(item.name for item in names_source),
                },
                provider_metadata=(result.metadata,),
            )
        # 지역 검색이 알아낸 정식 상호명으로 저장소를 다시 찾는다. "북촌"은 저장소에
        # 없지만 지역 검색이 "북촌 한옥마을"을 주므로, 여기서 다시 찾으면 집중률
        # 매핑까지 이어진다. 재조회가 실패해도 지역 검색 결과는 그대로 쓴다.
        if selected.latitude is not None and selected.longitude is not None:
            if enforce_service_area:
                outside = self._outside_service_area_result(
                    selected.latitude, selected.longitude, (result.metadata,)
                )
                if outside is not None:
                    return outside
        # 재조회는 집중률 매핑을 붙이기 위한 것이다. 검색 중심점에는 그 필드가
        # 쓰이지 않으므로(consumer는 service.py의 INFO 혼잡도 한 곳뿐) 건너뛴다.
        if (
            purpose is LocationPurpose.PLACE_IDENTITY
            and selected.name.strip() != requested_query.strip()
        ):
            stored = await self._lookup_stored_place(requested_query, lookup_name=selected.name)
            if stored is not None and stored.status is ResolveLocationStatus.SUCCESS:
                return stored
        return self._local_search_success(requested_query, selected, result.metadata)

    @staticmethod
    def _local_search_success(
        requested_query: str,
        place: LocalSearchPlace,
        metadata: ProviderMetadata,
    ) -> ResolveLocationResult:
        # candidates 단계에서 좌표 존재 여부를 확인했으므로 여기서는 확정값이다.
        assert place.latitude is not None and place.longitude is not None
        return ResolveLocationResult(
            status=ResolveLocationStatus.SUCCESS,
            location=ResolvedLocation(
                requested_query=requested_query,
                provider_query=requested_query,
                resolved_name=place.name,
                latitude=place.latitude,
                longitude=place.longitude,
                resolution_method=ResolutionMethod.LOCAL_SEARCH,
                confidence=ResolutionConfidence.APPROXIMATE,
                address=place.road_address or place.address,
                place_category=place.category,
            ),
            error=None,
            warnings=("local_search_used",),
            provider_metadata=(metadata,),
        )

    async def _lookup_stored_place(
        self, requested_query: str, *, lookup_name: str | None = None
    ) -> ResolveLocationResult | None:
        """저장된 TourAPI 장소를 먼저 찾아 상호명 지오코딩 실패를 줄인다.

        lookup_name을 주면 그 이름으로 조회하되 요청 원문은 그대로 보고한다 — 지역
        검색이 알아낸 상호명으로 재조회할 때 쓴다.
        """
        if self._place_repository is None:
            return None
        try:
            matches = await self._place_repository.find_active_places_by_name(
                lookup_name or requested_query
            )
        except AppError:
            # 저장소 장애만으로 주소 기반 지오코딩까지 막지는 않는다.
            return None
        if not matches:
            return None
        metadata = (
            ProviderMetadata(
                # fake 저장소가 실저장소로 보이면 안 된다(D-042).
                source=getattr(
                    self._place_repository,
                    "provider_source",
                    ProviderSource.SUPABASE_PLACES,
                ),
                status=ProviderStatus.SUCCESS,
                retrieved_at=datetime.now(UTC),
            ),
        )
        if len(matches) > 1:
            return self._error_result(
                status=ResolveLocationStatus.NO_DATA,
                code="no_data",
                cause="ambiguous_location",
                retryable=False,
                details={
                    "reason": "ambiguous_location",
                    "candidate_names": _join_candidate_names(place.title for place in matches),
                },
                provider_metadata=metadata,
            )
        place = matches[0]
        return ResolveLocationResult(
            status=ResolveLocationStatus.SUCCESS,
            location=ResolvedLocation(
                requested_query=requested_query,
                provider_query=place.title,
                resolved_name=place.title,
                latitude=place.latitude,
                longitude=place.longitude,
                resolution_method=ResolutionMethod.DATABASE,
                confidence=ResolutionConfidence.EXACT,
                place_id=place.content_id,
                address=place.address,
                concentration_name=place.concentration_name,
                concentration_search_keys=place.concentration_search_keys,
            ),
            error=None,
            provider_metadata=metadata,
        )

    async def _lookup(
        self, provider_query: str, *, use_alias: bool = False
    ) -> tuple[GeocodeResult, ProviderMetadata] | ResolveLocationResult:
        try:
            result = await self._provider.geocode(
                provider_query,
                use_alias=use_alias,
            )
            return result.data, result.metadata
        except AppError as exc:
            if exc.code == "location_not_found":
                return self._error_result(
                    status=ResolveLocationStatus.NO_DATA,
                    code="no_data",
                    cause="location_not_found",
                    retryable=False,
                )
            return self._error_result(
                status=ResolveLocationStatus.UNAVAILABLE,
                code="unavailable",
                cause=_map_unavailable_cause(exc.code),
                retryable=exc.retryable,
            )

    def _success_or_policy_result(
        self,
        *,
        result: GeocodeResult,
        requested_query: str,
        provider_query: str,
        method: ResolutionMethod,
        warnings: tuple[str, ...] = (),
        provider_metadata: tuple[ProviderMetadata, ...] = (),
        enforce_service_area: bool = True,
    ) -> ResolveLocationResult:
        # 지역 판정을 먼저 한다 - 지원 범위 밖이면 "어느 장소인지" 되물어도 소용없다.
        if enforce_service_area:
            outside = self._outside_service_area_result(
                result.latitude, result.longitude, provider_metadata
            )
            if outside is not None:
                return outside
        if method is not ResolutionMethod.ALIAS and result.candidate_count > 1:
            return self._error_result(
                status=ResolveLocationStatus.NO_DATA,
                code="no_data",
                cause="ambiguous_location",
                retryable=False,
                details={"reason": "ambiguous_location"},
                provider_metadata=provider_metadata,
            )
        return ResolveLocationResult(
            status=ResolveLocationStatus.SUCCESS,
            location=ResolvedLocation(
                requested_query=requested_query,
                provider_query=provider_query,
                resolved_name=result.resolved_name,
                latitude=result.latitude,
                longitude=result.longitude,
                resolution_method=method,
                confidence=(
                    ResolutionConfidence.EXACT
                    if method in (ResolutionMethod.ALIAS, ResolutionMethod.DATABASE)
                    else ResolutionConfidence.APPROXIMATE
                ),
            ),
            error=None,
            warnings=warnings,
            provider_metadata=provider_metadata,
        )

    @classmethod
    def _outside_service_area_result(
        cls,
        latitude: float,
        longitude: float,
        provider_metadata: tuple[ProviderMetadata, ...],
    ) -> ResolveLocationResult | None:
        """지원 지역 밖이면 unsupported, 안이면 None.

        저장소에서 해석된 장소에는 쓰지 않는다 — 이미 지원 구 장소로 등록된 것이라
        경계선에 붙어 있어도 지원 대상이 맞다(D-044).
        """
        if is_within_service_area(latitude, longitude):
            return None
        return cls._error_result(
            status=ResolveLocationStatus.UNSUPPORTED,
            code="unsupported_region",
            cause="outside_supported_region",
            retryable=False,
            details={"reason": "outside_supported_region"},
            provider_metadata=provider_metadata,
        )

    @staticmethod
    def _error_result(
        *,
        status: ResolveLocationStatus,
        code: str,
        cause: str,
        retryable: bool,
        details: dict[str, str] | None = None,
        provider_metadata: tuple[ProviderMetadata, ...] = (),
    ) -> ResolveLocationResult:
        """Provider 조회 뒤 정책 판정이 실패해도 조회 메타데이터는 보존한다."""

        return ResolveLocationResult(
            status=status,
            location=None,
            error=ResolveLocationError(
                code=code,
                message=_error_message(code, cause),
                cause=cause,
                retryable=retryable,
                details=details or {},
            ),
            provider_metadata=provider_metadata,
        )


def _map_unavailable_cause(provider_code: str) -> str:
    if provider_code == "provider_timeout":
        return "timeout"
    return "upstream_error"


def _error_message(code: str, cause: str) -> str:
    # 지원 범위를 문구에 직접 쓰지 않는다 - 구가 늘 때 SUPPORTED_DISTRICTS만
    # 고치면 여기도 따라오게 한다.
    if cause == "ambiguous_location":
        return (
            f"{supported_district_label()} 안에서 어느 장소인지 "
            "조금 더 구체적으로 알려주세요."
        )
    if cause == "outside_supported_region":
        return (
            f"현재는 {supported_district_label(with_city=True)} 안에서만 "
            "찾아드릴 수 있어요."
        )
    if code == "no_data":
        return "입력한 위치를 찾을 수 없습니다. 주소나 장소명을 확인해주세요."
    return "위치 검색 서비스를 사용할 수 없습니다. 잠시 후 다시 시도해주세요."
