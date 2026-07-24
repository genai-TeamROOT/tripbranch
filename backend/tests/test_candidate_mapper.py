from datetime import datetime

import pytest

from app.domain.candidate_mapper import map_places_to_scoring_candidates
from app.providers.stub import FakePlaceProvider
from app.tools.nearby_place_details import NearbyPlaceDetailsQuery, NearbyPlaceDetailsTool


@pytest.mark.asyncio
async def test_maps_place_tool_result_to_scoring_candidate() -> None:
    provider = FakePlaceProvider()
    result = await NearbyPlaceDetailsTool(provider, provider).execute(
        NearbyPlaceDetailsQuery(37.5796, 126.9770, limit=2)
    )

    candidates = map_places_to_scoring_candidates(
        result,
        origin_latitude=37.5796,
        origin_longitude=126.9770,
        visit_at=datetime(2026, 7, 24, 12, 0),
    )

    assert len(candidates) == 2
    assert candidates[0].place_id == "fake-museum-1"
    assert candidates[0].environment_type == "indoor"
    assert candidates[0].operating_hours is not None
    assert candidates[0].raw_source == "fake_place"
