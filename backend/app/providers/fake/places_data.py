# FakePlaceProvider가 제공하는 10개의 고정 장소 데이터.
# 요구사항에 명시된 모든 케이스(실내/야외/혼합/환경미확인, 운영중/종료/30분내마감/시간미확인,
# 서로 다른 카테고리·거리)를 의도적으로 하나씩 포함시켜뒀다. 사용법: 테스트 시나리오가
# 더 필요하면 여기 Place를 추가하되, 어떤 케이스를 커버하는지 주석으로 남길 것.

"""Static fake place dataset.

Deliberately kept separate from FakePlaceProvider (places.py) so the data
and the "search" behavior can be edited independently. All places are
positioned a short, varied distance from Gyeongbokgung Palace (경복궁) so
they show up for the fake geocoding results.

Operating hours use the *same* open/close time every day of the week, so
tests can pick any `now` datetime and get deterministic results without
worrying about which weekday it falls on -- except `museum_2`, which is
closed every day (already-closed case), and `cafe_2`/`temple_1`, which have
no schedule at all (unknown case).
"""

from __future__ import annotations

from app.domain.models import (
    DaySchedule,
    DayStatus,
    EnvironmentType,
    OperatingHours,
    Place,
    Weekday,
)

ALL_WEEKDAYS = list(Weekday)


def _daily(open_time: str, close_time: str) -> OperatingHours:
    return OperatingHours(
        schedule={
            day: DaySchedule(status=DayStatus.OPEN, open_time=open_time, close_time=close_time)
            for day in ALL_WEEKDAYS
        }
    )


def _closed_all_week() -> OperatingHours:
    return OperatingHours(
        schedule={day: DaySchedule(status=DayStatus.CLOSED) for day in ALL_WEEKDAYS}
    )


def _unknown_all_week() -> OperatingHours:
    return OperatingHours(schedule={})


FAKE_PLACES: list[Place] = [
    Place(
        id="museum_1",
        name="경복궁 역사 박물관",
        category="museum",
        latitude=37.5810,
        longitude=126.9770,
        opening_hours=_daily("09:00", "21:00"),
        environment_type=EnvironmentType.INDOOR,
    ),
    Place(
        id="cafe_1",
        name="북촌 골목 카페",
        category="cafe",
        latitude=37.5825,
        longitude=126.9790,
        opening_hours=_daily("09:00", "18:00"),
        environment_type=EnvironmentType.INDOOR,
    ),
    Place(
        id="park_1",
        name="사직 공원",
        category="park",
        latitude=37.5850,
        longitude=126.9800,
        opening_hours=_daily("06:00", "20:30"),
        environment_type=EnvironmentType.OUTDOOR,
    ),
    Place(
        id="gallery_1",
        name="서촌 아트 갤러리",
        category="gallery",
        latitude=37.5870,
        longitude=126.9750,
        opening_hours=_daily("09:00", "19:00"),
        environment_type=EnvironmentType.MIXED,
    ),
    Place(
        id="cafe_2",
        name="이름 없는 로스터리",
        category="cafe",
        latitude=37.5800,
        longitude=126.9740,
        opening_hours=_unknown_all_week(),
        environment_type=EnvironmentType.UNKNOWN,
    ),
    Place(
        id="restaurant_1",
        name="경복궁 아침 식당",
        category="restaurant",
        latitude=37.5795,
        longitude=126.9760,
        opening_hours=_daily("06:00", "09:00"),
        environment_type=EnvironmentType.INDOOR,
    ),
    Place(
        id="museum_2",
        name="휴관 중인 전시관",
        category="museum",
        latitude=37.5950,
        longitude=126.9900,
        opening_hours=_closed_all_week(),
        environment_type=EnvironmentType.INDOOR,
    ),
    Place(
        id="market_1",
        name="통인 시장",
        category="market",
        latitude=37.5880,
        longitude=126.9820,
        opening_hours=_daily("09:00", "18:30"),
        environment_type=EnvironmentType.OUTDOOR,
    ),
    Place(
        id="temple_1",
        name="이름 미상 사찰",
        category="temple",
        latitude=37.5760,
        longitude=126.9700,
        opening_hours=_unknown_all_week(),
        environment_type=EnvironmentType.UNKNOWN,
    ),
    Place(
        id="bookstore_1",
        name="광화문 대형 서점",
        category="bookstore",
        latitude=37.6000,
        longitude=126.9950,
        opening_hours=_daily("10:00", "23:00"),
        environment_type=EnvironmentType.INDOOR,
    ),
]
