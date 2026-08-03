"""사용자 위치 표현을 종로구 범위의 좌표로 해석하는 내부 Tool."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from app.domain.models import GeocodeResult, LocalSearchPlace
from app.errors import AppError
from app.providers.contracts import (
    ProviderMetadata,
    ProviderSource,
    ProviderStatus,
)
from app.providers.geocoding import get_jongno_landmark_alias
from app.providers.protocols import GeocodingProvider, LocalSearchProvider
from app.repositories.protocols import PlaceLocationRepository
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

    return None


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


@dataclass(frozen=True)
class ResolveLocationQuery:
    location_query: str

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
    place_id: str | None = None
    address: str | None = None
    concentration_name: str | None = None


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
        requested_query = query.location_query.strip()
        if is_address_query(requested_query):
            return await self._resolve_address(requested_query)

        stored_result = await self._lookup_stored_place(requested_query)
        if stored_result is not None:
            return stored_result

        local_search_result = await self._lookup_local_search(requested_query)
        if local_search_result is not None:
            return local_search_result

        alias = get_jongno_landmark_alias(requested_query)

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
                )
            first_data, first_metadata = first
            return self._success_or_policy_result(
                result=first_data,
                requested_query=requested_query,
                provider_query=alias,
                method=ResolutionMethod.ALIAS,
                provider_metadata=(first_metadata,),
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
        )

    async def _resolve_address(self, requested_query: str) -> ResolveLocationResult:
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
        )

    async def _lookup_local_search(self, requested_query: str) -> ResolveLocationResult | None:
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
            return self._error_result(
                status=ResolveLocationStatus.NO_DATA,
                code="no_data",
                cause="ambiguous_location",
                retryable=False,
                details={"reason": "ambiguous_location"},
                provider_metadata=(result.metadata,),
            )
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
            ),
            error=None,
            warnings=("local_search_used",),
            provider_metadata=(metadata,),
        )

    async def _lookup_stored_place(self, requested_query: str) -> ResolveLocationResult | None:
        """저장된 TourAPI 장소를 먼저 찾아 상호명 지오코딩 실패를 줄인다."""
        if self._place_repository is None:
            return None
        try:
            matches = await self._place_repository.find_active_places_by_name(requested_query)
        except AppError:
            # 저장소 장애만으로 주소 기반 지오코딩까지 막지는 않는다.
            return None
        if not matches:
            return None
        metadata = (
            ProviderMetadata(
                source=ProviderSource.SUPABASE_PLACES,
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
                details={"reason": "ambiguous_location"},
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
    ) -> ResolveLocationResult:
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
    if cause == "ambiguous_location":
        return "종로구 안에서 어느 장소인지 조금 더 구체적으로 알려주세요."
    if cause == "outside_supported_region":
        return "현재는 서울특별시 종로구 내 장소만 지원합니다."
    if code == "no_data":
        return "입력한 위치를 찾을 수 없습니다. 주소나 장소명을 확인해주세요."
    return "위치 검색 서비스를 사용할 수 없습니다. 잠시 후 다시 시도해주세요."
