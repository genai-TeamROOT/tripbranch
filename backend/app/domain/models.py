"""Weather/Geocoding provider가 공유하는 내부 도메인 모델.

역할: 외부 API(Naver Geocoding, KMA 단기예보) 응답을 라우터/서비스가 직접 다루지
않도록, provider 구현체가 반드시 이 타입으로 변환해서 반환하게 한다.
이 모듈은 FastAPI/Pydantic/HTTP 라이브러리를 import하지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from app.domain.operating_hours import OperatingSchedule


class WeatherCondition(StrEnum):
    GOOD = "good"
    NEUTRAL = "neutral"
    BAD = "bad"


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
class PlaceCategoryFilter:
    """TourAPI 장소 목록 조회에 사용할 선택적 분류 코드 묶음."""

    content_type_id: str | None = None
    lcls_systm1: str | None = None
    lcls_systm2: str | None = None
    lcls_systm3: str | None = None

    def __post_init__(self) -> None:
        values = (
            self.content_type_id,
            self.lcls_systm1,
            self.lcls_systm2,
            self.lcls_systm3,
        )
        if any(value is not None and not value.strip() for value in values):
            raise ValueError("분류 코드는 비어 있는 문자열일 수 없습니다.")
        if self.lcls_systm2 and not self.lcls_systm1:
            raise ValueError("lcls_systm2 사용 시 lcls_systm1이 필요합니다.")
        if self.lcls_systm3 and not (self.lcls_systm1 and self.lcls_systm2):
            raise ValueError(
                "lcls_systm3 사용 시 lcls_systm1과 lcls_systm2가 필요합니다."
            )


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
    rest_date: str | None
    raw_common: Mapping[str, object]
    raw_intro: Mapping[str, object]
    provider: str
    operating_schedule: OperatingSchedule | None = None


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
