"""C Context Service와 내부 Tool·Provider 의존성을 조립한다."""

from __future__ import annotations

import httpx

from app.agent_context.enrichment_service import CandidateEnrichmentService
from app.agent_context.service import ContextService, ContextTools
from app.config import settings
from app.providers.factory import (
    get_concentration_provider,
    get_geocoding_provider,
    get_holiday_provider,
    get_place_details_provider,
    get_place_location_repository,
    get_place_search_provider,
    get_weather_provider,
)
from app.tools.concentration import GetConcentrationTool
from app.tools.holiday import GetHolidaysTool
from app.tools.nearby_place_details import NearbyPlaceDetailsTool
from app.tools.resolve_location import ResolveLocationTool
from app.tools.weather_forecast import GetWeatherForecastTool


def get_context_provider(client: httpx.AsyncClient) -> ContextService:
    """설정된 Fake/Real Provider로 A–C ContextProvider를 생성한다."""

    return ContextService(
        ContextTools(
            location=ResolveLocationTool(
                get_geocoding_provider(client),
                place_repository=get_place_location_repository(client),
            ),
            places=NearbyPlaceDetailsTool(
                search_provider=get_place_search_provider(client),
                details_provider=get_place_details_provider(client),
            ),
            weather=GetWeatherForecastTool(get_weather_provider(client)),
            holidays=GetHolidaysTool(get_holiday_provider(client)),
            concentration=GetConcentrationTool(get_concentration_provider(client)),
        ),
        candidate_limit=settings.recommendation_candidate_limit,
    )


def get_candidate_enrichment_service(
    client: httpx.AsyncClient,
) -> CandidateEnrichmentService:
    """설정된 Concentration Provider를 공통 Tool로 감싼 후보 보강 서비스를 생성한다."""

    return CandidateEnrichmentService(
        GetConcentrationTool(get_concentration_provider(client)),
        candidate_limit=settings.recommendation_result_limit,
    )


__all__ = ["get_candidate_enrichment_service", "get_context_provider"]
