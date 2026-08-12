"""C 응답 → 개발자용 Audit 표시 정보 변환.

역할: C의 AgentContextResponse에서 관측 전용 정보만 뽑아 A의 ToolExecutionDebug로
옮긴다. context_transform이 A→C 변환을 전담하는 것과 같은 원칙으로, 이 모듈은
C→Audit 변환만 전담한다.

이 변환은 판정에 관여하지 않는다 — 여기서 만든 값은 AgentResponse.tool_executions에
실려 /dev-chat 감사 패널에 표시될 뿐이고, 추천 결과나 응답 문장을 바꾸지 않는다.
그래서 실패해도 요청을 중단시키지 않는다(build_tool_execution_debug()의 예외 처리).
"""

from __future__ import annotations

import logging
from collections import Counter

from app.agent_context.compare_schemas import CompareContextResponse
from app.agent_context.enrichment_schemas import (
    CandidateEnrichmentResponse,
    CandidateEnrichmentResult,
)
from app.agent_context.info_schemas import InfoContextResponse
from app.agent_context.schemas import (
    AgentContextResponse,
    ContextValue,
    ProviderMetadata,
    RecommendationContext,
    ResolvedLocation,
)
from app.schemas import (
    CandidateConcentrationDebug,
    ToolContextItemDebug,
    ToolExecutionDebug,
    ToolProviderDebug,
)

logger = logging.getLogger(__name__)

# RecommendationContext의 항목을 표시 순서대로 나열한다. C가 항목을 추가하면
# 여기에도 넣어야 패널에 나타난다 — 빠뜨려도 조회 자체는 정상 동작한다.
_CONTEXT_ITEM_KEYS = ("location", "weather", "places", "holidays")


def _to_provider_debug(metadata: ProviderMetadata) -> ToolProviderDebug:
    return ToolProviderDebug(
        source=metadata.source,
        status=metadata.status,
        retrieved_at=metadata.retrieved_at.isoformat(),
    )


def _dedupe_providers(collected: list[ProviderMetadata]) -> list[ToolProviderDebug]:
    """Provider metadata를 표시용으로 옮기고 중복을 제거한다."""

    seen: set[tuple[str, str, str]] = set()
    providers: list[ToolProviderDebug] = []
    for metadata in collected:
        debug = _to_provider_debug(metadata)
        marker = (debug.source, debug.status, debug.retrieved_at or "")
        if marker in seen:
            continue
        seen.add(marker)
        providers.append(debug)
    return providers


def _collect_context_providers(response: AgentContextResponse) -> list[ToolProviderDebug]:
    """최상위 metadata와 항목별 provider_metadata를 합쳐 중복을 제거한다.

    C는 같은 Provider 기록을 두 곳에 모두 담을 수 있어서, 어느 한쪽만 보면
    호출 이력이 빠진다. (source, status, retrieved_at)이 같으면 같은 호출로 본다.
    """

    collected: list[ProviderMetadata] = list(response.metadata.provider_metadata)
    context = response.context
    if context is not None:
        for key in _CONTEXT_ITEM_KEYS:
            value = getattr(context, key, None)
            if value is not None:
                collected.extend(value.provider_metadata)

    return _dedupe_providers(collected)


def _item_count(value: ContextValue[object]) -> int | None:
    """목록형 항목만 개수를 센다. 단건형(location/weather)은 None을 그대로 둔다."""

    data = value.data
    if isinstance(data, (list, tuple)):
        return len(data)
    return None


def _to_item_debug(key: str, value: ContextValue[object] | None) -> ToolContextItemDebug:
    if value is None:
        # C가 조회하지 않은 항목. 조회 후 실패(status=unavailable 등)와 구분된다.
        return ToolContextItemDebug(key=key, fetched=False)
    return ToolContextItemDebug(
        key=key,
        fetched=True,
        status=value.status,
        error_code=value.error.code if value.error is not None else None,
        warning_codes=[warning.code for warning in value.warnings],
        item_count=_item_count(value),
    )


def _resolved_location(context: RecommendationContext | None) -> ResolvedLocation | None:
    if context is None or context.location is None:
        return None
    data = context.location.data
    return data if isinstance(data, ResolvedLocation) else None


def build_tool_execution_debug(
    response: AgentContextResponse,
    *,
    latency_ms: int | None = None,
) -> ToolExecutionDebug | None:
    """C 응답에서 감사용 표시 정보를 뽑는다. 실패하면 None을 반환한다.

    표시 전용이라 어떤 예외도 요청을 중단시켜서는 안 된다 — C가 계약에 없는 모양의
    응답을 주더라도 추천 흐름은 그대로 진행되어야 하므로 여기서 삼키고 로그만 남긴다.
    """

    try:
        context = response.context
        location = _resolved_location(context)
        return ToolExecutionDebug(
            operation="context_fetch",
            request_id=response.request_id,
            status=response.status,
            latency_ms=latency_ms,
            providers=_collect_context_providers(response),
            context_items=[
                _to_item_debug(key, getattr(context, key, None) if context else None)
                for key in _CONTEXT_ITEM_KEYS
            ],
            rule_versions=dict(response.metadata.rule_versions),
            resolved_location_name=location.resolved_name if location else None,
            resolved_location_address=location.address if location else None,
            error_code=response.error.code if response.error is not None else None,
            clarification_code=(
                response.clarification.code if response.clarification is not None else None
            ),
        )
    except Exception:  # noqa: BLE001 - 표시 정보 때문에 요청을 실패시키지 않는다.
        logger.warning("C 응답에서 Audit 표시 정보를 만들지 못함", exc_info=True)
        return None


