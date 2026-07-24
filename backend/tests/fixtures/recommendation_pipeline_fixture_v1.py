"""추천 파이프라인 1차 E2E 검증용 재사용 가능 Fixture (D-03).

역할: `run_recommendation_pipeline()`을 날씨 유무 시나리오별로 반복 검증할 수
있도록 Fake Provider 조합과 이름 있는 케이스를 고정한다. Scoring 자체의
결측/제외 조합은 `scoring_fixture_v1.py`(D-02)가 이미 다루므로, 여기서는
파이프라인 조립(Tool Context → Candidate → Scoring → Response) 관점의
시나리오만 다룬다.
입력: 없음 (Fake Provider와 케이스 데이터만 제공).
출력: `RECOMMENDATION_PIPELINE_FIXTURE_V1` (이름 있는 케이스 목록).
호출 시점: `test_recommendation_pipeline_fixture.py`가 파라미터화해 사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain.models import (
    ConcentrationResult,
    PlaceDetails,
    WeatherCondition,
    WeatherForecastResult,
    WeatherForecastSlot,
)
from app.domain.operating_hours import normalize_operating_schedule
from app.errors import ProviderUnavailableError
from app.providers.contracts import (
    ProviderResult,
    ProviderSource,
    ProviderStatus,
    provider_result,
)
from app.providers.geocoding import FakeGeocodingProvider
from app.providers.holiday import FakeHolidayProvider
from app.providers.stub import FakeWeatherProvider
from app.schemas import PlaceCandidate
from app.services.recommendation_pipeline import RecommendationTools
from app.tools.concentration import GetConcentrationTool
from app.tools.holiday import GetHolidaysTool
from app.tools.nearby_place_details import NearbyPlaceDetailsTool
from app.tools.resolve_location import ResolveLocationTool
from app.tools.weather_forecast import GetWeatherForecastTool

KST = ZoneInfo("Asia/Seoul")
VISIT_AT = datetime(2026, 7, 24, 12, tzinfo=KST)


class ManyPlacesProvider:
    """운영시간 "09:00~18:00"으로 동일한 장소 7곳을 거리순으로 반환한다."""

    async def search_places(
        self,
        latitude: float,
        longitude: float,
        preferred_categories: list[str],
        search_radius_km: float,
        category_filter=None,
        limit: int = 20,
    ) -> ProviderResult[list[PlaceCandidate]]:
        candidates = [
            PlaceCandidate(
                place_id=f"place-{index}",
                content_type_id="14",
                name=f"장소 {index}",
                category="museum",
                latitude=latitude + index * 0.001,
                longitude=longitude,
                raw_source="test",
            )
            for index in range(7)
        ][:limit]
        return provider_result(candidates, source=ProviderSource.FAKE_PLACE)

    async def get_details(
        self,
        content_id: str,
        content_type_id: str,
    ) -> ProviderResult[PlaceDetails]:
        return provider_result(
            PlaceDetails(
                content_id=content_id,
                content_type_id=content_type_id,
                title=content_id,
                address=None,
                overview="상세정보",
                homepage=None,
                telephone=None,
                operating_hours="09:00~18:00",
                rest_date=None,
                raw_common={},
                raw_intro={},
                provider="fake_place",
                operating_schedule=normalize_operating_schedule(
                    content_type_id=content_type_id,
                    operating_hours="09:00~18:00",
                    rest_date=None,
                ),
            ),
            source=ProviderSource.FAKE_PLACE,
        )


class RecordingConcentrationProvider:
    """혼잡도 조회 대상 장소명을 기록만 하고 항상 NO_DATA를 반환한다."""

    def __init__(self) -> None:
        self.place_names: list[str] = []

    async def get_forecast(
        self,
        area_code: str,
        district_code: str,
        place_name: str | None = None,
    ) -> ProviderResult[ConcentrationResult]:
        self.place_names.append(place_name or "")
        return provider_result(
            ConcentrationResult(
                area_code=area_code,
                district_code=district_code,
                requested_place_name=place_name,
                forecasts=(),
                provider="fake_concentration",
            ),
            source=ProviderSource.FAKE_CONCENTRATION,
            status=ProviderStatus.NO_DATA,
        )


class SucceedingWeatherProvider:
    """VISIT_AT을 기준으로 예보 범위를 고정해 실제 시각과 무관하게 성공한다."""

    def __init__(self, condition: WeatherCondition) -> None:
        self._condition = condition

    async def get_current_condition(self, latitude: float, longitude: float):
        return provider_result(self._condition, source=ProviderSource.FAKE_WEATHER)

    async def get_forecast_slots(
        self,
        latitude: float,
        longitude: float,
    ) -> ProviderResult[WeatherForecastResult]:
        return provider_result(
            WeatherForecastResult(
                latitude=latitude,
                longitude=longitude,
                grid_x=60,
                grid_y=127,
                slots=tuple(
                    WeatherForecastSlot(
                        forecast_for=VISIT_AT + timedelta(hours=offset),
                        condition=self._condition,
                        sky_code=None,
                        precipitation_type=None,
                    )
                    for offset in range(-3, 4)
                ),
                provider="fake_weather",
            ),
            source=ProviderSource.FAKE_WEATHER,
        )


class UnavailableWeatherProvider:
    """날씨 Provider 호출이 항상 실패하는 상황을 재현한다."""

    async def get_current_condition(self, latitude: float, longitude: float):
        raise ProviderUnavailableError("weather")

    async def get_forecast_slots(
        self,
        latitude: float,
        longitude: float,
    ) -> ProviderResult[WeatherForecastResult]:
        raise ProviderUnavailableError("weather")


def build_tools(
    places: ManyPlacesProvider,
    concentration: RecordingConcentrationProvider,
    *,
    weather_provider=None,
) -> RecommendationTools:
    return RecommendationTools(
        location=ResolveLocationTool(FakeGeocodingProvider()),
        weather=GetWeatherForecastTool(
            weather_provider or FakeWeatherProvider(WeatherCondition.NEUTRAL)
        ),
        places=NearbyPlaceDetailsTool(places, places),
        concentration=GetConcentrationTool(concentration),
        holidays=GetHolidaysTool(FakeHolidayProvider()),
    )


@dataclass(frozen=True)
class RecommendationPipelineFixtureCase:
    """파이프라인 1차 E2E 검증용 이름 있는 시나리오 1건."""

    name: str
    description: str
    weather_condition: WeatherCondition | None  # None이면 날씨 Provider 실패
    expect_weather_in_weights: bool


def weather_provider_for(case: RecommendationPipelineFixtureCase):
    if case.weather_condition is None:
        return UnavailableWeatherProvider()
    return SucceedingWeatherProvider(case.weather_condition)


RECOMMENDATION_PIPELINE_FIXTURE_V1: tuple[RecommendationPipelineFixtureCase, ...] = (
    RecommendationPipelineFixtureCase(
        name="weather_available_good",
        description="날씨 조회 성공(GOOD) - weights_used에 weather가 포함된다.",
        weather_condition=WeatherCondition.GOOD,
        expect_weather_in_weights=True,
    ),
    RecommendationPipelineFixtureCase(
        name="weather_available_bad",
        description="날씨 조회 성공(BAD) - weights_used에 weather가 포함된다.",
        weather_condition=WeatherCondition.BAD,
        expect_weather_in_weights=True,
    ),
    RecommendationPipelineFixtureCase(
        name="weather_unavailable",
        description=(
            "날씨 Provider 실패 - weather 가중치가 재분배되어 "
            "weights_used에서 제외된다."
        ),
        weather_condition=None,
        expect_weather_in_weights=False,
    ),
)
