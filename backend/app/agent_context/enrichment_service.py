"""상위 추천 후보의 Concentration 정보를 후조회하는 C 서비스."""

from __future__ import annotations

import asyncio

from app.agent_context.enrichment_schemas import (
    CandidateEnrichmentRequest,
    CandidateEnrichmentResponse,
    CandidateEnrichmentResult,
    CandidateEnrichmentTarget,
    ConcentrationForecastData,
    resolve_enrichment_status,
)
from app.agent_context.schemas import ContextError, ProviderMetadata
from app.providers.contracts import ProviderMetadata as ProviderMetadataData
from app.tools.concentration import ConcentrationQuery, GetConcentrationTool
from app.tools.contracts import ToolStatus

_JONGNO_AREA_CODE = "11"
_JONGNO_DISTRICT_CODE = "11110"


class CandidateEnrichmentService:
    """D의 상위 후보를 받아 C의 Concentration Tool로 보강한다."""

    def __init__(self, concentration_tool: GetConcentrationTool) -> None:
        self._concentration_tool = concentration_tool

    async def enrich(
        self,
        request: CandidateEnrichmentRequest,
    ) -> CandidateEnrichmentResponse:
        """후보 순서를 유지하며 Concentration 조회를 병렬 실행한다."""

        candidates = await asyncio.gather(
            *(self._enrich_candidate(candidate) for candidate in request.candidates)
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

        concentration = tool_result.concentration
        forecasts = (
            [
                ConcentrationForecastData(
                    place_name=forecast.place_name,
                    forecast_date=forecast.forecast_date,
                    concentration_rate=forecast.concentration_rate,
                )
                for forecast in concentration.forecasts
            ]
            if concentration is not None
            else []
        )
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


__all__ = ["CandidateEnrichmentService"]
