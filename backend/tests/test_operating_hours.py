# domain/operating_hours.py 테스트: open/closed/unknown 판정과 남은 운영시간 계산을
# 고정된 datetime(월요일 17:45)을 기준으로 검증. 실제 시계에 의존하지 않아 결과가 결정적이다.

from __future__ import annotations

from datetime import datetime

from app.domain.models import DaySchedule, DayStatus, OperatingHours, Weekday
from app.domain.operating_hours import current_day_status, remaining_open_minutes

MONDAY_1745 = datetime(2024, 1, 15, 17, 45)  # 2024-01-15 is a Monday


def _open_every_day(open_time: str, close_time: str) -> OperatingHours:
    return OperatingHours(
        schedule={
            day: DaySchedule(status=DayStatus.OPEN, open_time=open_time, close_time=close_time)
            for day in Weekday
        }
    )


def test_currently_open_status() -> None:
    hours = _open_every_day("09:00", "21:00")

    assert current_day_status(hours, MONDAY_1745) == DayStatus.OPEN


def test_already_closed_status_when_past_close_time() -> None:
    hours = _open_every_day("06:00", "09:00")

    assert current_day_status(hours, MONDAY_1745) == DayStatus.CLOSED


def test_unknown_status_when_no_schedule() -> None:
    hours = OperatingHours(schedule={})

    assert current_day_status(hours, MONDAY_1745) == DayStatus.UNKNOWN


def test_explicit_closed_status() -> None:
    hours = OperatingHours(schedule={day: DaySchedule(status=DayStatus.CLOSED) for day in Weekday})

    assert current_day_status(hours, MONDAY_1745) == DayStatus.CLOSED


def test_remaining_open_minutes_when_open() -> None:
    hours = _open_every_day("09:00", "19:00")

    assert remaining_open_minutes(hours, MONDAY_1745) == 75


def test_remaining_open_minutes_is_none_when_closed() -> None:
    hours = _open_every_day("06:00", "09:00")

    assert remaining_open_minutes(hours, MONDAY_1745) is None


def test_remaining_open_minutes_is_none_when_unknown() -> None:
    hours = OperatingHours(schedule={})

    assert remaining_open_minutes(hours, MONDAY_1745) is None
