"""Provider가 공유하는 정상 결과 메타데이터와 wrapper 계약."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Generic, TypeVar


class ProviderStatus(StrEnum):
    """외부 호출과 정규화가 완료된 Provider 정상 결과 상태."""

    SUCCESS = "success"
    NO_DATA = "no_data"
    PARTIAL = "partial"


class ProviderSource(StrEnum):
    """Provider 구현 클래스가 아닌 데이터 출처·기능 식별자."""

    NAVER_GEOCODING = "naver_geocoding"
    KMA_ULTRA_SHORT_FORECAST = "kma_ultra_short_forecast"
    TOUR_API_PLACE = "tour_api_place"
    TOUR_API_CONCENTRATION = "tour_api_concentration"
    KASI_HOLIDAY = "kasi_holiday"
    FAKE_GEOCODING = "fake_geocoding"
    FAKE_WEATHER = "fake_weather"
    FAKE_PLACE = "fake_place"
    FAKE_CONCENTRATION = "fake_concentration"
    FAKE_HOLIDAY = "fake_holiday"


@dataclass(frozen=True)
class ProviderMetadata:
    source: ProviderSource
    status: ProviderStatus
    retrieved_at: datetime

    def __post_init__(self) -> None:
        if self.retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at은 timezone-aware datetime이어야 합니다.")


T = TypeVar("T")


@dataclass(frozen=True)
class ProviderResult(Generic[T]):
    data: T
    metadata: ProviderMetadata


Clock = Callable[[], datetime]


def provider_result(
    data: T,
    *,
    source: ProviderSource,
    status: ProviderStatus = ProviderStatus.SUCCESS,
    clock: Clock | None = None,
) -> ProviderResult[T]:
    """UTC 조회 시각을 포함한 정상 Provider 결과를 생성한다."""

    retrieved_at = (clock or (lambda: datetime.now(UTC)))()
    if retrieved_at.tzinfo is None:
        raise ValueError("Provider clock은 timezone-aware datetime을 반환해야 합니다.")
    return ProviderResult(
        data=data,
        metadata=ProviderMetadata(
            source=source,
            status=status,
            retrieved_at=retrieved_at.astimezone(UTC),
        ),
    )
