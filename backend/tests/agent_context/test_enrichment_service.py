"""후보별 Concentration 후조회 계약과 서비스 상태 집계를 검증한다."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from pydantic import ValidationError

from app.agent_context.enrichment_schemas import (
    CandidateEnrichmentRequest,
    CandidateEnrichmentTarget,
)
from app.agent_context.enrichment_service import (
    CandidateEnrichmentService,
    _normalize_concentration,
)
from app.config import settings
from app.domain.models import ConcentrationForecast, ConcentrationResult
from app.errors import AppError, ProviderTimeoutError
from app.providers.concentration import FakeConcentrationProvider
from app.providers.contracts import (
    ProviderMetadata,
    ProviderResult,
    ProviderSource,
    ProviderStatus,
)
from app.tools.concentration import GetConcentrationTool

RETRIEVED_AT = datetime(2026, 7, 28, 1, tzinfo=UTC)
REFERENCE_TIME = datetime(2026, 7, 29, 10, tzinfo=UTC)


def _target(index: int, *, name: str | None = None) -> CandidateEnrichmentTarget:
    return CandidateEnrichmentTarget(
        place_id=f"place-{index}",
        name=name or f"후보 {index}",
        latitude=37.57 + index / 1000,
        longitude=126.97 + index / 1000,
    )


def _request(*targets: CandidateEnrichmentTarget) -> CandidateEnrichmentRequest:
    return CandidateEnrichmentRequest(
        request_id="enrichment-request-1",
        candidates=list(targets),
        features=["concentration"],
    )


def _provider_result(
    name: str,
    *,
    status: ProviderStatus = ProviderStatus.SUCCESS,
    has_data: bool = True,
) -> ProviderResult[ConcentrationResult]:
    forecasts = (
        (
            ConcentrationForecast(
                place_name=name,
                forecast_date="20260729",
                concentration_rate=42.0,
                raw_data={"cnctrRate": 42.0},
            ),
        )
        if has_data
        else ()
    )
    return ProviderResult(
        data=ConcentrationResult(
            area_code="11",
            district_code="11110",
            requested_place_name=name,
            forecasts=forecasts,
            provider="test_concentration",
        ),
        metadata=ProviderMetadata(
            source=ProviderSource.TOUR_API_CONCENTRATION,
            status=status,
            retrieved_at=RETRIEVED_AT,
        ),
    )


def _service(provider: _ScriptedConcentrationProvider) -> CandidateEnrichmentService:
    return CandidateEnrichmentService(
        GetConcentrationTool(provider),
        candidate_limit=5,
        clock=lambda: REFERENCE_TIME,
    )


class _ScriptedConcentrationProvider:
    """후보 이름별 결과나 오류를 반환하고 호출 인자를 기록한다."""

    def __init__(
        self,
        outcomes: dict[str, ProviderResult[ConcentrationResult] | AppError],
    ) -> None:
        self._outcomes = outcomes
        self.calls: list[tuple[str, str, str | None]] = []

    async def get_forecast(
        self,
        area_code: str,
        district_code: str,
        place_name: str | None = None,
    ) -> ProviderResult[ConcentrationResult]:
        self.calls.append((area_code, district_code, place_name))
        outcome = self._outcomes[str(place_name)]
        if isinstance(outcome, AppError):
            raise outcome
        return outcome


def test_request_enforces_system_limit_and_concentration_only() -> None:
    """Schema 절대 상한과 지원 feature를 계약 단계에서 거부한다."""

    valid = _request(*(_target(index) for index in range(1, 21)))

    assert len(valid.candidates) == 20
    with pytest.raises(ValidationError):
        _request(*(_target(index) for index in range(1, 22)))
    with pytest.raises(ValidationError):
        CandidateEnrichmentRequest(
            request_id="request-unsupported",
            candidates=[_target(1)],
            features=["weather"],
        )


@pytest.mark.asyncio
async def test_service_enforces_configured_candidate_limit() -> None:
    provider = _ScriptedConcentrationProvider({})
    request = _request(*(_target(index) for index in range(1, 7)))

    with pytest.raises(ValueError, match="최대 5개"):
        await _service(provider).enrich(request)

    assert provider.calls == []


@pytest.mark.asyncio
async def test_all_success_preserves_order_metadata_and_internal_region_codes() -> None:
    """네 후보 필드와 Provider metadata를 유지하고 종로구 코드로 조회한다."""

    first = _target(1, name="경복궁")
    second = _target(2, name="창덕궁")
    provider = _ScriptedConcentrationProvider(
        {
            "경복궁": _provider_result("경복궁"),
            "창덕궁": _provider_result("창덕궁"),
        }
    )

    response = await _service(provider).enrich(_request(first, second))

    assert response.status == "success"
    assert [candidate.place_id for candidate in response.candidates] == [
        first.place_id,
        second.place_id,
    ]
    assert response.candidates[0].latitude == first.latitude
    assert response.candidates[0].longitude == first.longitude
    assert response.candidates[0].concentration[0].concentration_rate == 42.0
    assert response.candidates[0].concentration[0].forecast_date == "2026-07-29"
    metadata = response.candidates[0].provider_metadata[0]
    assert metadata.source == "tour_api_concentration"
    assert metadata.status == "success"
    assert metadata.retrieved_at == RETRIEVED_AT
    assert provider.calls == [
        ("11", "11110", "경복궁"),
        ("11", "11110", "창덕궁"),
    ]


@pytest.mark.asyncio
async def test_service_keeps_only_today_and_prefers_matching_place_name() -> None:
    """여러 날짜·장소가 섞인 응답에서 오늘의 요청 장소 한 건만 반환한다."""

    provider_result = _provider_result("경복궁")
    provider_result = ProviderResult(
        data=ConcentrationResult(
            area_code="11",
            district_code="11110",
            requested_place_name="경복궁",
            forecasts=(
                ConcentrationForecast(
                    place_name="경복궁",
                    forecast_date="20260728",
                    concentration_rate=31.0,
                    raw_data={},
                ),
                ConcentrationForecast(
                    place_name="다른 장소",
                    forecast_date="2026-07-29",
                    concentration_rate=44.0,
                    raw_data={},
                ),
                ConcentrationForecast(
                    place_name="경복궁",
                    forecast_date="20260729",
                    concentration_rate=55.5,
                    raw_data={},
                ),
                ConcentrationForecast(
                    place_name="경복궁",
                    forecast_date="20260730",
                    concentration_rate=78.0,
                    raw_data={},
                ),
            ),
            provider="test_concentration",
        ),
        metadata=provider_result.metadata,
    )
    provider = _ScriptedConcentrationProvider({"경복궁": provider_result})

    response = await _service(provider).enrich(_request(_target(1, name="경복궁")))

    assert response.status == "success"
    assert response.candidates[0].concentration is not None
    assert len(response.candidates[0].concentration) == 1
    assert response.candidates[0].concentration[0].forecast_date == "2026-07-29"
    assert response.candidates[0].concentration[0].concentration_rate == 55.5
    assert response.candidates[0].concentration[0].concentration_level == "normal"
    assert response.candidates[0].concentration[0].concentration_label == "보통"


@pytest.mark.parametrize(
    ("rate", "expected_level", "expected_label"),
    [
        (0.0, "relaxed", "여유"),
        (50.0, "relaxed", "여유"),
        (50.1, "normal", "보통"),
        (75.0, "normal", "보통"),
        (75.1, "slightly_crowded", "약간 붐빔"),
        (100.0, "slightly_crowded", "약간 붐빔"),
        (100.1, "crowded", "붐빔"),
    ],
)
def test_normalize_concentration_uses_agreed_boundaries(
    rate: float,
    expected_level: str,
    expected_label: str,
) -> None:
    assert _normalize_concentration(rate) == (expected_level, expected_label)


@pytest.mark.asyncio
async def test_service_returns_no_data_when_today_has_no_valid_rate() -> None:
    """오늘 항목이 없거나 숫자값이 유효하지 않으면 다른 날짜로 대체하지 않는다."""

    provider_result = _provider_result("경복궁")
    provider_result = ProviderResult(
        data=ConcentrationResult(
            area_code="11",
            district_code="11110",
            requested_place_name="경복궁",
            forecasts=(
                ConcentrationForecast(
                    place_name="경복궁",
                    forecast_date="20260728",
                    concentration_rate=42.0,
                    raw_data={},
                ),
                ConcentrationForecast(
                    place_name="경복궁",
                    forecast_date="20260729",
                    concentration_rate=-1.0,
                    raw_data={},
                ),
            ),
            provider="test_concentration",
        ),
        metadata=provider_result.metadata,
    )
    provider = _ScriptedConcentrationProvider({"경복궁": provider_result})

    response = await _service(provider).enrich(_request(_target(1, name="경복궁")))

    assert response.status == "no_data"
    assert response.candidates[0].status == "no_data"
    assert response.candidates[0].concentration == []


@pytest.mark.asyncio
async def test_mixed_candidate_outcomes_return_partial_without_removing_candidates() -> None:
    """성공·빈 결과·실패 후보가 섞여도 모든 후보를 그대로 반환한다."""

    provider = _ScriptedConcentrationProvider(
        {
            "성공": _provider_result("성공"),
            "빈 결과": _provider_result(
                "빈 결과",
                status=ProviderStatus.NO_DATA,
                has_data=False,
            ),
            "실패": ProviderTimeoutError("Concentration"),
        }
    )

    response = await _service(provider).enrich(
        _request(
            _target(1, name="성공"),
            _target(2, name="빈 결과"),
            _target(3, name="실패"),
        )
    )

    assert response.status == "partial"
    assert [candidate.status for candidate in response.candidates] == [
        "success",
        "no_data",
        "unavailable",
    ]
    assert len(response.candidates) == 3
    assert response.candidates[1].concentration == []
    assert response.candidates[1].provider_metadata[0].status == "no_data"
    assert response.candidates[2].concentration is None
    assert response.candidates[2].error is not None
    assert response.candidates[2].error.retryable is True


@pytest.mark.asyncio
async def test_all_no_data_returns_no_data_and_keeps_candidates() -> None:
    """모든 Provider 조회가 빈 결과여도 후보는 제거하지 않는다."""

    provider = _ScriptedConcentrationProvider(
        {
            "첫째": _provider_result(
                "첫째",
                status=ProviderStatus.NO_DATA,
                has_data=False,
            ),
            "둘째": _provider_result(
                "둘째",
                status=ProviderStatus.NO_DATA,
                has_data=False,
            ),
        }
    )

    response = await _service(provider).enrich(
        _request(_target(1, name="첫째"), _target(2, name="둘째"))
    )

    assert response.status == "no_data"
    assert len(response.candidates) == 2
    assert all(candidate.status == "no_data" for candidate in response.candidates)


@pytest.mark.asyncio
async def test_all_failures_return_unavailable_and_keep_candidates() -> None:
    """모든 호출이 실패하면 전체 unavailable과 후보별 오류를 반환한다."""

    provider = _ScriptedConcentrationProvider(
        {
            "첫째": ProviderTimeoutError("Concentration"),
            "둘째": ProviderTimeoutError("Concentration"),
        }
    )

    response = await _service(provider).enrich(
        _request(_target(1, name="첫째"), _target(2, name="둘째"))
    )

    assert response.status == "unavailable"
    assert len(response.candidates) == 2
    assert all(candidate.status == "unavailable" for candidate in response.candidates)
    assert all(candidate.error is not None for candidate in response.candidates)


@pytest.mark.asyncio
async def test_fake_provider_uses_the_common_concentration_contract() -> None:
    """실제 서비스가 Fake ConcentrationProvider 공통 계약으로 동작한다."""

    response = await CandidateEnrichmentService(
        GetConcentrationTool(FakeConcentrationProvider()),
        candidate_limit=5,
    ).enrich(_request(_target(1, name="경복궁")))

    assert response.status == "success"
    assert response.candidates[0].status == "success"
    assert response.candidates[0].provider_metadata[0].source == "fake_concentration"


@pytest.mark.asyncio
async def test_factory_wires_configured_concentration_provider() -> None:
    """Factory가 설정된 Provider를 Tool 경계 안에서 보강 서비스에 연결한다."""

    from app.agent_context.factory import get_candidate_enrichment_service

    async with httpx.AsyncClient() as client:
        response = await get_candidate_enrichment_service(client).enrich(
            _request(_target(1, name="경복궁"))
        )

    assert response.status == "success"
    assert response.candidates[0].provider_metadata[0].source == "fake_concentration"


@pytest.mark.asyncio
async def test_factory_uses_recommendation_result_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent_context.factory import get_candidate_enrichment_service

    monkeypatch.setattr(settings, "recommendation_result_limit", 1)

    async with httpx.AsyncClient() as client:
        service = get_candidate_enrichment_service(client)
        with pytest.raises(ValueError, match="최대 1개"):
            await service.enrich(_request(_target(1), _target(2)))
