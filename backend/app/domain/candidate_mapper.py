"""장소 Tool 결과를 Provider 독립적인 ScoringCandidate로 변환한다."""

from __future__ import annotations

import math
from datetime import datetime, time
from typing import Any

from app.agent_context.schemas import RecommendationContext
from app.domain.models import OperatingHours, ScoringCandidate

_INDOOR_CATEGORIES = {"museum", "cafe", "gallery", "restaurant", "culture"}
_OUTDOOR_CATEGORIES = {"park", "trail", "beach", "attraction"}
_WEEKDAY_NAMES = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def map_context_to_scoring_candidates(
    context: RecommendationContext,
    *,
    visit_at: datetime,
) -> tuple[ScoringCandidate, ...]:
    """A–C 공개 Context를 D의 ScoringCandidate 목록으로 변환한다.

    공휴일 Context는 이번 변환에서 사용하지 않는다. 정기 휴무 요일과 운영시간은
    장소별 ``operating_schedule``만 사용하고, 실제 폐점 제외는 Scoring이 수행한다.
    """

    location_value = context.location
    places_value = context.places
    if (
        location_value is None
        or location_value.status not in {"success", "partial"}
        or location_value.data is None
        or places_value is None
        or places_value.status not in {"success", "partial"}
        or not places_value.data
    ):
        return ()

    origin = location_value.data.location
    source = (
        places_value.provider_metadata[0].source if places_value.provider_metadata else "unknown"
    )
    return tuple(
        ScoringCandidate(
            place_id=place.place_id,
            name=place.name,
            category=place.category,
            environment_type=_environment_type(place.category),
            distance_km=_haversine_km(
                origin.latitude,
                origin.longitude,
                place.location.latitude,
                place.location.longitude,
            ),
            operating_hours=_operating_hours_from_context(
                place.operating_schedule,
                visit_at,
            ),
            raw_source=source,
        )
        for place in places_value.data
    )


def _environment_type(category: str) -> str:
    normalized = category.strip().lower()
    if normalized in _INDOOR_CATEGORIES:
        return "indoor"
    if normalized in _OUTDOOR_CATEGORIES:
        return "outdoor"
    return "unknown"


def _operating_hours_from_context(
    schedule: dict[str, Any] | None,
    visit_at: datetime,
) -> OperatingHours | None:
    """직렬화된 운영 규칙에서 방문 시각에 적용되는 당일 구간을 선택한다."""

    if not schedule or schedule.get("availability") == "unknown":
        return None
    if _is_regular_closure(schedule, visit_at):
        return OperatingHours(open_time=time.min, close_time=time.min)
    if schedule.get("availability") == "all_day":
        return OperatingHours(open_time=time.min, close_time=time.max)

    raw_rules = schedule.get("rules")
    rules = (
        raw_rules
        if isinstance(raw_rules, list) and raw_rules
        else [{"months": None, "weekdays": None, "time_ranges": schedule.get("time_ranges")}]
    )
    found_supported_range = False
    for rule in rules:
        if not isinstance(rule, dict) or not _rule_applies(rule, visit_at):
            continue
        ranges = _context_time_ranges(rule.get("time_ranges"))
        if not ranges:
            continue
        found_supported_range = True
        current_time = visit_at.time()
        active = next(
            (
                (open_time, close_time)
                for open_time, close_time in ranges
                if open_time <= current_time < close_time
            ),
            None,
        )
        if active is not None:
            return OperatingHours(open_time=active[0], close_time=active[1])
    if found_supported_range:
        return OperatingHours(open_time=time.min, close_time=time.min)
    return None


def _is_regular_closure(schedule: dict[str, Any], visit_at: datetime) -> bool:
    weekday = _WEEKDAY_NAMES[visit_at.weekday()]
    closure_rules = schedule.get("closure_rules")
    if not isinstance(closure_rules, list):
        return False
    return any(
        isinstance(rule, dict)
        and isinstance(rule.get("weekdays"), list)
        and weekday in rule["weekdays"]
        for rule in closure_rules
    )


def _rule_applies(rule: dict[str, Any], visit_at: datetime) -> bool:
    months = rule.get("months")
    if isinstance(months, list) and visit_at.month not in months:
        return False
    weekdays = rule.get("weekdays")
    return not (isinstance(weekdays, list) and _WEEKDAY_NAMES[visit_at.weekday()] not in weekdays)


def _context_time_ranges(value: object) -> tuple[tuple[time, time], ...]:
    if not isinstance(value, list):
        return ()
    result: list[tuple[time, time]] = []
    for item in value:
        if not isinstance(item, dict) or item.get("crosses_midnight") is True:
            continue
        try:
            open_time = time.fromisoformat(str(item["open_time"]))
            close_time = time.fromisoformat(str(item["close_time"]))
        except (KeyError, TypeError, ValueError):
            continue
        if open_time <= close_time:
            result.append((open_time, close_time))
    return tuple(result)


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
