from __future__ import annotations

from collections.abc import Iterable

import pytest

from app.domain.models import GeocodeResult
from app.errors import AppError
from app.tools.resolve_location import (
    ResolutionConfidence,
    ResolutionMethod,
    ResolveLocationQuery,
    ResolveLocationStatus,
    ResolveLocationTool,
)


class SequenceGeocodingProvider:
    def __init__(self, responses: Iterable[GeocodeResult | AppError]) -> None:
        self._responses = iter(responses)
        self.calls: list[tuple[str, bool]] = []

    async def geocode(
        self, location_query: str, *, use_alias: bool = True
    ) -> GeocodeResult:
        self.calls.append((location_query, use_alias))
        response = next(self._responses)
        if isinstance(response, AppError):
            raise response
        return response


def _result(
    *,
    query: str = "서울특별시 종로구 사직로 161",
    district: str | None = "종로구",
    count: int = 1,
) -> GeocodeResult:
    return GeocodeResult(
        query=query,
        resolved_name=query,
        latitude=37.5788,
        longitude=126.9770,
        candidate_count=count,
        administrative_district=district,
    )


@pytest.mark.asyncio
async def test_resolves_alias_in_jongno() -> None:
    provider = SequenceGeocodingProvider([_result()])
    tool = ResolveLocationTool(provider)

    result = await tool.execute(ResolveLocationQuery("경복궁"))

    assert result.status is ResolveLocationStatus.SUCCESS
    assert result.location is not None
    assert result.location.resolution_method is ResolutionMethod.ALIAS
    assert result.location.confidence is ResolutionConfidence.EXACT
    assert result.location.provider_query == "서울특별시 종로구 사직로 161"
    assert provider.calls == [("서울특별시 종로구 사직로 161", False)]


@pytest.mark.asyncio
async def test_falls_back_to_original_only_after_alias_no_data() -> None:
    provider = SequenceGeocodingProvider(
        [
            AppError(code="location_not_found", message="없음", status_code=404),
            _result(query="서울특별시 종로구 경복궁"),
        ]
    )

    result = await ResolveLocationTool(provider).execute(
        ResolveLocationQuery("경복궁")
    )

    assert result.status is ResolveLocationStatus.SUCCESS
    assert result.location is not None
    assert result.location.resolution_method is ResolutionMethod.FALLBACK
    assert result.warnings == ("fallback_used",)
    assert provider.calls == [
        ("서울특별시 종로구 사직로 161", False),
        ("경복궁", False),
    ]


@pytest.mark.asyncio
async def test_does_not_fallback_after_provider_failure() -> None:
    provider = SequenceGeocodingProvider(
        [
            AppError(
                code="geocoding_unavailable",
                message="장애",
                status_code=502,
                retryable=True,
            )
        ]
    )

    result = await ResolveLocationTool(provider).execute(
        ResolveLocationQuery("경복궁")
    )

    assert result.status is ResolveLocationStatus.UNAVAILABLE
    assert result.error is not None
    assert result.error.code == "unavailable"
    assert result.error.retryable is True
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_rejects_location_outside_jongno() -> None:
    provider = SequenceGeocodingProvider(
        [_result(query="서울특별시 용산구 한강대로", district="용산구")]
    )

    result = await ResolveLocationTool(provider).execute(
        ResolveLocationQuery("서울역")
    )

    assert result.status is ResolveLocationStatus.UNSUPPORTED
    assert result.error is not None
    assert result.error.cause == "outside_supported_region"


@pytest.mark.asyncio
async def test_ambiguous_location_requires_clarification() -> None:
    provider = SequenceGeocodingProvider([_result(count=3)])

    result = await ResolveLocationTool(provider).execute(
        ResolveLocationQuery("인사동")
    )

    assert result.status is ResolveLocationStatus.NO_DATA
    assert result.error is not None
    assert result.error.cause == "ambiguous_location"
    assert result.error.details["reason"] == "ambiguous_location"


@pytest.mark.asyncio
async def test_unknown_location_is_no_data() -> None:
    provider = SequenceGeocodingProvider(
        [AppError(code="location_not_found", message="없음", status_code=404)]
    )

    result = await ResolveLocationTool(provider).execute(
        ResolveLocationQuery("알 수 없는 장소")
    )

    assert result.status is ResolveLocationStatus.NO_DATA
    assert result.error is not None
    assert result.error.cause == "location_not_found"


@pytest.mark.parametrize("value", ["", " ", "가" * 201])
def test_validates_query(value: str) -> None:
    with pytest.raises(ValueError):
        ResolveLocationQuery(value)
