from __future__ import annotations

import pytest

from app.domain.models import GeocodeResult
from app.errors import AppError
from app.providers.geocoding import FakeGeocodingProvider


@pytest.mark.asyncio
async def test_fake_geocoding_provider_resolves_known_location() -> None:
    provider = FakeGeocodingProvider()

    result = await provider.geocode("경복궁 근처")

    assert result == GeocodeResult(
        query="경복궁 근처", resolved_name="경복궁", latitude=37.5796, longitude=126.9770
    )


@pytest.mark.asyncio
async def test_fake_geocoding_provider_raises_not_found_for_unknown_location() -> None:
    provider = FakeGeocodingProvider()

    with pytest.raises(AppError) as exc_info:
        await provider.geocode("아무도 모르는 동네")

    assert exc_info.value.code == "location_not_found"


@pytest.mark.asyncio
async def test_fake_geocoding_provider_raises_invalid_request_for_blank_query() -> None:
    provider = FakeGeocodingProvider()

    with pytest.raises(AppError) as exc_info:
        await provider.geocode("   ")

    assert exc_info.value.code == "invalid_request"
