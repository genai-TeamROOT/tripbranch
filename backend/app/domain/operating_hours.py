"""장소 운영시간 원문을 보존하면서 안전하게 정규화한다."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time
from enum import StrEnum
from html.parser import HTMLParser

_COURSE_CONTENT_TYPE_ID = "25"
OPERATING_PARSER_VERSION = "operating-hours-1.1.0"
_WEEKDAY_INDEX = {
    "월": 0,
    "화": 1,
    "수": 2,
    "목": 3,
    "금": 4,
    "토": 5,
    "일": 6,
}
_TIME_RANGE_PATTERN = re.compile(
    r"(?P<start_hour>\d{1,2})\s*:\s*(?P<start_minute>\d{2})"
    r"\s*(?:~|∼|～|–|—|-)\s*"
    r"(?P<next_day>(?:익일|다음\s*날)\s*)?"
    r"(?P<end_hour>\d{1,2})\s*:\s*(?P<end_minute>\d{2})"
)
_LAST_ADMISSION_PATTERN = re.compile(
    r"(?:입장\s*마감|매표\s*마감|마지막\s*입장)\s*"
    r"(?P<hour>\d{1,2})\s*:\s*(?P<minute>\d{2})"
)
_MONTH_RANGE_PATTERN = re.compile(
    r"(?P<start>\d{1,2})\s*월\s*(?:~|∼|～|–|—|-)\s*"
    r"(?P<end>\d{1,2})\s*월"
)
_WEEKLY_CLOSURE_PATTERN = re.compile(
    r"매주\s*(?P<weekdays>(?:[월화수목금토일](?:요일)?(?:\s*[,·/및과와]\s*)?)+)"
)
# TourAPI 관광지·자연 원문에서 "24시간"만큼 흔한 상시 개방 표기. D-024와 같은 이유로
# 시간 구간을 못 읽었다는 이유만으로 후보를 운영 미확인으로 떨어뜨리지 않는다.
_ALWAYS_OPEN_PATTERN = re.compile(r"상시\s*(?:개방|운영|이용|출입)?")


class OperatingParseStatus(StrEnum):
    PARSED = "parsed"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    ASSUMED = "assumed"


class OperatingAvailability(StrEnum):
    SCHEDULED = "scheduled"
    ALL_DAY = "all_day"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TimeRange:
    start: time
    end: time
    crosses_midnight: bool


@dataclass(frozen=True)
class OperatingRule:
    months: frozenset[int] | None
    weekdays: frozenset[int] | None
    time_ranges: tuple[TimeRange, ...]
    last_admission: time | None
    source_text: str


@dataclass(frozen=True)
class ClosureRule:
    weekdays: frozenset[int]
    source_text: str


@dataclass(frozen=True)
class OperatingSchedule:
    raw_operating_hours: str | None
    raw_rest_date: str | None
    cleaned_operating_hours: str | None
    cleaned_rest_date: str | None
    availability: OperatingAvailability
    rules: tuple[OperatingRule, ...]
    closure_rules: tuple[ClosureRule, ...]
    parse_status: OperatingParseStatus
    assumption_reason: str | None
    warnings: tuple[str, ...]


class _TextExtractor(HTMLParser):
    _BREAK_TAGS = {"br", "div", "p", "li", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.lower() in self._BREAK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._BREAK_TAGS - {"br"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def clean_operating_text(value: str | None) -> str | None:
    """HTML 줄바꿈·entity·태그와 불필요한 공백을 정리한다."""
    if value is None or not value.strip():
        return None
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    lines = [
        re.sub(r"[^\S\n]+", " ", line).strip()
        for line in "".join(parser.parts).splitlines()
    ]
    cleaned = "\n".join(line for line in lines if line)
    return cleaned or None


def normalize_operating_schedule(
    *,
    content_type_id: str,
    operating_hours: str | None,
    rest_date: str | None,
) -> OperatingSchedule:
    """TourAPI 운영시간·휴무 원문을 해석 가능한 범위에서 정규화한다."""
    cleaned_hours = clean_operating_text(operating_hours)
    cleaned_rest = clean_operating_text(rest_date)

    if content_type_id == _COURSE_CONTENT_TYPE_ID and cleaned_hours is None:
        return OperatingSchedule(
            raw_operating_hours=operating_hours,
            raw_rest_date=rest_date,
            cleaned_operating_hours=None,
            cleaned_rest_date=cleaned_rest,
            availability=OperatingAvailability.ALL_DAY,
            rules=(),
            closure_rules=_parse_closures(cleaned_rest),
            parse_status=OperatingParseStatus.ASSUMED,
            assumption_reason="course_without_operating_hours",
            warnings=("여행코스의 운영시간 누락을 24시간 이용 가능으로 가정했습니다.",),
        )

    closure_rules = _parse_closures(cleaned_rest)
    if cleaned_hours and "24시간" in cleaned_hours:
        return OperatingSchedule(
            raw_operating_hours=operating_hours,
            raw_rest_date=rest_date,
            cleaned_operating_hours=cleaned_hours,
            cleaned_rest_date=cleaned_rest,
            availability=OperatingAvailability.ALL_DAY,
            rules=(),
            closure_rules=closure_rules,
            parse_status=OperatingParseStatus.PARSED,
            assumption_reason=None,
            warnings=(),
        )

    rules = _parse_operating_rules(cleaned_hours)
    if rules:
        warnings = ()
        status = OperatingParseStatus.PARSED
        if cleaned_rest and (
            (not closure_rules and "연중무휴" not in cleaned_rest)
            or _has_complex_closure_exception(cleaned_rest)
        ):
            status = OperatingParseStatus.PARTIAL
            warnings = ("휴무 문구의 일부 예외를 구조화하지 못했습니다.",)
        return OperatingSchedule(
            raw_operating_hours=operating_hours,
            raw_rest_date=rest_date,
            cleaned_operating_hours=cleaned_hours,
            cleaned_rest_date=cleaned_rest,
            availability=OperatingAvailability.SCHEDULED,
            rules=rules,
            closure_rules=closure_rules,
            parse_status=status,
            assumption_reason=None,
            warnings=warnings,
        )

    # 구간을 하나라도 읽었으면 그 구간을 신뢰한다. "상시 개방 ※ 낙산 전시관
    # 09:00~17:00"처럼 부속 시설 시간이 함께 적힌 원문을 통째로 24시간으로
    # 넓히지 않기 위해, 상시 개방 판정은 구간을 못 읽은 경우로 한정한다.
    if cleaned_hours and _ALWAYS_OPEN_PATTERN.search(cleaned_hours):
        return OperatingSchedule(
            raw_operating_hours=operating_hours,
            raw_rest_date=rest_date,
            cleaned_operating_hours=cleaned_hours,
            cleaned_rest_date=cleaned_rest,
            availability=OperatingAvailability.ALL_DAY,
            rules=(),
            closure_rules=closure_rules,
            parse_status=OperatingParseStatus.PARSED,
            # 원문에 시각이 없어 마감을 자정으로 잡은 근거를 남긴다. Provider 명시값이라
            # parse_status는 PARSED지만, "24시간"처럼 시각이 적힌 표기와는 구분해야
            # 소비 측이 잔여시간 만점의 출처를 설명할 수 있다.
            assumption_reason="always_open_text",
            warnings=(),
        )

    warnings = ()
    status = OperatingParseStatus.UNKNOWN
    if cleaned_hours or closure_rules:
        status = OperatingParseStatus.PARTIAL
        warnings = ("운영시간을 구조화하지 못했습니다.",)
    return OperatingSchedule(
        raw_operating_hours=operating_hours,
        raw_rest_date=rest_date,
        cleaned_operating_hours=cleaned_hours,
        cleaned_rest_date=cleaned_rest,
        availability=OperatingAvailability.UNKNOWN,
        rules=(),
        closure_rules=closure_rules,
        parse_status=status,
        assumption_reason=None,
        warnings=warnings,
    )


def _parse_operating_rules(value: str | None) -> tuple[OperatingRule, ...]:
    if value is None:
        return ()
    rules: list[OperatingRule] = []
    for line in value.splitlines():
        time_ranges = tuple(
            parsed
            for match in _TIME_RANGE_PATTERN.finditer(line)
            if (parsed := _try_time_range(match)) is not None
        )
        if not time_ranges:
            continue
        admission_match = _LAST_ADMISSION_PATTERN.search(line)
        rules.append(
            OperatingRule(
                months=_parse_months(line),
                weekdays=None,
                time_ranges=time_ranges,
                last_admission=(
                    _try_time(
                        admission_match.group("hour"),
                        admission_match.group("minute"),
                    )
                    if admission_match
                    else None
                ),
                source_text=line,
            )
        )
    return tuple(rules)


def _parse_months(value: str) -> frozenset[int] | None:
    match = _MONTH_RANGE_PATTERN.search(value)
    if match is None:
        return None
    start = int(match.group("start"))
    end = int(match.group("end"))
    if not 1 <= start <= 12 or not 1 <= end <= 12:
        return None
    if start <= end:
        return frozenset(range(start, end + 1))
    return frozenset((*range(start, 13), *range(1, end + 1)))


def _parse_closures(value: str | None) -> tuple[ClosureRule, ...]:
    if value is None or "연중무휴" in value:
        return ()
    rules: list[ClosureRule] = []
    for line in value.splitlines():
        match = _WEEKLY_CLOSURE_PATTERN.search(line)
        if match is None:
            continue
        weekday_text = match.group("weekdays").replace("요일", "")
        weekdays = frozenset(
            _WEEKDAY_INDEX[token]
            for token in re.findall(r"[월화수목금토일]", weekday_text)
        )
        if weekdays:
            rules.append(ClosureRule(weekdays=weekdays, source_text=line))
    return tuple(rules)


def _has_complex_closure_exception(value: str) -> bool:
    return any(
        token in value
        for token in ("공휴일", "대체공휴일", "비공휴일", "다음 날", "변동", "문의")
    )


def _try_time_range(match: re.Match[str]) -> TimeRange | None:
    start = _try_time(match.group("start_hour"), match.group("start_minute"))
    end_hour = match.group("end_hour")
    end_minute = match.group("end_minute")
    # "09:00~24:00"의 24:00은 자정 통과가 아니라 당일 종료다. time(0)으로 두면
    # end <= start가 되어 자정 통과로 오분류되고, 당일 구간만 다루는 소비 측
    # (`candidate_mapper`)에서 통째로 버려져 운영 미확인이 된다.
    end = (
        time.max
        if end_hour == "24" and end_minute == "00"
        else _try_time(end_hour, end_minute)
    )
    if start is None or end is None:
        return None
    return TimeRange(
        start=start,
        end=end,
        crosses_midnight=bool(match.group("next_day")) or end <= start,
    )


def _try_time(hour: str, minute: str) -> time | None:
    parsed_hour = int(hour)
    parsed_minute = int(minute)
    if not 0 <= parsed_hour <= 23 or not 0 <= parsed_minute <= 59:
        return None
    return time(parsed_hour, parsed_minute)
