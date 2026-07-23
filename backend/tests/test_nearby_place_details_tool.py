from __future__ import annotations

import asyncio

import pytest

from app.domain.models import PlaceDetails
from app.errors import ProviderUnavailableError
from app.schemas import PlaceCandidate
from app.tools.nearby_place_details import (
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

    async def search_places(
        self,
        latitude: float,
        longitude: float,
        preferred_categories: list[str],
        search_radius_km: float,
        category_filter=None,
        limit: int = 20,
    ) -> list[PlaceCandidate]:
        self.seen_limit = limit
        return self.candidates[:limit]


class DetailsProvider:
    def __init__(self, failures: frozenset[str] = frozenset()) -> None:
        self.failures = failures
        self.active = 0
        self.max_active = 0

    async def get_details(
        self, content_id: str, content_type_id: str
    ) -> PlaceDetails:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.001)
        self.active -= 1
        if content_id in self.failures:
            raise ProviderUnavailableError("test")
        return _details(_candidate(int(content_id.rsplit("-", 1)[1]), content_type_id))


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


@pytest.mark.asyncio
async def test_tool_returns_no_data_without_candidates() -> None:
    result = await NearbyPlaceDetailsTool(
        SearchProvider([]),
        DetailsProvider(),
    ).execute(NearbyPlaceDetailsQuery(37.5, 127.0))

    assert result.status is ToolStatus.NO_DATA
    assert result.places == ()


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
