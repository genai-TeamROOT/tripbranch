"""A의 조건 요청을 받아 필요한 C Tool을 실행하고 공통 Context를 반환한다."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from time import perf_counter
from typing import Literal, cast
from urllib.parse import quote
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
    parse_concentration_forecast_date,
    select_concentration_forecast,
    select_concentration_forecasts,
)
from app.agent_context.info_field_rules import clean_text, extract_info_fields
from app.agent_context.info_schemas import (
    ConcentrationForecastInfo,
    ConcentrationInfoResult,
    EventInfoResult,
    EventItem,
    InfoContextRequest,
    InfoContextResponse,
    PlaceCard,
    PlaceInfoResult,
    PopulationForecastInfo,
    RealtimeCityInfoResult,
    RealtimeCommercialInfoResult,
    RealtimeInfoDetailItem,
    RealtimePopulationInfoResult,
)
from app.agent_context.schemas import (
    AgentContextRequest,
    AgentContextResponse,
    Clarification,
    ContextError,
    Coordinates,
    ResponseMetadata,
    parse_candidate_names,
)
from app.agent_context.schemas import ProviderMetadata as ContextProviderMetadata
from app.agent_context.seoul_realtime_areas import (
    COMMERCIAL_AREA_PROXY_MAX_DISTANCE_KM,
    POPULATION_AREAS,
    SeoulRealtimeArea,
    select_nearest_commercial_area,
    select_nearest_population_area,
)
from app.agent_context.tool_rules import (
    TOOL_EXECUTION_RULE_VERSION,
    ContextTool,
    build_tool_execution_plan,
)
from app.concentration_policy import (
    INFO_CONCENTRATION_FALLBACK_ATTEMPT_LIMIT,
    INFO_CONCENTRATION_FALLBACK_RADIUS_KM,
    concentration_signgu_code,
    is_valid_concentration_rate,
    normalize_concentration,
)
from app.config import settings
from app.domain.models import (
    ConcentrationResult,
    MunicipalParkingStatus,
    PlaceDetails,
    RealtimeBusStop,
    RealtimeCityEvent,
    RealtimeCommercialCategory,
    RealtimeParkingLot,
    RealtimeSubwayArrival,
)
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
from app.repositories.protocols import MunicipalParkingCatalogRepository
from app.schemas import CompareCriteria, ComparisonItem, StaleAreaProbeDebug
from app.service_area import SUPPORTED_DISTRICTS
from app.tools.concentration import (
    GetConcentrationTool,
)
from app.tools.contracts import ToolError, ToolStatus
from app.tools.festival import FestivalQuery, GetFestivalsTool
from app.tools.holiday import GetHolidaysTool, HolidayQuery
from app.tools.municipal_parking import GetMunicipalParkingTool, MunicipalParkingQuery
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
from app.tools.realtime_citydata import GetRealtimeCityDataTool, RealtimeCityDataQuery
from app.tools.realtime_commercial import (
    GetRealtimeCommercialTool,
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
# TRAVEL_TIME은 travel_* 수단별 값을 여기서 채우지 않는다(A가 실측 호출 후 채운다)
# — 대신 실측에 필요한 좌표(latitude)가 있는지로 판정한다.
_COMPARE_CRITERIA_FIELDS: dict[CompareCriteria, str] = {
    CompareCriteria.TIME: "remaining_minutes",
    CompareCriteria.TRAVEL_TIME: "latitude",
}

# INFO 행사 응답에 싣는 최대 건수. 챗봇 말풍선 한 번에 읽히는 분량으로 제한한다.
INFO_EVENT_RESULT_LIMIT = 5
_CURRENT_ACTIVITY_MARKERS = ("지금", "현재", "오늘")
_COMMERCIAL_CATEGORY_MARKERS = ("카페", "커피", "제과", "패스트푸드")
_REALTIME_CITYDATA_QUESTION_TYPES = {
    "realtime_parking",
    "realtime_subway",
    "realtime_bus",
    "realtime_event",
    "realtime_traffic",
}
_PUBLIC_PARKING_QUESTION_TYPE = "realtime_public_parking"
_CITYDATA_SOURCE_URL = "https://data.seoul.go.kr/dataList/OA-21285/F/1/datasetView.do"
_MUNICIPAL_PARKING_SOURCE_URL = "https://data.seoul.go.kr/dataList/OA-21709/S/1/datasetView.do"

logger = logging.getLogger(__name__)

# 인구 목록(POPULATION_AREAS)에 있는 이름 집합. 낡음 감지 probe가 "서울시 API는
# 지원하는데 우리 목록엔 없다"를 판정하는 기준이다.
_POPULATION_AREA_NAMES = {area.name for area in POPULATION_AREAS}

# 같은 장소 이름을 반복 probe하지 않기 위한 프로세스 메모리 캐시. 값은 "서울시
# API가 실제로 지원하는지" 여부다. 재시작하면 비워지는데, probe는 그 정도로도
# 충분한 저비용 모니터링이라 별도 TTL·영속화를 두지 않는다(TP-141/D-084).
_stale_area_probe_cache: dict[str, bool] = {}


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
    # 서울시 실시간 도시데이터의 지역·업종별 상권 활동 조회 전용.
    realtime_commercial: GetRealtimeCommercialTool | None = None
    realtime_citydata: GetRealtimeCityDataTool | None = None
    # 명시적 공영/시영주차장 질문은 도시데이터의 근접 목록이 아니라 구 단위
    # GetParkingInfo를 쓴다. 좌표 카탈로그는 한 번 지오코딩한 정적 값만 보관한다.
    municipal_parking: GetMunicipalParkingTool | None = None
    municipal_parking_catalog: MunicipalParkingCatalogRepository | None = None
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
        if not (MIN_RECOMMENDATION_LIMIT <= candidate_limit <= MAX_RECOMMENDATION_CANDIDATE_LIMIT):
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
                ResolveLocationQuery(location_query, purpose=LocationPurpose.SEARCH_CENTER)
            )
            if location_query is not None
            else _gps_location_result(request, self._clock())
        )
        if location_result.status is not ToolStatus.SUCCESS or location_result.location is None:
            return assemble_agent_context_response(
                ContextAssemblyInput(
                    request=request,
                    location_result=location_result,
                    # 기준점을 못 풀어 추천이 성립하지 않는 응답이다. 발화 위치를 따로
                    # 지오코딩하는 비용은 추천이 나가는 요청에서만 치르고, 여기서는
                    # 기기 GPS만 싣는다(TP-109까지의 동작 그대로).
                    user_location_result=self._device_gps_location(request),
                ),
                rule_versions=_rule_versions(),
            )

        visit_at = _as_kst(self._clock())
        location = location_result.location
        user_location_task = asyncio.create_task(
            self._resolve_user_location(
                request,
                location_query=location_query,
                location_result=location_result,
            )
        )
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
                self._tools.holidays.execute(HolidayQuery(year=visit_at.year, month=visit_at.month))
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
        user_location_result = await user_location_task

        return assemble_agent_context_response(
            ContextAssemblyInput(
                request=request,
                location_result=location_result,
                user_location_result=user_location_result,
                weather_result=weather_result,
                places_result=places_result,
                holidays_result=holidays_result,
                weather_requested=execution_plan.requires(ContextTool.GET_WEATHER),
                holidays_requested=execution_plan.requires(ContextTool.GET_HOLIDAYS),
            ),
            rule_versions=_rule_versions(),
        )

    async def _resolve_user_location(
        self,
        request: AgentContextRequest,
        *,
        location_query: str | None,
        location_result: ResolveLocationResult,
    ) -> ResolveLocationResult | None:
        """사용자가 있는 곳을 해석한다. 발화(current_location)가 기기 GPS보다 앞선다.

        기준점(`location`)이 search_center → current_location → GPS 순인 것과 같은
        우선순위다. 기준점만 발화를 앞세우고 사용자 위치만 GPS를 앞세우면 한 요청
        안에서 두 좌표가 서로 다른 규칙으로 정해진다(TP-112).

        `state/field_spec.py`의 "v0.3에서 current_location의 필수 지위가
        api_context.gps_location으로 이관되었다"는 **위치를 하나도 모를 때 무엇이
        빈칸을 채우는가**에 대한 것이지, 둘 다 있을 때 무엇이 이기는가가 아니다.
        낡은 발화 위치를 버리는 것은 A의 몫이다 — 되묻기의 "다른 지역" 선택이
        current_location을 명시적으로 지운다(agent_runtime.py).

        발화를 앞세우지 않으면 GPS가 없을 때 사용자 위치가 통째로 사라진다.
        `"지금 서대문역인데 혜화역 근처"`에서 location_query가 혜화역으로 정해지면
        서대문역은 지오코딩조차 되지 않기 때문이다(GPS 만료는 TTL 1시간이라 흔하다).
        """

        spoken = request.conditions.current_location
        if spoken is None:
            return self._device_gps_location(request)
        if spoken == location_query:
            # 기준점이 이미 같은 문자열을 푼 결과다. 같은 질의를 두 번 지오코딩하지
            # 않는다 — search_center가 없거나 발화와 같을 때가 여기 해당한다.
            return location_result
        result = await self._tools.location.execute(
            # 기준점과 같은 이유로 좌표만 있으면 된다. PLACE_IDENTITY를 쓰면 종로구
            # 코퍼스 밖 이름("서대문역")에서 저장소 조회만 헛돈다(resolve_location.py).
            ResolveLocationQuery(spoken, purpose=LocationPurpose.SEARCH_CENTER)
        )
        if result.status is ToolStatus.SUCCESS and result.location is not None:
            return result
        # 발화를 못 풀면 기기 GPS로 내려간다. D-042(Real 실패 시 Fake로 자동 전환하지
        # 않는다)와는 다른 상황이다 — 지어낸 값이 아니라 같은 질문에 대한 다른 사실이다.
        return self._device_gps_location(request)

    def _device_gps_location(self, request: AgentContextRequest) -> ResolveLocationResult | None:
        """기기 GPS만으로 사용자 위치 결과를 만든다. GPS가 없으면 그 사실대로 None."""

        if request.gps_location is None:
            return None
        return _gps_location_result(request, self._clock())

    async def fetch_compare_context(
        self,
        request: CompareContextRequest,
    ) -> CompareContextResponse:
        """비교 후보의 place_id를 장소명으로 해석해 비교 사실을 조립한다.

        수치(거리·남은 운영시간·실내외)는 B가 보관한 추천 시점 스냅샷이므로 다시
        조회하지 않고 그대로 통과시킨다 — 사용자가 카드에서 본 값과 어긋나면 안 된다
        (D-050, docs/design/int-04-compare.md §13). C는 우열을 판정하지 않는다.
        그건 A의 LLM 요약 몫이다.

        좌표(latitude/longitude)는 예외다(TRAVEL_TIME, 2026-08-21) — 카드 조회
        시점에 항상 함께 실어 보낸다. 스냅샷이 아니라 "지금 이 장소가 어디 있는지"
        라는 불변에 가까운 사실이라 D-050이 막으려던 문제(스냅샷과 최신값의 어긋남)
        와 무관하고, A가 이 좌표로 실측 경로를 조회할 때만 쓴다 — C는 여기서도
        거리·시간을 계산하거나 우열을 매기지 않는다.
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
        card_result = await card_tool.get_cards([candidate.place_id for candidate in candidates])
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

        cards_by_id = {card.content_id: card for card in card_result.cards if card.name is not None}
        items = [
            ComparisonItem(
                place_id=candidate.place_id,
                place_name=cards_by_id[candidate.place_id].name,
                rank=candidate.rank,
                distance_km=candidate.distance_km,
                remaining_minutes=candidate.remaining_minutes,
                environment_type=candidate.environment_type,
                # TRAVEL_TIME 전용 — 사실 그대로 전달만 한다(우열 판정은 A 몫).
                latitude=cards_by_id[candidate.place_id].latitude,
                longitude=cards_by_id[candidate.place_id].longitude,
            )
            for candidate in candidates
            if candidate.place_id in cards_by_id
        ]
        missing = [
            candidate.place_id for candidate in candidates if candidate.place_id not in cards_by_id
        ]

        # 이름을 못 찾은 후보는 빼고 진행하되, 남은 수가 비교를 이루지 못하면
        # no_data다 — 한 곳만 남겨두고 "비교"라고 답할 수는 없다.
        if len(items) < _MIN_COMPARE_ITEMS:
            return _compare_error_response(request, status="no_data", missing_place_ids=missing)

        # 기준에 해당하는 값이 전원 비어 있으면 비교할 사실이 없다. 그대로 넘기면
        # A의 LLM이 빈 값에서 뭔가 지어낼 여지가 생긴다(프롬프트가 "C가 준 값만
        # 쓰라"고 제한하는 취지와도 어긋난다).
        field = _COMPARE_CRITERIA_FIELDS.get(request.criteria)
        if field is not None and all(getattr(item, field) is None for item in items):
            return _compare_error_response(request, status="no_data", missing_place_ids=missing)

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
        - ``event`` → 주변 행사 조회
        - ``realtime_commercial`` → 가까운 서울시 제공 상권의 카페 활동 조회
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

        current_activity_candidate = _is_current_activity_candidate(request)
        current_population_candidate = _is_current_population_candidate(request, self._clock())
        parking_district = (
            _supported_district_name(place_name) if request.question_type == "parking" else None
        )
        is_realtime_citydata_purpose = (
            request.question_type == "realtime_commercial"
            or request.question_type == _PUBLIC_PARKING_QUESTION_TYPE
            or request.question_type in _REALTIME_CITYDATA_QUESTION_TYPES
            or parking_district is not None
        )
        location_purpose = (
            LocationPurpose.REALTIME_CITYDATA
            if is_realtime_citydata_purpose
            else LocationPurpose.PLACE_IDENTITY
        )
        location_result = await self._tools.location.execute(
            # INFO는 좌표가 아니라 "집중률 매핑이 걸린 그 장소"를 확정해야 한다(D-043).
            # 단, 실시간 상권은 서울시 82개 제공 지역을 별도로 쓰므로 종로구 추천
            # 범위를 위치 해석 단계에 적용하지 않는다.
            #
            # 오늘 날짜 혼잡 질문은 저장소를 먼저 봐야 명동성당·아시아프처럼
            # TourAPI 코퍼스엔 있지만 Naver 지역 검색·Geocoding으론 못 찾는
            # 장소가 산다(TP-171) — 그래서 PLACE_IDENTITY를 쓴다. 다만 강남역·
            # 여의도처럼 지원 16개 구 밖의 실시간 인구 허브도 여전히 답해야
            # 하므로(실측: 121곳 중 49곳·82곳 중 32곳이 지원 구 밖), 지역 제한만
            # 명시적으로 끈다 — PLACE_IDENTITY의 기본 지역 제한과 저장소 우선
            # 순위는 원래 서로 다른 이유로 묶여 있던 게 아니다.
            ResolveLocationQuery(
                # "종로 주차장 정보"의 종로는 특정 관광지가 아니라 구 단위 범위다.
                # 지역 검색 후보를 되묻지 말고 행정구역 좌표로 확정해 해당 구의
                # 공영주차장 최신 현황을 찾는다.
                f"서울특별시 {parking_district}" if parking_district else place_name,
                purpose=location_purpose,
                enforce_service_area=(False if current_population_candidate else None),
                skip_local_search=parking_district is not None,
            )
        )
        if location_result.status is ToolStatus.NO_DATA:
            cause = location_result.error.cause if location_result.error else None
            if cause == "ambiguous_location":
                candidate_names = parse_candidate_names(
                    location_result.error.details.get("candidate_names", "")
                    if location_result.error
                    else ""
                )
                filtered_candidates = await self._filter_info_place_candidates(
                    candidate_names,
                    question_type=request.question_type,
                    location_purpose=location_purpose,
                    is_realtime_citydata_purpose=is_realtime_citydata_purpose,
                    current_population_candidate=current_population_candidate,
                )
                return InfoContextResponse(
                    request_id=request.request_id,
                    status="needs_clarification",
                    clarification=Clarification(
                        code="place_ambiguous",
                        missing_fields=[],
                        # 걸러서 하나도 안 남으면 거르기 전 원본을 그대로 보여준다 —
                        # 버튼 없는 것보다 낫다(RECOMMEND의 location_ambiguous와 같은
                        # 원칙).
                        candidates=filtered_candidates or candidate_names,
                    ),
                )
            if request.question_type == "concentration":
                # 위치 해석이 완전히 실패해도 집중률만으로는 답할 수 있는 경우가
                # 있다(TP-171, 사용자 결정: "실시간 혼잡도가 없으면 집중률이라도").
                # 좌표가 없어 D-036 인근 대체(_fetch_info_concentration_fallback)는
                # 못 쓰므로, 이름이 매핑에 정확히 하나만 일치할 때만 시도한다.
                return await self._fetch_concentration_by_name_only(
                    request,
                    reference_date=_info_reference_date(request.visit_time, self._clock()),
                    provider_metadata=(location_result.provider_metadata,),
                )
            return _info_no_data_response(request, location_result.provider_metadata)
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

        if request.question_type == "realtime_commercial" or (
            request.question_type == "concentration"
            and current_activity_candidate
            and _is_commercial_place_category(resolved_location.place_category)
        ):
            return await self._fetch_realtime_commercial_info(
                request,
                place_name=place_name,
                resolved_location=resolved_location,
                location_metadata=location_result.provider_metadata,
            )
        if current_population_candidate:
            return await self._fetch_realtime_population_or_concentration_info(
                request,
                place_name=place_name,
                resolved_location=resolved_location,
                location_metadata=location_result.provider_metadata,
            )
        if request.question_type == _PUBLIC_PARKING_QUESTION_TYPE:
            return await self._fetch_realtime_public_parking_info(
                request,
                place_name=place_name,
                resolved_location=resolved_location,
                location_metadata=location_result.provider_metadata,
            )
        if request.question_type in _REALTIME_CITYDATA_QUESTION_TYPES:
            return await self._fetch_realtime_city_info(
                request,
                place_name=place_name,
                resolved_location=resolved_location,
                location_metadata=location_result.provider_metadata,
            )

        if request.question_type == "parking" and parking_district is not None:
            return await self._fetch_realtime_public_parking_info(
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

    async def _filter_info_place_candidates(
        self,
        candidate_names: list[str],
        *,
        question_type: str,
        location_purpose: LocationPurpose,
        is_realtime_citydata_purpose: bool,
        current_population_candidate: bool,
    ) -> list[str]:
        """되묻기 후보 중 이번 질문 유형의 정보가 실제로 조회 가능한 곳만 남긴다.

        후보 이름마다 다시 한번 개별 해석해 identity/좌표를 얻은 뒤 판정한다 —
        resolve_location.py는 question_type을 모르므로(좌표/신원 해석만 책임진다)
        가용성 판정은 이 계층에서만 한다. 재해석 자체가 또 애매하게 나오면
        (예: DB에 동명 타이틀 2건) "조회 불가"로 단정하지 않고 후보를 그대로
        남긴다 — 확실히 실패했을 때만 버린다. 호출부가 결과가 비면 원본 목록으로
        되돌린다.
        """
        kept: list[str] = []
        for name in candidate_names:
            result = await self._tools.location.execute(
                ResolveLocationQuery(name, purpose=location_purpose)
            )
            if result.status is ToolStatus.NO_DATA:
                kept.append(name)
                continue
            if result.status is not ToolStatus.SUCCESS or result.location is None:
                continue
            if _place_candidate_has_data(
                result.location,
                question_type=question_type,
                is_realtime_citydata_purpose=is_realtime_citydata_purpose,
                current_population_candidate=current_population_candidate,
            ):
                kept.append(name)
        return kept

    async def _fetch_realtime_population_or_concentration_info(
        self,
        request: InfoContextRequest,
        *,
        place_name: str,
        resolved_location: ResolvedLocation,
        location_metadata: tuple[ProviderMetadata, ...],
    ) -> InfoContextResponse:
        """현재형 혼잡 질문은 가까운 실시간 인구 값을 먼저 확인한다.

        서울시가 제공하는 지역 중심점이 1km 밖이거나 인구 객체가 비어 있으면,
        현재값인 것처럼 꾸며내지 않고 기존 관광지 일 단위 예측으로 낮춘다. 반면
        서울시 API 자체 장애는 실시간 조회 실패로 드러낸다.
        """

        nearest = select_nearest_population_area(
            latitude=resolved_location.latitude,
            longitude=resolved_location.longitude,
        )
        if nearest is None:
            return await self._fetch_concentration_info(
                request,
                place_name=place_name,
                resolved_location=resolved_location,
                location_metadata=location_metadata,
            )

        tool = self._tools.realtime_citydata
        if tool is None:
            return _info_error_response(
                request,
                status="unavailable",
                error=ContextError(
                    code="realtime_population_not_configured",
                    message="실시간 인구 혼잡도 조회 기능을 사용할 수 없습니다.",
                    retryable=False,
                ),
                provider_metadata=(location_metadata,),
            )

        area, distance_km = nearest
        tool_result = await tool.execute(RealtimeCityDataQuery(area.code))
        if tool_result.status is ToolStatus.UNAVAILABLE:
            return _info_error_response(
                request,
                status="unavailable",
                error=_context_error_from_tool(
                    tool_result.error,
                    fallback_code="realtime_population_unavailable",
                    fallback_message="실시간 인구 혼잡도를 가져오지 못했습니다.",
                    retryable=True,
                ),
                provider_metadata=(location_metadata, tool_result.provider_metadata),
            )

        population = tool_result.citydata.population if tool_result.citydata is not None else None
        if (
            tool_result.status is ToolStatus.NO_DATA
            or population is None
            or population.current_congestion_level is None
        ):
            return await self._fetch_concentration_info(
                request,
                place_name=place_name,
                resolved_location=resolved_location,
                location_metadata=(*location_metadata, *tool_result.provider_metadata),
            )

        stale_area_detected = await self._probe_stale_population_area(
            place_name=place_name,
            matched_area_name=area.name,
            matched_area_distance_km=distance_km,
            tool=tool,
        )

        return InfoContextResponse(
            request_id=request.request_id,
            status="success",
            result=RealtimePopulationInfoResult(
                status="success",
                requested_place_name=place_name,
                resolved_place_name=resolved_location.resolved_name,
                area_name=population.area_name or area.name,
                area_code=population.area_code or area.code,
                proxy_distance_km=distance_km,
                current_congestion_level=population.current_congestion_level,
                current_congestion_message=population.current_congestion_message,
                observed_at=population.observed_at,
                population_forecasts=[
                    PopulationForecastInfo(
                        forecast_at=slot.forecast_at,
                        congestion_level=slot.congestion_level,
                        population_min=slot.population_min,
                        population_max=slot.population_max,
                    )
                    for slot in population.forecasts
                ]
                if population.forecast_available
                else [],
                source_url=_CITYDATA_SOURCE_URL,
                map_url=_seoul_realtime_map_url(area),
                stale_area_detected=stale_area_detected,
            ),
            metadata=_info_response_metadata(location_metadata, tool_result.provider_metadata),
        )

    async def _probe_stale_population_area(
        self,
        *,
        place_name: str,
        matched_area_name: str,
        matched_area_distance_km: float,
        tool: GetRealtimeCityDataTool,
    ) -> StaleAreaProbeDebug | None:
        """우리 121곳 목록엔 없지만 서울시 API는 지원하는 지역을 조용히 찾는다.

        응답(추천 판정)에는 절대 개입하지 않는다 — 이 메서드는 항상 감사용
        신호만 만들거나 아무것도 하지 않는다(TP-141/D-084). 탐색 실패는 이유를
        따지지 않고 "신호 없음"으로 취급한다 — 서울시 API 자체 장애와 미지원
        지역을 구분하려 들면 이 probe가 본 요청의 실패 판정에 영향을 줄 수 있다.
        """

        if not settings.seoul_area_staleness_probe_enabled:
            return None
        if matched_area_name == place_name:
            # 대체가 안 일어났다 — place_name이 이미 우리 목록에 있다는 뜻이라
            # 확인할 게 없다.
            return None
        if place_name in _POPULATION_AREA_NAMES:
            # 좌표 기준 최근접은 다른 지역으로 잡혔지만(드문 경우), place_name
            # 자체는 이미 우리 목록에 있다 — probe로 확인할 새 사실이 없다.
            return None

        cached = _stale_area_probe_cache.get(place_name)
        if cached is None:
            try:
                probe_result = await tool.execute(RealtimeCityDataQuery(place_name))
            except Exception:  # noqa: BLE001 - probe 실패가 본 요청에 번지면 안 된다.
                logger.warning("낡음 감지 probe 호출 실패: %s", place_name, exc_info=True)
                _stale_area_probe_cache[place_name] = False
                return None
            supported = (
                probe_result.status is not ToolStatus.UNAVAILABLE
                and probe_result.citydata is not None
                and probe_result.citydata.population is not None
            )
            _stale_area_probe_cache[place_name] = supported
            cached = supported

        if not cached:
            return None

        logger.warning(
            "서울시 실시간 도시데이터가 지원하는데 우리 121곳 목록엔 없는 지역: %s",
            place_name,
        )
        return StaleAreaProbeDebug(
            probed_area_name=place_name,
            matched_area_name=matched_area_name,
            matched_area_distance_km=matched_area_distance_km,
        )

    async def _fetch_realtime_commercial_info(
        self,
        request: InfoContextRequest,
        *,
        place_name: str,
        resolved_location: ResolvedLocation,
        location_metadata: tuple[ProviderMetadata, ...],
    ) -> InfoContextResponse:
        """개별 매장 대신 최근접 서울시 제공 상권의 카페 활동을 안내한다."""

        nearest = select_nearest_commercial_area(
            latitude=resolved_location.latitude,
            longitude=resolved_location.longitude,
        )
        if nearest is None:
            return _info_error_response(
                request,
                status="unsupported",
                error=ContextError(
                    code="realtime_commercial_unsupported_region",
                    message="서울시 실시간 상권 데이터 제공 지역이 아닙니다.",
                    retryable=False,
                ),
                provider_metadata=(location_metadata,),
            )

        area, distance_km = nearest
        tool = self._tools.realtime_citydata
        if tool is None:
            return _info_error_response(
                request,
                status="unavailable",
                error=ContextError(
                    code="realtime_commercial_not_configured",
                    message="실시간 상권 조회 기능을 사용할 수 없습니다.",
                    retryable=False,
                ),
                provider_metadata=(location_metadata,),
            )

        tool_result = await tool.execute(RealtimeCityDataQuery(area.code))
        if tool_result.status is ToolStatus.UNAVAILABLE:
            return _info_error_response(
                request,
                status="unavailable",
                error=_context_error_from_tool(
                    tool_result.error,
                    fallback_code="realtime_commercial_unavailable",
                    fallback_message="실시간 상권 정보를 가져오지 못했습니다.",
                    retryable=True,
                ),
                provider_metadata=(location_metadata, tool_result.provider_metadata),
            )

        citydata = tool_result.citydata
        commercial = citydata.commercial if citydata is not None else None
        population = citydata.population if citydata is not None else None
        selected_category = _select_commercial_category(
            commercial.categories if commercial is not None else (),
            request.specific_question,
        )
        if tool_result.status is ToolStatus.NO_DATA or commercial is None:
            return InfoContextResponse(
                request_id=request.request_id,
                status="no_data",
                result=RealtimeCommercialInfoResult(
                    status="no_data",
                    requested_place_name=place_name,
                    resolved_place_name=resolved_location.resolved_name,
                    area_name=area.name,
                    area_code=area.code,
                    proxy_distance_km=distance_km,
                ),
                metadata=_info_response_metadata(location_metadata, tool_result.provider_metadata),
            )

        if selected_category is not None:
            category_label, commercial_level = selected_category
            commercial_scope = "cafe_category"
        else:
            # 실 API는 조회 시점에 대표 업종 한 건만 내려줄 수 있다. 카페 세부 업종이
            # 빠졌다고 지역 전체 활동값까지 버리면 "용리단길 카페" 같은 질문이 매번
            # no_data가 된다. 단, 카페 값처럼 보이지 않도록 응답 범위를 명시한다.
            category_label = None
            commercial_level = commercial.area_activity_level
            commercial_scope = "area_overall"
        if commercial_level is None:
            return InfoContextResponse(
                request_id=request.request_id,
                status="no_data",
                result=RealtimeCommercialInfoResult(
                    status="no_data",
                    requested_place_name=place_name,
                    resolved_place_name=resolved_location.resolved_name,
                    area_name=area.name,
                    area_code=area.code,
                    proxy_distance_km=distance_km,
                ),
                metadata=_info_response_metadata(location_metadata, tool_result.provider_metadata),
            )
        return InfoContextResponse(
            request_id=request.request_id,
            status="success",
            result=RealtimeCommercialInfoResult(
                status="success",
                requested_place_name=place_name,
                resolved_place_name=resolved_location.resolved_name,
                area_name=commercial.area_name or area.name,
                area_code=commercial.area_code or area.code,
                proxy_distance_km=distance_km,
                category_label=category_label,
                commercial_level=commercial_level,
                commercial_scope=commercial_scope,
                observed_at=commercial.observed_at,
                population_current_level=(
                    population.current_congestion_level if population is not None else None
                ),
                population_observed_at=population.observed_at if population is not None else None,
                population_forecasts=(
                    [
                        PopulationForecastInfo(
                            forecast_at=slot.forecast_at,
                            congestion_level=slot.congestion_level,
                            population_min=slot.population_min,
                            population_max=slot.population_max,
                        )
                        for slot in population.forecasts
                    ]
                    if population is not None and population.forecast_available
                    else []
                ),
                detail_items=_to_commercial_detail_items(
                    commercial.categories,
                    area_activity_level=commercial.area_activity_level,
                ),
                source_url=_CITYDATA_SOURCE_URL,
            ),
            metadata=_info_response_metadata(location_metadata, tool_result.provider_metadata),
        )

    async def _fetch_realtime_public_parking_info(
        self,
        request: InfoContextRequest,
        *,
        place_name: str,
        resolved_location: ResolvedLocation,
        location_metadata: tuple[ProviderMetadata, ...],
    ) -> InfoContextResponse:
        """공영/시영주차장을 명시한 질문에 구 단위 최신 대수를 돌려준다.

        GetParkingInfo에는 좌표가 없어 카탈로그가 있으면 거리순으로, 아직 동기화되지
        않았으면 같은 구의 실시간 수치가 있는 항목 우선으로 보인다. 이 fallback은
        주소를 요청 중에 지오코딩하지 않으므로 API 비용·응답시간을 늘리지 않는다.
        """

        district = _district_from_address(resolved_location.address)
        if district is None:
            return _realtime_city_info_no_data_response(
                request,
                place_name=place_name,
                resolved_location=resolved_location,
                provider_metadata=location_metadata,
            )
        if self._tools.municipal_parking is None:
            return _info_error_response(
                request,
                status="unavailable",
                error=ContextError(
                    code="municipal_parking_unavailable",
                    message="공영주차장 실시간 조회 도구가 설정되지 않았습니다.",
                    retryable=False,
                ),
                provider_metadata=location_metadata,
            )
        tool_result = await self._tools.municipal_parking.execute(MunicipalParkingQuery(district))
        if tool_result.status is ToolStatus.UNAVAILABLE:
            return _info_error_response(
                request,
                status="unavailable",
                error=_context_error_from_tool(
                    tool_result.error,
                    fallback_code="municipal_parking_unavailable",
                    fallback_message="공영주차장 실시간 정보를 가져오지 못했습니다.",
                    retryable=True,
                ),
                provider_metadata=(location_metadata, tool_result.provider_metadata),
            )

        catalog = {}
        if self._tools.municipal_parking_catalog is not None:
            try:
                catalog = await self._tools.municipal_parking_catalog.find_by_codes(
                    [lot.code for lot in tool_result.lots]
                )
            except AppError:
                # 좌표 카탈로그 장애가 공영주차장 실측 수치까지 막으면 안 된다. 거리만
                # 생략하고 구 단위 목록으로 안전하게 계속한다.
                logger.warning("공영주차장 좌표 카탈로그 조회 실패", exc_info=True)

        entries = [
            _municipal_status_to_realtime_lot(lot, catalog.get(lot.code))
            for lot in tool_result.lots
            if lot.is_live and lot.current_parked_count is not None
        ]
        entries.sort(
            key=lambda item: (
                0 if item.available_spaces is not None else 1,
                _parking_distance_or_inf(resolved_location, item),
                -(item.available_spaces or -1),
            )
        )
        fields = {f"[공영] {item.name}": _format_realtime_parking(item) for item in entries[:5]}
        observed_at = next((item.observed_at for item in entries if item.observed_at), None)
        return InfoContextResponse(
            request_id=request.request_id,
            status="success" if fields else "no_data",
            result=RealtimeCityInfoResult(
                status="success" if fields else "no_data",
                question_type="realtime_public_parking",
                requested_place_name=place_name,
                resolved_place_name=resolved_location.resolved_name,
                area_name=district,
                observed_at=observed_at,
                fields=fields,
                detail_items=_to_parking_detail_items(
                    entries[:15],
                    latitude=resolved_location.latitude,
                    longitude=resolved_location.longitude,
                ),
                source_url=_MUNICIPAL_PARKING_SOURCE_URL,
            ),
            metadata=_info_response_metadata(location_metadata, tool_result.provider_metadata),
        )

    async def _fetch_realtime_city_info(
        self,
        request: InfoContextRequest,
        *,
        place_name: str,
        resolved_location: ResolvedLocation,
        location_metadata: tuple[ProviderMetadata, ...],
    ) -> InfoContextResponse:
        """서울시 citydata의 주차·지하철·버스·행사 객체를 INFO 카드로 정규화한다.

        citydata(통합)는 상권 82개보다 넓은 121개 지역을 지원하므로(경복궁·한강공원
        등) 인구 목록으로 조회한다. 거리 허용치는 기존 상권 조회와 같은 2km를
        유지한다 — 이 조회는 인구 혼잡도처럼 "지금 여기" 정확도가 중요한 값이
        아니라 주차·지하철 같은 주변 정보라 더 넓게 대체해도 된다.
        """

        nearest = select_nearest_population_area(
            latitude=resolved_location.latitude,
            longitude=resolved_location.longitude,
            max_distance_km=COMMERCIAL_AREA_PROXY_MAX_DISTANCE_KM,
        )
        if nearest is None:
            return _realtime_city_info_no_data_response(
                request,
                place_name=place_name,
                resolved_location=resolved_location,
                provider_metadata=location_metadata,
            )
        if self._tools.realtime_citydata is None:
            return _info_error_response(
                request,
                status="unavailable",
                error=ContextError(
                    code="realtime_citydata_unavailable",
                    message="실시간 도시데이터 조회 도구가 설정되지 않았습니다.",
                    retryable=False,
                ),
                provider_metadata=(location_metadata,),
            )
        area, _ = nearest
        tool_result = await self._tools.realtime_citydata.execute(RealtimeCityDataQuery(area.code))
        if tool_result.status is ToolStatus.UNAVAILABLE or tool_result.citydata is None:
            return _info_error_response(
                request,
                status="unavailable",
                error=_context_error_from_tool(
                    tool_result.error,
                    fallback_code="realtime_citydata_unavailable",
                    fallback_message="실시간 도시데이터를 가져오지 못했습니다.",
                    retryable=True,
                ),
                provider_metadata=(location_metadata, tool_result.provider_metadata),
            )
        citydata = tool_result.citydata
        question_type = request.question_type
        detail_items: list[RealtimeInfoDetailItem]
        if question_type == "realtime_parking":
            all_entries = sorted(
                citydata.parking_lots,
                key=lambda item: haversine_km(
                    resolved_location.latitude,
                    resolved_location.longitude,
                    item.latitude,
                    item.longitude,
                )
                if item.latitude is not None and item.longitude is not None
                else float("inf"),
            )
            # 공영/민영으로 나눠 보여준다 — 한쪽이 비어도(예: 공원 주변은 민영이
            # 없거나, 역세권은 공영이 없는 경우) 있는 쪽만으로 정상 응답한다.
            grouped_lots: dict[str, list[RealtimeParkingLot]] = {
                "공영": [],
                "민영": [],
                "기타": [],
            }
            for item in all_entries:
                grouped_lots[item.lot_type or "기타"].append(item)
            # 같은 공영/민영 묶음 안에서는 실시간 대수 제공 항목을 먼저 보여준다.
            # 기존에는 단순 거리순이라 실제 잔여 여부가 있는 주차장이 4번째 이후로
            # 밀려 카드에 안 나오는 문제가 있었다.
            for lots in grouped_lots.values():
                lots.sort(
                    key=lambda item: (
                        (
                            0
                            if item.current_available and item.current_parked_count is not None
                            else 1
                        ),
                        _parking_distance_or_inf(resolved_location, item),
                    )
                )
            entries: list[RealtimeParkingLot] = []
            fields = {}
            for label in ("공영", "민영", "기타"):
                for item in grouped_lots[label][:3]:
                    entries.append(item)
                    key = item.name if label == "기타" else f"[{label}] {item.name}"
                    fields[key] = _format_realtime_parking(item)
            observed_at = next((item.observed_at for item in entries if item.observed_at), None)
            detail_items = _to_parking_detail_items(
                grouped_lots["공영"][:10] + grouped_lots["민영"][:10] + grouped_lots["기타"][:10],
                latitude=resolved_location.latitude,
                longitude=resolved_location.longitude,
            )
        elif question_type == "realtime_subway":
            all_entries = citydata.subway_arrivals
            # 역+호선 단위로 묶어 서로 다른 방향을 우선 살린다. 예전에는
            # all_entries[:4]로 원본 순서대로만 잘라 같은 역의 두 방향(상행/하행)이
            # 겹치면 한쪽이 밀려났다.
            by_station_line: dict[str, list[RealtimeSubwayArrival]] = {}
            station_line_order: list[str] = []
            for item in all_entries:
                key = f"{item.station_name}|{item.line or ''}"
                if key not in by_station_line:
                    by_station_line[key] = []
                    station_line_order.append(key)
                by_station_line[key].append(item)
            entries = []
            for key in station_line_order:
                entries.extend(by_station_line[key][:2])  # 방향은 최대 2개(상/하행)
                if len(entries) >= 4:
                    break
            fields = {
                _subway_field_key(item): _format_subway_arrival(item) for item in entries
            }
            observed_at = None
            detail_items = _to_subway_detail_items(all_entries[:12])
        elif question_type == "realtime_bus":
            all_entries = citydata.bus_stops
            entries = all_entries[:5]
            fields = {
                item.name: f"정류장 번호 {item.ars_id}" if item.ars_id else "주변 정류장"
                for item in entries
            }
            observed_at = None
            detail_items = _to_bus_detail_items(all_entries[:12])
        elif question_type == "realtime_traffic":
            traffic = citydata.road_traffic
            fields = (
                {
                    key: value
                    for key, value in {
                        "도로소통 단계": traffic.level,
                        "평균 주행속도": (
                            f"{traffic.average_speed_kmh:.0f}km/h"
                            if traffic.average_speed_kmh is not None
                            else None
                        ),
                        "안내": traffic.message,
                    }.items()
                    if value is not None
                }
                if traffic is not None
                else {}
            )
            observed_at = traffic.observed_at if traffic is not None else None
            detail_items = (
                [
                    RealtimeInfoDetailItem(
                        title="도로소통 안내",
                        subtitle=traffic.level,
                        details={"안내": traffic.message} if traffic.message else {},
                    )
                ]
                if traffic is not None and traffic.message is not None
                else []
            )
        else:
            all_entries = citydata.events
            entries = all_entries[:5]
            fields = {
                item.name: " · ".join(part for part in (item.period, item.place) if part)
                for item in entries
            }
            observed_at = None
            detail_items = _to_event_detail_items(all_entries[:10])
        result_status: Literal["success", "no_data", "unavailable"] = (
            "success" if fields else "no_data"
        )
        return InfoContextResponse(
            request_id=request.request_id,
            status="success" if fields else "no_data",
            result=RealtimeCityInfoResult(
                status=result_status,
                question_type=cast(
                    Literal[
                        "realtime_parking",
                        "realtime_public_parking",
                        "realtime_subway",
                        "realtime_bus",
                        "realtime_event",
                        "realtime_traffic",
                    ],
                    question_type,
                ),
                requested_place_name=place_name,
                resolved_place_name=resolved_location.resolved_name,
                area_name=area.name,
                observed_at=observed_at,
                fields=fields,
                detail_items=detail_items,
                source_url=_CITYDATA_SOURCE_URL,
            ),
            metadata=_info_response_metadata(location_metadata, tool_result.provider_metadata),
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
        # 조회할 구는 해석된 장소의 것을 쓴다. concentration_name이 있다는 건 저장소
        # 에서 푼 장소라는 뜻이라 district_code도 함께 온다.
        signgu_code = concentration_signgu_code(resolved_location.district_code)
        if signgu_code is None:
            # 구를 모르면 직접 조회를 하지 않는다. 종로구로 대신 물으면 다른 구
            # 장소는 언제나 0건이라, 틀린 조회가 "정보 없음"으로 보인다. 인근
            # 대체 경로는 그대로 탄다 - 매핑 없는 이름일 때와 같은 처리다.
            return await self._fetch_info_concentration_fallback(
                request,
                latitude=resolved_location.latitude,
                longitude=resolved_location.longitude,
                reference_date=reference_date,
                concentration_tool=concentration_tool,
                provider_metadata=(location_metadata,),
            )
        concentration_result = await execute_concentration_by_search_keys(
            concentration_tool,
            search_keys=resolved_location.concentration_search_keys,
            canonical_name=concentration_place_name,
            signgu_code=signgu_code,
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
                forecasts=_to_concentration_forecast_infos(
                    concentration_result.concentration,
                    candidate_name=concentration_place_name,
                    start_date=reference_date,
                ),
            ),
            metadata=_info_response_metadata(
                location_metadata,
                concentration_result.provider_metadata,
            ),
        )

    async def _fetch_concentration_by_name_only(
        self,
        request: InfoContextRequest,
        *,
        reference_date: date,
        provider_metadata: tuple[tuple[ProviderMetadata, ...], ...],
    ) -> InfoContextResponse:
        """위치 해석이 완전히 실패했을 때 이름만으로 집중률 매핑을 대조한다(TP-171).

        좌표가 없어 D-036 인근 대체(``_fetch_info_concentration_fallback``)는 쓸 수
        없다 — 이름이 매핑에 정확히 하나만 일치할 때만 답하고, 없거나 여럿이면
        억지로 하나를 고르지 않고 no_data로 끝낸다.
        """

        place_name = request.place_name
        concentration_tool = self._tools.concentration
        if (
            place_name is None
            or concentration_tool is None
            or self._concentration_mapping_cache is None
        ):
            return _info_no_data_response(request, *provider_metadata)
        try:
            mapped_places = await self._concentration_mapping_cache.places()
        except AppError:
            return _info_no_data_response(request, *provider_metadata)

        normalized_query = _normalize_place_name(place_name)
        matches = [
            place
            for place in mapped_places
            if place.concentration_name is not None
            and _normalize_place_name(place.title) == normalized_query
        ]
        if len(matches) != 1:
            return _info_no_data_response(request, *provider_metadata)
        matched_place = matches[0]

        signgu_code = concentration_signgu_code(matched_place.district_code)
        if signgu_code is None:
            return _info_no_data_response(request, *provider_metadata)

        concentration_result = await execute_concentration_by_search_keys(
            concentration_tool,
            search_keys=matched_place.concentration_search_keys,
            canonical_name=cast(str, matched_place.concentration_name),
            signgu_code=signgu_code,
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
                provider_metadata=(*provider_metadata, concentration_result.provider_metadata),
            )
        if concentration_result.status is ToolStatus.NO_DATA:
            return _info_no_data_response(
                request, *provider_metadata, concentration_result.provider_metadata
            )

        forecast = select_concentration_forecast(
            concentration_result.concentration,
            candidate_name=cast(str, matched_place.concentration_name),
            reference_date=reference_date,
        )
        rate = forecast.concentration_rate if forecast is not None else None
        if forecast is None or not is_valid_concentration_rate(rate):
            return _info_no_data_response(
                request, *provider_metadata, concentration_result.provider_metadata
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
                forecasts=_to_concentration_forecast_infos(
                    concentration_result.concentration,
                    candidate_name=cast(str, matched_place.concentration_name),
                    start_date=reference_date,
                ),
            ),
            metadata=_info_response_metadata(
                *provider_metadata, concentration_result.provider_metadata
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
            # 구를 모르는 장소는 건너뛴다. 종로구로 대신 물으면 다른 구 장소는
            # 언제나 0건이라, 조회 실패가 "정보 없음"과 구분되지 않는다.
            proxy_signgu_code = concentration_signgu_code(proxy_place.district_code)
            if proxy_signgu_code is None:
                continue
            proxy_result = await execute_concentration_by_search_keys(
                concentration_tool,
                search_keys=proxy_place.concentration_search_keys,
                canonical_name=proxy_place.concentration_name,
                signgu_code=proxy_signgu_code,
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
                forecasts=_to_concentration_forecast_infos(
                    proxy_result.concentration,
                    candidate_name=proxy_place.concentration_name,
                    start_date=reference_date,
                ),
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
            # "종각역 주차장 정보"처럼 장소 좌표는 확정됐지만 TourAPI 관광 DB에는
            # 없는 역·상권도 있다. 이때 "확인할 수 없음"으로 끝내지 않고, 해당
            # 좌표를 기준으로 가까운 공영주차장의 최신 잔여 면수를 안내한다. 반대로
            # 관광지 상세에 주차 필드가 있으면 아래 기존 상세 경로를 유지한다.
            if request.question_type == "parking":
                return await self._fetch_realtime_public_parking_info(
                    request,
                    place_name=place_name,
                    resolved_location=resolved_location,
                    location_metadata=location_metadata,
                )
            return _place_info_response(
                request,
                requested_place_name=place_name,
                resolved_place_name=resolved_location.resolved_name,
                place_id=resolved_location.place_id,
                destination_coordinates=_to_info_destination_coordinates(resolved_location),
                fields={},
                provider_metadata=(location_metadata, detail_result.provider_metadata),
            )

        fields = extract_info_fields(request.question_type, detail_result.details)
        if request.question_type == "parking" and not fields:
            # 상세 행은 찾았어도 주차 정보가 비어 있으면 같은 기준으로 주변
            # 공영주차장으로 대체한다. "주차 불가"라는 명시값은 fields에 남으므로
            # 대체하지 않는다.
            return await self._fetch_realtime_public_parking_info(
                request,
                place_name=place_name,
                resolved_location=resolved_location,
                location_metadata=location_metadata,
            )

        return _place_info_response(
            request,
            requested_place_name=place_name,
            resolved_place_name=(detail_result.details.title or resolved_location.resolved_name),
            place_id=detail_result.details.content_id or resolved_location.place_id,
            destination_coordinates=_to_info_destination_coordinates(resolved_location),
            fields=fields,
            # 카드는 질문 유형과 무관하게 채운다. status는 위 fields로만 정해진다.
            place_card=_to_place_card(detail_result.details, resolved_location.place_id),
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
        festival_result = await festival_tool.execute(FestivalQuery(reference_date=reference_date))
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
            metadata=_info_response_metadata(location_metadata, festival_result.provider_metadata),
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


def _select_commercial_category(
    categories: tuple[RealtimeCommercialCategory, ...],
    question: str | None,
) -> tuple[str, str] | None:
    """질문에 언급된 업종을 서울시 상권 응답의 모든 업종에서 고른다.

    명시 업종이 없을 때만 카페·커피 계열을 우선한다. 업종값이 없으면 지역 전체
    상권으로 낮춰 고지하며, 다른 업종 값을 요청 업종처럼 바꾸지 않는다.
    """

    normalized_question = (question or "").replace(" ", "")
    for category in categories:
        label = " · ".join(
            value
            for value in (category.large_category, category.middle_category)
            if value is not None
        )
        category_terms = tuple(
            value.replace(" ", "")
            for value in (category.large_category, category.middle_category)
            if value
        )
        if category.activity_level is not None and any(
            term in normalized_question for term in category_terms
        ):
            return label, category.activity_level
    for category in categories:
        label = " · ".join(
            value
            for value in (category.large_category, category.middle_category)
            if value is not None
        )
        if category.activity_level is not None and any(
            marker in label for marker in _COMMERCIAL_CATEGORY_MARKERS
        ):
            return label, category.activity_level
    return None


def _to_commercial_detail_items(
    categories: tuple[RealtimeCommercialCategory, ...],
    *,
    area_activity_level: str | None,
) -> list[RealtimeInfoDetailItem]:
    """서울시가 제공한 업종별 상권 활동을 상세 카드용 목록으로 정리한다."""

    items = [
        RealtimeInfoDetailItem(
            title=" · ".join(
                value
                for value in (category.large_category, category.middle_category)
                if value is not None
            )
            or "업종별 상권 활동",
            subtitle=category.activity_level,
            details={"실시간 활동": category.activity_level}
            if category.activity_level is not None
            else {},
        )
        for category in categories
    ]
    if not items and area_activity_level is not None:
        items.append(
            RealtimeInfoDetailItem(
                title="지역 전체 상권",
                subtitle=area_activity_level,
                details={"실시간 활동": area_activity_level},
            )
        )
    return items


def _to_parking_detail_items(
    entries: list[RealtimeParkingLot] | tuple[RealtimeParkingLot, ...],
    *,
    latitude: float,
    longitude: float,
) -> list[RealtimeInfoDetailItem]:
    """주차장은 가까운 순으로, 현재 제공된 실측 필드만 상세 카드에 싣는다."""

    items: list[RealtimeInfoDetailItem] = []
    for item in entries:
        details = {
            key: value
            for key, value in {
                "거리": _distance_from_location_label(
                    latitude,
                    longitude,
                    item.latitude,
                    item.longitude,
                ),
                "주소": item.address,
                "유형": item.lot_type or "기타",
                "총 주차": f"총 {item.capacity}대" if item.capacity is not None else None,
                "현재 주차": (
                    f"{item.current_parked_count}대 주차 중"
                    if item.current_available and item.current_parked_count is not None
                    else None
                ),
                "가능 주차": (
                    f"{item.available_spaces}대 가능" if item.available_spaces is not None else None
                ),
                "요금": "유료" if item.paid is True else "무료" if item.paid is False else None,
                "기준 시각": item.observed_at,
            }.items()
            if value is not None
        }
        items.append(
            RealtimeInfoDetailItem(
                title=item.name,
                subtitle=_format_realtime_parking(item),
                details=details,
            )
        )
    return items


def _to_subway_detail_items(
    entries: list[RealtimeSubwayArrival] | tuple[RealtimeSubwayArrival, ...],
) -> list[RealtimeInfoDetailItem]:
    return [
        RealtimeInfoDetailItem(
            title=f"{item.station_name} {item.line or ''}".strip(),
            subtitle=_format_subway_arrival(item),
            details={
                key: value
                for key, value in {
                    "방면": item.direction,
                    "종착역": item.destination,
                    "도착 안내": item.arrival_message,
                }.items()
                if value is not None
            },
        )
        for item in entries
    ]


def _to_bus_detail_items(
    entries: list[RealtimeBusStop] | tuple[RealtimeBusStop, ...],
) -> list[RealtimeInfoDetailItem]:
    return [
        RealtimeInfoDetailItem(
            title=item.name,
            subtitle=f"정류장 번호 {item.ars_id}" if item.ars_id else "주변 버스정류장",
            details={"정류장 번호": item.ars_id} if item.ars_id else {},
        )
        for item in entries
    ]


def _to_event_detail_items(
    entries: list[RealtimeCityEvent] | tuple[RealtimeCityEvent, ...],
) -> list[RealtimeInfoDetailItem]:
    return [
        RealtimeInfoDetailItem(
            title=item.name,
            subtitle=" · ".join(part for part in (item.period, item.place) if part) or None,
            details={
                key: value
                for key, value in {"기간": item.period, "장소": item.place}.items()
                if value is not None
            },
            thumbnail_url=item.thumbnail_url,
            external_url=item.url,
        )
        for item in entries
    ]


def _distance_from_location_label(
    latitude: float,
    longitude: float,
    target_latitude: float | None,
    target_longitude: float | None,
) -> str | None:
    if target_latitude is None or target_longitude is None:
        return None
    distance_km = haversine_km(latitude, longitude, target_latitude, target_longitude)
    return f"약 {round(distance_km * 1000):,}m"


def _seoul_realtime_map_url(area: SeoulRealtimeArea) -> str:
    """서울시 실시간 도시데이터 지도의 제공 지역 딥링크를 만든다.

    지도 URL은 ``y=경도``, ``x=위도`` 순서를 사용한다. 응답의 AREA_NM보다
    고정 지역 목록의 이름·대표 좌표가 URL 파라미터 계약에 맞으므로 그 값을 쓴다.
    """

    return (
        "https://data.seoul.go.kr/SeoulRtd/map?hotspotNm="
        f"{quote(area.name, safe='')}&y={area.longitude}&x={area.latitude}"
    )


def _format_realtime_parking(item: RealtimeParkingLot) -> str:
    capacity = f"총 {item.capacity}면" if item.capacity is not None else "총면수 미제공"
    if item.available_spaces is not None:
        current = f"잔여 {item.available_spaces}면 · 현재 {item.current_parked_count}대 주차"
    elif item.current_available and item.current_parked_count is not None:
        current = f"현재 {item.current_parked_count}대 주차"
    else:
        current = "실시간 주차 대수 미제공"
    paid = "유료" if item.paid is True else "무료" if item.paid is False else "요금 정보 미제공"
    return f"{capacity} · {current} · {paid}"


def _district_from_address(address: str | None) -> str | None:
    """주소에서 서울시 자치구를 꺼낸다. 공영주차장 API의 구 단위 파라미터다."""

    if not address:
        return None
    for token in address.replace(",", " ").split():
        if token.endswith("구") and len(token) >= 2:
            return token
    return None


def _municipal_status_to_realtime_lot(
    status: MunicipalParkingStatus,
    catalog_entry: object | None,
) -> RealtimeParkingLot:
    """공영주차장 최신값과 좌표 카탈로그를 기존 실시간 카드 모델로 합친다."""

    latitude = getattr(catalog_entry, "latitude", None)
    longitude = getattr(catalog_entry, "longitude", None)
    capacity = (
        status.capacity
        if status.capacity is not None
        else getattr(catalog_entry, "capacity", None)
    )
    available_spaces = (
        max(0, capacity - status.current_parked_count)
        if capacity is not None and status.current_parked_count is not None and status.is_live
        else None
    )
    return RealtimeParkingLot(
        name=status.name,
        latitude=latitude,
        longitude=longitude,
        capacity=capacity,
        current_parked_count=status.current_parked_count,
        current_available=status.is_live,
        paid=status.paid if status.paid is not None else getattr(catalog_entry, "paid", None),
        observed_at=status.observed_at,
        address=status.address or getattr(catalog_entry, "address", None),
        code=status.code,
        lot_type="공영",
        available_spaces=available_spaces,
    )


def _parking_distance_or_inf(location: ResolvedLocation, item: RealtimeParkingLot) -> float:
    if item.latitude is None or item.longitude is None:
        return float("inf")
    return haversine_km(location.latitude, location.longitude, item.latitude, item.longitude)


def _subway_field_key(item: RealtimeSubwayArrival) -> str:
    """같은 역·같은 호선의 두 방향이 같은 키로 겹쳐 한쪽이 지워지는 걸 막는다."""

    base = f"{item.station_name} {item.line or ''}".strip()
    return f"{base} · {item.direction}" if item.direction else base


def _format_subway_arrival(item: RealtimeSubwayArrival) -> str:
    destination = f"{item.destination}행" if item.destination else "방면 정보 미제공"
    arrival = item.arrival_message or (
        f"약 {max(1, round(item.arrival_seconds / 60))}분 후"
        if item.arrival_seconds is not None
        else "도착 정보 미제공"
    )
    direction = f" · {item.direction}" if item.direction else ""
    return f"{destination}{direction} · {arrival}"


def _to_concentration_forecast_infos(
    concentration: ConcentrationResult | None,
    *,
    candidate_name: str,
    start_date: date,
) -> list[ConcentrationForecastInfo]:
    """관광지 집중률의 방문일 이후 7일 예측을 INFO 계약으로 정규화한다."""

    items: list[ConcentrationForecastInfo] = []
    for forecast in select_concentration_forecasts(
        concentration,
        candidate_name=candidate_name,
        start_date=start_date,
    ):
        forecast_date = parse_concentration_forecast_date(forecast.forecast_date)
        rate = forecast.concentration_rate
        if forecast_date is None or not is_valid_concentration_rate(rate):
            continue
        normalized = normalize_concentration(rate)
        items.append(
            ConcentrationForecastInfo(
                forecast_date=forecast_date.isoformat(),
                concentration_rate=rate,
                concentration_level=cast(
                    Literal["quiet", "normal", "slightly_crowded", "crowded"],
                    normalized.level.value,
                ),
                concentration_label=normalized.label.value,
            )
        )
    return items


def _normalize_place_name(value: str) -> str:
    """공백·대소문자 차이를 무시하고 장소명을 대조한다(TP-171 이름-일치 폴백 전용)."""

    return value.casefold().replace(" ", "")


def _supported_district_name(value: str) -> str | None:
    """'종로'·'종로구'처럼 지원 구를 가리키는 짧은 권역명을 정규화한다.

    주차장 질문의 이 표현은 특정 관광지 식별이 아니라 구 안의 주차장 목록을
    찾으려는 뜻이다. 임의 지명까지 넓히지 않고, 서비스가 실제로 지원하는 구
    이름만 받는다. 따라서 '종각'처럼 역·명소와 혼동될 수 있는 입력은 기존
    후보 되묻기 흐름을 유지한다.
    """

    normalized = value.casefold().replace(" ", "")
    for district in SUPPORTED_DISTRICTS:
        full_name = district.name.casefold()
        short_name = full_name.removesuffix("구")
        if normalized in {full_name, short_name}:
            return district.name
    return None


def _is_current_activity_candidate(request: InfoContextRequest) -> bool:
    """'지금 사람 많아?'처럼 현재 상권 경로 전환 가능성이 있는지 판단한다."""

    question = request.specific_question or ""
    return any(marker in question for marker in _CURRENT_ACTIVITY_MARKERS)


def _is_current_population_candidate(request: InfoContextRequest, clock_value: datetime) -> bool:
    """현재형 INFO 혼잡 질문을 실시간 인구 경로로 보낼지 결정한다.

    날짜가 없는 질문은 INFO 추출 규칙상 오늘으로 정규화된다. 반대로 내일·주말처럼
    방문일이 오늘보다 뒤면 관광지 집중률 예측만 사용한다. 이 판정은 LLM 프롬프트를
    바꾸지 않고, 같은 ``concentration`` question_type 안에서 데이터 출처만 고른다.

    (TP-171) 위치 해석에도 영향을 준다 — True면 저장소 지역 제한(enforce_service_area)
    을 명시적으로 끈다. 저장소 조회 자체는 끄지 않는다(그래서 명동성당류가 산다) —
    끄는 건 "지원 16개 구 밖이면 막는다"는 지역 제한 하나뿐이다. 자세한 이유는
    fetch_info_context() 호출부의 주석 참고.
    """

    return (
        request.question_type == "concentration"
        and request.specific_question is not None
        and _info_reference_date(request.visit_time, clock_value) == _as_kst(clock_value).date()
    )


def _place_candidate_has_data(
    location: ResolvedLocation,
    *,
    question_type: str,
    is_realtime_citydata_purpose: bool,
    current_population_candidate: bool,
) -> bool:
    """되묻기 후보 하나가 이번 질문 유형에 실제로 답할 데이터를 갖고 있는지.

    fetch_info_context()가 실제로 타는 갈래(위 question_type 분기)와 같은 기준을
    쓴다 — 여기서 통과시켜 놓고 정작 그 갈래에서 no_data가 나면 되묻기가
    무의미해진다.
    """
    if question_type == "realtime_commercial":
        return (
            select_nearest_commercial_area(
                latitude=location.latitude, longitude=location.longitude
            )
            is not None
        )
    if is_realtime_citydata_purpose:
        return (
            select_nearest_population_area(
                latitude=location.latitude, longitude=location.longitude
            )
            is not None
        )
    if question_type == "concentration":
        if location.concentration_name is not None:
            return True
        # 현재형 혼잡 질문은 집중률 매핑이 없어도 실시간 인구로 답할 수 있다
        # (_fetch_realtime_population_or_concentration_info와 같은 기준).
        if current_population_candidate:
            return (
                select_nearest_population_area(
                    latitude=location.latitude, longitude=location.longitude
                )
                is not None
            )
        return False
    # 그 외(주차·화장실 등 시설 상세)는 우리 DB에 저장된 장소인지만 본다 —
    # 특정 필드까지 미리 조회하진 않는다(비용 대비 실익 작음, 클릭 후 그
    # 필드가 비어 있으면 기존과 같은 "정보 없음"으로 끝난다).
    return location.place_id is not None


def _is_commercial_place_category(category: str | None) -> bool:
    """Naver Local Search 업종이 상권 활동 대체 대상인지 확인한다."""

    return category is not None and any(
        marker in category for marker in _COMMERCIAL_CATEGORY_MARKERS
    )


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


def _realtime_city_info_no_data_response(
    request: InfoContextRequest,
    *,
    place_name: str,
    resolved_location: ResolvedLocation,
    provider_metadata: tuple[ProviderMetadata, ...],
) -> InfoContextResponse:
    """citydata 제공 지역 밖에서도 질문 유형을 보존한 no_data 응답을 만든다."""

    return InfoContextResponse(
        request_id=request.request_id,
        status="no_data",
        result=RealtimeCityInfoResult(
            status="no_data",
            question_type=cast(
                Literal[
                    "realtime_parking",
                    "realtime_public_parking",
                    "realtime_subway",
                    "realtime_bus",
                    "realtime_event",
                    "realtime_traffic",
                ],
                request.question_type,
            ),
            requested_place_name=place_name,
            resolved_place_name=resolved_location.resolved_name,
        ),
        metadata=_info_response_metadata(provider_metadata),
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
