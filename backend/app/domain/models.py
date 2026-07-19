# 추천 로직 전체가 의존하는 내부 도메인 모델(Place, OperatingHours, EnvironmentType 등).
# 외부 API(지오코딩/장소/날씨/LLM) 응답을 다른 코드가 직접 쓰지 않도록, provider 구현체가
# 반드시 이 모델로 변환해서 반환해야 한다. 사용법: 새 provider를 real/*.py에 구현할 때
# 이 파일의 타입만 보고 만들면 되고, 외부 API의 원본 응답 shape은 여기 노출되면 안 된다.

"""Internal domain models.

These types are the only representation of "place" and "recommendation"
data that domain/service code is allowed to depend on. External API
responses (from providers) must be converted into these models before
they reach recommendation logic. This module must not import FastAPI,
Pydantic, or any HTTP/provider library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class EnvironmentType(StrEnum):
    INDOOR = "indoor"
    OUTDOOR = "outdoor"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class WeatherCondition(StrEnum):
    GOOD = "good"
    NEUTRAL = "neutral"
    BAD = "bad"


class Weekday(StrEnum):
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"

    @classmethod
    def from_python_weekday(cls, python_weekday: int) -> Weekday:
        """python_weekday: 0=Monday .. 6=Sunday (datetime.weekday())."""
        return list(cls)[python_weekday]


class DayStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DaySchedule:
    """Operating status for a single weekday.

    open_time / close_time are only meaningful when status == OPEN, and are
    expressed as "HH:MM" 24h local time strings to keep the domain layer
    free of timezone-handling libraries.
    """

    status: DayStatus
    open_time: str | None = None
    close_time: str | None = None

    def __post_init__(self) -> None:
        if self.status == DayStatus.OPEN and (self.open_time is None or self.close_time is None):
            raise ValueError("open_time and close_time are required when status is OPEN")


@dataclass(frozen=True)
class OperatingHours:
    """Weekly operating schedule, keyed by weekday."""

    schedule: dict[Weekday, DaySchedule] = field(default_factory=dict)

    def for_day(self, weekday: Weekday) -> DaySchedule:
        return self.schedule.get(weekday, DaySchedule(status=DayStatus.UNKNOWN))


@dataclass(frozen=True)
class Place:
    """Canonical internal representation of a place candidate."""

    id: str
    name: str
    category: str
    latitude: float
    longitude: float
    opening_hours: OperatingHours
    environment_type: EnvironmentType


@dataclass(frozen=True)
class GeocodeResult:
    query: str
    resolved_name: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class InterpretedInput:
    """Structured result of turning free-text user input into search
    conditions, produced by an LlmProvider."""

    location_query: str
    preferred_categories: list[str]
    weather_condition: WeatherCondition | None
    search_radius_km: float
