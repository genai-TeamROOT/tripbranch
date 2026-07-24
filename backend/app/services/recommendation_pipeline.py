"""Tool Context를 조립하고 Candidate Scoring을 실행하는 추천 파이프라인."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import TypeAlias
from zoneinfo import ZoneInfo

from app.domain.agent_context import AgentToolContext, context_value
from app.domain.candidate_mapper import map_places_to_scoring_candidates
from app.domain.evidence import build_evidence
from app.domain.models import ScoringCandidate
from app.domain.scoring import RankedCandidate, ScoringResult, score_candidates
from app.errors import AppError
from app.schemas import (
    InterpretedConditions,
    RecommendationItem,
    RecommendationResponse,
)
from app.tools.concentration import (
    ConcentrationQuery,
    ConcentrationToolResult,
    GetConcentrationTool,
)
from app.tools.contracts import ToolError, ToolStatus
from app.tools.holiday import GetHolidaysTool, HolidayQuery
from app.tools.nearby_place_details import (
    EnrichedPlace,
    NearbyPlaceDetailsQuery,
    NearbyPlaceDetailsTool,
)
from app.tools.resolve_location import (
    ResolveLocationQuery,
    ResolveLocationTool,
)
from app.tools.weather_forecast import (
    GetWeatherForecastTool,
    WeatherForecastQuery,
)

_KST = ZoneInfo("Asia/Seoul")
DEFAULT_RECOMMENDATION_LIMIT = 5
DEFAULT_CANDIDATE_LIMIT = 10
_JONGNO_AREA_CODE = "11"
_JONGNO_DISTRICT_CODE = "11110"


@dataclass(frozen=True)
class RecommendationPipelineRequest:
    location_query: str
    preferred_categories: tuple[str, ...]
    search_radius_km: float
    visit_at: datetime
    shown_place_ids: frozenset[str] = frozenset()
    rejected_place_ids: frozenset[str] = frozenset()
    recommendation_limit: int = DEFAULT_RECOMMENDATION_LIMIT
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT

    def __post_init__(self) -> None:
        if not self.location_query.strip():
            raise ValueError("location_query는 비어 있을 수 없습니다.")
        if not 1 <= self.recommendation_limit <= 20:
            raise ValueError("recommendation_limit은 1 이상 20 이하여야 합니다.")
        if not self.recommendation_limit <= self.candidate_limit <= 20:
            raise ValueError(
                "candidate_limit은 recommendation_limit 이상 20 이하여야 합니다."
            )


@dataclass(frozen=True)
class RecommendationTools:
    location: ResolveLocationTool
    weather: GetWeatherForecastTool
    places: NearbyPlaceDetailsTool
    concentration: GetConcentrationTool
    holidays: GetHolidaysTool


@dataclass(frozen=True)
class CandidateConcentration:
    place_id: str
    place_name: str
    result: ConcentrationToolResult


@dataclass(frozen=True)
class RecommendationPipelineResult:
    response: RecommendationResponse
    context: AgentToolContext
    scoring: ScoringResult
    concentrations: tuple[CandidateConcentration, ...]


Clock = Callable[[], datetime]
Timer: TypeAlias = Callable[[], float]


def build_pipeline_request(
    conditions: InterpretedConditions,
    shown_place_ids: list[str],
    *,
    clock: Clock | None = None,
    recommendation_limit: int = DEFAULT_RECOMMENDATION_LIMIT,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> RecommendationPipelineRequest:
    now = (clock or (lambda: datetime.now(_KST)))()
    if now.tzinfo is None:
        now = now.replace(tzinfo=_KST)
    else:
        now = now.astimezone(_KST)
    return RecommendationPipelineRequest(
        location_query=conditions.location_query,
        preferred_categories=tuple(conditions.preferred_categories),
        search_radius_km=conditions.search_radius_km,
        visit_at=now,
        shown_place_ids=frozenset(shown_place_ids),
        recommendation_limit=recommendation_limit,
        candidate_limit=candidate_limit,
    )


async def run_recommendation_pipeline(
    request: RecommendationPipelineRequest,
    tools: RecommendationTools,
    *,
    timer: Timer = perf_counter,
) -> RecommendationPipelineResult:
    started_at = timer()
    location_result = await tools.location.execute(
        ResolveLocationQuery(request.location_query)
    )
    if location_result.status is not ToolStatus.SUCCESS or location_result.location is None:
        raise _location_error(location_result.status, location_result.error)

    location = location_result.location
    weather_result, places_result, holiday_result = await asyncio.gather(
        tools.weather.execute(
            WeatherForecastQuery(
                location.latitude,
                location.longitude,
                visit_at=request.visit_at,
            )
        ),
        tools.places.execute(
            NearbyPlaceDetailsQuery(
                latitude=location.latitude,
                longitude=location.longitude,
                search_radius_km=request.search_radius_km,
                limit=request.candidate_limit,
                preferred_categories=request.preferred_categories,
                excluded_place_ids=(
                    request.shown_place_ids | request.rejected_place_ids
                ),
            )
        ),
        tools.holidays.execute(
            HolidayQuery(request.visit_at.year, request.visit_at.month)
        ),
    )

    if places_result.status is ToolStatus.UNAVAILABLE:
        error = places_result.error
        raise AppError(
            code=error.code if error else "unavailable",
            message=error.message if error else "주변 장소를 검색하지 못했습니다.",
            status_code=502,
            retryable=error.retryable if error else True,
        )

    candidates = map_places_to_scoring_candidates(
        places_result,
        origin_latitude=location.latitude,
        origin_longitude=location.longitude,
        visit_at=request.visit_at,
    )
    weather_condition = (
        weather_result.forecast.condition
        if weather_result.status is ToolStatus.SUCCESS
        and weather_result.forecast is not None
        else None
    )
    scoring = score_candidates(
        candidates,
        now=request.visit_at,
        weather_condition=weather_condition,
        max_distance_km=request.search_radius_km,
        shown_place_ids=request.shown_place_ids,
        rejected_place_ids=request.rejected_place_ids,
    )
    ranked = scoring.ranked[: request.recommendation_limit]
    concentrations = await _fetch_ranked_concentrations(ranked, tools.concentration)
    context = _build_context(
        location_result=location_result,
        weather_result=weather_result,
        places_result=places_result,
        holiday_result=holiday_result,
        concentrations=concentrations,
    )
    response = _build_response(
        ranked,
        candidates,
        places_result.places,
        request.visit_at,
    )
    response = response.model_copy(
        update={"elapsed_ms": round((timer() - started_at) * 1000, 2)}
    )
    return RecommendationPipelineResult(
        response=response,
        context=context,
        scoring=scoring,
        concentrations=concentrations,
    )


async def _fetch_ranked_concentrations(
    ranked: tuple[RankedCandidate, ...],
    tool: GetConcentrationTool,
) -> tuple[CandidateConcentration, ...]:
    results = await asyncio.gather(
        *(
            tool.execute(
                ConcentrationQuery(
                    _JONGNO_AREA_CODE,
                    _JONGNO_DISTRICT_CODE,
                    item.name,
                )
            )
            for item in ranked
        )
    )
    return tuple(
        CandidateConcentration(
            place_id=item.place_id,
            place_name=item.name,
            result=result,
        )
        for item, result in zip(ranked, results, strict=True)
    )


def _build_context(
    *,
    location_result,
    weather_result,
    places_result,
    holiday_result,
    concentrations: tuple[CandidateConcentration, ...],
) -> AgentToolContext:
    concentration_status, concentration_error, concentration_warnings = (
        _aggregate_concentration_status(concentrations)
    )
    concentration_metadata = tuple(
        metadata
        for item in concentrations
        for metadata in item.result.provider_metadata
    )
    return AgentToolContext(
        location=context_value(
            status=location_result.status,
            data=location_result.location,
            error=location_result.error,
            warnings=location_result.warnings,
            provider_metadata=location_result.provider_metadata,
        ),
        weather=context_value(
            status=weather_result.status,
            data=weather_result.forecast,
            error=weather_result.error,
            warnings=weather_result.warnings,
            provider_metadata=weather_result.provider_metadata,
        ),
        places=context_value(
            status=places_result.status,
            data=places_result.places,
            error=places_result.error,
            warnings=places_result.warnings,
            provider_metadata=places_result.provider_metadata,
        ),
        concentration=context_value(
            status=concentration_status,
            data=concentrations,
            error=concentration_error,
            warnings=concentration_warnings,
            provider_metadata=concentration_metadata,
        ),
        holidays=context_value(
            status=holiday_result.status,
            data=holiday_result.holidays,
            error=holiday_result.error,
            warnings=holiday_result.warnings,
            provider_metadata=holiday_result.provider_metadata,
        ),
    )


def _aggregate_concentration_status(
    concentrations: tuple[CandidateConcentration, ...],
) -> tuple[ToolStatus, ToolError | None, tuple[str, ...]]:
    if not concentrations:
        return ToolStatus.NO_DATA, None, ()
    statuses = tuple(item.result.status for item in concentrations)
    if all(status is ToolStatus.SUCCESS for status in statuses):
        return ToolStatus.SUCCESS, None, ()
    if any(status is ToolStatus.SUCCESS for status in statuses):
        return ToolStatus.PARTIAL, None, ("partial_data",)
    if all(status is ToolStatus.UNAVAILABLE for status in statuses):
        return ToolStatus.UNAVAILABLE, concentrations[0].result.error, ()
    if any(status is ToolStatus.UNAVAILABLE for status in statuses):
        return ToolStatus.PARTIAL, None, ("partial_data",)
    return ToolStatus.NO_DATA, None, ()


def _build_response(
    ranked: tuple[RankedCandidate, ...],
    candidates: tuple[ScoringCandidate, ...],
    places: tuple[EnrichedPlace, ...],
    visit_at: datetime,
) -> RecommendationResponse:
    candidate_by_id = {item.place_id: item for item in candidates}
    place_by_id = {item.candidate.place_id: item for item in places}
    verified: list[RecommendationItem] = []
    unverified: list[RecommendationItem] = []

    for ranked_item in ranked:
        candidate = candidate_by_id[ranked_item.place_id]
        place = place_by_id[ranked_item.place_id]
        evidence = build_evidence(ranked_item)
        item = RecommendationItem(
            place_id=candidate.place_id,
            name=candidate.name,
            category=candidate.category,
            distance_km=round(candidate.distance_km, 2),
            remaining_minutes=_remaining_minutes(candidate, visit_at),
            environment_type=candidate.environment_type,
            recommendation_reason=_recommendation_reason(ranked_item),
            warnings=list(ranked_item.warnings)
            + (
                ["장소 상세정보 일부를 확인하지 못했습니다."]
                if place.details is None
                and "방문 전에 운영 여부를 확인해주세요."
                not in ranked_item.warnings
                else []
            ),
            score=evidence.score,
            feature_scores={
                contribution.feature: contribution.score
                for contribution in evidence.contributions
            },
            weights_used={
                contribution.feature: contribution.weight
                for contribution in evidence.contributions
                if contribution.weight is not None
            },
        )
        (unverified if ranked_item.is_unverified else verified).append(item)

    return RecommendationResponse(
        recommendations=verified,
        unverified_recommendations=unverified,
        elapsed_ms=0,
    )


def _remaining_minutes(
    candidate: ScoringCandidate,
    visit_at: datetime,
) -> int | None:
    hours = candidate.operating_hours
    if hours is None or not (hours.open_time <= visit_at.time() < hours.close_time):
        return None
    close_at = datetime.combine(
        visit_at.date(),
        hours.close_time,
        tzinfo=visit_at.tzinfo,
    )
    return max(0, int((close_at - visit_at).total_seconds() // 60))


def _recommendation_reason(ranked: RankedCandidate) -> str:
    return (
        f"거리·날씨·운영시간 조건을 종합한 {ranked.rank}순위 추천이에요."
    )


def _location_error(status: ToolStatus, error: ToolError | None) -> AppError:
    return AppError(
        code=error.code if error else "unavailable",
        message=error.message if error else "위치 검색 서비스를 사용할 수 없습니다.",
        status_code={
            ToolStatus.NO_DATA: 404,
            ToolStatus.UNSUPPORTED: 422,
            ToolStatus.UNAVAILABLE: 502,
        }.get(status, 502),
        retryable=error.retryable if error else False,
        details=error.details if error else None,
    )
