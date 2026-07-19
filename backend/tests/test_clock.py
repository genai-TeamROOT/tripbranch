# core/clock.py 단위 테스트: SystemClock/FixedClock이 계약대로 동작하는지 확인.

from __future__ import annotations

from datetime import datetime, timedelta

from app.core.clock import FixedClock, SystemClock


def test_fixed_clock_always_returns_the_same_instant() -> None:
    fixed = datetime(2026, 7, 15, 14, 0, 0)
    clock = FixedClock(fixed)

    assert clock.now() == fixed
    assert clock.now() == fixed  # calling twice must not drift


def test_system_clock_returns_a_recent_real_time() -> None:
    before = datetime.now()
    clock = SystemClock()
    reported = clock.now()
    after = datetime.now()

    assert before - timedelta(seconds=1) <= reported <= after + timedelta(seconds=1)
