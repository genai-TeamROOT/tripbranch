"""Provider/Tool이 공유하는 내부 도메인 모델.

역할: 외부 API(Naver Geocoding, KMA 단기예보, TourAPI 등) 응답을 라우터/서비스가
직접 다루지 않도록, provider 구현체가 반드시 이 타입으로 변환해서 반환하게 한다.
`ScoringCandidate`처럼 특정 provider 출력이 아니라 여러 Tool 결과가 조합되어
채워지는 Scoring 입력 모델도 이 모듈에 둔다.
이 모듈은 FastAPI/Pydantic/HTTP 라이브러리를 import하지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class WeatherCondition(StrEnum):
    GOOD = "good"
    NEUTRAL = "neutral"
    BAD = "bad"


class PlaceStatus(StrEnum):
    """Scoring 단계에서 사용하는 장소 운영 상태.

    OPEN/CLOSED는 운영시간 데이터로 확인된 상태이고, UNKNOWN은 운영시간
    데이터 자체를 확인하지 못한 상태다. 폐점(CLOSED)과 미확인(UNKNOWN)은
    서로 다른 상태이므로 하드필터 적용 여부가 다르다.
    """

    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class GeocodeResult:
    query: str
    resolved_name: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class ConcentrationForecast:
    """관광지의 날짜별 상대 집중률 예측 한 건."""

    place_name: str
    forecast_date: str | None
    concentration_rate: float | None
    raw_data: Mapping[str, object]


@dataclass(frozen=True)
class ConcentrationResult:
    """지역·관광지 조건으로 조회한 집중률 예측 결과."""

    area_code: str
    district_code: str
    requested_place_name: str | None
    forecasts: tuple[ConcentrationForecast, ...]
    provider: str


@dataclass(frozen=True)
class PlaceDetails:
    """TourAPI의 공통·소개 상세 응답을 정규화한 장소 상세정보."""

    content_id: str
    content_type_id: str
    title: str | None
    address: str | None
    overview: str | None
    homepage: str | None
    telephone: str | None
    operating_hours: str | None
    raw_common: Mapping[str, object]
    raw_intro: Mapping[str, object]
    provider: str


@dataclass(frozen=True)
class HolidayEntry:
    """한국천문연구원 공휴일 API 응답 한 건."""

    date: str
    name: str
    kind: str | None
    sequence: int | None
    is_holiday: bool
    raw_data: Mapping[str, object]


@dataclass(frozen=True)
class HolidayResult:
    """연·월 조건으로 조회한 공휴일 결과."""

    year: int
    month: int | None
    entries: tuple[HolidayEntry, ...]
    provider: str

    @property
    def holidays(self) -> tuple[HolidayEntry, ...]:
        """응답 중 isHoliday=Y인 항목만 반환한다."""
        return tuple(entry for entry in self.entries if entry.is_holiday)


@dataclass(frozen=True)
class ScoringCandidate:
    """Scoring v1의 입력 후보 공통 모델 (Candidate Model v1).

    역할: 특정 Provider나 Tool 출력 형태에 종속되지 않는 정규화된 후보 표현.
    `PlaceCandidate`(Provider 산출물)에 Tool Context가 채워 넣은 판단 근거
    (운영 상태, 남은 영업시간, 실내외 구분, 거리)를 더해 Scoring이 필요로
    하는 형태로 만든 것이다. C-01 Tool 계약이 확정되기 전에는 이 모델에
    맞춘 응답 샘플/Stub 데이터로 Scoring을 개발하고, Tool 완성 후에는
    Tool 출력 → 이 모델로의 변환만 새로 작성하면 된다.
    """

    place_id: str
    name: str
    category: str
    environment_type: str  # "indoor" | "outdoor" | "unknown"
    distance_km: float
    place_status: PlaceStatus
    remaining_open_minutes: int | None
    raw_source: str = "unknown"
