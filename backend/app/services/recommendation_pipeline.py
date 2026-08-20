"""RecommendationContext를 Scoring→Evidence→Explanation으로 조립하는 추천 파이프라인.

D는 C Tool을 직접 호출하지 않는다([TECH-02]). Tool 조회는 호출자(A, 또는
`app/services/recommendations.py`처럼 아직 조건 스키마 통합 전인 레거시
호출자)가 맡고, D는 그 결과인 RecommendationContext만 입력으로 받는다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, time
from time import perf_counter
from typing import TypeAlias

from app.agent_context.enrichment_schemas import CandidateEnrichmentResponse
from app.agent_context.schemas import RecommendationContext
from app.concentration_policy import ConcentrationLevel
from app.domain.candidate_mapper import map_context_to_scoring_candidates
from app.domain.evidence import build_evidence
from app.domain.explanation import build_explanations
from app.domain.models import ScoringCandidate, WeatherCondition
from app.domain.scoring import (
    CONCENTRATION_WEIGHTS,
    ExclusionReason,
    PrepareResult,
    RankedCandidate,
    concentration_score,
    prepare_candidates,
    redistribute_weights,
    score_prepared_candidates,
    weights_for_feature_scores,
)
from app.domain.travel_route import TravelRoute
from app.domain.weather_judgment import (
    WeatherReason,
    judge_weather_condition_from_facts,
    judge_weather_condition_from_stated,
)
from app.errors import AppError
from app.recommendation_limits import DEFAULT_RECOMMENDATION_RESULT_LIMIT
from app.schemas import (
    RecommendationItem,
    RecommendationResponse,
    UserConditions,
    WeatherIntent,
)

_OPERATING_HOURS_UNVERIFIED_WARNING = "방문 전에 운영 여부를 확인해주세요."
_DETAILS_MISSING_WARNING = "장소 상세정보 일부를 확인하지 못했습니다."
# 날씨가 Scoring에 빠지는 이유는 두 가지이고, 사용자에게 같은 말로 알리면 안 된다.
# (1) 조회 자체를 안 한 경우: weather_intent=IGNORE(= "날씨 상관없어" 명시)면 C가
#     Weather Tool을 실행하지 않는다(tool_rules.py). 정상 흐름이므로 오류처럼 알리지
#     않는다. int-01-recommend.md §8의 IGNORE 정의 참고.
# (2) 조회했으나 실패한 경우: 날씨 API 장애 등 — 이때만 "확인하지 못했다"가 사실이다.
_WEATHER_IGNORED_WARNING = "날씨 조건을 반영하지 않기로 하셔서 이번 추천에는 제외했어요."
_WEATHER_MISSING_WARNING = "현재 날씨 정보를 확인하지 못해 이 조건은 반영되지 않았어요."
_NO_NOTABLE_EXPLANATION_WARNING = (
    "이 장소는 특별히 강조할 만한 조건은 없지만, 조건에 맞아 추천했어요."
)
# 24시간 영업은 운영 구간이 time.min~time.max로 들어온다. 그대로 포맷하면
# "00:00~23:59"가 되어 마감이 임박한 것처럼 읽힌다.
_ALL_DAY_OPERATING_HOURS_DISPLAY = "24시간"
# 원문 "09:00~24:00"의 종료도 time.max로 들어온다(operating_hours.py). 원문이 24:00인데
# "23:59"로 보이면 1분 일찍 닫는 것처럼 읽히므로 원문 표기를 되살린다.
_MIDNIGHT_CLOSE_DISPLAY = "24:00"
# 다만 C의 직렬화(agent_context/mappers.py::_operating_schedule)가 close_time을
# "%H:%M"으로 자르는 탓에 time.max(23:59:59.999999)는 D까지 "23:59"로 도착한다 —
# 자정 마감이라는 표식이 도중에 지워진다. 그래서 23:59도 자정 마감으로 함께 본다.
# 종로구 데이터에 23:59 마감 원문은 0건이고(전부 "24:00" 표기) 설령 생기더라도
# 표기가 1분 어긋날 뿐이라, C의 직렬화를 바꾸는 것보다 이쪽이 비용이 작다.
_MIDNIGHT_CLOSE_TIMES = (time.max, time(hour=23, minute=59))

Timer: TypeAlias = Callable[[], float]


@dataclass(frozen=True)
class PreparedRecommendationResult:
    """Context 변환과 하드 필터를 마쳐 최종 채점을 기다리는 결과."""

    preparation: PrepareResult
    all_candidates: tuple[ScoringCandidate, ...]
    weather_condition: WeatherCondition | None
    weather_reason: WeatherReason
    requested_environment: str | None
    details_missing_place_ids: frozenset[str]
    visit_at: datetime
    weather_ignored: bool
    ignore_operating_hours: bool
    # 거리 기준점의 표시 이름(resolve_origin_name 참고). 하드 필터 입력이 아니라
    # 근거 문장 재료라 filter_context에는 넣지 않는다 — 날씨 판정과 같은 취급으로,
    # 병합 시 첫 배치 값을 그대로 쓴다.
    origin_name: str | None = None

    @property
    def filter_context(self) -> tuple[object, ...]:
        """하드 필터가 실제로 입력으로 받은 값 — 배치 간 이게 같아야 병합할 수 있다.

        `prepare_candidates()`에 들어가는 것만 담는다. 날씨·요청 환경은 여기
        없다 — 하드 필터는 그 값을 아예 받지 않기 때문에, 배치별로 달라도
        통과/제외 결과를 오염시킬 수 없다(`merge_prepared_recommendations()`
        docstring 참고).
        """
        return (self.visit_at, self.ignore_operating_hours)


def merge_prepared_recommendations(
    results: Sequence[PreparedRecommendationResult],
) -> PreparedRecommendationResult:
    """같은 요청에서 여러 번 준비한 후보를 중복 없이 하나로 합친다.

    하드 필터 입력(`filter_context` — 방문 시각과 운영시간 무시 여부)은 모든
    보충 조회에서 같아야 한다. 이게 다르면 같은 장소가 조회 순서에 따라 다르게
    걸러져 통과/제외 목록 자체가 오염되므로 오류로 처리한다.

    반면 채점 조건(날씨 판정·요청 환경·weather_ignored)은 **첫 배치 값을 그대로
    재사용한다.** 보충 조회는 같은 요청·같은 시각·같은 좌표를 다시 조회하는
    것이라 날씨가 달라질 이유가 없고, 실제로 달라졌다면 그건 보충 조회의 기상
    조회가 실패했다는 뜻이지 판정이 바뀌었다는 뜻이 아니다. 그리고 하드 필터
    (`prepare_candidates()`)는 날씨를 인자로 받지 않고, 후보 변환
    (`map_context_to_scoring_candidates()`)도 `context.weather`를 읽지 않는다 —
    채점은 병합이 끝난 뒤 이 단일 기준으로 한 번만 돌기 때문에, 배치별 날씨
    차이가 결과에 섞여 들어갈 경로가 없다. 여기서 배치를 거부하면 멀쩡한 보충
    후보만 통째로 버리게 된다.

    Provider가 같은 장소를 다시 반환하면 첫 분류만 유지한다.
    """
    if not results:
        raise ValueError("병합할 준비 결과가 없습니다.")

    first = results[0]
    for result in results[1:]:
        if result.filter_context != first.filter_context:
            raise ValueError(
                "준비 결과의 방문 시각 또는 운영시간 무시 여부가 서로 다릅니다."
            )

    eligible_by_id = {}
    excluded_by_id = {}
    candidates_by_id = {}
    for result in results:
        for candidate in result.all_candidates:
            candidates_by_id.setdefault(candidate.place_id, candidate)
        for prepared in result.preparation.eligible_candidates:
            place_id = prepared.candidate.place_id
            if place_id not in excluded_by_id:
                eligible_by_id.setdefault(place_id, prepared)
        for excluded in result.preparation.excluded_candidates:
            place_id = excluded.place_id
            if place_id not in eligible_by_id:
                excluded_by_id.setdefault(place_id, excluded)

    return PreparedRecommendationResult(
        preparation=PrepareResult(
            eligible_candidates=tuple(eligible_by_id.values()),
            excluded_candidates=tuple(excluded_by_id.values()),
            input_count=len(candidates_by_id),
        ),
        all_candidates=tuple(candidates_by_id.values()),
        weather_condition=first.weather_condition,
        weather_reason=first.weather_reason,
        requested_environment=first.requested_environment,
        details_missing_place_ids=frozenset().union(
            *(result.details_missing_place_ids for result in results)
        ),
        visit_at=first.visit_at,
        weather_ignored=first.weather_ignored,
        ignore_operating_hours=first.ignore_operating_hours,
        origin_name=first.origin_name,
    )


async def prepare_recommendation_from_context(
    context: RecommendationContext | None,
    *,
    # A가 넘기는 사용자 발화 조건. weather_intent와 발화 날씨(conditions.weather)를
    # resolve_weather_condition()에 전달해 D-051 판정(사실+의도)에 쓴다.
    # AVOID/ENJOY면 C가 날씨를 조회하지 않을 수 있어 그때는 발화 값으로 대신 판정한다.
    conditions: UserConditions | None = None,
    visit_at: datetime,
    shown_place_ids: frozenset[str] = frozenset(),
    rejected_place_ids: frozenset[str] = frozenset(),
    # True면 폐점 후보도 채점에 포함한다 — "운영중이 아닌 곳도 볼래요"(no_data_closed
    # 되묻기) 해소 턴에서만 A가 켠다.
    ignore_operating_hours: bool = False,
) -> PreparedRecommendationResult:
    """Context를 후보로 변환하고 하드 필터까지만 적용한다.

    Context 상태 처리: `context` 자체가 `None`이거나(예: A의
    `AgentContextResponse.status`가 `needs_clarification`/`unsupported`/
    `unavailable`일 때), `location`/`places`가 없거나 `unavailable`(조회
    자체 실패)이면 `AppError`를 던진다. `no_data`(정상 조회했지만 결과
    없음)는 에러가 아니라 후보 0건으로 처리한다 — "확인 못 함"과 "확인했는데
    없음"은 다른 상황이라 구분한다.

    호출자 책임: 같은 사용자 요청 안에서 후보를 보충하려고 이 함수를 여러 번
    부를 때는 모든 호출에 같은 `visit_at`과 `ignore_operating_hours`를 넘겨야
    한다. 하드 필터 입력이 호출마다 달라지면 같은 장소가 조회 순서에 따라 다르게
    걸러진다. `merge_prepared_recommendations()`가 이걸 `filter_context`로
    검사하고, 다르면 `ValueError`를 던진다.
    """
    if context is None:
        raise AppError(
            code="context_unavailable",
            message="Context 정보가 없습니다.",
            status_code=502,
            retryable=True,
        )

    location = context.location
    if location is None or location.status not in {"success", "partial"} or location.data is None:
        raise AppError(
            code="location_unavailable",
            message="위치 정보를 확인할 수 없습니다.",
            status_code=502,
            retryable=True,
        )

    places = context.places
    if places is None or places.status == "unavailable":
        error = places.error if places is not None else None
        raise AppError(
            code=error.code if error else "unavailable",
            message=error.message if error else "주변 장소를 검색하지 못했습니다.",
            status_code=502,
            retryable=error.retryable if error else True,
        )

    candidates = map_context_to_scoring_candidates(context, visit_at=visit_at)
    resolved_weather_condition, weather_reason = resolve_weather_condition(context, conditions)
    preparation = prepare_candidates(
        candidates,
        now=visit_at,
        shown_place_ids=shown_place_ids,
        rejected_place_ids=rejected_place_ids,
        ignore_operating_hours=ignore_operating_hours,
    )

    return PreparedRecommendationResult(
        preparation=preparation,
        all_candidates=candidates,
        weather_condition=resolved_weather_condition,
        weather_reason=weather_reason,
        requested_environment=resolve_requested_environment(conditions),
        details_missing_place_ids=frozenset(
            place.place_id
            for place in (places.data or [])
            if place.operating_schedule is None
        ),
        visit_at=visit_at,
        weather_ignored=_is_weather_explicitly_ignored(context, conditions),
        ignore_operating_hours=ignore_operating_hours,
        origin_name=resolve_origin_name(context),
    )


async def score_prepared_recommendation(
    prepared: PreparedRecommendationResult,
    *,
    search_radius_km: float,
    recommendation_limit: int = DEFAULT_RECOMMENDATION_RESULT_LIMIT,
    # A가 조회한 실측 도보 경로. 비어 있으면 거리 Feature가 직선거리로 계산된다.
    travel_routes: Sequence[TravelRoute] = (),
    timer: Timer = perf_counter,
) -> RecommendationResponse:
    """준비된 후보를 채점하고 Evidence·Explanation 응답을 조립한다.

    호출자 책임: `search_radius_km`은 C가 `context.places`를 조회할 때 실제로
    사용한 검색 반경과 동일해야 한다 — Scoring의 거리 점수 정규화
    (`max_distance_km`)가 이 값을 그대로 재사용하기 때문이다
    (`docs/design/recommendation-scoring.md` 참고). 값이 어긋나면 거리 점수가
    실제 후보 풀 범위와 안 맞게 계산된다.
    """
    started_at = timer()
    scoring = score_prepared_candidates(
        prepared.preparation.eligible_candidates,
        weather_condition=prepared.weather_condition,
        weather_reason=prepared.weather_reason,
        max_distance_km=search_radius_km,
        requested_environment=prepared.requested_environment,
        travel_routes=travel_routes,
    )
    ranked = scoring.ranked[:recommendation_limit]
    # 결과가 0건이고, 그 이유가 전부 폐점 후보 제외였다면(다른 이유로 제외된 후보가
    # 없었다면) A가 "운영중이 아닌 곳도 볼래요" 되묻기를 띄울 수 있게 표시한다.
    excluded = prepared.preparation.excluded_candidates
    excluded_closed_place_ids = tuple(
        candidate.candidate.place_id
        for candidate in excluded
        if candidate.reason is ExclusionReason.CLOSED
    )
    excluded_closed_count = len(excluded_closed_place_ids)
    excluded_all_closed = (
        not ranked
        and excluded_closed_count > 0
        and excluded_closed_count == len(excluded)
    )
    response = _build_response(
        ranked,
        prepared.all_candidates,
        prepared.details_missing_place_ids,
        prepared.visit_at,
        weather_ignored=prepared.weather_ignored,
        excluded_all_closed=excluded_all_closed,
        excluded_closed_place_ids=excluded_closed_place_ids,
        origin_name=prepared.origin_name,
    )
    return response.model_copy(update={"elapsed_ms": round((timer() - started_at) * 1000, 2)})


async def run_recommendation_pipeline_from_context(
    context: RecommendationContext | None,
    *,
    conditions: UserConditions | None = None,
    visit_at: datetime,
    search_radius_km: float,
    shown_place_ids: frozenset[str] = frozenset(),
    rejected_place_ids: frozenset[str] = frozenset(),
    recommendation_limit: int = DEFAULT_RECOMMENDATION_RESULT_LIMIT,
    ignore_operating_hours: bool = False,
    timer: Timer = perf_counter,
) -> RecommendationResponse:
    """prepare와 score를 연속 실행하는 기존 호환 진입점.

    A가 C에서 받은 RecommendationContext를 그대로 넘기면 D 내부(후보 변환→
    하드 필터→Scoring→Evidence→Explanation 조립)를 전부 처리해
    RecommendationResponse만 반환한다. C Tool을 직접 호출하지 않는다([TECH-02]).
    후보를 보충하지 않는 호출자(HTTP 추천 라우트 등)는 이 진입점만 쓰면 된다.

    각 인자의 의미와 호출자 책임은 `prepare_recommendation_from_context()`와
    `score_prepared_recommendation()` docstring을 본다.
    """
    # 경과 시간은 prepare까지 포함한 전체 구간으로 다시 잰다 —
    # score_prepared_recommendation()이 채운 값은 채점 구간만이라 여기서 덮어쓴다.
    started_at = timer()
    prepared = await prepare_recommendation_from_context(
        context,
        conditions=conditions,
        visit_at=visit_at,
        shown_place_ids=shown_place_ids,
        rejected_place_ids=rejected_place_ids,
        ignore_operating_hours=ignore_operating_hours,
    )
    response = await score_prepared_recommendation(
        prepared,
        search_radius_km=search_radius_km,
        recommendation_limit=recommendation_limit,
        timer=timer,
    )
    return response.model_copy(update={"elapsed_ms": round((timer() - started_at) * 1000, 2)})


async def rerank_with_concentration(
    response: RecommendationResponse,
    weather_condition: WeatherCondition | None,
    concentration: CandidateEnrichmentResponse,
    *,
    seek: bool,
    weather_reason: WeatherReason = None,
    # 1차와 같은 기준점 이름. 안 넘기면 근거 문장이 "현재 위치"로 폴백해 1차와
    # 2차가 같은 요청에서 다른 문장을 말하게 되므로, 호출자가 반드시 1차에 쓴
    # 값을 그대로 넘긴다(real_recommendation_provider.py).
    origin_name: str | None = None,
    timer: Timer = perf_counter,
) -> RecommendationResponse:
    """D의 2차 Scoring 진입점(D-040, concentration_intent AVOID/SEEK 전용).

    `response`는 1차 `run_recommendation_pipeline_from_context()` 결과(이미
    호출자가 지정한 개수로 좁혀진 상태 — RECOMMEND는 5개, SCHEDULE은 10개)다.
    여기서 새 Candidate를 다시 만들지 않는다 —
    `RecommendationItem.feature_scores`(weather/remaining_operating_time/distance)를
    그대로 재사용한다. concentration과 무관하게 이 값들은 변하지 않기 때문이다.
    `weather_condition`/`weather_reason`은 1차 호출과 같은 입력(`context`,
    `conditions`)으로 `resolve_weather_condition()`을 호출해 얻은 값이어야 한다 —
    근거 문장을 다시 조립하는 데만 쓰고, 점수 자체를 다시 계산하지는 않는다.
    호출자가 직접 판정 로직을 다시 구현하면(예: 옛 `to_weather_condition()`을
    계속 쓰면) 1차와 2차의 판정이 갈라질 수 있다 — 반드시
    `resolve_weather_condition()`을 통해 같은 값을 재사용해야 한다.
    `weather_reason`은 기본값 `None`이라, 호출자가 아직 안 넘겨도(현재
    `agent_runtime.py`가 그렇다) 동작은 그대로 유지되고 근거 문장만
    `weather_condition` 기반 라벨로 폴백한다.

    concentration 결측(C가 해당 후보에 no_data/unavailable을 반환) 처리는
    weather/remaining_operating_time과 동일한 패턴이다 — 그 후보만
    `redistribute_weights()`로 재분배한다.
    """
    started_at = timer()

    concentration_by_place_id = {result.place_id: result for result in concentration.candidates}
    unverified_place_ids = frozenset(item.place_id for item in response.unverified_recommendations)

    items = [*response.recommendations, *response.unverified_recommendations]

    order_key: list[tuple[float, float, str]] = []
    rescoring_context: dict[
        str,
        tuple[
            RecommendationItem,
            dict[str, float | None],
            dict[str, float],
            ConcentrationLevel | None,
        ],
    ] = {}

    for item in items:
        result = concentration_by_place_id.get(item.place_id)
        concentration_rate: float | None = None
        concentration_level: ConcentrationLevel | None = None
        if result is not None and result.status == "success" and result.concentration:
            forecast = result.concentration[0]
            concentration_rate = forecast.concentration_rate
            concentration_level = forecast.concentration_level

        feature_scores: dict[str, float | None] = dict(item.feature_scores)
        feature_scores["concentration"] = (
            None
            if concentration_rate is None
            else concentration_score(concentration_rate, seek=seek)
        )

        # 1차가 날씨 대신 요청 환경으로 채점했다면 2차 가중치도 같은 키를 써야
        # 한다 — 안 맞추면 environment 점수가 합산에서 통째로 빠지고, 없는
        # weather가 결측으로 잡혀 재분배까지 일어난다.
        base_weights = weights_for_feature_scores(CONCENTRATION_WEIGHTS, feature_scores)
        missing = [feature for feature in base_weights if feature_scores.get(feature) is None]
        weights_used = (
            redistribute_weights(base_weights, missing) if missing else dict(base_weights)
        )
        score = round(
            sum(
                feature_scores[feature] * weight  # type: ignore[operator]
                for feature, weight in weights_used.items()
            ),
            4,
        )

        order_key.append((score, item.distance_km, item.place_id))
        # concentration_level은 근거 문장 조립에만 쓰고 정렬 키에는 관여하지 않는다.
        rescoring_context[item.place_id] = (
            item,
            feature_scores,
            weights_used,
            concentration_level,
        )

    order_key.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))

    verified: list[RecommendationItem] = []
    unverified: list[RecommendationItem] = []

    for rank, (score, _distance_km, place_id) in enumerate(order_key, start=1):
        item, feature_scores, weights_used, concentration_level = rescoring_context[place_id]
        is_unverified = place_id in unverified_place_ids
        candidate = RankedCandidate(
            place_id=item.place_id,
            name=item.name,
            category=item.category,
            rank=rank,
            score=score,
            feature_scores=feature_scores,
            weights_used=weights_used,
            is_unverified=is_unverified,
            warnings=tuple(w for w in item.warnings if w != _NO_NOTABLE_EXPLANATION_WARNING),
            distance_km=item.distance_km,
            remaining_minutes=item.remaining_minutes,
            weather_condition=weather_condition,
            weather_reason=weather_reason,
            environment_type=item.environment_type,
            concentration_level=concentration_level,
        )
        # feature_order를 넘기지 않는다 — build_evidence()가 feature_scores의 키로
        # concentration 포함 여부와 날씨/환경 중 어느 쪽인지를 함께 판단한다.
        evidence = build_evidence(candidate, origin_name=origin_name)
        explanations = build_explanations(evidence)
        warnings = list(candidate.warnings)
        if not explanations:
            warnings.append(_NO_NOTABLE_EXPLANATION_WARNING)

        new_item = RecommendationItem(
            place_id=item.place_id,
            name=item.name,
            category=item.category,
            distance_km=item.distance_km,
            remaining_minutes=item.remaining_minutes,
            # 2차는 후보를 다시 만들지 않고 1차 값을 재사용한다 — 운영 구간도
            # 혼잡도와 무관하게 변하지 않으므로 그대로 가져온다. 여기서 빠뜨리면
            # 혼잡도 재순위를 탄 요청만 이 필드가 조용히 사라진다.
            operating_hours_display=item.operating_hours_display,
            # 혼잡도 재순위는 후보를 다시 만들지 않으므로 실측 이동 정보도
            # 1차 값을 그대로 가져온다 — 여기서 빠뜨리면 2차를 탄
            # 요청만 이 필드가 조용히 사라진다.
            travel_distance_m=item.travel_distance_m,
            travel_duration_seconds=item.travel_duration_seconds,
            travel_mode=item.travel_mode,
            environment_type=item.environment_type,
            recommendation_reason=_recommendation_reason(candidate),
            explanations=list(explanations),
            warnings=warnings,
            score=evidence.score,
            feature_scores={
                contribution.feature: contribution.score for contribution in evidence.contributions
            },
            weights_used={
                contribution.feature: contribution.weight
                for contribution in evidence.contributions
                if contribution.weight is not None
            },
        )
        (unverified if is_unverified else verified).append(new_item)

    return RecommendationResponse(
        recommendations=verified,
        unverified_recommendations=unverified,
        elapsed_ms=round((timer() - started_at) * 1000, 2),
        # 2차(혼잡도 재순위)는 1차가 이미 채점을 마친 후보만 다시 정렬할 뿐,
        # 하드 필터를 다시 태우지 않는다 — 1차가 걸러낸 폐점 후보 id는 그대로다.
        excluded_all_closed=response.excluded_all_closed,
        excluded_closed_place_ids=response.excluded_closed_place_ids,
    )


def resolve_weather_condition(
    context: RecommendationContext,
    conditions: UserConditions | None,
) -> tuple[WeatherCondition | None, WeatherReason]:
    """D-051: 사실(C 조회) 우선, 없으면 발화 값으로 판정한다.

    `context.weather`가 있으면 그게 C가 실제로 조회한 사실이므로 우선 쓴다 —
    NO_MENTION 경로뿐 아니라, AVOID/ENJOY인데 발화에서 5단계 값을 못 뽑아 C가
    대신 조회한 경우(PR #102)도 여기 해당한다. `weather_intent`를 그대로 넘겨서
    ENJOY의 강수 반전 등 의도 재해석이 두 경로 모두에 적용되게 한다.

    `context.weather`가 없으면(AVOID/ENJOY라 조회를 생략하고 발화 값을 뽑은 경우)
    `conditions.weather`로 대신 판정한다.

    반환하는 두 번째 값(`WeatherReason`)은 판정 원인(비/눈/폭염/한파)이다 —
    `WeatherCondition`만으로는 explanation.py가 "왜"를 알 수 없어서 근거 문장
    조립에 따로 필요하다(scoring.py::RankedCandidate.weather_reason 참고).

    `run_recommendation_pipeline_from_context()`(1차)가 내부에서 쓰는 것과 동일한
    함수를 `rerank_with_concentration()`(2차) 호출자도 그대로 써야 한다 — 같은
    `context`/`conditions`에 대해 두 판정이 서로 다른 로직으로 갈라지면 1차 설명과
    2차 설명이 어긋난다. public으로 둔 이유가 이것이다(D-051 "남은 것" 참고).
    """
    weather_intent = conditions.weather_intent if conditions is not None else None

    weather = context.weather
    if weather is not None and weather.status in {"success", "partial"}:
        data = weather.data
        if data is not None:
            return judge_weather_condition_from_facts(
                data.precipitation, data.sky, data.temperature_celsius, weather_intent
            )

    if (
        conditions is not None
        and conditions.weather_intent in (WeatherIntent.AVOID, WeatherIntent.ENJOY)
        and conditions.weather is not None
    ):
        return judge_weather_condition_from_stated(conditions.weather, conditions.weather_intent)

    return None, None


def resolve_origin_name(context: RecommendationContext) -> str | None:
    """거리·경로의 기준점을 사용자에게 뭐라고 부를지 정한다.

    C는 사실만 싣는다(D-051) — 좌표의 출처(`source`)와 사용자가 말한 문자열
    (`requested_query`)이 전부고, 그걸 문구로 옮기는 판정은 D가 한다. 기기 GPS가
    기준점이면 부를 이름이 없으므로 None을 돌려주고, 문장 쪽이 "현재 위치"로
    옮긴다(`explanation.py::_distance_sentence()`).

    `resolved_name`을 쓰지 않는다. 기준점이 지오코딩으로 풀리면 그 값이 도로명
    주소라(`providers/geocoding.py`) "서울특별시 종로구 사직로 161에서 걸어서 41분"이
    된다. `requested_query`는 수식어를 뗀 사용자 발화라 언제나 부를 수 있는
    이름이다(`tools/resolve_location.py::strip_location_modifiers()`).
    """
    location = context.location
    if location is None or location.data is None:
        return None
    if location.data.source == "device_gps":
        return None
    return location.data.requested_query


def resolve_requested_environment(conditions: UserConditions | None) -> str | None:
    """날씨 언급이 없을 때만 사용자가 명시한 실내/실외를 Scoring에 넘긴다.

    `weather_intent`가 AVOID/ENJOY면 발화에 날씨가 있는 것이고(D-049), 그 경로는
    이미 날씨 판정이 실내/실외를 의도대로 반영한다("비 오는데 실내로" →
    BAD/indoor=1.00). 여기서 환경으로 갈아타면 같은 조건을 두 번 세는 셈이라
    기존 날씨 판정을 그대로 둔다.

    `any`(실내외 무관)는 `scoring.uses_environment_feature()`가 걸러낸다 —
    되묻기 기본값이 ANY라(D-053) 그 구분이 필요하다.
    """
    if conditions is None or conditions.environment is None:
        return None
    if conditions.weather_intent in (WeatherIntent.AVOID, WeatherIntent.ENJOY):
        return None
    return conditions.environment.value


def _is_weather_explicitly_ignored(
    context: RecommendationContext,
    conditions: UserConditions | None,
) -> bool:
    """weather Feature가 빠졌을 때 "제외했어요"와 "확인 못 했어요" 중 뭘 보여줄지 정한다.

    `conditions`가 있으면 `IGNORE`(상관없다고 명시)만 진짜 opt-out이다. 그 외에
    weather가 빠졌다면(AVOID/ENJOY인데 발화·조회 둘 다 실패 등) 사용자 선택이
    아니라 실패이므로 "확인 못 했어요" 쪽이 맞다. `conditions`가 없는 레거시
    호출자는 그런 구분을 할 수 없어 기존 동작(`context.weather is None`)을 그대로
    쓴다.
    """
    if conditions is not None:
        return conditions.weather_intent is WeatherIntent.IGNORE
    return context.weather is None


def _build_response(
    ranked: tuple[RankedCandidate, ...],
    candidates: tuple[ScoringCandidate, ...],
    details_missing_place_ids: frozenset[str],
    visit_at: datetime,
    *,
    weather_ignored: bool,
    excluded_all_closed: bool = False,
    excluded_closed_place_ids: Sequence[str] = (),
    origin_name: str | None = None,
) -> RecommendationResponse:
    candidate_by_id = {item.place_id: item for item in candidates}
    verified: list[RecommendationItem] = []
    unverified: list[RecommendationItem] = []

    for ranked_item in ranked:
        candidate = candidate_by_id[ranked_item.place_id]
        evidence = build_evidence(ranked_item, origin_name=origin_name)
        explanations = build_explanations(evidence)
        item = RecommendationItem(
            place_id=candidate.place_id,
            name=candidate.name,
            category=candidate.category,
            distance_km=round(candidate.distance_km, 2),
            remaining_minutes=_remaining_minutes(candidate, visit_at),
            operating_hours_display=_operating_hours_display(candidate),
            travel_distance_m=ranked_item.travel_distance_m,
            travel_duration_seconds=ranked_item.travel_duration_seconds,
            travel_mode=ranked_item.travel_mode,
            environment_type=candidate.environment_type,
            recommendation_reason=_recommendation_reason(ranked_item),
            explanations=list(explanations),
            warnings=list(ranked_item.warnings)
            + _extra_warnings(
                ranked_item,
                ranked_item.place_id in details_missing_place_ids,
                explanations,
                weather_ignored=weather_ignored,
            ),
            score=evidence.score,
            feature_scores={
                contribution.feature: contribution.score for contribution in evidence.contributions
            },
            weights_used={
                contribution.feature: contribution.weight
                for contribution in evidence.contributions
                if contribution.weight is not None
            },
        )
        (unverified if ranked_item.is_unverified else verified).append(item)

    return RecommendationResponse(
        recommendations=verified,
        unverified_recommendations=unverified,
        elapsed_ms=0,
        excluded_all_closed=excluded_all_closed,
        excluded_closed_place_ids=list(excluded_closed_place_ids),
    )


def _extra_warnings(
    ranked: RankedCandidate,
    details_missing: bool,
    explanations: tuple[str, ...],
    *,
    weather_ignored: bool,
) -> list[str]:
    """운영시간 결측 외에, 지금까지 조용히 생략되던 두 케이스를 warning으로 보충한다.

    (1) 날씨 결측으로 weather Feature 점수가 없는 경우 — 조회를 안 한 것(IGNORE)과
        조회에 실패한 것을 구분해 서로 다른 문구를 쓴다.
    (2) Feature 점수가 있어도 전부 임계값 미만이라 explanations가 비는 경우
    """
    extra: list[str] = []
    if details_missing and _OPERATING_HOURS_UNVERIFIED_WARNING not in ranked.warnings:
        extra.append(_DETAILS_MISSING_WARNING)
    # 요청 환경으로 채점한 실행에는 weather 키 자체가 없다. 그건 결측이 아니라
    # "이번 실행에 존재하지 않는 Feature"이므로 날씨 warning을 붙이지 않는다.
    if "weather" in ranked.feature_scores and ranked.feature_scores["weather"] is None:
        extra.append(_WEATHER_IGNORED_WARNING if weather_ignored else _WEATHER_MISSING_WARNING)
    if not explanations:
        extra.append(_NO_NOTABLE_EXPLANATION_WARNING)
    return extra


def _operating_hours_display(candidate: ScoringCandidate) -> str | None:
    """그 후보에 적용된 당일 운영 구간을 "09:00~18:00" 형태로 만든다.

    `candidate.operating_hours`는 `_operating_hours_from_context()`가 방문 시각에
    맞춰 이미 고른 값이라 여기서 요일·휴무를 다시 따지지 않는다. 영업 중이 아닌
    후보는 `_is_closed()`가 Scoring 단계에서 이미 걸러내므로, 여기 도달한 값은
    실제로 지금 적용 중인 구간이다.

    자정 마감은 두 가지 뜻으로 들어오므로 `open_time`까지 함께 봐야 한다
    (`operating_hours.py`, `candidate_mapper.py`):
    - `time.min ~ 자정`: 24시간 영업 → "00:00~23:59"로 쓰면 엉뚱하다.
    - `09:00 ~ 자정`: 원문의 "09:00~24:00"(당일 자정 종료). `strftime`을 그대로
      쓰면 "23:59"가 되어 실제보다 1분 일찍 닫는 것처럼 보인다.
    """
    hours = candidate.operating_hours
    if hours is None:
        return None
    if hours.open_time == hours.close_time:
        # 길이 0 구간은 표시할 시각이 없다는 뜻이다 — 유도한 정기 휴무처럼 그날
        # 구간이 원문에 없는 경우다(`candidate_mapper.py`). 그대로 포맷하면
        # "00:00~00:00"이 카드에 찍힌다.
        return None
    closes_at_midnight = hours.close_time in _MIDNIGHT_CLOSE_TIMES
    if hours.open_time == time.min and closes_at_midnight:
        return _ALL_DAY_OPERATING_HOURS_DISPLAY
    close_display = (
        _MIDNIGHT_CLOSE_DISPLAY if closes_at_midnight else hours.close_time.strftime("%H:%M")
    )
    return f"{hours.open_time.strftime('%H:%M')}~{close_display}"


def _remaining_minutes(
    candidate: ScoringCandidate,
    visit_at: datetime,
) -> int | None:
    hours = candidate.operating_hours
    if (
        hours is None
        or hours.is_regular_closure
        or not (hours.open_time <= visit_at.time() < hours.close_time)
    ):
        return None
    close_at = datetime.combine(
        visit_at.date(),
        hours.close_time,
        tzinfo=visit_at.tzinfo,
    )
    return max(0, int((close_at - visit_at).total_seconds() // 60))


def _recommendation_reason(ranked: RankedCandidate) -> str:
    return f"거리·날씨·운영시간 조건을 종합한 {ranked.rank}순위 추천이에요."
