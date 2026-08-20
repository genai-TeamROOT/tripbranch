"""A의 조건 요청을 받아 필요한 C Tool을 실행하고 공통 Context를 반환한다."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from time import perf_counter
from typing import Literal, cast
from zoneinfo import ZoneInfo

from app.agent_context.assembler import (
    ContextAssemblyInput,
    assemble_agent_context_response,
)
from app.agent_context.category_rules import (
    CategoryQueryPlan,
    ExcludedCategoryPlan,
    build_category_query_plan,
    build_excluded_category_plan,
)
from app.agent_context.compare_schemas import (
    CompareContextRequest,
    CompareContextResponse,
)
from app.agent_context.concentration_proxy import (
    ConcentrationMappingCache,
    select_nearest_mapped_places,
)
from app.agent_context.enrichment_service import (
    execute_concentration_by_search_keys,
    select_concentration_forecast,
)
from app.agent_context.info_field_rules import clean_text, extract_info_fields
from app.agent_context.info_schemas import (
    ConcentrationInfoResult,
    EventInfoResult,
    EventItem,
    InfoContextRequest,
    InfoContextResponse,
    PlaceCard,
    PlaceInfoResult,
)
from app.agent_context.schemas import (
    AgentContextRequest,
    AgentContextResponse,
    Clarification,
    ContextError,
    Coordinates,
    ResponseMetadata,
)
from app.agent_context.schemas import ProviderMetadata as ContextProviderMetadata
from app.agent_context.tool_rules import (
    TOOL_EXECUTION_RULE_VERSION,
    ContextTool,
    build_tool_execution_plan,
)
from app.concentration_policy import (
    INFO_CONCENTRATION_FALLBACK_ATTEMPT_LIMIT,
    INFO_CONCENTRATION_FALLBACK_RADIUS_KM,
    is_valid_concentration_rate,
    normalize_concentration,
)
from app.domain.models import PlaceDetails
from app.errors import AppError
from app.geo import haversine_km
from app.place_search_policy import (
    DEFAULT_PLACE_SEARCH_RADIUS_KM,
    MAX_PLACE_SEARCH_RADIUS_KM,
    MIN_PLACE_SEARCH_RADIUS_KM,
    WALKING_SPEED_KM_PER_MINUTE,
)
from app.providers.contracts import ProviderMetadata, ProviderSource, ProviderStatus
from app.providers.festival import FestivalEvent
from app.recommendation_limits import (
    MAX_RECOMMENDATION_CANDIDATE_LIMIT,
    MIN_RECOMMENDATION_LIMIT,
)
from app.schemas import CompareCriteria, ComparisonItem
from app.tools.concentration import (
    GetConcentrationTool,
)
from app.tools.contracts import ToolError, ToolStatus
from app.tools.festival import FestivalQuery, GetFestivalsTool
from app.tools.holiday import GetHolidaysTool, HolidayQuery
from app.tools.nearby_place_details import (
    CANDIDATE_POOL_TRUNCATED_WARNING,
    EnrichedPlace,
    NearbyPlaceDetailsQuery,
    NearbyPlaceDetailsResult,
    NearbyPlaceDetailsTool,
)
from app.tools.place_detail import (
    GetPlaceDetailTool,
    PlaceDetailQuery,
)
from app.tools.recommendation_cards import RecommendationCardTool
from app.tools.resolve_location import (
    LocationPurpose,
    LocationSource,
    ResolutionConfidence,
    ResolutionMethod,
    ResolvedLocation,
    ResolveLocationQuery,
    ResolveLocationResult,
    ResolveLocationTool,
)
from app.tools.weather_forecast import (
    GetWeatherForecastTool,
    WeatherForecastQuery,
)

_KST = ZoneInfo("Asia/Seoul")
_CATEGORY_RULE_VERSION = "tour-category-v1"
_SEARCH_RADIUS_RULE_VERSION = "walking-radius-v1"

# 비교가 성립하는 최소 후보 수. 1건이 남으면 비교가 아니라 단일 안내다.
_MIN_COMPARE_ITEMS = 2

# criteria별로 "이 값이 없으면 비교할 게 없는" 필드. overall은 세 값을 함께 설명하는
# 방식이라(A 확정) 특정 필드를 요구하지 않는다.
_COMPARE_CRITERIA_FIELDS: dict[CompareCriteria, str] = {
    CompareCriteria.DISTANCE: "distance_km",
    CompareCriteria.TIME: "remaining_minutes",
}

# INFO 행사 응답에 싣는 최대 건수. 챗봇 말풍선 한 번에 읽히는 분량으로 제한한다.
INFO_EVENT_RESULT_LIMIT = 5


@dataclass(frozen=True)
class ContextTools:
    """Context 수집에 필요한 Tool 묶음."""

    location: ResolveLocationTool
    places: NearbyPlaceDetailsTool
    weather: GetWeatherForecastTool
    holidays: GetHolidaysTool
    # INFO 혼잡도는 RECOMMEND Context와 별도 경로다. 기존 RECOMMEND 조립 코드와
    # 테스트의 호환을 위해 선택적으로 두고, Factory에서는 항상 실제 Tool을 주입한다.
    concentration: GetConcentrationTool | None = None
    # INFO 상세 질의(concentration 외) 전용. 위와 같은 이유로 선택적이다.
    place_detail: GetPlaceDetailTool | None = None
    # INFO 행사 질의(question_type=event) 전용. 위와 같은 이유로 선택적이다.
    festivals: GetFestivalsTool | None = None
    # COMPARE의 place_id → 장소명 해석 전용. 추천 카드와 같은 Tool을 쓴다 —
    # 같은 places 행에서 같은 이름을 읽어야 카드와 비교 답변이 어긋나지 않는다.
    cards: RecommendationCardTool | None = None


class ContextService:
    """A가 지정한 조건으로 C의 Tool 실행 계획을 만들고 결과를 조립한다."""

    def __init__(
        self,
        tools: ContextTools,
        *,
        candidate_limit: int,
        clock: Callable[[], datetime] | None = None,
        search_radius_km: float = DEFAULT_PLACE_SEARCH_RADIUS_KM,
        concentration_mapping_cache: ConcentrationMappingCache | None = None,
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
        self._tools = tools
        self._clock = clock or (lambda: datetime.now(_KST))
        self._search_radius_km = search_radius_km
        self._candidate_limit = candidate_limit
        # 없으면 INFO fallback을 건너뛴다(기존 RECOMMEND 테스트 호환).
        self._concentration_mapping_cache = concentration_mapping_cache

    async def fetch_context(
        self,
        request: AgentContextRequest,
    ) -> AgentContextResponse:
        conditions = request.conditions
        execution_plan = build_tool_execution_plan(conditions)
        location_query = conditions.search_center or conditions.current_location
        if location_query is None and request.gps_location is None:
            return assemble_agent_context_response(
                ContextAssemblyInput(request=request, location_result=None),
                rule_versions=_rule_versions(),
            )

        category_plan = build_category_query_plan(
            conditions.place_types,
            conditions.place_tags,
        )
        if category_plan.has_unsupported_conditions or category_plan.has_conflicts:
            return _unsupported_category_response(request, category_plan)

        location_result = (
            await self._tools.location.execute(
                # 추천은 반경 검색의 기준 좌표만 필요하다. 저장소 정체성 확정은
                # 후보 보강 단계가 place_id로 따로 한다(enrichment_service).
                ResolveLocationQuery(
                    location_query, purpose=LocationPurpose.SEARCH_CENTER
                )
            )
            if location_query is not None
            else _gps_location_result(request, self._clock())
        )
        if location_result.status is not ToolStatus.SUCCESS or location_result.location is None:
            return assemble_agent_context_response(
                ContextAssemblyInput(
                    request=request,
                    location_result=location_result,
                ),
                rule_versions=_rule_versions(),
            )

        visit_at = _as_kst(self._clock())
        location = location_result.location
        weather_task = (
            asyncio.create_task(
                self._tools.weather.execute(
                    WeatherForecastQuery(
                        latitude=location.latitude,
                        longitude=location.longitude,
                        visit_at=visit_at,
                    )
                )
            )
            if execution_plan.requires(ContextTool.GET_WEATHER)
            else None
        )
        holidays_task = (
            asyncio.create_task(
                self._tools.holidays.execute(
                    HolidayQuery(year=visit_at.year, month=visit_at.month)
                )
            )
            if execution_plan.requires(ContextTool.GET_HOLIDAYS)
            else None
        )
        places_task = asyncio.create_task(
            self._collect_places(
                category_plan,
                excluded_plan=build_excluded_category_plan(conditions.exclude_tags),
                latitude=location.latitude,
                longitude=location.longitude,
                search_radius_km=_resolve_search_radius_km(
                    conditions.max_travel_time,
                    default_radius_km=self._search_radius_km,
                ),
                excluded_place_ids=frozenset(request.excluded_place_ids),
            )
        )
        weather_result = await weather_task if weather_task is not None else None
        holidays_result = await holidays_task if holidays_task is not None else None
        places_result = await places_task

        return assemble_agent_context_response(
            ContextAssemblyInput(
                request=request,
                location_result=location_result,
                weather_result=weather_result,
                places_result=places_result,
                holidays_result=holidays_result,
                weather_requested=execution_plan.requires(ContextTool.GET_WEATHER),
                holidays_requested=execution_plan.requires(ContextTool.GET_HOLIDAYS),
            ),
            rule_versions=_rule_versions(),
        )

    async def fetch_compare_context(
        self,
        request: CompareContextRequest,
    ) -> CompareContextResponse:
        """비교 후보의 place_id를 장소명으로 해석해 비교 사실을 조립한다.

        수치(거리·남은 운영시간·실내외)는 B가 보관한 추천 시점 스냅샷이므로 다시
        조회하지 않고 그대로 통과시킨다 — 사용자가 카드에서 본 값과 어긋나면 안 된다
        (D-050). C는 우열을 판정하지 않는다. 그건 A의 LLM 요약 몫이다.
        """

        card_tool = self._tools.cards
        if card_tool is None:
            return _compare_error_response(
                request,
                status="unavailable",
                error=ContextError(
                    code="place_lookup_not_configured",
                    message="비교에 필요한 장소 정보를 조회할 수 없습니다.",
                    retryable=False,
                ),
            )

        candidates = sorted(request.candidates, key=lambda item: item.rank)
        card_result = await card_tool.get_cards(
            [candidate.place_id for candidate in candidates]
        )
        if card_result.status is ToolStatus.UNAVAILABLE:
            return _compare_error_response(
                request,
                status="unavailable",
                error=_context_error_from_tool(
                    card_result.error,
                    fallback_code="unavailable",
                    fallback_message="비교에 필요한 장소 정보를 불러오지 못했습니다.",
                    retryable=True,
                ),
            )

        names = {
            card.content_id: card.name
            for card in card_result.cards
            if card.name is not None
        }
        items = [
            ComparisonItem(
                place_id=candidate.place_id,
                place_name=names[candidate.place_id],
                rank=candidate.rank,
                distance_km=candidate.distance_km,
                remaining_minutes=candidate.remaining_minutes,
                environment_type=candidate.environment_type,
            )
            for candidate in candidates
            if candidate.place_id in names
        ]
        missing = [
            candidate.place_id
            for candidate in candidates
            if candidate.place_id not in names
        ]

        # 이름을 못 찾은 후보는 빼고 진행하되, 남은 수가 비교를 이루지 못하면
        # no_data다 — 한 곳만 남겨두고 "비교"라고 답할 수는 없다.
        if len(items) < _MIN_COMPARE_ITEMS:
            return _compare_error_response(
                request, status="no_data", missing_place_ids=missing
            )

        # 기준에 해당하는 값이 전원 비어 있으면 비교할 사실이 없다. 그대로 넘기면
        # A의 LLM이 빈 값에서 뭔가 지어낼 여지가 생긴다(프롬프트가 "C가 준 값만
        # 쓰라"고 제한하는 취지와도 어긋난다).
        field = _COMPARE_CRITERIA_FIELDS.get(request.criteria)
        if field is not None and all(getattr(item, field) is None for item in items):
            return _compare_error_response(
                request, status="no_data", missing_place_ids=missing
            )

        return CompareContextResponse(
            request_id=request.request_id,
            status="partial" if missing else "success",
            criteria=request.criteria,
            items=items,
            missing_place_ids=missing,
        )

    async def fetch_info_context(
        self,
        request: InfoContextRequest,
    ) -> InfoContextResponse:
        """INFO 단일 장소 질의를 question_type에 맞는 경로로 처리한다.

        장소 식별(ResolveLocationTool)까지는 모든 question_type이 공통이고, 그
        뒤가 갈린다.

        - ``concentration`` → 집중률 API + D-036 인근 대체 조회
        - ``event`` → searchFestival2 연동이 없어 unsupported
        - 그 외 → 장소 상세 조회(TourAPI detailCommon2/detailIntro2)
        """

        place_name = request.place_name
        if place_name is None:
            return InfoContextResponse(
                request_id=request.request_id,
                status="needs_clarification",
                clarification=Clarification(
                    code="place_required",
                    missing_fields=["place_name"],
                    candidates=[],
                ),
            )

        location_result = await self._tools.location.execute(
            # INFO는 좌표가 아니라 "집중률 매핑이 걸린 그 장소"를 확정해야 한다(D-043).
            ResolveLocationQuery(place_name, purpose=LocationPurpose.PLACE_IDENTITY)
        )
        if location_result.status is ToolStatus.NO_DATA:
            cause = location_result.error.cause if location_result.error else None
            if cause == "ambiguous_location":
                return InfoContextResponse(
                    request_id=request.request_id,
                    status="needs_clarification",
                    clarification=Clarification(
                        code="place_ambiguous",
                        missing_fields=[],
                        candidates=[],
                    ),
                )
            return _info_no_data_response(
                request, location_result.provider_metadata
            )
        if location_result.status is ToolStatus.UNSUPPORTED:
            return _info_error_response(
                request,
                status="unsupported",
                error=_context_error_from_tool(
                    location_result.error,
                    fallback_code="unsupported",
                    fallback_message="현재 지원하지 않는 위치입니다.",
                    retryable=False,
                ),
                provider_metadata=(location_result.provider_metadata,),
            )
        if location_result.status is ToolStatus.UNAVAILABLE:
            return _info_error_response(
                request,
                status="unavailable",
                error=_context_error_from_tool(
                    location_result.error,
                    fallback_code="location_unavailable",
                    fallback_message="위치 정보를 가져오지 못했습니다.",
                    retryable=True,
                ),
                provider_metadata=(location_result.provider_metadata,),
            )

        resolved_location = location_result.location
        if resolved_location is None:
            # ResolveLocationTool 계약상 success에는 location이 있어야 한다.
            # 예기치 않은 구현 불일치는 외부 연동 오류로 정규화한다.
            return _info_error_response(
                request,
                status="unavailable",
                error=ContextError(
                    code="location_result_invalid",
                    message="위치 정보를 확인하지 못했습니다.",
                    retryable=True,
                ),
                provider_metadata=(location_result.provider_metadata,),
            )

        if request.question_type == "event":
            return await self._fetch_event_info(
                request,
                place_name=place_name,
                resolved_location=resolved_location,
                location_metadata=location_result.provider_metadata,
            )

        if request.question_type != "concentration":
            return await self._fetch_place_detail_info(
                request,
                place_name=place_name,
                resolved_location=resolved_location,
                location_metadata=location_result.provider_metadata,
            )

        return await self._fetch_concentration_info(
            request,
            place_name=place_name,
            resolved_location=resolved_location,
            location_metadata=location_result.provider_metadata,
        )

    async def _fetch_concentration_info(
        self,
        request: InfoContextRequest,
        *,
        place_name: str,
        resolved_location: ResolvedLocation,
        location_metadata: tuple[ProviderMetadata, ...],
    ) -> InfoContextResponse:
        """INFO 혼잡도 질의를 집중률 API로 처리한다(기존 경로 그대로).

        직접 조회가 안 되면 D-036 인근 관광지 대체 조회로 낮춘다.
        """

        reference_date = _info_reference_date(request.visit_time, self._clock())
        concentration_tool = self._tools.concentration
        if concentration_tool is None:
            return _info_error_response(
                request,
                status="unavailable",
                error=ContextError(
                    code="concentration_not_configured",
                    message="집중률 조회 기능을 사용할 수 없습니다.",
                    retryable=False,
                ),
                provider_metadata=(location_metadata,),
            )

        concentration_place_name = resolved_location.concentration_name
        if concentration_place_name is None:
            # 매핑이 없는 이름을 tAtsNm에 그대로 넣으면 안 된다. 부분 일치 검색이라
            # "종로"가 낙지볶음 골목·세종로공원·대학천 책방거리를 함께 끌어와, 그중
            # 하나의 값을 "종로의 혼잡도"로 답하게 된다(2026-08-04 실측). 활성 장소
            # 847건 중 매핑은 100건뿐이라 이 경로가 다수다.
            return await self._fetch_info_concentration_fallback(
                request,
                latitude=resolved_location.latitude,
                longitude=resolved_location.longitude,
                reference_date=reference_date,
                concentration_tool=concentration_tool,
                provider_metadata=(location_metadata,),
            )
        # 조회는 검색어로, 대조는 정식 명칭으로 한다. tAtsNm은 공백이 든 값에 0건을
        # 돌려주므로 "종묘 [유네스코 세계유산]"은 "종묘"로 조회해야 한다. 대신 그
        # 응답에는 "종묘광장공원"도 섞여 오므로 고를 때는 정식 명칭을 써야 한다.
        concentration_result = await execute_concentration_by_search_keys(
            concentration_tool,
            search_keys=resolved_location.concentration_search_keys,
            canonical_name=concentration_place_name,
        )
        if concentration_result.status is ToolStatus.UNAVAILABLE:
            return _info_error_response(
                request,
                status="unavailable",
                error=_context_error_from_tool(
                    concentration_result.error,
                    fallback_code="concentration_unavailable",
                    fallback_message="집중률 정보를 가져오지 못했습니다.",
                    retryable=True,
                ),
                provider_metadata=(
                    location_metadata,
                    concentration_result.provider_metadata,
                ),
            )
        if concentration_result.status is ToolStatus.NO_DATA:
            return await self._fetch_info_concentration_fallback(
                request,
                latitude=resolved_location.latitude,
                longitude=resolved_location.longitude,
                reference_date=reference_date,
                concentration_tool=concentration_tool,
                provider_metadata=(
                    location_metadata,
                    concentration_result.provider_metadata,
                ),
            )

        forecast = select_concentration_forecast(
            concentration_result.concentration,
            candidate_name=concentration_place_name,
            reference_date=reference_date,
        )
        rate = forecast.concentration_rate if forecast is not None else None
        if forecast is None or not is_valid_concentration_rate(rate):
            # 매핑된 장소인데도 쓸 값이 없다 — 여러 장소가 섞여 와 특정하지 못했거나
            # 해당 날짜 예보가 없는 경우다. 인근 장소로 답할 수 있으면 답한다.
            return await self._fetch_info_concentration_fallback(
                request,
                latitude=resolved_location.latitude,
                longitude=resolved_location.longitude,
                reference_date=reference_date,
                concentration_tool=concentration_tool,
                provider_metadata=(
                    location_metadata,
                    concentration_result.provider_metadata,
                ),
            )

        normalized = normalize_concentration(rate)
        return InfoContextResponse(
            request_id=request.request_id,
            status="success",
            result=ConcentrationInfoResult(
                status="success",
                is_proxy=False,
                requested_place_name=place_name,
                resolved_place_name=forecast.place_name,
                forecast_date=reference_date.isoformat(),
                concentration_rate=rate,
                concentration_level=cast(
                    Literal["quiet", "normal", "slightly_crowded", "crowded"],
                    normalized.level.value,
                ),
                concentration_label=normalized.label.value,
            ),
            metadata=_info_response_metadata(
                location_metadata,
                concentration_result.provider_metadata,
            ),
        )

    async def _fetch_info_concentration_fallback(
        self,
        request: InfoContextRequest,
        *,
        latitude: float,
        longitude: float,
        reference_date: date,
        concentration_tool: GetConcentrationTool,
        provider_metadata: tuple[tuple[ProviderMetadata, ...], ...],
    ) -> InfoContextResponse:
        """직접 데이터가 없는 INFO 장소를 인근 관광지 기준으로 대체 조회한다.

        D-036의 INFO 전용 경로다. 추천 후보 보강에는 이 함수를 사용하지 않는다.
        집중률 매핑이 있는 장소를 가까운 순으로 시도해 첫 성공을 채택한다 — 매핑에
        이름이 있어도 조회가 실패할 수 있어(표기 차이·API 갱신) 한 곳만 보고
        포기하지 않는다.
        """

        if self._concentration_mapping_cache is None:
            return _info_no_data_response(request, *provider_metadata)
        try:
            mapped_places = await self._concentration_mapping_cache.places()
        except AppError as exc:
            return _info_error_response(
                request,
                status="unavailable",
                error=ContextError(
                    code="concentration_mapping_unavailable",
                    message="인근 관광지를 찾지 못했습니다.",
                    retryable=exc.retryable,
                ),
                provider_metadata=provider_metadata,
            )

        proxy_places = select_nearest_mapped_places(
            mapped_places,
            latitude=latitude,
            longitude=longitude,
            radius_km=INFO_CONCENTRATION_FALLBACK_RADIUS_KM,
            limit=INFO_CONCENTRATION_FALLBACK_ATTEMPT_LIMIT,
        )
        if not proxy_places:
            return _info_no_data_response(request, *provider_metadata)

        attempted_metadata: list[tuple[ProviderMetadata, ...]] = []
        for proxy_place in proxy_places:
            # 매핑 테이블이 보유한 집중률 API 기준 이름을 쓴다 — TourAPI 장소명을
            # 그대로 던지던 기존 방식은 이름이 달라 조회에 실패하는 경우가 있었다.
            # 직접 조회와 같이 조회는 검색어로, 대조는 정식 명칭으로 한다.
            proxy_result = await execute_concentration_by_search_keys(
                concentration_tool,
                search_keys=proxy_place.concentration_search_keys,
                canonical_name=proxy_place.concentration_name,
            )
            attempted_metadata.append(proxy_result.provider_metadata)

            if proxy_result.status is ToolStatus.UNAVAILABLE:
                # 외부 장애는 다음 후보로 넘어가도 같은 결과일 가능성이 높다.
                return _info_error_response(
                    request,
                    status="unavailable",
                    error=_context_error_from_tool(
                        proxy_result.error,
                        fallback_code="concentration_unavailable",
                        fallback_message="집중률 정보를 가져오지 못했습니다.",
                        retryable=True,
                    ),
                    provider_metadata=(*provider_metadata, *attempted_metadata),
                )

            if proxy_result.status is ToolStatus.NO_DATA:
                continue

            forecast = select_concentration_forecast(
                proxy_result.concentration,
                candidate_name=proxy_place.concentration_name,
                reference_date=reference_date,
            )
            rate = forecast.concentration_rate if forecast is not None else None
            if forecast is None or not is_valid_concentration_rate(rate):
                # 이 장소는 해당 날짜 예보가 없다 — 다음으로 가까운 곳을 시도한다.
                continue

            normalized = normalize_concentration(rate)
            return InfoContextResponse(
                request_id=request.request_id,
                status="success",
                result=ConcentrationInfoResult(
                    status="success",
                    is_proxy=True,
                    requested_place_name=request.place_name,
                    resolved_place_name=forecast.place_name,
                    forecast_date=reference_date.isoformat(),
                    concentration_rate=rate,
                    concentration_level=cast(
                        Literal["quiet", "normal", "slightly_crowded", "crowded"],
                        normalized.level.value,
                    ),
                    concentration_label=normalized.label.value,
                ),
                metadata=_info_response_metadata(*provider_metadata, *attempted_metadata),
            )

        return _info_no_data_response(request, *provider_metadata, *attempted_metadata)

    async def _fetch_place_detail_info(
        self,
        request: InfoContextRequest,
        *,
        place_name: str,
        resolved_location: ResolvedLocation,
        location_metadata: tuple[ProviderMetadata, ...],
    ) -> InfoContextResponse:
        """INFO 상세 질의(concentration 외)를 장소 상세 조회로 처리한다.

        location_info는 장소 해석 결과만으로 답할 수 있어 상세 API를 호출하지
        않는다 — 주소는 ResolveLocationTool이 이미 들고 나온다. 전화번호까지
        필요하면 상세 조회가 필요하지만, 주소만으로 질문이 성립하므로 외부 호출을
        한 번 아끼는 쪽을 택했다.
        """

        if request.question_type == "location_info":
            fields: dict[str, str] = {}
            if resolved_location.address:
                fields["address"] = resolved_location.address
            return _place_info_response(
                request,
                requested_place_name=place_name,
                resolved_place_name=resolved_location.resolved_name,
                place_id=resolved_location.place_id,
                destination_coordinates=_to_info_destination_coordinates(resolved_location),
                fields=fields,
                provider_metadata=(location_metadata,),
            )

        detail_tool = self._tools.place_detail
        if detail_tool is None:
            return _info_error_response(
                request,
                status="unavailable",
                error=ContextError(
                    code="place_detail_not_configured",
                    message="장소 상세 조회 기능을 사용할 수 없습니다.",
                    retryable=False,
                ),
                provider_metadata=(location_metadata,),
            )

        # 사용자 발화가 아니라 해석된 정식 명칭으로 조회한다 — provider가 이름
        # 정확 일치로 후보를 고르기 때문이다("종묘" → "종묘 [유네스코 세계유산]").
        detail_result = await detail_tool.execute(
            PlaceDetailQuery(place_name=resolved_location.resolved_name)
        )
        if detail_result.status is ToolStatus.UNAVAILABLE:
            return _info_error_response(
                request,
                status="unavailable",
                error=_context_error_from_tool(
                    detail_result.error,
                    fallback_code="place_detail_unavailable",
                    fallback_message="장소 상세정보를 가져오지 못했습니다.",
                    retryable=True,
                ),
                provider_metadata=(location_metadata, detail_result.provider_metadata),
            )
        if detail_result.status is ToolStatus.NO_DATA or detail_result.details is None:
            return _place_info_response(
                request,
                requested_place_name=place_name,
                resolved_place_name=resolved_location.resolved_name,
                place_id=resolved_location.place_id,
                destination_coordinates=_to_info_destination_coordinates(resolved_location),
                fields={},
                provider_metadata=(location_metadata, detail_result.provider_metadata),
            )

        return _place_info_response(
            request,
            requested_place_name=place_name,
            resolved_place_name=(
                detail_result.details.title or resolved_location.resolved_name
            ),
            place_id=detail_result.details.content_id or resolved_location.place_id,
            destination_coordinates=_to_info_destination_coordinates(resolved_location),
            fields=extract_info_fields(request.question_type, detail_result.details),
            # 카드는 질문 유형과 무관하게 채운다. status는 위 fields로만 정해진다.
            place_card=_to_place_card(
                detail_result.details, resolved_location.place_id
            ),
            provider_metadata=(location_metadata, detail_result.provider_metadata),
        )

    async def _fetch_event_info(
        self,
        request: InfoContextRequest,
        *,
        place_name: str,
        resolved_location: ResolvedLocation,
        location_metadata: tuple[ProviderMetadata, ...],
    ) -> InfoContextResponse:
        """INFO 행사 질의를 지역 행사 목록 + 좌표 근접으로 처리한다(D-055).

        TourAPI에 장소별 행사 조회가 없어, 종로구 행사를 받아 진행 중인 것만
        남기고 대상 장소에서 가까운 순으로 정렬한다. 대부분은 그 장소의 행사가
        아니라 근처 행사이므로 is_direct_match/distance_km으로 구분을 넘긴다 —
        집중률의 is_proxy와 같은 취지다(D-036).
        """

        festival_tool = self._tools.festivals
        if festival_tool is None:
            return _info_error_response(
                request,
                status="unavailable",
                error=ContextError(
                    code="festival_not_configured",
                    message="행사 조회 기능을 사용할 수 없습니다.",
                    retryable=False,
                ),
                provider_metadata=(location_metadata,),
            )

        reference_date = _info_reference_date(request.visit_time, self._clock())
        festival_result = await festival_tool.execute(
            FestivalQuery(reference_date=reference_date)
        )
        if festival_result.status is ToolStatus.UNAVAILABLE:
            return _info_error_response(
                request,
                status="unavailable",
                error=_context_error_from_tool(
                    festival_result.error,
                    fallback_code="festival_unavailable",
                    fallback_message="행사 정보를 가져오지 못했습니다.",
                    retryable=True,
                ),
                provider_metadata=(location_metadata, festival_result.provider_metadata),
            )

        events = _to_event_items(
            festival_result.events,
            resolved_name=resolved_location.resolved_name,
            latitude=resolved_location.latitude,
            longitude=resolved_location.longitude,
        )
        status: Literal["success", "no_data"] = "success" if events else "no_data"
        return InfoContextResponse(
            request_id=request.request_id,
            status=status,
            result=EventInfoResult(
                status=status,
                requested_place_name=place_name,
                resolved_place_name=resolved_location.resolved_name,
                reference_date=reference_date.isoformat(),
                events=events,
                has_direct_match=any(item.is_direct_match for item in events),
            ),
            metadata=_info_response_metadata(
                location_metadata, festival_result.provider_metadata
            ),
        )

    async def _collect_places(
        self,
        plan: CategoryQueryPlan,
        *,
        excluded_plan: ExcludedCategoryPlan,
        latitude: float,
        longitude: float,
        search_radius_km: float,
        excluded_place_ids: frozenset[str] = frozenset(),
    ) -> NearbyPlaceDetailsResult:
        """분류별 장소 조회를 병렬 실행하고 중복·제외 후보를 걸러 한 결과로 합친다.

        `excluded_place_ids`는 분류별 조회 각각에 같은 집합으로 넘긴다 — 분류마다
        결과 집합이 다르므로 "앞에서 몇 건"이 아니라 id로 걸러야 맞다.
        """

        started_at = perf_counter()
        results = await asyncio.gather(
            *(
                self._tools.places.execute(
                    NearbyPlaceDetailsQuery(
                        latitude=latitude,
                        longitude=longitude,
                        search_radius_km=search_radius_km,
                        limit=self._candidate_limit,
                        preferred_categories=plan.resolved_place_tags,
                        category_filter=category_filter,
                        excluded_place_ids=excluded_place_ids,
                    )
                )
                for category_filter in plan.filters
            )
        )
        return _merge_place_results(
            results,
            limit=self._candidate_limit,
            started_at=started_at,
            excluded_plan=excluded_plan,
        )


def _gps_location_result(
    request: AgentContextRequest, retrieved_at: datetime
) -> ResolveLocationResult:
    """장소명이 없을 때 A가 전달한 기기 GPS를 위치 Tool 성공 결과로 정규화한다."""

    gps = request.gps_location
    if gps is None:
        raise ValueError("gps_location이 필요합니다.")
    return ResolveLocationResult(
        status=ToolStatus.SUCCESS,
        location=ResolvedLocation(
            requested_query="gps_location",
            provider_query="device_gps",
            resolved_name="기기 GPS 위치",
            source=LocationSource.DEVICE_GPS,
            latitude=gps.latitude,
            longitude=gps.longitude,
            resolution_method=ResolutionMethod.DIRECT,
            confidence=ResolutionConfidence.EXACT,
        ),
        error=None,
        provider_metadata=(
            ProviderMetadata(
                source=ProviderSource.DEVICE_GPS,
                status=ProviderStatus.SUCCESS,
                retrieved_at=_as_kst(retrieved_at).astimezone(UTC),
            ),
        ),
    )


def _info_reference_date(visit_time: str | None, clock_value: datetime) -> date:
    """INFO 요청의 방문일이 없으면 C 조회 시각의 한국 날짜를 사용한다."""

    if visit_time is not None:
        return date.fromisoformat(visit_time)
    return _as_kst(clock_value).date()


def _info_no_data_response(
    request: InfoContextRequest,
    *provider_metadata: tuple[ProviderMetadata, ...],
) -> InfoContextResponse:
    """직접 조회 결과가 없을 때의 INFO 응답을 한 형태로 유지한다."""

    return InfoContextResponse(
        request_id=request.request_id,
        status="no_data",
        result=ConcentrationInfoResult(
            status="no_data",
            requested_place_name=request.place_name,
        ),
        metadata=_info_response_metadata(*provider_metadata),
    )


def _to_event_items(
    events: tuple[FestivalEvent, ...],
    *,
    resolved_name: str,
    latitude: float,
    longitude: float,
) -> list[EventItem]:
    """행사를 대상 장소 기준으로 정렬해 계약 모델로 옮긴다.

    정렬은 (직접 매칭 우선, 가까운 순)이다. 좌표가 없는 행사는 거리 없이 뒤로
    보낸다 — 목록에서 빼면 "행사가 없다"로 잘못 보일 수 있어 남긴다.

    반경으로 자르지 않는 이유: 조회 자체가 이미 종로구(법정동 110)로 한정돼
    있어 지역 필터가 반경 역할을 한다. 여기서 임의 반경을 하나 더 두면 근거
    없는 숫자가 늘어난다. 대신 개수만 상한을 둔다.
    """

    def distance_of(event: FestivalEvent) -> float | None:
        if event.latitude is None or event.longitude is None:
            return None
        return haversine_km(latitude, longitude, event.latitude, event.longitude)

    def is_direct(event: FestivalEvent) -> bool:
        # "경복궁 별빛야행"처럼 제목이 장소를 지목하는 경우만 직접 매칭으로 본다.
        # eventplace를 보려면 행사마다 detailIntro2를 열어야 해(N+1) 이번 단계는
        # 제목 매칭까지만 한다.
        return resolved_name in event.title

    scored = [(event, distance_of(event), is_direct(event)) for event in events]
    scored.sort(
        key=lambda entry: (
            not entry[2],  # 직접 매칭 먼저
            entry[1] if entry[1] is not None else float("inf"),
        )
    )
    return [
        EventItem(
            title=event.title,
            start_date=event.start_date.isoformat(),
            end_date=event.end_date.isoformat(),
            address=event.address,
            distance_km=round(distance, 2) if distance is not None else None,
            is_direct_match=direct,
        )
        for event, distance, direct in scored[:INFO_EVENT_RESULT_LIMIT]
    ]


def _place_info_response(
    request: InfoContextRequest,
    *,
    requested_place_name: str,
    resolved_place_name: str,
    place_id: str | None,
    destination_coordinates: Coordinates | None,
    fields: dict[str, str],
    place_card: PlaceCard | None = None,
    provider_metadata: tuple[tuple[ProviderMetadata, ...], ...] = (),
) -> InfoContextResponse:
    """장소 상세 INFO 응답을 한 형태로 유지한다.

    뽑아낸 필드가 하나도 없으면 no_data다 — 장소는 찾았지만 그 질문에 답할 값이
    TourAPI에 없는 경우다. 이때도 resolved_place_name은 채워 보낸다(A가 "OO의
    주차 정보는 없어요"처럼 장소를 짚어 안내할 수 있게).

    **status 판정에는 fields만 쓴다.** place_card는 질문과 무관하게 채우므로
    판정에 넣으면 "주차 정보는 없어요"가 영영 나오지 않는다 — overview가 거의
    항상 있어 카드가 비는 일이 없기 때문이다.
    """

    status: Literal["success", "no_data"] = "success" if fields else "no_data"
    return InfoContextResponse(
        request_id=request.request_id,
        status=status,
        result=PlaceInfoResult(
            status=status,
            question_type=request.question_type,
            requested_place_name=requested_place_name,
            resolved_place_name=resolved_place_name,
            place_id=place_id,
            destination_coordinates=destination_coordinates,
            fields=fields,
            place_card=place_card,
        ),
        metadata=_info_response_metadata(*provider_metadata),
    )


def _to_info_destination_coordinates(location: ResolvedLocation) -> Coordinates:
    """C가 확정한 INFO 목적지를 A의 도보 경로 입력 형태로만 재노출한다."""

    return Coordinates(latitude=location.latitude, longitude=location.longitude)


def _to_place_card(details: PlaceDetails, place_id: str | None) -> PlaceCard:
    """상세 조회 결과를 카드 표시용 묶음으로 옮긴다.

    fields와 같은 clean_text를 태워 HTML·엔티티 정리 결과가 두 곳에서 갈리지 않게
    한다. 값이 없으면 None으로 두고 문구를 지어내지 않는다.
    """
    return PlaceCard(
        place_id=details.content_id or place_id,
        place_name=clean_text(details.title),
        thumbnail_url=details.thumbnail_url,
        overview=clean_text(details.overview),
        operating_hours=clean_text(details.operating_hours),
        rest_date=clean_text(details.rest_date),
        parking=clean_text(details.parking),
        parking_fee=clean_text(details.parking_fee),
        fee=clean_text(details.fee),
        baby_carriage=clean_text(details.baby_carriage),
        pet=clean_text(details.pet),
        credit_card=clean_text(details.credit_card),
        restroom=clean_text(details.restroom),
        homepage=clean_text(details.homepage),
    )


def _info_error_response(
    request: InfoContextRequest,
    *,
    status: Literal["unsupported", "unavailable"],
    error: ContextError,
    provider_metadata: tuple[tuple[ProviderMetadata, ...], ...] = (),
) -> InfoContextResponse:
    return InfoContextResponse(
        request_id=request.request_id,
        status=status,
        error=error,
        metadata=_info_response_metadata(*provider_metadata),
    )


def _compare_error_response(
    request: CompareContextRequest,
    *,
    status: Literal["no_data", "unavailable"],
    missing_place_ids: list[str] | None = None,
    error: ContextError | None = None,
) -> CompareContextResponse:
    """비교를 진행할 수 없을 때의 응답을 한 형태로 유지한다."""

    return CompareContextResponse(
        request_id=request.request_id,
        status=status,
        criteria=request.criteria,
        items=[],
        missing_place_ids=missing_place_ids or [],
        error=error,
    )


def _context_error_from_tool(
    error: ToolError | None,
    *,
    fallback_code: str,
    fallback_message: str,
    retryable: bool,
) -> ContextError:
    """Tool 오류 세부 정보는 유지하되 INFO 계약의 오류 모델로 변환한다."""

    return ContextError(
        code=error.code if error is not None else fallback_code,
        message=error.message if error is not None else fallback_message,
        retryable=error.retryable if error is not None else retryable,
    )


def _info_response_metadata(
    *provider_metadata_groups: tuple[ProviderMetadata, ...],
) -> ResponseMetadata:
    """INFO의 직접·대체 조회 전 과정을 A가 추적할 수 있게 누적한다."""

    return ResponseMetadata(
        provider_metadata=[
            ContextProviderMetadata(
                source=item.source.value,
                status=item.status.value,
                retrieved_at=item.retrieved_at,
            )
            for group in provider_metadata_groups
            for item in group
        ]
    )


def _resolve_search_radius_km(
    max_travel_time: int | None,
    *,
    default_radius_km: float,
) -> float:
    """최대 이동시간을 MVP 도보 속도로 환산한 후보 수집 반경으로 변환한다."""

    if max_travel_time is None:
        return default_radius_km
    estimated_radius = max_travel_time * WALKING_SPEED_KM_PER_MINUTE
    return min(
        max(estimated_radius, MIN_PLACE_SEARCH_RADIUS_KM),
        MAX_PLACE_SEARCH_RADIUS_KM,
    )


def _is_excluded(place: EnrichedPlace, excluded_small_codes: frozenset[str]) -> bool:
    """후보의 TourAPI 소분류가 제외 태그에 걸리는지.

    소분류(lcls_systm3)가 비어 있는 후보는 제외 여부를 판단할 근거가 없으므로
    남긴다 — 판단 못 하는 것을 제외로 취급하면 후보가 조용히 사라진다.
    """

    if not excluded_small_codes:
        return False
    small_code = place.candidate.lcls_systm3
    return small_code is not None and small_code.strip() in excluded_small_codes


def _place_warnings(
    status: ToolStatus,
    excluded_plan: ExcludedCategoryPlan,
    *,
    truncated: bool = False,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if status is ToolStatus.PARTIAL:
        warnings.append("partial_data")
    if excluded_plan.has_unmapped_tags:
        # 분류 매핑이 없어 걸러내지 못한 제외 태그가 있다는 걸 A/D가 알 수 있게 남긴다.
        warnings.append("exclude_tags_unmapped")
    if truncated:
        # 분류 조회 중 하나라도 Provider 행 상한에 걸렸다. 합쳐진 결과가 비어도
        # "더 없음"이 아니라 "더 못 받아옴"이라는 뜻이라 A가 구분해야 한다.
        warnings.append(CANDIDATE_POOL_TRUNCATED_WARNING)
    return tuple(warnings)


def _merge_place_results(
    results: list[NearbyPlaceDetailsResult],
    *,
    limit: int,
    started_at: float,
    excluded_plan: ExcludedCategoryPlan | None = None,
) -> NearbyPlaceDetailsResult:
    excluded_plan = excluded_plan or ExcludedCategoryPlan()
    if not results:
        return NearbyPlaceDetailsResult(
            places=(),
            status=ToolStatus.UNSUPPORTED,
            source="agent_context_service",
            retrieved_at=datetime.now(UTC),
            elapsed_ms=(perf_counter() - started_at) * 1000,
            error=ToolError(
                code="unsupported_category",
                message="지원하는 장소 분류를 찾지 못했습니다.",
                cause="unsupported_category",
                retryable=False,
            ),
        )

    places: list[EnrichedPlace] = []
    seen_place_ids: set[str] = set()
    excluded_count = 0
    for result in results:
        for place in result.places:
            place_id = place.candidate.place_id
            if place_id in seen_place_ids:
                continue
            seen_place_ids.add(place_id)
            # 제외는 limit을 적용하기 전에 건다 — 나중에 걸러내면 제외될 후보가
            # 먼저 정원을 차지해 실제 추천 가능한 후보가 줄어든다.
            if _is_excluded(place, excluded_plan.small_codes):
                excluded_count += 1
                continue
            places.append(place)
            if len(places) == limit:
                break
        if len(places) == limit:
            break

    statuses = tuple(result.status for result in results)
    if places:
        status = (
            ToolStatus.PARTIAL
            if any(item in {ToolStatus.PARTIAL, ToolStatus.UNAVAILABLE} for item in statuses)
            else ToolStatus.SUCCESS
        )
        error = None
    elif excluded_count or all(item is ToolStatus.NO_DATA for item in statuses):
        # 조회는 됐지만 전부 제외 태그에 걸린 경우도 "조건에 맞는 후보 없음"이다.
        # 장애(unavailable)로 떨어뜨리면 사용자에게 오류처럼 보인다.
        status = ToolStatus.NO_DATA
        error = None
    elif all(item is ToolStatus.UNSUPPORTED for item in statuses):
        status = ToolStatus.UNSUPPORTED
        error = next((result.error for result in results if result.error), None)
    else:
        status = ToolStatus.UNAVAILABLE
        error = next((result.error for result in results if result.error), None)

    return NearbyPlaceDetailsResult(
        places=tuple(places),
        status=status,
        source="agent_context_service",
        retrieved_at=max(result.retrieved_at for result in results),
        elapsed_ms=(perf_counter() - started_at) * 1000,
        error=error,
        warnings=_place_warnings(
            status,
            excluded_plan,
            truncated=any(
                CANDIDATE_POOL_TRUNCATED_WARNING in result.warnings for result in results
            ),
        ),
        provider_metadata=tuple(
            metadata for result in results for metadata in result.provider_metadata
        ),
    )


def _unsupported_category_response(
    request: AgentContextRequest,
    plan: CategoryQueryPlan,
) -> AgentContextResponse:
    details = [
        *plan.unsupported_place_types,
        *plan.unsupported_place_tags,
        *plan.conflicting_place_tags,
    ]
    message = "지원하지 않거나 서로 맞지 않는 장소 분류입니다."
    if details:
        message = f"{message} ({', '.join(details)})"
    return AgentContextResponse(
        request_id=request.request_id,
        intent=request.intent,
        status="unsupported",
        context=None,
        error=ContextError(
            code="unsupported_category",
            message=message,
            retryable=False,
        ),
        metadata=ResponseMetadata(rule_versions=_rule_versions()),
    )


def _rule_versions() -> dict[str, str]:
    return {
        "category": _CATEGORY_RULE_VERSION,
        "search_radius": _SEARCH_RADIUS_RULE_VERSION,
        "tool_execution": TOOL_EXECUTION_RULE_VERSION,
    }


def _as_kst(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=_KST)
    return value.astimezone(_KST)


__all__ = ["ContextService", "ContextTools"]
