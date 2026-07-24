"""추천 결과를 조립하는 도메인 서비스.

역할: Provider Factory로 Tool을 조립하고 공통 추천 파이프라인을 실행한다.
입력: 해석된 조건(InterpretedConditions), 이미 노출된 place_id 목록.
출력: RecommendationResponse 모델.
호출 시점: /api/recommendations 라우터가 get_recommendations()를 호출한다.
"""

from __future__ import annotations

import httpx

from app.config import settings
from app.providers.protocols import (
    ConcentrationProvider,
    GeocodingProvider,
    HolidayProvider,
    PlaceProvider,
    WeatherProvider,
)
from app.schemas import (
    InterpretedConditions,
    RecommendationItem,
    RecommendationResponse,
)
from app.services.recommendation_pipeline import (
    RecommendationTools,
    build_pipeline_request,
    run_recommendation_pipeline,
)
from app.tools.concentration import GetConcentrationTool
from app.tools.holiday import GetHolidaysTool
from app.tools.nearby_place_details import NearbyPlaceDetailsTool
from app.tools.resolve_location import ResolveLocationTool
from app.tools.weather_forecast import GetWeatherForecastTool


async def build_recommendations(
    conditions: InterpretedConditions,
    shown_place_ids: list[str],
    geocoding_provider: GeocodingProvider,
    place_provider: PlaceProvider,
    weather_provider: WeatherProvider,
    concentration_provider: ConcentrationProvider,
    holiday_provider: HolidayProvider,
) -> RecommendationResponse:
    """Fake/Real과 무관하게 동일한 Tool·Candidate·Scoring 흐름을 실행한다."""
    result = await run_recommendation_pipeline(
        build_pipeline_request(
            conditions,
            shown_place_ids,
            recommendation_limit=settings.recommendation_result_limit,
            candidate_limit=settings.recommendation_candidate_limit,
        ),
        RecommendationTools(
            location=ResolveLocationTool(geocoding_provider),
            weather=GetWeatherForecastTool(weather_provider),
            places=NearbyPlaceDetailsTool(place_provider, place_provider),
            concentration=GetConcentrationTool(concentration_provider),
            holidays=GetHolidaysTool(holiday_provider),
        ),
    )
    return result.response


def get_stub_recommendations(shown_place_ids: list[str]) -> RecommendationResponse:
    """레거시 고정 stub 응답. 기존 회귀 테스트가 이 결과를 검증한다."""
    stub_items = [
        RecommendationItem(
            place_id="stub-museum-1",
            name="테스트 박물관",
            category="museum",
            distance_km=0.4,
            remaining_minutes=150,
            environment_type="indoor",
            recommendation_reason="비 오는 날 방문하기 좋은 실내 장소예요.",
            warnings=[],
        ),
        RecommendationItem(
            place_id="stub-cafe-1",
            name="테스트 카페",
            category="cafe",
            distance_km=0.7,
            remaining_minutes=80,
            environment_type="indoor",
            recommendation_reason="현재 위치에서 가까운 장소예요.",
            warnings=[],
        ),
        RecommendationItem(
            place_id="stub-park-1",
            name="테스트 공원",
            category="park",
            distance_km=0.9,
            remaining_minutes=200,
            environment_type="outdoor",
            recommendation_reason="가까운 야외 장소예요.",
            warnings=["현재 날씨를 확인해주세요."],
        ),
    ]
    stub_unverified = [
        RecommendationItem(
            place_id="stub-gallery-1",
            name="운영시간 미확인 갤러리",
            category="gallery",
            distance_km=0.8,
            remaining_minutes=None,
            environment_type="indoor",
            recommendation_reason="선호한 문화 장소와 비슷한 장소예요.",
            warnings=["방문 전에 운영 여부를 확인해주세요."],
        )
    ]

    shown = set(shown_place_ids)
    return RecommendationResponse(
        recommendations=[i for i in stub_items if i.place_id not in shown],
        unverified_recommendations=[i for i in stub_unverified if i.place_id not in shown],
        elapsed_ms=0,
    )


async def get_recommendations(
    conditions: InterpretedConditions, shown_place_ids: list[str]
) -> RecommendationResponse:
    """라우터가 호출하는 Fake/Real 공통 추천 파이프라인 진입점."""
    from app.providers.factory import (
        get_concentration_provider,
        get_geocoding_provider,
        get_holiday_provider,
        get_place_provider,
        get_weather_provider,
    )

    async with httpx.AsyncClient() as client:
        return await build_recommendations(
            conditions,
            shown_place_ids,
            geocoding_provider=get_geocoding_provider(client),
            place_provider=get_place_provider(client),
            weather_provider=get_weather_provider(client),
            concentration_provider=get_concentration_provider(client),
            holiday_provider=get_holiday_provider(client),
        )
