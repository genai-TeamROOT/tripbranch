"""후보별 Concentration 후조회 계약과 서비스 상태 집계를 검증한다."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from pydantic import ValidationError

from app.agent_context.concentration_proxy import ConcentrationMappingCache
from app.agent_context.enrichment_schemas import (
    CandidateEnrichmentRequest,
    CandidateEnrichmentTarget,
)
from app.agent_context.enrichment_service import CandidateEnrichmentService
from app.concentration_policy import normalize_concentration
from app.config import settings
from app.domain.models import (
    ConcentrationForecast,
    ConcentrationResult,
    StoredPlaceLocation,
)
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
    assert response.candidates[0].concentration[0].concentration_level == "slightly_crowded"
    assert response.candidates[0].concentration[0].concentration_label == "다소 혼잡"


@pytest.mark.parametrize(
    ("rate", "expected_level", "expected_label"),
    [
        (0.0, "quiet", "한적함"),
        (19.9, "quiet", "한적함"),
        (20.0, "normal", "보통"),
        (49.9, "normal", "보통"),
        (50.0, "slightly_crowded", "다소 혼잡"),
        (69.9, "slightly_crowded", "다소 혼잡"),
        (70.0, "crowded", "혼잡"),
    ],
)
def test_normalize_concentration_uses_agreed_boundaries(
    rate: float,
    expected_level: str,
    expected_label: str,
) -> None:
    normalized = normalize_concentration(rate)

    assert normalized.level == expected_level
    assert normalized.label == expected_label


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
    """Factory가 설정된 Provider를 Tool 경계 안에서 보강 서비스에 연결한다.

    place_id는 fake 저장소의 content_id를 쓴다 — 매핑에 없는 후보는 조회 자체를
    건너뛰므로(D-057 이관) 임의 id로는 Provider까지 도달하지 않는다.
    """

    from app.agent_context.factory import get_candidate_enrichment_service

    async with httpx.AsyncClient() as client:
        response = await get_candidate_enrichment_service(client).enrich(
            _request(
                CandidateEnrichmentTarget(
                    place_id="126508",  # fake 저장소의 경복궁
                    name="경복궁",
                    latitude=37.5788,
                    longitude=126.9770,
                )
            )
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


class _StubMappingRepository:
    """집중률 매핑 저장소 fake. 캐시가 읽는 목록만 돌려준다."""

    def __init__(self, places: tuple[StoredPlaceLocation, ...]) -> None:
        self._places = places

    async def find_concentration_mapped_places(self) -> tuple[StoredPlaceLocation, ...]:
        return self._places


def _mapped_place(
    content_id: str,
    *,
    title: str,
    concentration_name: str,
    search_keys: tuple[str, ...],
) -> StoredPlaceLocation:
    return StoredPlaceLocation(
        content_id=content_id,
        title=title,
        address=None,
        latitude=37.5739,
        longitude=126.9945,
        concentration_name=concentration_name,
        concentration_search_keys=search_keys,
    )


def _mapped_service(
    provider: _ScriptedConcentrationProvider,
    places: tuple[StoredPlaceLocation, ...],
) -> CandidateEnrichmentService:
    return CandidateEnrichmentService(
        GetConcentrationTool(provider),
        candidate_limit=5,
        clock=lambda: REFERENCE_TIME,
        mapping_cache=ConcentrationMappingCache(_StubMappingRepository(places)),
    )


@pytest.mark.asyncio
async def test_mapped_candidate_queries_by_search_key_and_matches_canonical_name() -> None:
    """조회는 검색어로, 대조는 정식 명칭으로 한다(D-057).

    후보 이름('종묘')을 tAtsNm에 그대로 넣던 기존 방식은 응답에 섞여 오는
    '종묘광장공원'과 구분하지 못한다. 검색어로 조회하고 매핑의 정식 명칭으로
    골라야 올바른 장소가 선택된다.
    """

    canonical = "종묘 [유네스코 세계유산]"
    provider = _ScriptedConcentrationProvider(
        {
            "종묘": ProviderResult(
                data=ConcentrationResult(
                    area_code="11",
                    district_code="11110",
                    requested_place_name="종묘",
                    forecasts=(
                        ConcentrationForecast(
                            place_name="종묘광장공원",
                            forecast_date="20260729",
                            concentration_rate=35.28,
                            raw_data={},
                        ),
                        ConcentrationForecast(
                            place_name=canonical,
                            forecast_date="20260729",
                            concentration_rate=61.97,
                            raw_data={},
                        ),
                    ),
                    provider="test_concentration",
                ),
                metadata=ProviderMetadata(
                    source=ProviderSource.TOUR_API_CONCENTRATION,
                    status=ProviderStatus.SUCCESS,
                    retrieved_at=RETRIEVED_AT,
                ),
            )
        }
    )
    service = _mapped_service(
        provider,
        (
            _mapped_place(
                "126510",
                title="종묘",
                concentration_name=canonical,
                search_keys=("종묘",),
            ),
        ),
    )

    response = await service.enrich(
        _request(
            CandidateEnrichmentTarget(
                place_id="126510",
                name="종묘",
                latitude=37.5739,
                longitude=126.9945,
            )
        )
    )

    assert provider.calls == [("11", "11110", "종묘")]
    candidate = response.candidates[0]
    assert candidate.status == "success"
    assert candidate.concentration is not None
    # 첫 행(종묘광장공원 35.28)이 아니라 정식 명칭의 값을 골라야 한다.
    assert candidate.concentration[0].place_name == canonical
    assert candidate.concentration[0].concentration_rate == 61.97


@pytest.mark.asyncio
async def test_unmapped_candidate_skips_provider_call() -> None:
    """매핑이 없는 후보는 호출하지 않고 no_data로 끝낸다.

    매핑은 집중률 API에 데이터가 있는 장소 목록이라, 없으면 조회해도 안 나온다.
    활성 844건 중 매핑은 101건이고 음식점 191건은 0건이라(2026-08-09 실측) 이
    건너뛰기가 대부분의 헛호출을 없앤다.
    """

    provider = _ScriptedConcentrationProvider({})
    service = _mapped_service(
        provider,
        (
            _mapped_place(
                "126510",
                title="종묘",
                concentration_name="종묘 [유네스코 세계유산]",
                search_keys=("종묘",),
            ),
        ),
    )

    response = await service.enrich(
        _request(
            CandidateEnrichmentTarget(
                place_id="999999",
                name="스타벅스 종로점",
                latitude=37.5700,
                longitude=126.9900,
            )
        )
    )

    assert provider.calls == []
    assert response.candidates[0].status == "no_data"
    assert response.candidates[0].concentration == []


@pytest.mark.asyncio
async def test_search_keys_are_tried_in_order_until_data_found() -> None:
    """앞 검색어가 0건이면 다음 검색어로 넘어간다(D-057)."""

    provider = _ScriptedConcentrationProvider(
        {
            # 실 Provider는 forecasts가 비면 NO_DATA를 낸다(concentration.py:133).
            "서울": _provider_result(
                "서울", status=ProviderStatus.NO_DATA, has_data=False
            ),
            "운현궁": _provider_result("서울 운현궁"),
        }
    )
    service = _mapped_service(
        provider,
        (
            _mapped_place(
                "126520",
                title="운현궁",
                concentration_name="서울 운현궁",
                search_keys=("서울", "운현궁"),
            ),
        ),
    )

    response = await service.enrich(
        _request(
            CandidateEnrichmentTarget(
                place_id="126520",
                name="운현궁",
                latitude=37.5745,
                longitude=126.9855,
            )
        )
    )

    assert [call[2] for call in provider.calls] == ["서울", "운현궁"]
    assert response.candidates[0].status == "success"