def build_info_concentration_execution_debug(
    response: InfoContextResponse,
    *,
    latency_ms: int | None = None,
) -> ToolExecutionDebug | None:
    """INFO 단일 장소 조회를 감사용 단계 정보로 변환한다.

    이름은 concentration이지만 question_type 8종 전체가 이 함수를 거친다
    (D-054/D-055 A 배선). is_proxy는 ConcentrationInfoResult 전용 필드라
    PlaceInfoResult/EventInfoResult에는 없으므로 getattr로 방어한다 —
    없으면 AttributeError로 감사 기록 전체가 조용히 사라진다.
    """

    try:
        result = response.result
        error = result.error if result is not None and result.error is not None else response.error
        return ToolExecutionDebug(
            operation="info_concentration",
            request_id=response.request_id,
            status=response.status,
            latency_ms=latency_ms,
            providers=_dedupe_providers(list(response.metadata.provider_metadata)),
            context_items=[
                ToolContextItemDebug(
                    key="concentration",
                    fetched=True,
                    status=result.status if result is not None else response.status,
                    error_code=error.code if error is not None else None,
                    item_count=1 if result is not None else None,
                )
            ],
            rule_versions=dict(response.metadata.rule_versions),
            resolved_location_name=result.resolved_place_name if result is not None else None,
            error_code=error.code if error is not None else None,
            clarification_code=(
                response.clarification.code if response.clarification is not None else None
            ),
            is_proxy=getattr(result, "is_proxy", None) if result is not None else None,
        )
    except Exception:  # noqa: BLE001 - 표시 정보 때문에 요청을 실패시키지 않는다.
        logger.warning("INFO 응답에서 Audit 표시 정보를 만들지 못함", exc_info=True)
        return None


def build_compare_execution_debug(
    response: CompareContextResponse,
    *,
    latency_ms: int | None = None,
) -> ToolExecutionDebug | None:
    """COMPARE 장소명 보강 조회를 개발자 Audit 단계 정보로 변환한다."""

    try:
        return ToolExecutionDebug(
            operation="compare_fetch",
            request_id=response.request_id,
            status=response.status,
            latency_ms=latency_ms,
            # Compare 계약은 장소명·추천 시점 Feature 스냅샷만 반환한다. 일반
            # Context처럼 Provider metadata/rule_versions를 싣지 않으므로, Audit도
            # 빈 값으로 두고 존재하지 않는 필드를 읽지 않는다.
            providers=[],
            context_items=[
                ToolContextItemDebug(
                    key="comparison_candidates",
                    fetched=True,
                    status=response.status,
                    error_code=response.error.code if response.error is not None else None,
                    item_count=len(response.items),
                )
            ],
            error_code=response.error.code if response.error is not None else None,
        )
    except Exception:  # noqa: BLE001 - Audit 때문에 COMPARE 응답을 실패시키지 않는다.
        logger.warning("COMPARE 응답에서 Audit 표시 정보를 만들지 못함", exc_info=True)
        return None


def _candidate_concentration_debug(
    candidate: CandidateEnrichmentResult,
) -> CandidateConcentrationDebug:
    """후보 한 건의 혼잡도 출처를 감사용으로 옮긴다.

    한 후보의 concentration은 오늘 예보 한 건이라 첫 항목만 본다
    (select_concentration_forecast가 날짜·장소로 이미 한 건으로 좁힌다).
    """
    forecast = candidate.concentration[0] if candidate.concentration else None
    return CandidateConcentrationDebug(
        place_id=candidate.place_id,
        name=candidate.name,
        status=candidate.status,
        is_proxy=bool(forecast is not None and forecast.is_proxy),
        proxy_place_name=forecast.proxy_place_name if forecast is not None else None,
        proxy_distance_km=forecast.proxy_distance_km if forecast is not None else None,
    )


def build_candidate_enrichment_execution_debug(
    response: CandidateEnrichmentResponse,
    *,
    latency_ms: int | None = None,
) -> ToolExecutionDebug | None:
    """추천 후보 혼잡도 보강 조회를 감사용 단계 정보로 변환한다."""

    try:
        status_counts = dict(Counter(candidate.status for candidate in response.candidates))
        first_error = next(
            (candidate.error for candidate in response.candidates if candidate.error is not None),
            None,
        )
        metadata = [
            item
            for candidate in response.candidates
            for item in candidate.provider_metadata
        ]
        return ToolExecutionDebug(
            operation="candidate_enrichment",
            request_id=response.request_id,
            status=response.status,
            latency_ms=latency_ms,
            providers=_dedupe_providers(metadata),
            context_items=[
                ToolContextItemDebug(
                    key="concentration_candidates",
                    fetched=True,
                    status=response.status,
                    error_code=first_error.code if first_error is not None else None,
                    item_count=len(response.candidates),
                )
            ],
            error_code=first_error.code if first_error is not None else None,
            candidate_status_counts=status_counts,
            candidate_concentration=[
                _candidate_concentration_debug(candidate)
                for candidate in response.candidates
            ],
        )
    except Exception:  # noqa: BLE001 - 표시 정보 때문에 요청을 실패시키지 않는다.
        logger.warning("후보 혼잡도 보강 응답에서 Audit 표시 정보를 만들지 못함", exc_info=True)
        return None
