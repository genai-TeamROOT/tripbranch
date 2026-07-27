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
from app.schemas import InterpretedConditions, RecommendationResponse
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
