"""TripBranch provider 계층의 최소 인터페이스 정의.

역할: 해석 provider와 추천 provider가 구현해야 할 메서드 계약을 표현한다.
입력: 사용자 자연어 입력 또는 이미 노출된 place_id 목록.
출력: 해석 조건 모델 또는 추천 응답 모델.
호출 시점: 실제 provider 주입 구조를 만들 때 타입 계약으로 사용된다.
TODO: provider가 늘어나면 오류 타입, 비동기 계약, 메타데이터 계약을 분리한다.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from app.domain.models import (
    ConcentrationResult,
    GeocodeResult,
    HolidayResult,
    LocalSearchPlace,
    PlaceCategoryFilter,
    PlaceDetails,
    PlaceOperatingDetails,
    TourPlacePage,
    WeatherForecastResult,
)
from app.place_search_policy import DEFAULT_PLACE_PROVIDER_RESULT_LIMIT
from app.providers.contracts import ProviderResult
from app.schemas import (
    GeneralTopic,
    IntentClassificationResult,
    InterpretedConditions,
    LLMOutput,
    PlaceCandidate,
    RecommendationResponse,
    UserConditions,
)


class InterpretProvider(Protocol):
    def interpret(self, user_input: str) -> InterpretedConditions:
        """Return structured trip conditions from free-form input."""
        ...


class LLMProvider(Protocol):
    async def classify_intent(
        self,
        user_input: str,
        *,
        has_previous_recommendation: bool,
        shown_place_count: int,
    ) -> ProviderResult[IntentClassificationResult]:
        """사용자 발화의 Intent를 1단계로 판정한다."""
        ...

    async def extract_recommend_conditions(
        self, user_input: str
    ) -> ProviderResult[LLMOutput]:
        """RECOMMEND 발화에서 UserConditions를 추출한다."""
        ...

    async def extract_modify_conditions(
        self, user_input: str, current_conditions: UserConditions
    ) -> ProviderResult[LLMOutput]:
        """MODIFY 발화에서 modify_type과 condition_changes를 추출한다."""
        ...

    async def extract_info_query(
        self,
        user_input: str,
        *,
        has_previous_recommendation: bool,
        reference_date: date,
    ) -> ProviderResult[LLMOutput]:
        """INFO 발화에서 장소/질문 정보를 추출한다.

        reference_date: "오늘"/"내일"/"이번 주말" 등 concentration 질의의
        visit_time을 실제 날짜로 환산하는 기준일(KST). concentration-conditions.md §3.2.
        """
        ...

    async def extract_compare_request(
        self, user_input: str, *, shown_place_count: int
    ) -> ProviderResult[LLMOutput]:
        """COMPARE 발화에서 비교 대상과 기준을 추출한다."""
        ...

    async def extract_general_request(
        self, user_input: str
    ) -> ProviderResult[LLMOutput]:
        """GENERAL 발화의 주제를 분류한다."""
        ...

    async def generate_general_answer(
        self, topic: GeneralTopic, original_question: str
    ) -> ProviderResult[str]:
        """GENERAL 발화에 실제로 답할 배경지식 문장을 생성한다.

        다른 메서드와 달리 구조화 조건 추출이 아니라 자유 텍스트 답변이다 —
        docs/design/agent-response-generation.md §3/§6의 유일한 LLM 신규 호출 지점.
        """
        ...


class RecommendationProvider(Protocol):
    def recommendations(self, shown_place_ids: list[str]) -> RecommendationResponse:
        """Return place recommendations, excluding already shown IDs."""
        ...

class GeocodingProvider(Protocol):
    async def geocode(
        self, location_query: str, *, use_alias: bool = True
    ) -> ProviderResult[GeocodeResult]:
        """장소 이름이나 주소를 정규화된 좌표 결과로 변환한다."""
        ...


class LocalSearchProvider(Protocol):
    async def search_places_by_name(
        self, query: str, *, display: int = 5
    ) -> ProviderResult[tuple[LocalSearchPlace, ...]]:
        """상호명·시설명으로 Naver 지역 검색 후보를 반환한다."""
        ...

class WeatherProvider(Protocol):
    async def get_forecast_slots(
        self, latitude: float, longitude: float
    ) -> ProviderResult[WeatherForecastResult]:
        """좌표의 시각별 초단기예보 목록을 반환한다."""
        ...


class PlaceSearchProvider(Protocol):
    async def search_places(
        self,
        latitude: float,
        longitude: float,
        preferred_categories: list[str],
        search_radius_km: float,
        region_code: str | None = None,
        district_code: str | None = None,
        category_filter: PlaceCategoryFilter | None = None,
        limit: int = DEFAULT_PLACE_PROVIDER_RESULT_LIMIT,
    ) -> ProviderResult[list[PlaceCandidate]]:
        """주어진 좌표/조건으로 장소 후보 목록을 조회해 공통 모델로 반환한다."""
        ...


class PlaceDetailsProvider(Protocol):
    async def get_details(
        self, content_id: str, content_type_id: str
    ) -> ProviderResult[PlaceDetails]:
        """장소 ID와 유형 ID로 정규화된 상세정보를 반환한다."""
        ...


@runtime_checkable
class BatchPlaceDetailsProvider(Protocol):
    """여러 장소의 상세정보를 한 번의 조회로 반환할 수 있는 provider.

    미리 구축된 저장소를 읽는 provider만 구현한다. content_id별로 개별 호출이
    필요한 외부 API provider는 기존 PlaceDetailsProvider만 만족하면 되고,
    Tool이 런타임에 이 계약 지원 여부를 보고 조회 방식을 고른다.
    """

    async def get_details_batch(
        self,
        content_ids: list[str],
    ) -> ProviderResult[dict[str, PlaceDetails]]:
        """content_id 목록에 대한 상세정보를 content_id 기준 dict로 반환한다.

        조회되지 않은 content_id는 결과에서 빠진다(호출자가 누락으로 처리한다).
        """
        ...


class PlaceProvider(PlaceSearchProvider, PlaceDetailsProvider, Protocol):
    async def search_by_keyword(
        self,
        keyword: str,
        region_code: str | None = None,
        district_code: str | None = None,
        limit: int = DEFAULT_PLACE_PROVIDER_RESULT_LIMIT,
    ) -> ProviderResult[list[PlaceCandidate]]:
        """장소명·키워드로 후보와 TourAPI content ID를 조회한다."""
        ...

    async def find_details_by_name(
        self,
        name: str,
        region_code: str | None = None,
        district_code: str | None = None,
    ) -> ProviderResult[PlaceDetails]:
        """장소명으로 정확히 일치하는 후보를 찾아 상세정보까지 반환한다."""
        ...


class TourAreaPlaceProvider(Protocol):
    async def list_places_by_area(
        self,
        area_code: str,
        district_code: str,
        page_no: int,
        num_of_rows: int = 100,
    ) -> TourPlacePage:
        """행정구역에 속한 TourAPI 장소 목록 한 페이지를 반환한다."""
        ...

    async def get_operating_details(
        self,
        content_id: str,
        content_type_id: str,
    ) -> PlaceOperatingDetails:
        """소개 상세 조회만 사용해 운영시간과 휴무일 원문을 반환한다."""
        ...


class ConcentrationProvider(Protocol):
    async def get_forecast(
        self,
        area_code: str,
        district_code: str,
        place_name: str | None = None,
    ) -> ProviderResult[ConcentrationResult]:
        """지역과 선택적인 관광지명에 대한 향후 집중률을 반환한다."""
        ...


class HolidayProvider(Protocol):
    async def get_holidays(
        self, year: int, month: int | None = None
    ) -> ProviderResult[HolidayResult]:
        """공휴일 목록을 반환한다."""
        ...
