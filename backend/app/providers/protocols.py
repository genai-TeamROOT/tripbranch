"""TripBranch provider 계층의 최소 인터페이스 정의.

역할: 해석 provider와 추천 provider가 구현해야 할 메서드 계약을 표현한다.
입력: 사용자 자연어 입력 또는 이미 노출된 place_id 목록.
출력: 해석 조건 모델 또는 추천 응답 모델.
호출 시점: 실제 provider 주입 구조를 만들 때 타입 계약으로 사용된다.
TODO: provider가 늘어나면 오류 타입, 비동기 계약, 메타데이터 계약을 분리한다.
"""

from __future__ import annotations

from typing import Protocol

from app.domain.models import (
    ConcentrationResult,
    GeocodeResult,
    HolidayResult,
    PlaceCategoryFilter,
    PlaceDetails,
    WeatherCondition,
)
from app.schemas import InterpretedConditions, PlaceCandidate, RecommendationResponse


class InterpretProvider(Protocol):
    def interpret(self, user_input: str) -> InterpretedConditions:
        """Return structured trip conditions from free-form input."""
        ...


class RecommendationProvider(Protocol):
    def recommendations(self, shown_place_ids: list[str]) -> RecommendationResponse:
        """Return place recommendations, excluding already shown IDs."""
        ...

class GeocodingProvider(Protocol):
    async def geocode(self, location_query: str) -> GeocodeResult:
        """장소 이름이나 주소를 정규화된 좌표 결과로 변환한다."""
        ...


class WeatherProvider(Protocol):
    async def get_current_condition(
        self, latitude: float, longitude: float
    ) -> WeatherCondition:
        """좌표의 현재 날씨를 공통 상태로 반환한다."""
        ...


class PlaceSearchProvider(Protocol):
    async def search_places(
        self,
        latitude: float,
        longitude: float,
        preferred_categories: list[str],
        search_radius_km: float,
        category_filter: PlaceCategoryFilter | None = None,
        limit: int = 20,
    ) -> list[PlaceCandidate]:
        """주어진 좌표/조건으로 장소 후보 목록을 조회해 공통 모델로 반환한다."""
        ...


class PlaceDetailsProvider(Protocol):
    async def get_details(self, content_id: str, content_type_id: str) -> PlaceDetails:
        """장소 ID와 유형 ID로 정규화된 상세정보를 반환한다."""
        ...


class PlaceProvider(PlaceSearchProvider, PlaceDetailsProvider, Protocol):
    async def search_by_keyword(
        self,
        keyword: str,
        region_code: str | None = None,
        district_code: str | None = None,
        limit: int = 20,
    ) -> list[PlaceCandidate]:
        """장소명·키워드로 후보와 TourAPI content ID를 조회한다."""
        ...

    async def find_details_by_name(
        self,
        name: str,
        region_code: str | None = None,
        district_code: str | None = None,
    ) -> PlaceDetails:
        """장소명으로 정확히 일치하는 후보를 찾아 상세정보까지 반환한다."""
        ...


class ConcentrationProvider(Protocol):
    async def get_forecast(
        self,
        area_code: str,
        district_code: str,
        place_name: str | None = None,
    ) -> ConcentrationResult:
        """지역과 선택적인 관광지명에 대한 향후 집중률을 반환한다."""
        ...


class HolidayProvider(Protocol):
    async def get_holidays(
        self, year: int, month: int | None = None
    ) -> HolidayResult:
        """공휴일 목록을 반환한다."""
        ...
