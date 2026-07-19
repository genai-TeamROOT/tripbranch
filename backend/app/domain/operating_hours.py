# 요일별 운영시간(OperatingHours)을 보고 "지금 열려있는지"와 "몇 분 후 닫는지"를 계산.
# 모든 함수가 시스템 시계 대신 now: datetime을 인자로 받는다 - 순수 함수로 유지해
# 테스트에서 임의의 시각을 주입할 수 있게 하기 위함(실제 datetime.now()는 호출부인
# api/routes/recommendations.py에서만 만든다).
# TODO: 자정을 넘겨서 운영하는 장소(예: 00:00~02:00)는 현재 모델로 표현이 애매함 - 필요해지면
# DaySchedule에 "익일까지 운영" 플래그를 추가하는 방향을 고려할 것.

"""Operating-hours status and remaining-time calculations.

All functions take an explicit `now: datetime` argument (instead of reading
the system clock internally) so that recommendation logic stays pure and
deterministic/testable.
"""

from __future__ import annotations

from datetime import datetime, time

from app.domain.models import DayStatus, OperatingHours, Weekday


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(hour=int(hour), minute=int(minute))


def current_day_status(operating_hours: OperatingHours, now: datetime) -> DayStatus:
    """Determine open/closed/unknown status for `now`'s weekday.

    Note: this only checks the weekday-level status. A place whose day
    schedule is OPEN but whose current clock time falls outside
    [open_time, close_time) is treated as CLOSED for `now`.
    """
    weekday = Weekday.from_python_weekday(now.weekday())
    day_schedule = operating_hours.for_day(weekday)

    if day_schedule.status != DayStatus.OPEN:
        return day_schedule.status

    open_time = _parse_hhmm(day_schedule.open_time)
    close_time = _parse_hhmm(day_schedule.close_time)
    current_time = now.time()

    if open_time <= current_time < close_time:
        return DayStatus.OPEN
    return DayStatus.CLOSED


def remaining_open_minutes(operating_hours: OperatingHours, now: datetime) -> int | None:
    """Minutes left until closing, or None if not currently open or unknown."""
    weekday = Weekday.from_python_weekday(now.weekday())
    day_schedule = operating_hours.for_day(weekday)

    if day_schedule.status != DayStatus.OPEN:
        return None

    if current_day_status(operating_hours, now) != DayStatus.OPEN:
        return None

    close_time = _parse_hhmm(day_schedule.close_time)
    close_minutes = close_time.hour * 60 + close_time.minute
    now_minutes = now.hour * 60 + now.minute

    return max(close_minutes - now_minutes, 0)
