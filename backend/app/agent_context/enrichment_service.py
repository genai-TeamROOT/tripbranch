"""상위 추천 후보의 Concentration 정보를 후조회하는 C 서비스."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.agent_context.concentration_proxy import ConcentrationMappingCache
from app.agent_context.enrichment_schemas import (
    CandidateEnrichmentRequest,
    CandidateEnrichmentResponse,
    CandidateEnrichmentResult,
    CandidateEnrichmentStatus,
    CandidateEnrichmentTarget,
    ConcentrationForecastData,
    resolve_enrichment_status,
)
from app.agent_context.schemas import ContextError, ProviderMetadata
from app.concentration_policy import (
    is_valid_concentration_rate,
    normalize_concentration,
)
from app.domain.models import (
    ConcentrationForecast,
    ConcentrationResult,
    StoredPlaceLocation,
)
from app.providers.contracts import ProviderMetadata as ProviderMetadataData
from app.recommendation_limits import (
    MAX_RECOMMENDATION_CANDIDATE_LIMIT,
    MIN_RECOMMENDATION_LIMIT,
)
from app.tools.concentration import (
    ConcentrationQuery,
    ConcentrationToolResult,
    GetConcentrationTool,
)
from app.tools.contracts import ToolStatus

# 집중률 API의 종로구 행정 코드. INFO와 후보 보강이 같은 MVP 범위를 사용한다.
JONGNO_CONCENTRATION_AREA_CODE = "11"
JONGNO_CONCENTRATION_DISTRICT_CODE = "11110"
_KST = ZoneInfo("Asia/Seoul")


class CandidateEnrichmentService:
    """D의 상위 후보를 받아 C의 Concentration Tool로 보강한다."""

    def __init__(
        self,
        concentration_tool: GetConcentrationTool,
        *,
        candidate_limit: int,
        clock: Callable[[], datetime] | None = None,
        mapping_cache: ConcentrationMappingCache | None = None,
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
        # 없으면 후보 이름 원문으로 조회한다(Supabase 미설정 환경·기존 테스트 호환).
        self._mapping_cache = mapping_cache

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
        mappings = await self._mappings_by_place_id()
        candidates = await asyncio.gather(
            *(
                self._enrich_candidate(
                    candidate,
                    reference_date=reference_date,
                    mapping=mappings.get(candidate.place_id) if mappings is not None else None,
                    mappings_available=mappings is not None,
                )
                for candidate in request.candidates
            )
        )
        statuses: list[CandidateEnrichmentStatus] = [
            candidate.status for candidate in candidates
        ]
        return CandidateEnrichmentResponse(
            request_id=request.request_id,
            status=resolve_enrichment_status(statuses),
            candidates=candidates,
        )

    async def _mappings_by_place_id(self) -> dict[str, StoredPlaceLocation] | None:
        """집중률 매핑을 content_id로 색인한다. 캐시가 없으면 None(기존 경로)."""

        if self._mapping_cache is None:
            return None
        places = await self._mapping_cache.places()
        return {place.content_id: place for place in places}

    async def _enrich_candidate(
        self,
        candidate: CandidateEnrichmentTarget,
        *,
        reference_date: date,
        mapping: StoredPlaceLocation | None,
        mappings_available: bool,
    ) -> CandidateEnrichmentResult:
        """후보 1건의 집중률을 조회한다.

        매핑이 있으면 조회는 검색어 목록으로, 대조는 정식 명칭으로 한다(D-057) —
        INFO 경로와 같은 방식이다. 후보 이름 원문을 그대로 `tAtsNm`에 넣던 기존
        방식은 공백이 든 이름에 항상 0건이 돌아오고(D-043), 이름이 정식 명칭과
        다르면 대조에서 탈락한다. 2026-08-09 기준 매핑 101건 중 원문으로 조회가
        통하는 건 67건뿐이었다.

        매핑이 없는 후보는 **호출하지 않고** no_data로 끝낸다. 매핑은 집중률 API에
        데이터가 존재하는 장소의 목록이므로, 없다는 것은 조회해도 안 나온다는 뜻이다
        (활성 844건 중 매핑 101건, 음식점 191건은 0건).
        """
        if mappings_available and mapping is None:
            return CandidateEnrichmentResult(
                **candidate.model_dump(),
                status="no_data",
                concentration=[],
                error=None,
                provider_metadata=[],
            )

        canonical_name = (
            mapping.concentration_name
            if mapping is not None and mapping.concentration_name
            else candidate.name
        )
        search_keys = mapping.concentration_search_keys if mapping is not None else ()
        tool_result = await execute_concentration_by_search_keys(
            self._concentration_tool,
            search_keys=search_keys,
            canonical_name=canonical_name,
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

        forecast = select_concentration_forecast(
            tool_result.concentration,
            candidate_name=canonical_name,
            reference_date=reference_date,
        )
        forecasts: list[ConcentrationForecastData] = []
        rate = forecast.concentration_rate if forecast is not None else None
        if forecast is not None and is_valid_concentration_rate(rate):
            normalized = normalize_concentration(rate)
            forecasts = [
                ConcentrationForecastData(
                    place_name=forecast.place_name,
                    forecast_date=reference_date.isoformat(),
                    concentration_rate=rate,
                    concentration_level=normalized.level,
                    concentration_label=normalized.label,
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


async def execute_concentration_by_search_keys(
    concentration_tool: GetConcentrationTool,
    *,
    search_keys: Sequence[str],
    canonical_name: str,
) -> ConcentrationToolResult:
    """검색어를 순서대로 시도하고 결과가 나오면 멈춘다(D-057).

    tAtsNm은 공백이 든 값에 0건을 돌려주므로 정식 명칭을 그대로 못 쓰는 이름이 많다.
    검색어를 하나만 두면 '서울 동대문 닭한마리 골목'이 '닭한마리'로만 조회돼, 사용자가
    다른 표현으로 물으면 못 찾는다. 목록을 앞에서부터 시도해 폭을 넓힌다.

    1순위는 이관 전 단일 검색어와 같은 값이라 기존 동작이 그대로 유지된다. 뒤 토큰은
    앞에서 결과가 나오면 호출되지 않으므로 평상시 호출 수도 늘지 않는다.

    UNAVAILABLE은 즉시 반환한다 — 외부 장애는 다음 검색어로 바꿔도 같은 결과다.

    INFO 경로(`service.py`)와 추천 후보 보강이 함께 쓴다. 두 경로가 같은 조회 규칙을
    갖도록 여기 한 곳에만 둔다.
    """
    candidates = [key for key in search_keys if key] or [canonical_name]
    result = None
    for candidate in candidates:
        result = await concentration_tool.execute(
            ConcentrationQuery(
                area_code=JONGNO_CONCENTRATION_AREA_CODE,
                district_code=JONGNO_CONCENTRATION_DISTRICT_CODE,
                place_name=candidate,
            )
        )
        if result.status is not ToolStatus.NO_DATA:
            return result
    assert result is not None  # candidates는 항상 하나 이상이다
    return result


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


def parse_concentration_forecast_date(value: str | None) -> date | None:
    """Provider별 날짜 표기를 date로 통일한다."""
    if value is None:
        return None
    normalized = value.strip()
    try:
        if len(normalized) == 8 and normalized.isdigit():
            return datetime.strptime(normalized, "%Y%m%d").date()
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def select_concentration_forecast(
    concentration: ConcentrationResult | None,
    *,
    candidate_name: str,
    reference_date: date,
) -> ConcentrationForecast | None:
    """오늘 날짜의 유효값 중 요청 후보와 이름이 같은 예측을 고른다.

    집중률 API의 tAtsNm은 부분 일치 검색이라 한 번에 여러 장소가 딸려 온다("종묘"로
    조회하면 "종묘광장공원"도 함께 온다). 이름이 안 맞는데 첫 예보로 폴백하면 엉뚱한
    장소의 혼잡도를 정상 응답처럼 답하게 되므로, 여러 장소가 섞여 왔는데 일치하는
    이름이 없으면 답을 포기한다. 틀린 값보다 "정보 없음"이 낫다.

    한 곳만 온 경우에는 표기가 달라도(예: 요청 "운현궁" ↔ 응답 "서울 운현궁") 그
    장소가 맞으므로 그대로 쓴다.
    """

    if concentration is None:
        return None
    forecasts = [
        forecast
        for forecast in concentration.forecasts
        if parse_concentration_forecast_date(forecast.forecast_date) == reference_date
        and is_valid_concentration_rate(forecast.concentration_rate)
    ]
    if not forecasts:
        return None
    normalized_name = candidate_name.strip()
    matched = next(
        (
            forecast
            for forecast in forecasts
            if forecast.place_name.strip() == normalized_name
        ),
        None,
    )
    if matched is not None:
        return matched
    if len({forecast.place_name.strip() for forecast in forecasts}) > 1:
        return None
    return forecasts[0]

__all__ = [
    "CandidateEnrichmentService",
    "JONGNO_CONCENTRATION_AREA_CODE",
    "JONGNO_CONCENTRATION_DISTRICT_CODE",
    "select_concentration_forecast",
]
