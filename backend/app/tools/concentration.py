"""관광지 집중률 Provider를 공통 Tool 계약으로 노출한다."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import ConcentrationResult
from app.errors import AppError
from app.providers.contracts import ProviderMetadata, ProviderStatus
from app.providers.protocols import ConcentrationProvider
from app.tools.contracts import ToolError, ToolStatus


@dataclass(frozen=True)
class ConcentrationQuery:
    area_code: str
    district_code: str
    place_name: str | None = None

    def __post_init__(self) -> None:
        if not self.area_code.strip() or not self.district_code.strip():
            raise ValueError("area_code와 district_code가 필요합니다.")


@dataclass(frozen=True)
class ConcentrationToolResult:
    status: ToolStatus
    concentration: ConcentrationResult | None
    error: ToolError | None
    warnings: tuple[str, ...] = ()
    provider_metadata: tuple[ProviderMetadata, ...] = ()


class GetConcentrationTool:
    def __init__(self, provider: ConcentrationProvider) -> None:
        self._provider = provider

    async def execute(self, query: ConcentrationQuery) -> ConcentrationToolResult:
        try:
            result = await self._provider.get_forecast(
                query.area_code.strip(),
                query.district_code.strip(),
                query.place_name.strip() if query.place_name else None,
            )
        except AppError as exc:
            return ConcentrationToolResult(
                status=ToolStatus.UNAVAILABLE,
                concentration=None,
                error=ToolError(
                    code="unavailable",
                    message="집중률 정보를 가져오지 못했습니다.",
                    cause="timeout" if exc.code == "provider_timeout" else "upstream_error",
                    retryable=exc.retryable,
                ),
            )

        status = (
            ToolStatus.NO_DATA
            if result.metadata.status is ProviderStatus.NO_DATA
            else ToolStatus.SUCCESS
        )
        return ConcentrationToolResult(
            status=status,
            concentration=result.data,
            error=None,
            provider_metadata=(result.metadata,),
        )
