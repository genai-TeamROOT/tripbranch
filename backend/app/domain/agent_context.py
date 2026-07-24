"""Agent가 Provider 종류와 무관하게 소비하는 Tool Context 모델."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from app.providers.contracts import ProviderMetadata
from app.tools.contracts import ToolError, ToolStatus

T = TypeVar("T")


@dataclass(frozen=True)
class ToolContextValue(Generic[T]):
    status: ToolStatus
    data: T | None
    error: ToolError | None
    warnings: tuple[str, ...] = ()
    provider_metadata: tuple[ProviderMetadata, ...] = ()


def context_value(
    *,
    status: ToolStatus,
    data: T | None,
    error: ToolError | None,
    warnings: tuple[str, ...] = (),
    provider_metadata: tuple[ProviderMetadata, ...] = (),
) -> ToolContextValue[T]:
    """Tool별 payload를 동일한 Agent Context 형식으로 감싼다."""

    return ToolContextValue(
        status=status,
        data=data,
        error=error,
        warnings=warnings,
        provider_metadata=provider_metadata,
    )


@dataclass(frozen=True)
class AgentToolContext:
    """한 추천 실행에서 수집한 Tool 결과 스냅샷."""

    location: ToolContextValue[object] | None = None
    weather: ToolContextValue[object] | None = None
    places: ToolContextValue[object] | None = None
    concentration: ToolContextValue[object] | None = None
    holidays: ToolContextValue[object] | None = None

    @property
    def provider_metadata(self) -> tuple[ProviderMetadata, ...]:
        values = (
            self.location,
            self.weather,
            self.places,
            self.concentration,
            self.holidays,
        )
        return tuple(
            metadata
            for value in values
            if value is not None
            for metadata in value.provider_metadata
        )

    @property
    def warnings(self) -> tuple[str, ...]:
        values = (
            self.location,
            self.weather,
            self.places,
            self.concentration,
            self.holidays,
        )
        return tuple(
            warning
            for value in values
            if value is not None
            for warning in value.warnings
        )
