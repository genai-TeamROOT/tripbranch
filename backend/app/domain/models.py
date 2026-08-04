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
from datetime import datetime, time
from enum import StrEnum

from app.domain.operating_hours import OperatingSchedule


class WeatherCondition(StrEnum):
    GOOD = "good"
    NEUTRAL = "neutral"
    BAD = "bad"


@dataclass(frozen=True)
class WeatherForecastSlot:
    forecast_for: datetime
    condition: WeatherCondition
    sky_code: str | None
    precipitation_type: str | None


@dataclass(frozen=True)
class WeatherForecastResult:
    latitude: float
    longitude: float
    grid_x: int
    grid_y: int
    slots: tuple[WeatherForecastSlot, ...]
    provider: str


@dataclass(frozen=True)
class OperatingHours:
    """하루 운영시간 구간 (개장~마감).

    v1은 `open_time <= close_time`인 당일 운영만 다룬다. 자정을 넘기는
    운영시간(예: 22:00~02:00)은 범위 밖이며 `TBD`다.
    """

    open_time: time
    close_time: time


@dataclass(frozen=True)
class GeocodeResult:
    query: str
    resolved_name: str
    latitude: float
    longitude: float
    candidate_count: int = 1
    administrative_district: str | None = None


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
class LocalSearchPlace:
    """Naver Local Search가 반환한 장소·업체 후보 한 건."""

    name: str
    address: str | None
    road_address: str | None
    category: str | None
    latitude: float | None
    longitude: float | None




@dataclass(frozen=True)
class TourPlaceRecord:
    """TourAPI 지역 기반 목록의 장소 한 건."""

    content_id: str
    content_type_id: str
    title: str
    address: str | None
    latitude: float | None
    longitude: float | None
    area_code: str
    district_code: str
    lcls_systm1: str | None
    lcls_systm2: str | None
    lcls_systm3: str | None
    source_modified_at: datetime | None


@dataclass(frozen=True)
class TourPlacePage:
    """TourAPI 지역 기반 목록의 페이지 메타데이터와 장소 목록."""

    page_no: int
    num_of_rows: int
    total_count: int
    places: tuple[TourPlaceRecord, ...]


@dataclass(frozen=True)
class PlaceOperatingDetails:
    """TourAPI 소개 상세 응답에서 가져온 운영시간·휴무일 원문."""

    content_id: str
    content_type_id: str
    operating_hours_raw: str | None
    rest_date_raw: str | None


@dataclass(frozen=True)
class StoredPlaceLocation:
    """저장된 TourAPI 장소의 검색 중심점 해석용 최소 정보."""

    content_id: str
    title: str
    address: str | None
    latitude: float
    longitude: float
    # 집중률 응답에서 장소를 골라낼 때 대조할 정식 명칭.
    concentration_name: str | None = None
    # tAtsNm에 넣을 검색어. 비어 있으면 concentration_name을 그대로 쓴다.
    concentration_search_key: str | None = None


@dataclass(frozen=True)
class StoredPlaceDetail:
    """요청 시 저장소에서 읽어오는 장소 상세·운영정보 한 건.

    운영시간은 정규화 결과가 아니라 TourAPI 원문(``*_raw``)을 그대로 담는다 —
    소비 시점에 normalize_operating_schedule()로 다시 정규화하므로 TourAPI를
    직접 호출하는 경로와 동일한 결과가 보장된다.
    """

    content_id: str
    content_type_id: str
    title: str | None
    address: str | None
    operating_hours_raw: str | None
    rest_date_raw: str | None
    detail_fetch_status: str
    detail_fetched_at: datetime | None
    source_modified_at: datetime | None


@dataclass(frozen=True)
class StoredPlaceState:
    """상세 재조회와 활성화 여부 판단에 필요한 기존 장소 상태."""

    content_id: str
    source_modified_at: datetime | None
    detail_fetched_at: datetime | None
    detail_fetch_status: str
    operating_parser_version: str
    operating_hours_raw: str | None
    rest_date_raw: str | None
    is_active: bool
    inactive_reason: str | None


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
    (운영 상태, 실내외 구분, 거리)를 더해 Scoring이 필요로 하는 형태로 만든
    것이다. C-01 Tool 계약이 확정되기 전에는 이 모델에 맞춘 응답 샘플/Stub
    데이터로 Scoring을 개발하고, Tool 완성 후에는 Tool 출력 → 이 모델로의
    변환만 새로 작성하면 된다.

    `category`는 표시용 메타데이터로만 보존한다 (Scoring v1은 카테고리를
    가중치 계산에 사용하지 않고, place_type/place_tag 1차 하드 필터가 이미
    처리했다고 전제한다). `operating_hours`가 `None`이면 운영시간 자체를
    확인하지 못한 상태(미검증)이고, 폐점 여부는 Scoring이 `now`와
    `operating_hours`를 비교해 최종 하드 필터로 직접 판정한다.
    """

    place_id: str
    name: str
    category: str
    environment_type: str  # "indoor" | "outdoor" | "unknown"
    distance_km: float
    operating_hours: OperatingHours | None
    raw_source: str = "unknown"
