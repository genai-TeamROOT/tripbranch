"""Weather/Geocoding provider가 공유하는 내부 도메인 모델.

역할: 외부 API(Naver Geocoding, KMA 단기예보) 응답을 라우터/서비스가 직접 다루지
않도록, provider 구현체가 반드시 이 타입으로 변환해서 반환하게 한다.
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
