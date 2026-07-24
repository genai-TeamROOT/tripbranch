"""장소 Tool 결과를 Provider 독립적인 ScoringCandidate로 변환한다."""

from __future__ import annotations

import math
from datetime import datetime, time

from app.domain.models import OperatingHours, ScoringCandidate
from app.domain.operating_hours import OperatingAvailability, OperatingSchedule
from app.tools.nearby_place_details import NearbyPlaceDetailsResult

_INDOOR_CATEGORIES = {"museum", "cafe", "gallery", "restaurant", "culture"}
_OUTDOOR_CATEGORIES = {"park", "trail", "beach", "attraction"}


def map_places_to_scoring_candidates(
    result: NearbyPlaceDetailsResult,
    *,
    origin_latitude: float,
    origin_longitude: float,
    visit_at: datetime,
) -> tuple[ScoringCandidate, ...]:
    source = (
        result.provider_metadata[0].source.value
        if result.provider_metadata
        else "unknown"
    )
    return tuple(
        ScoringCandidate(
            place_id=item.candidate.place_id,
            name=item.candidate.name,
            category=item.candidate.category,
            environment_type=_environment_type(item.candidate.category),
            distance_km=_haversine_km(
                origin_latitude,
                origin_longitude,
                item.candidate.latitude,
                item.candidate.longitude,
            ),
            operating_hours=_operating_hours_for_visit(
                item.details.operating_schedule if item.details else None,
                visit_at,
            ),
            raw_source=source,
        )
        for item in result.places
    )


def _environment_type(category: str) -> str:
    normalized = category.strip().lower()
    if normalized in _INDOOR_CATEGORIES:
        return "indoor"
    if normalized in _OUTDOOR_CATEGORIES:
        return "outdoor"
    return "unknown"


def _operating_hours_for_visit(
    schedule: OperatingSchedule | None,
    visit_at: datetime,
) -> OperatingHours | None:
    if schedule is None or schedule.availability is OperatingAvailability.UNKNOWN:
        return None
    if any(visit_at.weekday() in rule.weekdays for rule in schedule.closure_rules):
        return OperatingHours(open_time=time.min, close_time=time.min)
    if schedule.availability is OperatingAvailability.ALL_DAY:
        return OperatingHours(open_time=time.min, close_time=time.max)

    found_supported_range = False
    for rule in schedule.rules:
        if rule.months is not None and visit_at.month not in rule.months:
            continue
        if rule.weekdays is not None and visit_at.weekday() not in rule.weekdays:
            continue
        usable_ranges = tuple(
            item for item in rule.time_ranges if not item.crosses_midnight
        )
        if not usable_ranges:
            continue
        found_supported_range = True
        current_time = visit_at.time()
        active = next(
            (
                item
                for item in usable_ranges
                if item.start <= current_time < item.end
            ),
            None,
        )
        if active is not None:
            return OperatingHours(open_time=active.start, close_time=active.end)
    if found_supported_range:
        return OperatingHours(open_time=time.min, close_time=time.min)
    return None


def _haversine_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    radius_km = 6371.0
    latitude_delta = math.radians(latitude_b - latitude_a)
    longitude_delta = math.radians(longitude_b - longitude_a)
    value = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(math.radians(latitude_a))
        * math.cos(math.radians(latitude_b))
        * math.sin(longitude_delta / 2) ** 2
    )
    return round(radius_km * 2 * math.asin(math.sqrt(value)), 3)
