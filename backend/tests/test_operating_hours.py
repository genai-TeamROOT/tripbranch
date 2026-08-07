from datetime import time

from app.domain.operating_hours import (
    OperatingAvailability,
    OperatingParseStatus,
    clean_operating_text,
    normalize_operating_schedule,
)


def test_clean_operating_text_preserves_html_line_breaks_and_entities() -> None:
    value = "<strong>운영시간</strong><br>09:00~18:00&nbsp;&amp; 입장 가능"

    assert clean_operating_text(value) == "운영시간\n09:00~18:00 & 입장 가능"


def test_normalizes_seasonal_hours_last_admission_and_weekly_closure() -> None:
    schedule = normalize_operating_schedule(
        content_type_id="12",
        operating_hours=(
            "[1월~2월] 09:00~17:00 (입장마감 16:00)<br>"
            "[3월~5월] 09:00~18:00 (입장마감 17:00)"
        ),
        rest_date="매주 화요일<br>공휴일과 겹치면 다음 비공휴일 휴무",
    )

    assert schedule.availability is OperatingAvailability.SCHEDULED
    assert schedule.parse_status is OperatingParseStatus.PARTIAL
    assert schedule.rules[0].months == frozenset({1, 2})
    assert schedule.rules[0].time_ranges[0].start == time(9)
    assert schedule.rules[0].time_ranges[0].end == time(17)
    assert schedule.rules[0].last_admission == time(16)
    assert schedule.closure_rules[0].weekdays == frozenset({1})
    assert schedule.warnings


def test_course_without_hours_is_assumed_all_day() -> None:
    schedule = normalize_operating_schedule(
        content_type_id="25",
        operating_hours=None,
        rest_date=None,
    )

    assert schedule.availability is OperatingAvailability.ALL_DAY
    assert schedule.parse_status is OperatingParseStatus.ASSUMED
    assert schedule.assumption_reason == "course_without_operating_hours"


def test_missing_hours_for_non_course_remains_unknown() -> None:
    schedule = normalize_operating_schedule(
        content_type_id="12",
        operating_hours=None,
        rest_date=None,
    )

    assert schedule.availability is OperatingAvailability.UNKNOWN
    assert schedule.parse_status is OperatingParseStatus.UNKNOWN
    assert schedule.assumption_reason is None


def test_parses_multiple_and_cross_midnight_ranges() -> None:
    schedule = normalize_operating_schedule(
        content_type_id="39",
        operating_hours="11:00~15:00, 17:00~익일 02:00",
        rest_date="연중무휴",
    )

    assert len(schedule.rules[0].time_ranges) == 2
    assert schedule.rules[0].time_ranges[1].crosses_midnight is True


def test_24_00_is_end_of_day_not_a_midnight_crossing() -> None:
    """24:00은 당일 종료이므로 자정 통과로 표시하지 않는다.

    time(0)으로 두면 end <= start가 되어 자정 통과로 오분류되고, 당일 구간만
    소비하는 candidate_mapper에서 구간이 통째로 버려진다.
    """
    schedule = normalize_operating_schedule(
        content_type_id="39",
        operating_hours="09:00~24:00",
        rest_date=None,
    )

    assert schedule.rules[0].time_ranges[0].end == time.max
    assert schedule.rules[0].time_ranges[0].crosses_midnight is False


def test_always_open_text_is_all_day() -> None:
    schedule = normalize_operating_schedule(
        content_type_id="12",
        operating_hours="상시 개방※ 우천 시, 안전상의 이유로 출입통제될 수 있음",
        rest_date=None,
    )

    assert schedule.availability is OperatingAvailability.ALL_DAY
    assert schedule.parse_status is OperatingParseStatus.PARSED
    assert schedule.rules == ()


def test_always_open_does_not_override_parsed_time_ranges() -> None:
    """부속 시설 시간이 함께 적힌 원문을 통째로 24시간으로 넓히지 않는다."""
    schedule = normalize_operating_schedule(
        content_type_id="12",
        operating_hours="상시 개방 ※ 낙산 전시관 09:00~17:00",
        rest_date=None,
    )

    assert schedule.availability is OperatingAvailability.SCHEDULED
    assert schedule.rules[0].time_ranges[0].end == time(17, 0)


def test_unrecognized_hours_are_partial_and_raw_value_is_preserved() -> None:
    schedule = normalize_operating_schedule(
        content_type_id="12",
        operating_hours="일몰 시간에 따라 변동",
        rest_date=None,
    )

    assert schedule.raw_operating_hours == "일몰 시간에 따라 변동"
    assert schedule.parse_status is OperatingParseStatus.PARTIAL
    assert schedule.availability is OperatingAvailability.UNKNOWN
    assert schedule.warnings
