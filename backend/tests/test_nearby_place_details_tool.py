from __future__ import annotations

import asyncio

import pytest

from app.domain.models import PlaceDetails
from app.errors import ProviderUnavailableError
from app.providers.contracts import (
    ProviderResult,
    ProviderSource,
    ProviderStatus,
    provider_result,
)
from app.schemas import PlaceCandidate
from app.tools.nearby_place_details import (
    CANDIDATE_POOL_TRUNCATED_WARNING,
    MAX_PLACE_PROVIDER_ROWS,
    DetailStatus,
    NearbyPlaceDetailsQuery,
    NearbyPlaceDetailsTool,
    ToolStatus,
)


def _candidate(index: int, content_type_id: str | None = "12") -> PlaceCandidate:
    return PlaceCandidate(
        place_id=f"place-{index}",
        content_type_id=content_type_id,
        name=f"장소 {index}",
        category="attraction",
        latitude=37.5 + index / 1000,
        longitude=127.0,
        raw_source="test",
    )


def _details(candidate: PlaceCandidate) -> PlaceDetails:
    return PlaceDetails(
        content_id=candidate.place_id,
        content_type_id=candidate.content_type_id or "",
        title=candidate.name,
        address=None,
        overview="상세정보",
        homepage=None,
        telephone=None,
        operating_hours="09:00~18:00",
        rest_date="매주 월요일",
        raw_common={},
        raw_intro={},
        provider="test",
    )


class SearchProvider:
    def __init__(self, candidates: list[PlaceCandidate]) -> None:
        self.candidates = candidates
        self.seen_limit: int | None = None
        self.seen_region_code: str | None = None
        self.seen_district_code: str | None = None

    async def search_places(
        self,
        latitude: float,
        longitude: float,
        preferred_categories: list[str],
        search_radius_km: float,
        region_code: str | None = None,
        district_code: str | None = None,
        category_filter=None,
        limit: int = 20,
    ) -> ProviderResult[list[PlaceCandidate]]:
        self.seen_limit = limit
        self.seen_region_code = region_code
        self.seen_district_code = district_code
        return provider_result(
            self.candidates[:limit],
            source=ProviderSource.FAKE_PLACE,
        )


class DetailsProvider:
    def __init__(self, failures: frozenset[str] = frozenset()) -> None:
        self.failures = failures
        self.active = 0
        self.max_active = 0

    async def get_details(
        self, content_id: str, content_type_id: str
    ) -> ProviderResult[PlaceDetails]:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.001)
        self.active -= 1
        if content_id in self.failures:
            raise ProviderUnavailableError("test")
        return provider_result(
            _details(_candidate(int(content_id.rsplit("-", 1)[1]), content_type_id)),
            source=ProviderSource.FAKE_PLACE,
        )


@pytest.mark.asyncio
async def test_tool_combines_separate_search_and_details_providers() -> None:
    search = SearchProvider([_candidate(index) for index in range(3)])
    details = DetailsProvider()
    tool = NearbyPlaceDetailsTool(search, details)

    result = await tool.execute(NearbyPlaceDetailsQuery(37.5, 127.0))

    assert result.status is ToolStatus.SUCCESS
    assert [item.candidate.place_id for item in result.places] == [
        "place-0",
        "place-1",
        "place-2",
    ]
    assert all(item.detail_status is DetailStatus.SUCCESS for item in result.places)
    assert result.retrieved_at.tzinfo is not None
    assert result.elapsed_ms >= 0
    assert len(result.provider_metadata) == 4
    assert search.seen_region_code == "11"
    # 구는 요청에 싣지 않는다 — 지원 구 판정은 응답의 lDongSignguCd로 한다
    # (D-025). 한 구로 좁히면 반경 안의 옆 지원 구 후보가 잘린다.
    assert search.seen_district_code is None


@pytest.mark.asyncio
async def test_tool_applies_exclusions_limit_and_concurrency() -> None:
    search = SearchProvider([_candidate(index) for index in range(10)])
    details = DetailsProvider()
    tool = NearbyPlaceDetailsTool(search, details, max_concurrency=3)

    result = await tool.execute(
        NearbyPlaceDetailsQuery(
            37.5,
            127.0,
            limit=5,
            excluded_place_ids=frozenset({"place-0", "place-1"}),
        )
    )

    assert search.seen_limit == 7
    assert [item.candidate.place_id for item in result.places] == [
        "place-2",
        "place-3",
        "place-4",
        "place-5",
        "place-6",
    ]
    assert details.max_active <= 3


