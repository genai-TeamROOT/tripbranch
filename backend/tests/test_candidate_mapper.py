from datetime import UTC, datetime

import pytest

from app.agent_context.schemas import (
    ContextValue,
    Coordinates,
    PlaceCandidate,
    ProviderMetadata,
    RecommendationContext,
    ResolvedLocation,
)
from app.domain.candidate_mapper import map_context_to_scoring_candidates


def _context(
    *,
    schedule: dict | None,
    category: str = "cafe",
) -> RecommendationContext:
    return RecommendationContext(
        location=ContextValue(
            status="success",
            data=ResolvedLocation(
                requested_query="경복궁",
                resolved_name="경복궁",
                location=Coordinates(latitude=37.5796, longitude=126.9770),
            ),
        ),
        places=ContextValue(
            status="success",
            data=[
                PlaceCandidate(
                    place_id="place-1",
                    name="후보 장소",
                    category=category,
                    location=Coordinates(latitude=37.5806, longitude=126.9770),
                    operating_schedule=schedule,
                )
            ],
            provider_metadata=[
                ProviderMetadata(
                    source="fake_place",
                    status="success",
                    retrieved_at=datetime(2026, 7, 24, tzinfo=UTC),
                )
            ],
        ),
    )


def test_maps_public_context_to_scoring_candidate() -> None:
    context = _context(
        schedule={
            "availability": "scheduled",
            "rules": [
                {
                    "months": [7],
                    "weekdays": ["friday"],
                    "time_ranges": [
                        {
                            "open_time": "09:00",
                            "close_time": "18:00",
                            "crosses_midnight": False,
                        }
                    ],
                }
            ],
            "closure_rules": [],
        }
    )

    candidates = map_context_to_scoring_candidates(
        context,
        visit_at=datetime(2026, 7, 24, 12, 0),
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.distance_km == pytest.approx(0.111, abs=0.001)
    assert candidate.environment_type == "indoor"
    assert candidate.operating_hours is not None
    assert candidate.operating_hours.open_time.isoformat() == "09:00:00"
    assert candidate.operating_hours.close_time.isoformat() == "18:00:00"
    assert candidate.raw_source == "fake_place"


def test_context_mapper_marks_regular_closure_for_scoring_filter() -> None:
    context = _context(
        schedule={
            "availability": "scheduled",
            "rules": [],
            "time_ranges": [
                {
                    "open_time": "09:00",
                    "close_time": "18:00",
                    "crosses_midnight": False,
                }
            ],
            "closure_rules": [{"weekdays": ["monday"]}],
        }
    )

    candidate = map_context_to_scoring_candidates(
        context,
        visit_at=datetime(2026, 7, 27, 12, 0),
    )[0]

    assert candidate.operating_hours is not None
    assert candidate.operating_hours.open_time == candidate.operating_hours.close_time


def test_context_mapper_keeps_unknown_hours_unverified() -> None:
    candidate = map_context_to_scoring_candidates(
        _context(schedule=None, category="unknown"),
        visit_at=datetime(2026, 7, 24, 12, 0),
    )[0]

    assert candidate.operating_hours is None
    assert candidate.environment_type == "unknown"


def test_context_mapper_returns_empty_without_usable_location_or_places() -> None:
    context = RecommendationContext(
        location=ContextValue(status="no_data", data=None),
        places=ContextValue(status="no_data", data=[]),
    )

    assert (
        map_context_to_scoring_candidates(
            context,
            visit_at=datetime(2026, 7, 24, 12, 0),
        )
        == ()
    )
