"""TripBranch fake provider 구현체 모음.

역할: 외부 API 호출 없이 고정/임시 데이터로 각 provider 계약을 만족시킨다.
입력: 각 provider protocol이 요구하는 파라미터.
출력: 각 provider protocol이 요구하는 응답 모델.
호출 시점: PLACE_PROVIDER=fake 등 설정이 fake일 때 provider 팩토리가 주입한다.
TODO: 실제 provider(RealPlaceProvider 등)가 준비되면 팩토리에서 설정값으로 분기한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain.models import (
    PlaceCategoryFilter,
    PlaceDetails,
    WeatherCondition,
    WeatherForecastResult,
    WeatherForecastSlot,
)
from app.domain.operating_hours import normalize_operating_schedule
from app.errors import AppError
from app.schemas import (
    InterpretedConditions,
    PlaceCandidate,
    RecommendationResponse,
)
from app.services.interpret import interpret_user_input
from app.services.recommendations import get_stub_recommendations


class FakeInterpretProvider:
    """자연어 입력 해석을 고정 조건으로 대체하는 fake provider."""

    def interpret(self, user_input: str) -> InterpretedConditions:
        return interpret_user_input(user_input)


class FakeRecommendationProvider:
    """추천 결과를 고정 목록으로 대체하는 fake provider."""

    def recommendations(self, shown_place_ids: list[str]) -> RecommendationResponse:
        return get_stub_recommendations(shown_place_ids)


class FakeWeatherProvider:
    """설정한 공통 날씨 상태를 반환하는 가짜 구현."""

    def __init__(self, condition: WeatherCondition = WeatherCondition.NEUTRAL) -> None:
        self._condition = condition

    async def get_current_condition(
        self, latitude: float, longitude: float
    ) -> WeatherCondition:
        return self._condition

    async def get_forecast_slots(
        self, latitude: float, longitude: float
    ) -> WeatherForecastResult:
        now = datetime.now(ZoneInfo("Asia/Seoul")).replace(
            minute=0,
            second=0,
            microsecond=0,
        )
        return WeatherForecastResult(
            latitude=latitude,
            longitude=longitude,
            grid_x=60,
            grid_y=127,
            slots=tuple(
                WeatherForecastSlot(
                    forecast_for=now + timedelta(hours=offset),
                    condition=self._condition,
                    sky_code=None,
                    precipitation_type=None,
                )
                for offset in range(6)
            ),
            provider="fake_weather",
        )


class FakePlaceProvider:
    """장소 검색 결과를 고정 후보 목록으로 대체하는 fake provider."""

    async def search_places(
        self,
        latitude: float,
        longitude: float,
        preferred_categories: list[str],
        search_radius_km: float,
        category_filter: PlaceCategoryFilter | None = None,
        limit: int = 20,
    ) -> list[PlaceCandidate]:
        candidates = [
            PlaceCandidate(
                place_id="fake-museum-1",
                content_type_id="14",
                lcls_systm1="VE",
                lcls_systm2="VE07",
                lcls_systm3="VE070100",
                name="테스트 박물관",
                category="museum",
                latitude=latitude,
                longitude=longitude,
                address="서울 종로구 어딘가",
                operating_hours="09:00-18:00",
                raw_source="fake_place",
            ),
            PlaceCandidate(
                place_id="fake-cafe-1",
                content_type_id="39",
                lcls_systm1="FD",
                lcls_systm2="FD05",
                lcls_systm3="FD050100",
                name="테스트 카페",
                category="cafe",
                latitude=latitude + 0.001,
                longitude=longitude + 0.001,
                address="서울 종로구 어딘가",
                operating_hours="08:00-22:00",
                raw_source="fake_place",
            ),
        ]
        if category_filter and category_filter.content_type_id:
            candidates = [
                candidate
                for candidate in candidates
                if candidate.content_type_id == category_filter.content_type_id
            ]
        return candidates[: max(1, min(limit, 100))]

    async def search_by_keyword(
        self,
        keyword: str,
        region_code: str | None = None,
        district_code: str | None = None,
        limit: int = 20,
    ) -> list[PlaceCandidate]:
        candidates = await self.search_places(37.5796, 126.9770, [], 1.0)
        normalized = keyword.strip().lower()
        return [candidate for candidate in candidates if normalized in candidate.name.lower()][
            :limit
        ]

    async def get_details(self, content_id: str, content_type_id: str) -> PlaceDetails:
        candidates = await self.search_places(37.5796, 126.9770, [], 1.0)
        candidate = next((item for item in candidates if item.place_id == content_id), None)
        operating_hours = candidate.operating_hours if candidate else None
        rest_date = "매주 월요일" if candidate else None
        return PlaceDetails(
            content_id=content_id,
            content_type_id=content_type_id,
            title=candidate.name if candidate else None,
            address=candidate.address if candidate else None,
            overview="Fake Provider의 장소 상세정보입니다.",
            homepage=None,
            telephone=None,
            operating_hours=operating_hours,
            rest_date=rest_date,
            raw_common={},
            raw_intro={},
            provider="fake_place",
            operating_schedule=normalize_operating_schedule(
                content_type_id=content_type_id,
                operating_hours=operating_hours,
                rest_date=rest_date,
            ),
        )

    async def find_details_by_name(
        self,
        name: str,
        region_code: str | None = None,
        district_code: str | None = None,
    ) -> PlaceDetails:
        normalized_name = name.strip()
        candidates = await self.search_by_keyword(
            normalized_name, region_code, district_code, limit=100
        )
        exact = next(
            (
                candidate
                for candidate in candidates
                if candidate.name.strip().casefold() == normalized_name.casefold()
            ),
            None,
        )
        if exact is None or not exact.content_type_id:
            raise AppError(
                code="place_not_found",
                message=f"'{normalized_name}' 장소를 정확히 찾을 수 없어요.",
                status_code=404,
            )
        return await self.get_details(exact.place_id, exact.content_type_id)
