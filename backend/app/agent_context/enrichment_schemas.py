"""D가 선정한 후보를 C가 후조회할 때 사용하는 독립 A–C 계약."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.agent_context.schemas import ContextError, ProviderMetadata, StrictModel


class CandidateEnrichmentTarget(StrictModel):
    """Concentration 보강을 요청할 추천 후보 한 건."""

    place_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    @field_validator("place_id", "name")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("후보 식별자와 이름은 공백일 수 없습니다.")
        return normalized


class CandidateEnrichmentRequest(StrictModel):
    """A가 D의 상위 후보를 받아 C에 전달하는 보강 요청."""

    request_id: str = Field(min_length=1)
    candidates: list[CandidateEnrichmentTarget] = Field(
        min_length=1,
        max_length=5,
    )
    features: list[Literal["concentration"]] = Field(min_length=1, max_length=1)

    @field_validator("request_id")
    @classmethod
    def normalize_request_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("request_id는 공백일 수 없습니다.")
        return normalized


class ConcentrationForecastData(StrictModel):
    """Provider 집중률 예측에서 A와 D가 소비할 표준 필드."""

    place_name: str
    forecast_date: str | None = None
    concentration_rate: float | None = None


class CandidateEnrichmentResult(StrictModel):
    """후보 원본 식별정보와 Concentration 후조회 결과."""

    place_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    status: Literal["success", "no_data", "unavailable"]
    concentration: list[ConcentrationForecastData] | None = None
    error: ContextError | None = None
    provider_metadata: list[ProviderMetadata] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_state(self) -> CandidateEnrichmentResult:
        if self.status == "success":
            if not self.concentration:
                raise ValueError("success 후보에는 집중률 데이터가 필요합니다.")
            if self.error is not None:
                raise ValueError("success 후보에는 error를 넣을 수 없습니다.")
        elif self.status == "no_data":
            if self.concentration != []:
                raise ValueError("no_data 후보의 집중률 데이터는 빈 목록이어야 합니다.")
            if self.error is not None:
                raise ValueError("no_data 후보에는 error를 넣을 수 없습니다.")
        else:
            if self.concentration is not None:
                raise ValueError("unavailable 후보에는 집중률 데이터를 넣을 수 없습니다.")
            if self.error is None:
                raise ValueError("unavailable 후보에는 error가 필요합니다.")
        return self


class CandidateEnrichmentResponse(StrictModel):
    """C가 후보 순서를 유지해 반환하는 Concentration 보강 응답."""

    request_id: str = Field(min_length=1)
    status: Literal["success", "partial", "no_data", "unavailable"]
    candidates: list[CandidateEnrichmentResult] = Field(
        min_length=1,
        max_length=5,
    )

    @model_validator(mode="after")
    def validate_overall_status(self) -> CandidateEnrichmentResponse:
        expected_status = resolve_enrichment_status(
            [candidate.status for candidate in self.candidates]
        )
        if self.status != expected_status:
            raise ValueError(
                f"후보 상태 조합에는 전체 상태 {expected_status!r}가 필요합니다."
            )
        return self


def resolve_enrichment_status(
    statuses: list[Literal["success", "no_data", "unavailable"]],
) -> Literal["success", "partial", "no_data", "unavailable"]:
    """후보별 상태 조합을 보강 응답의 전체 상태로 축약한다."""

    if statuses and all(status == "success" for status in statuses):
        return "success"
    if statuses and all(status == "no_data" for status in statuses):
        return "no_data"
    if statuses and all(status == "unavailable" for status in statuses):
        return "unavailable"
    return "partial"


__all__ = [
    "CandidateEnrichmentRequest",
    "CandidateEnrichmentResponse",
    "CandidateEnrichmentResult",
    "CandidateEnrichmentTarget",
    "ConcentrationForecastData",
]
