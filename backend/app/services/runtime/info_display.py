"""INFO 원본 데이터를 사용자 화면용으로 최소 정리한다.

C는 TourAPI에서 얻은 원문을 계약 데이터로 보존하고, A는 답변과 카드에 필요한
표시 규칙만 적용한다. 이 모듈은 원문 데이터의 성공/실패 판정에 관여하지 않는다.
"""

from __future__ import annotations

import re

_CAR_CAPACITY_PATTERN = re.compile(r"승용차\s*[^/,\)\]]+")


def format_parking_for_display(value: str | None) -> str | None:
    """주차 원문에서 일반 사용자가 우선 보는 승용차 정보만 표시한다.

    예: ``가능 (승용차 240대 / 버스 50대)`` → ``가능 (승용차 240대)``.
    승용차 수용 대수가 없는 값은 정보 손실을 막기 위해 원문 그대로 둔다.
    """

    if value is None:
        return None

    car_match = _CAR_CAPACITY_PATTERN.search(value)
    if car_match is None:
        return value

    status = value.split("(", maxsplit=1)[0].strip()
    if not status:
        return car_match.group(0).strip()
    return f"{status} ({car_match.group(0).strip()})"


__all__ = ["format_parking_for_display"]
