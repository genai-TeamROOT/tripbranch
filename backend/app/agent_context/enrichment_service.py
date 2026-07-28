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
from app.errors import AppError
from app.providers.contracts import ProviderMetadata as ProviderMetadataData
from app.providers.protocols import ConcentrationProvider

_JONGNO_AREA_CODE = "11"
_JONGNO_DISTRICT_CODE = "11110"


class CandidateEnrichmentService:
    """D의 상위 후보를 받아 C의 Concentration Provider로 보강한다."""

    def __init__(self, concentration_provider: ConcentrationProvider) -> None:
        self._concentration_provider = concentration_provider

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
        try:
            provider_result = await self._concentration_provider.get_forecast(
                area_code=_JONGNO_AREA_CODE,
                district_code=_JONGNO_DISTRICT_CODE,
                place_name=candidate.name,
            )
        except AppError as error:
            return CandidateEnrichmentResult(
                **candidate.model_dump(),
                status="unavailable",
                concentration=None,
                error=ContextError(
                    code=error.code,
                    message=error.message,
                    retryable=error.retryable,
                ),
                provider_metadata=[],
            )

        forecasts = [
            ConcentrationForecastData(
                place_name=forecast.place_name,
                forecast_date=forecast.forecast_date,
                concentration_rate=forecast.concentration_rate,
            )
            for forecast in provider_result.data.forecasts
        ]
        return CandidateEnrichmentResult(
            **candidate.model_dump(),
            status="success" if forecasts else "no_data",
            concentration=forecasts,
            error=None,
            provider_metadata=[_map_provider_metadata(provider_result.metadata)],
        )


def _map_provider_metadata(metadata: ProviderMetadataData) -> ProviderMetadata:
    """공통 Provider metadata를 A–C Pydantic 계약으로 옮긴다."""

    return ProviderMetadata(
        source=metadata.source.value,
        status=metadata.status.value,
        retrieved_at=metadata.retrieved_at,
    )


__all__ = ["CandidateEnrichmentService"]
