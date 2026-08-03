"""사용자 위치 표현을 종로구 범위의 좌표로 해석하는 내부 Tool."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from app.domain.models import GeocodeResult
from app.errors import AppError
from app.providers.contracts import (
    ProviderMetadata,
    ProviderSource,
    ProviderStatus,
)
from app.providers.geocoding import get_jongno_landmark_alias
from app.providers.protocols import GeocodingProvider
from app.repositories.protocols import PlaceLocationRepository
from app.tools.contracts import ToolError, ToolStatus

ResolveLocationStatus = ToolStatus


class ResolutionMethod(StrEnum):
    DIRECT = "direct"
    ALIAS = "alias"
    FALLBACK = "fallback"
    DATABASE = "database"


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
    ) -> None:
        self._provider = provider
        self._place_repository = place_repository

    async def execute(self, query: ResolveLocationQuery) -> ResolveLocationResult:
        requested_query = query.location_query.strip()
        stored_result = await self._lookup_stored_place(requested_query)
        if stored_result is not None:
            return stored_result

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

    async def _lookup_stored_place(
        self, requested_query: str
    ) -> ResolveLocationResult | None:
        """저장된 TourAPI 장소를 먼저 찾아 상호명 지오코딩 실패를 줄인다."""
        if self._place_repository is None:
            return None
        try:
            matches = await self._place_repository.find_active_places_by_name(
                requested_query
            )
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
        if (
            method is not ResolutionMethod.ALIAS
            and result.candidate_count > 1
        ):
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