@pytest.mark.asyncio
async def test_tool_warns_when_row_cap_blocks_new_candidates() -> None:
    """상한에 걸린 빈 결과는 "더 없음"이 아니라 "더 못 받아옴"이다.

    이 경고가 없으면 반경 안에 후보가 남았는데도 소진됐다고 답하게 된다.
    """

    excluded = frozenset(f"place-{index}" for index in range(MAX_PLACE_PROVIDER_ROWS))
    search = SearchProvider(
        [_candidate(index) for index in range(MAX_PLACE_PROVIDER_ROWS)]
    )
    tool = NearbyPlaceDetailsTool(search, DetailsProvider())

    result = await tool.execute(
        NearbyPlaceDetailsQuery(37.5, 127.0, limit=5, excluded_place_ids=excluded)
    )

    # 5 + 100 = 105를 요청했지만 상한이 100이라 새 후보가 하나도 안 남는다.
    assert search.seen_limit == MAX_PLACE_PROVIDER_ROWS
    assert result.status is ToolStatus.NO_DATA
    assert CANDIDATE_POOL_TRUNCATED_WARNING in result.warnings


@pytest.mark.asyncio
async def test_tool_does_not_warn_when_row_cap_is_not_reached() -> None:
    """상한 아래에서는 경고를 붙이지 않는다 — 정상 소진과 구분돼야 한다."""

    search = SearchProvider([_candidate(index) for index in range(10)])
    tool = NearbyPlaceDetailsTool(search, DetailsProvider())

    result = await tool.execute(
        NearbyPlaceDetailsQuery(
            37.5, 127.0, limit=5, excluded_place_ids=frozenset({"place-0"})
        )
    )

    assert CANDIDATE_POOL_TRUNCATED_WARNING not in result.warnings


@pytest.mark.asyncio
async def test_tool_returns_partial_for_detail_failures_and_missing_type() -> None:
    search = SearchProvider([_candidate(0), _candidate(1), _candidate(2, None)])
    details = DetailsProvider(failures=frozenset({"place-1"}))
    tool = NearbyPlaceDetailsTool(search, details)

    result = await tool.execute(NearbyPlaceDetailsQuery(37.5, 127.0))

    assert result.status is ToolStatus.PARTIAL
    assert [item.detail_status for item in result.places] == [
        DetailStatus.SUCCESS,
        DetailStatus.UNAVAILABLE,
        DetailStatus.NO_DATA,
    ]
    assert result.places[1].error_code == "provider_unavailable"
    assert result.places[2].error_code == "missing_content_type_id"
    assert result.warnings == ("partial_data",)
    assert len(result.provider_metadata) == 2
    assert all(
        metadata.source is ProviderSource.FAKE_PLACE
        and metadata.status is ProviderStatus.SUCCESS
        and metadata.retrieved_at.tzinfo is not None
        for metadata in result.provider_metadata
    )


@pytest.mark.asyncio
async def test_tool_returns_no_data_without_candidates() -> None:
    result = await NearbyPlaceDetailsTool(
        SearchProvider([]),
        DetailsProvider(),
    ).execute(NearbyPlaceDetailsQuery(37.5, 127.0))

    assert result.status is ToolStatus.NO_DATA
    assert result.places == ()
    assert result.provider_metadata[0].source is ProviderSource.FAKE_PLACE
    assert result.provider_metadata[0].status is ProviderStatus.SUCCESS
    assert result.provider_metadata[0].retrieved_at.tzinfo is not None


@pytest.mark.asyncio
async def test_tool_maps_search_failure_to_unavailable() -> None:
    class FailingSearchProvider(SearchProvider):
        async def search_places(self, *args, **kwargs):
            raise ProviderUnavailableError("test")

    result = await NearbyPlaceDetailsTool(
        FailingSearchProvider([]),
        DetailsProvider(),
    ).execute(NearbyPlaceDetailsQuery(37.5, 127.0))

    assert result.status is ToolStatus.UNAVAILABLE
    assert result.error is not None
    assert result.error.code == "unavailable"
    assert result.provider_metadata == ()


@pytest.mark.parametrize(
    "query",
    [
        NearbyPlaceDetailsQuery,
    ],
)
def test_query_validation(query) -> None:
    with pytest.raises(ValueError):
        query(91, 127)
    with pytest.raises(ValueError):
        query(37.5, 181)
    with pytest.raises(ValueError):
        query(37.5, 127, search_radius_km=0)
    with pytest.raises(ValueError):
        query(37.5, 127, limit=21)


def test_tool_validates_concurrency() -> None:
    with pytest.raises(ValueError):
        NearbyPlaceDetailsTool(SearchProvider([]), DetailsProvider(), max_concurrency=0)
