"""사용자 위치 표현을 종로구 범위의 좌표로 해석하는 내부 Tool."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.domain.models import GeocodeResult
from app.errors import AppError
from app.providers.geocoding import get_jongno_landmark_alias
from app.providers.protocols import GeocodingProvider

_SUPPORTED_DISTRICT = "종로구"


class ResolveLocationStatus(StrEnum):
    SUCCESS = "success"
    NO_DATA = "no_data"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"


class ResolutionMethod(StrEnum):
    DIRECT = "direct"
    ALIAS = "alias"
    FALLBACK = "fallback"


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


@dataclass(frozen=True)
class ResolveLocationError:
    code: str
    message: str
    cause: str | None
    retryable: bool
    details: dict[str, str]


@dataclass(frozen=True)
class ResolveLocationResult:
    status: ResolveLocationStatus
    location: ResolvedLocation | None
    error: ResolveLocationError | None
    warnings: tuple[str, ...] = ()


class ResolveLocationTool:
    def __init__(self, provider: GeocodingProvider) -> None:
        self._provider = provider

    async def execute(self, query: ResolveLocationQuery) -> ResolveLocationResult:
        requested_query = query.location_query.strip()
        alias = get_jongno_landmark_alias(requested_query)

        if alias:
            first = await self._lookup(alias)
            if isinstance(first, ResolveLocationResult):
                if first.status is not ResolveLocationStatus.NO_DATA:
                    return first
                fallback = await self._lookup(requested_query, use_alias=False)
                if isinstance(fallback, ResolveLocationResult):
                    return fallback
                return self._success_or_policy_result(
                    result=fallback,
                    requested_query=requested_query,
                    provider_query=requested_query,
                    method=ResolutionMethod.FALLBACK,
                    warnings=("fallback_used",),
                )
            return self._success_or_policy_result(
                result=first,
                requested_query=requested_query,
                provider_query=alias,
                method=ResolutionMethod.ALIAS,
            )

        direct = await self._lookup(requested_query, use_alias=False)
        if isinstance(direct, ResolveLocationResult):
            return direct
        return self._success_or_policy_result(
            result=direct,
            requested_query=requested_query,
            provider_query=requested_query,
            method=ResolutionMethod.DIRECT,
        )

    async def _lookup(
        self, provider_query: str, *, use_alias: bool = False
    ) -> GeocodeResult | ResolveLocationResult:
        try:
            return await self._provider.geocode(
                provider_query,
                use_alias=use_alias,
            )
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
    ) -> ResolveLocationResult:
        if result.administrative_district != _SUPPORTED_DISTRICT:
            return self._error_result(
                status=ResolveLocationStatus.UNSUPPORTED,
                code="unsupported",
                cause="outside_supported_region",
                retryable=False,
                details={"supported_region": "서울특별시 종로구"},
            )
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
                    if method is ResolutionMethod.ALIAS
                    else ResolutionConfidence.APPROXIMATE
                ),
            ),
            error=None,
            warnings=warnings,
        )

    @staticmethod
    def _error_result(
        *,
        status: ResolveLocationStatus,
        code: str,
        cause: str,
        retryable: bool,
        details: dict[str, str] | None = None,
    ) -> ResolveLocationResult:
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
