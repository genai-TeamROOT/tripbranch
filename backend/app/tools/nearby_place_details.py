"""주변 후보를 검색하고 상세정보를 제한 병렬로 보완하는 내부 Tool."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from time import perf_counter

from app.domain.models import PlaceCategoryFilter, PlaceDetails
from app.errors import AppError
from app.place_search_policy import (
    DEFAULT_PLACE_SEARCH_RADIUS_KM,
    MAX_PLACE_PROVIDER_ROWS,
    MAX_PLACE_SEARCH_RADIUS_KM,
    PLACE_SEARCH_LDONG_REGION_CODE,
)
from app.providers.contracts import ProviderMetadata
from app.providers.protocols import (
    BatchPlaceDetailsProvider,
    PlaceDetailsProvider,
    PlaceSearchProvider,
)
from app.recommendation_limits import (
    DEFAULT_RECOMMENDATION_CANDIDATE_LIMIT,
    MAX_RECOMMENDATION_CANDIDATE_LIMIT,
    MIN_RECOMMENDATION_LIMIT,
)
from app.schemas import PlaceCandidate
from app.tools.contracts import ToolError, ToolStatus

# 필요한 후보 수의 몇 배를 Provider에 요청할지.
#
# **응답에서 쓸 수 없는 행이 빠지기 때문에 필요분만 요청하면 항상 모자란다.**
# Provider는 미지원 분류(숙박·여행코스)와 지원 구 밖 장소를 걸러낸 뒤에 돌려주는데,
# 그 필터는 TourAPI가 numOfRows만큼 행을 고른 **다음에** 걸린다. 그래서 상위 N행에
# 숙박이 하나라도 섞이면 반경에 후보가 아무리 남아 있어도 N곳을 못 채운다.
#
# 3배로 잡은 근거는 실측 생존율이다(2026-08-27, 반경 2km, 30행·60행 요청):
#
#   성수동 97~98% / 안국역 80~87% / 명동 77~78% / 경복궁 62~70%
#   북촌 53~67% / 홍대입구 40~58%
#
# 최저가 홍대입구 40%였고 3배면 그 아래(33%)까지 덮는다. 홍대·북촌이 낮은 이유는
# 게스트하우스가 밀집해 상위 행이 숙박으로 채워지기 때문이다.
#
# **행 수를 늘리는 비용은 응답 크기뿐이다.** TourAPI 목록 조회는 numOfRows를 키워도
# 호출 1회고 일일 한도는 호출 수 기준이라, 한도 소모가 늘지 않는다. 그래서 넉넉히
# 받아 자르는 편이 "모자라면 다시 부르기"보다 싸다.
CANDIDATE_OVERFETCH_FACTOR = 3

# 상한(MAX_PLACE_PROVIDER_ROWS)까지 받고도 요청한 만큼 새 후보를 채우지 못했다.
CANDIDATE_POOL_TRUNCATED_WARNING = "candidate_pool_truncated"

# Provider가 실제 후보를 돌려줬지만, 모두 이전에 노출·거절한 place_id여서 남은
# 후보가 없을 때만 붙인다. 단순히 Provider 호출이 성공했다는 것과는 다르다.
CANDIDATE_POOL_EXHAUSTED_WARNING = "candidate_pool_exhausted"


class DetailStatus(StrEnum):
    SUCCESS = "success"
    NO_DATA = "no_data"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class NearbyPlaceDetailsQuery:
    latitude: float
    longitude: float
    search_radius_km: float = DEFAULT_PLACE_SEARCH_RADIUS_KM
    region_code: str = PLACE_SEARCH_LDONG_REGION_CODE
    # 구는 요청에 싣지 않는다 — 지원 구 판정은 응답의 lDongSignguCd로 한다(D-025).
    # 한 구로 좁히면 반경 안에 있는 옆 지원 구 후보가 잘리고, 구마다 호출하면
    # 호출 수가 구 수만큼 늘어난다.
    district_code: str | None = None
    limit: int = DEFAULT_RECOMMENDATION_CANDIDATE_LIMIT
    preferred_categories: tuple[str, ...] = ()
    category_filter: PlaceCategoryFilter | None = None
    excluded_place_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not -90 <= self.latitude <= 90:
            raise ValueError("latitude는 -90 이상 90 이하여야 합니다.")
        if not -180 <= self.longitude <= 180:
            raise ValueError("longitude는 -180 이상 180 이하여야 합니다.")
        if not 0 < self.search_radius_km <= MAX_PLACE_SEARCH_RADIUS_KM:
            raise ValueError(
                "search_radius_km는 0 초과 "
                f"{MAX_PLACE_SEARCH_RADIUS_KM:g} 이하여야 합니다."
            )
        if not (
            MIN_RECOMMENDATION_LIMIT
            <= self.limit
            <= MAX_RECOMMENDATION_CANDIDATE_LIMIT
        ):
            raise ValueError(
                "limit은 "
                f"{MIN_RECOMMENDATION_LIMIT} 이상 "
                f"{MAX_RECOMMENDATION_CANDIDATE_LIMIT} 이하여야 합니다."
            )


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
        # 제외분만큼 더 받아야 새 후보가 limit만큼 남는다. 장소 검색은 거리순 고정
        # 정렬이라 행 수만 늘리면 이전 결과의 상위집합이 와서 페이지 번호가 필요 없다.
        # 여기에 CANDIDATE_OVERFETCH_FACTOR를 곱하는 이유는 그 상수 주석에 있다 —
        # Provider가 걸러낸 뒤에 돌려주므로 필요분만 요청하면 limit을 못 채운다.
        needed_rows = query.limit + len(query.excluded_place_ids)
        wanted_rows = needed_rows * CANDIDATE_OVERFETCH_FACTOR
        provider_limit = min(MAX_PLACE_PROVIDER_ROWS, wanted_rows)
        row_cap_reached = wanted_rows > MAX_PLACE_PROVIDER_ROWS
        try:
            search_result = await self._search_provider.search_places(
                latitude=query.latitude,
                longitude=query.longitude,
                preferred_categories=list(query.preferred_categories),
                search_radius_km=query.search_radius_km,
                region_code=query.region_code,
                district_code=query.district_code,
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

        # 상한에 걸려 요청한 만큼 못 채운 경우를 표시한다. 판정을 "행 상한에 걸릴
        # 것 같다"가 아니라 **실제로 못 채웠다**로 두는 이유는, 넉넉히 받게 된
        # 뒤로는 상한에 걸리고도 limit을 다 채우는 경우가 흔해졌기 때문이다.
        # 이 표시가 붙은 결과는 "이 근처에 더 없음"이 아니라 "더 받아올 수 없음"이다
        # — 아직 후보가 남았는데 소진됐다고 답하는 걸 막는다.
        truncated = row_cap_reached and len(selected) < query.limit
        exhausted = bool(candidates) and bool(query.excluded_place_ids) and not selected

        if not selected:
            return self._result(
                places=(),
                status=ToolStatus.NO_DATA,
                started_at=started_at,
                provider_metadata=(search_result.metadata,),
                truncated=truncated,
                exhausted=exhausted,
            )

        if isinstance(self._details_provider, BatchPlaceDetailsProvider):
            return await self._enrich_in_batch(
                selected, search_result.metadata, started_at, truncated=truncated
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
            truncated=truncated,
        )

    async def _enrich_in_batch(
        self,
        selected: tuple[PlaceCandidate, ...],
        search_metadata: ProviderMetadata,
        started_at: float,
        *,
        truncated: bool = False,
    ) -> NearbyPlaceDetailsResult:
        """다건 조회를 지원하는 Provider로 후보 상세정보를 한 번에 가져온다.

        후보 순서는 검색 결과(selected) 순회로 재조립해 보존한다.
        """
        # content_type_id가 없는 후보는 단건 경로와 동일하게 조회 대상에서 제외한다
        # (원본인 TourAPI에 유형 정보가 없는 장소이므로 저장소에서도 신뢰하지 않는다).
        target_ids = [
            candidate.place_id for candidate in selected if candidate.content_type_id
        ]

        details_by_id: dict[str, PlaceDetails] = {}
        details_metadata: ProviderMetadata | None = None
        error_code: str | None = None
        if target_ids:
            try:
                batch_result = await self._details_provider.get_details_batch(target_ids)
                details_by_id = batch_result.data
                details_metadata = batch_result.metadata
            except AppError as exc:
                error_code = exc.code

        places: list[EnrichedPlace] = []
        for candidate in selected:
            if not candidate.content_type_id:
                places.append(
                    EnrichedPlace(
                        candidate=candidate,
                        details=None,
                        detail_status=DetailStatus.NO_DATA,
                        error_code="missing_content_type_id",
                    )
                )
                continue
            if error_code is not None:
                places.append(
                    EnrichedPlace(
                        candidate=candidate,
                        details=None,
                        detail_status=DetailStatus.UNAVAILABLE,
                        error_code=error_code,
                    )
                )
                continue
            details = details_by_id.get(candidate.place_id)
            if details is None or not self._has_detail_data(details):
                places.append(
                    EnrichedPlace(
                        candidate=candidate,
                        details=None,
                        detail_status=DetailStatus.NO_DATA,
                        error_code="detail_no_data",
                    )
                )
                continue
            places.append(
                EnrichedPlace(
                    candidate=candidate,
                    details=details,
                    detail_status=DetailStatus.SUCCESS,
                )
            )

        provider_metadata = (search_metadata,) + (
            (details_metadata,) if details_metadata is not None else ()
        )
        return self._result(
            places=tuple(places),
            status=self._batch_status(tuple(places), unavailable=error_code is not None),
            started_at=started_at,
            provider_metadata=provider_metadata,
            truncated=truncated,
        )

    @staticmethod
    def _batch_status(
        places: tuple[EnrichedPlace, ...], *, unavailable: bool
    ) -> ToolStatus:
        if unavailable:
            return ToolStatus.UNAVAILABLE
        if all(item.detail_status is DetailStatus.SUCCESS for item in places):
            return ToolStatus.SUCCESS
        if all(item.detail_status is not DetailStatus.SUCCESS for item in places):
            return ToolStatus.NO_DATA
        return ToolStatus.PARTIAL

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
        truncated: bool = False,
        exhausted: bool = False,
    ) -> NearbyPlaceDetailsResult:
        warnings = ("partial_data",) if status is ToolStatus.PARTIAL else ()
        if truncated:
            warnings = (*warnings, CANDIDATE_POOL_TRUNCATED_WARNING)
        if exhausted:
            warnings = (*warnings, CANDIDATE_POOL_EXHAUSTED_WARNING)
        return NearbyPlaceDetailsResult(
            places=places,
            status=status,
            source="nearby_place_details_tool",
            retrieved_at=datetime.now(UTC),
            elapsed_ms=(perf_counter() - started_at) * 1000,
            error=error,
            warnings=warnings,
            provider_metadata=provider_metadata,
        )
