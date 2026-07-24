"""주변 후보를 검색하고 상세정보를 제한 병렬로 보완하는 내부 Tool."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from time import perf_counter

from app.domain.models import PlaceCategoryFilter, PlaceDetails
from app.errors import AppError
from app.providers.contracts import ProviderMetadata
from app.providers.protocols import PlaceDetailsProvider, PlaceSearchProvider
from app.schemas import PlaceCandidate
from app.tools.contracts import ToolError, ToolStatus


class DetailStatus(StrEnum):
    SUCCESS = "success"
    NO_DATA = "no_data"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class NearbyPlaceDetailsQuery:
    latitude: float
    longitude: float
    search_radius_km: float = 2.0
    limit: int = 10
    preferred_categories: tuple[str, ...] = ()
    category_filter: PlaceCategoryFilter | None = None
    excluded_place_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not -90 <= self.latitude <= 90:
            raise ValueError("latitude는 -90 이상 90 이하여야 합니다.")
        if not -180 <= self.longitude <= 180:
            raise ValueError("longitude는 -180 이상 180 이하여야 합니다.")
        if not 0 < self.search_radius_km <= 20:
            raise ValueError("search_radius_km는 0 초과 20 이하여야 합니다.")
        if not 1 <= self.limit <= 20:
            raise ValueError("limit은 1 이상 20 이하여야 합니다.")


@dataclass(frozen=True)
class EnrichedPlace:
    candidate: PlaceCandidate
    details: PlaceDetails | None
    detail_status: DetailStatus
    error_code: str | None = None


@dataclass(frozen=True)
class NearbyPlaceDetailsResult:
    places: tuple[EnrichedPlace, ...]
    status: ToolStatus
    source: str
    retrieved_at: datetime
    elapsed_ms: float
    error: ToolError | None = None
    warnings: tuple[str, ...] = ()
    provider_metadata: tuple[ProviderMetadata, ...] = ()


class NearbyPlaceDetailsTool:
    def __init__(
        self,
        search_provider: PlaceSearchProvider,
        details_provider: PlaceDetailsProvider,
        max_concurrency: int = 3,
    ) -> None:
        if not 1 <= max_concurrency <= 10:
            raise ValueError("max_concurrency는 1 이상 10 이하여야 합니다.")
        self._search_provider = search_provider
        self._details_provider = details_provider
        self._max_concurrency = max_concurrency

    async def execute(
        self, query: NearbyPlaceDetailsQuery
    ) -> NearbyPlaceDetailsResult:
        started_at = perf_counter()
        provider_limit = min(
            100,
            query.limit + len(query.excluded_place_ids),
        )
        try:
            search_result = await self._search_provider.search_places(
                latitude=query.latitude,
                longitude=query.longitude,
                preferred_categories=list(query.preferred_categories),
                search_radius_km=query.search_radius_km,
                category_filter=query.category_filter,
                limit=provider_limit,
            )
        except AppError as exc:
            return self._result(
                places=(),
                status=ToolStatus.UNAVAILABLE,
                started_at=started_at,
                provider_metadata=(),
                error=ToolError(
                    code="unavailable",
                    message="주변 장소를 검색하지 못했습니다.",
                    cause=(
                        "timeout"
                        if exc.code == "provider_timeout"
                        else "upstream_error"
                    ),
                    retryable=exc.retryable,
                ),
            )
        candidates = search_result.data
        selected = tuple(
            candidate
            for candidate in candidates
            if candidate.place_id not in query.excluded_place_ids
        )[: query.limit]

        if not selected:
            return self._result(
                places=(),
                status=ToolStatus.NO_DATA,
                started_at=started_at,
                provider_metadata=(search_result.metadata,),
            )

        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def enrich(
            candidate: PlaceCandidate,
        ) -> tuple[EnrichedPlace, ProviderMetadata | None]:
            if not candidate.content_type_id:
                return (
                    EnrichedPlace(
                        candidate=candidate,
                        details=None,
                        detail_status=DetailStatus.NO_DATA,
                        error_code="missing_content_type_id",
                    ),
                    None,
                )

            try:
                async with semaphore:
                    details_result = await self._details_provider.get_details(
                        candidate.place_id,
                        candidate.content_type_id,
                    )
                    details = details_result.data
            except AppError as exc:
                return (
                    EnrichedPlace(
                        candidate=candidate,
                        details=None,
                        detail_status=DetailStatus.UNAVAILABLE,
                        error_code=exc.code,
                    ),
                    None,
                )

            if not self._has_detail_data(details):
                return (
                    EnrichedPlace(
                        candidate=candidate,
                        details=None,
                        detail_status=DetailStatus.NO_DATA,
                        error_code="detail_no_data",
                    ),
                    details_result.metadata,
                )
            return (
                EnrichedPlace(
                    candidate=candidate,
                    details=details,
                    detail_status=DetailStatus.SUCCESS,
                ),
                details_result.metadata,
            )

        enriched = tuple(await asyncio.gather(*(enrich(item) for item in selected)))
        places = tuple(item for item, _ in enriched)
        provider_metadata = (search_result.metadata,) + tuple(
            metadata for _, metadata in enriched if metadata is not None
        )
        status = (
            ToolStatus.SUCCESS
            if all(item.detail_status is DetailStatus.SUCCESS for item in places)
            else ToolStatus.PARTIAL
        )
        return self._result(
            places=places,
            status=status,
            started_at=started_at,
            provider_metadata=provider_metadata,
        )

    @staticmethod
    def _has_detail_data(details: PlaceDetails) -> bool:
        return any(
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

    @staticmethod
    def _result(
        places: tuple[EnrichedPlace, ...],
        status: ToolStatus,
        started_at: float,
        provider_metadata: tuple[ProviderMetadata, ...],
        error: ToolError | None = None,
    ) -> NearbyPlaceDetailsResult:
        return NearbyPlaceDetailsResult(
            places=places,
            status=status,
            source="nearby_place_details_tool",
            retrieved_at=datetime.now(UTC),
            elapsed_ms=(perf_counter() - started_at) * 1000,
            error=error,
            warnings=("partial_data",) if status is ToolStatus.PARTIAL else (),
            provider_metadata=provider_metadata,
        )
