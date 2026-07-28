"""상위 추천 후보의 Concentration 정보를 후조회하는 C 서비스."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from app.agent_context.enrichment_schemas import (
    CandidateEnrichmentRequest,
    CandidateEnrichmentResponse,
    CandidateEnrichmentResult,
    CandidateEnrichmentTarget,
    ConcentrationForecastData,
    resolve_enrichment_status,
)
from app.agent_context.schemas import ContextError, ProviderMetadata
from app.domain.models import ConcentrationForecast, ConcentrationResult
from app.providers.contracts import ProviderMetadata as ProviderMetadataData
from app.recommendation_limits import (
    MAX_RECOMMENDATION_CANDIDATE_LIMIT,
    MIN_RECOMMENDATION_LIMIT,
)
from app.tools.concentration import ConcentrationQuery, GetConcentrationTool
from app.tools.contracts import ToolStatus

_JONGNO_AREA_CODE = "11"
_JONGNO_DISTRICT_CODE = "11110"
_KST = ZoneInfo("Asia/Seoul")
_CONCENTRATION_RELAXED_MAX = 50.0
_CONCENTRATION_NORMAL_MAX = 75.0
_CONCENTRATION_SLIGHTLY_CROWDED_MAX = 100.0


class CandidateEnrichmentService:
    """D의 상위 후보를 받아 C의 Concentration Tool로 보강한다."""

    def __init__(
        self,
        concentration_tool: GetConcentrationTool,
        *,
        candidate_limit: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not (
            MIN_RECOMMENDATION_LIMIT
            <= candidate_limit
            <= MAX_RECOMMENDATION_CANDIDATE_LIMIT
        ):
            raise ValueError(
                "candidate_limit은 "
                f"{MIN_RECOMMENDATION_LIMIT} 이상 "
                f"{MAX_RECOMMENDATION_CANDIDATE_LIMIT} 이하여야 합니다."
            )
        self._concentration_tool = concentration_tool
        self._candidate_limit = candidate_limit
        self._clock = clock or (lambda: datetime.now(_KST))

    async def enrich(
        self,
        request: CandidateEnrichmentRequest,
    ) -> CandidateEnrichmentResponse:
        """후보 순서를 유지하며 Concentration 조회를 병렬 실행한다."""

        if len(request.candidates) > self._candidate_limit:
            raise ValueError(
                f"보강 후보는 최대 {self._candidate_limit}개까지 요청할 수 있습니다."
            )
        reference_date = _as_kst_date(self._clock())
        candidates = await asyncio.gather(
            *(
                self._enrich_candidate(candidate, reference_date=reference_date)
                for candidate in request.candidates
            )
        )
        statuses = [candidate.status for candidate in candidates]
        return CandidateEnrichmentResponse(
            request_id=request.request_id,
            status=resolve_enrichment_status(statuses),
            candidates=candidates,
        )

    async def _enrich_candidate(
        self,
        candidate: CandidateEnrichmentTarget,
        *,
        reference_date: date,
    ) -> CandidateEnrichmentResult:
        tool_result = await self._concentration_tool.execute(
            ConcentrationQuery(
                area_code=_JONGNO_AREA_CODE,
                district_code=_JONGNO_DISTRICT_CODE,
                place_name=candidate.name,
            )
        )
        if tool_result.status is ToolStatus.UNAVAILABLE:
            error = tool_result.error
            return CandidateEnrichmentResult(
                **candidate.model_dump(),
                status="unavailable",
                concentration=None,
                error=ContextError(
                    code=error.code if error else "unavailable",
                    message=(error.message if error else "집중률 정보를 가져오지 못했습니다."),
                    retryable=error.retryable if error else True,
                ),
                provider_metadata=[
                    _map_provider_metadata(metadata) for metadata in tool_result.provider_metadata
                ],
            )

        forecast = _select_current_forecast(
            tool_result.concentration,
            candidate_name=candidate.name,
            reference_date=reference_date,
        )
        forecasts: list[ConcentrationForecastData] = []
        if forecast is not None:
            level, label = _normalize_concentration(forecast.concentration_rate)
            forecasts = [
                ConcentrationForecastData(
                    place_name=forecast.place_name,
                    forecast_date=reference_date.isoformat(),
                    concentration_rate=forecast.concentration_rate,
                    concentration_level=level,
                    concentration_label=label,
                )
            ]
        metadata = [_map_provider_metadata(item) for item in tool_result.provider_metadata]
        return CandidateEnrichmentResult(
            **candidate.model_dump(),
            status="success" if forecasts else "no_data",
            concentration=forecasts,
            error=None,
            provider_metadata=metadata,
        )


def _map_provider_metadata(metadata: ProviderMetadataData) -> ProviderMetadata:
    """공통 Provider metadata를 A–C Pydantic 계약으로 옮긴다."""

    return ProviderMetadata(
        source=metadata.source.value,
        status=metadata.status.value,
        retrieved_at=metadata.retrieved_at,
    )


def _as_kst_date(value: datetime) -> date:
    """호출 시각을 한국 날짜로 바꿔 집중률 예측 기준일로 사용한다."""

    if value.tzinfo is None:
        return value.replace(tzinfo=_KST).date()
    return value.astimezone(_KST).date()


def _parse_forecast_date(value: str | None) -> date | None:
    if value is None:
        return None
    normalized = value.strip()
    try:
        if len(normalized) == 8 and normalized.isdigit():
            return datetime.strptime(normalized, "%Y%m%d").date()
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def _select_current_forecast(
    concentration: ConcentrationResult | None,
    *,
    candidate_name: str,
    reference_date: date,
) -> ConcentrationForecast | None:
    """오늘 날짜의 유효값 중 요청 후보와 이름이 같은 예측을 우선한다."""

    if concentration is None:
        return None
    forecasts = [
        forecast
        for forecast in concentration.forecasts
        if _parse_forecast_date(forecast.forecast_date) == reference_date
        and forecast.concentration_rate is not None
        and math.isfinite(forecast.concentration_rate)
        and forecast.concentration_rate >= 0
    ]
    if not forecasts:
        return None
    normalized_name = candidate_name.strip()
    return next(
        (
            forecast
            for forecast in forecasts
            if forecast.place_name.strip() == normalized_name
        ),
        forecasts[0],
    )


def _normalize_concentration(
    rate: float,
) -> tuple[
    Literal["relaxed", "normal", "slightly_crowded", "crowded"],
    Literal["여유", "보통", "약간 붐빔", "붐빔"],
]:
    """평시 대비 상대 집중률을 합의된 네 단계와 사용자 표시명으로 변환한다."""

    if rate <= _CONCENTRATION_RELAXED_MAX:
        return "relaxed", "여유"
    if rate <= _CONCENTRATION_NORMAL_MAX:
        return "normal", "보통"
    if rate <= _CONCENTRATION_SLIGHTLY_CROWDED_MAX:
        return "slightly_crowded", "약간 붐빔"
    return "crowded", "붐빔"


__all__ = ["CandidateEnrichmentService"]
