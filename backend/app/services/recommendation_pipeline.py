"""RecommendationContext를 Scoring→Evidence→Explanation으로 조립하는 추천 파이프라인.

D는 C Tool을 직접 호출하지 않는다([TECH-02]). Tool 조회는 호출자(A, 또는
`app/services/recommendations.py`처럼 아직 조건 스키마 통합 전인 레거시
호출자)가 맡고, D는 그 결과인 RecommendationContext만 입력으로 받는다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from time import perf_counter
from typing import TypeAlias

from app.agent_context.schemas import RecommendationContext
from app.domain.candidate_mapper import map_context_to_scoring_candidates
from app.domain.evidence import build_evidence
from app.domain.explanation import build_explanations
from app.domain.models import ScoringCandidate, WeatherCondition
from app.domain.scoring import RankedCandidate, score_candidates
from app.errors import AppError
from app.recommendation_limits import DEFAULT_RECOMMENDATION_RESULT_LIMIT
from app.schemas import RecommendationItem, RecommendationResponse

_OPERATING_HOURS_UNVERIFIED_WARNING = "방문 전에 운영 여부를 확인해주세요."
_DETAILS_MISSING_WARNING = "장소 상세정보 일부를 확인하지 못했습니다."
# 날씨가 Scoring에 빠지는 이유는 두 가지이고, 사용자에게 같은 말로 알리면 안 된다.
# (1) 조회 자체를 안 한 경우: weather_intent=IGNORE(= 발화에 날씨 언급 없음)면 C가
#     Weather Tool을 실행하지 않는다(tool_rules.py). 정상 흐름이므로 오류처럼 알리지
#     않는다. int-01-recommend.md §8의 IGNORE 정의 참고.
# (2) 조회했으나 실패한 경우: 날씨 API 장애 등 — 이때만 "확인하지 못했다"가 사실이다.
_WEATHER_IGNORED_WARNING = "날씨 조건을 따로 말씀하지 않으셔서 이번 추천에는 반영하지 않았어요."
_WEATHER_MISSING_WARNING = "현재 날씨 정보를 확인하지 못해 이 조건은 반영되지 않았어요."
_NO_NOTABLE_EXPLANATION_WARNING = (
    "이 장소는 특별히 강조할 만한 조건은 없지만, 조건에 맞아 추천했어요."
)

Timer: TypeAlias = Callable[[], float]


async def run_recommendation_pipeline_from_context(
    context: RecommendationContext | None,
    *,
    visit_at: datetime,
    search_radius_km: float,
    shown_place_ids: frozenset[str] = frozenset(),
    rejected_place_ids: frozenset[str] = frozenset(),
    recommendation_limit: int = DEFAULT_RECOMMENDATION_RESULT_LIMIT,
    timer: Timer = perf_counter,
) -> RecommendationResponse:
    """D의 유일한 공개 진입점. A가 C에서 받은 RecommendationContext를 그대로
    넘기면, D 내부(후보 변환→Scoring→Evidence→Explanation 조립)를 전부 처리해
    RecommendationResponse만 반환한다. C Tool을 직접 호출하지 않는다([TECH-02]).

    호출자 책임: `search_radius_km`은 C가 `context.places`를 조회할 때 실제로
    사용한 검색 반경과 동일해야 한다 — Scoring의 거리 점수 정규화
    (`max_distance_km`)가 이 값을 그대로 재사용하기 때문이다
    (`docs/design/recommendation-scoring.md` 참고). 값이 어긋나면 거리 점수가
    실제 후보 풀 범위와 안 맞게 계산된다.

    Context 상태 처리: `context` 자체가 `None`이거나(예: A의
    `AgentContextResponse.status`가 `needs_clarification`/`unsupported`/
    `unavailable`일 때), `location`/`places`가 없거나 `unavailable`(조회
    자체 실패)이면 `AppError`를 던진다. `no_data`(정상 조회했지만 결과
    없음)는 에러가 아니라 빈 `RecommendationResponse`로 처리한다 —
    "확인 못 함"과 "확인했는데 없음"은 다른 상황이라 구분한다.
    """
    started_at = timer()

    if context is None:
        raise AppError(
            code="context_unavailable",
            message="Context 정보가 없습니다.",
            status_code=502,
            retryable=True,
        )

    location = context.location
    if (
        location is None
        or location.status not in {"success", "partial"}
        or location.data is None
    ):
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
    weather_condition = _weather_condition_from_context(context)

    scoring = score_candidates(
        candidates,
        now=visit_at,
        weather_condition=weather_condition,
        max_distance_km=search_radius_km,
        shown_place_ids=shown_place_ids,
        rejected_place_ids=rejected_place_ids,
    )
    ranked = scoring.ranked[:recommendation_limit]

    details_missing_place_ids = frozenset(
        place.place_id
        for place in (places.data or [])
        if place.operating_schedule is None
    )
    # context.weather가 아예 없으면 C가 Weather Tool을 실행하지 않았다는 뜻이다
    # (weather_intent=IGNORE). 값이 있는데 status가 실패인 경우와 구분한다.
    response = _build_response(
        ranked,
        candidates,
        details_missing_place_ids,
        visit_at,
        weather_ignored=context.weather is None,
    )
    return response.model_copy(
        update={"elapsed_ms": round((timer() - started_at) * 1000, 2)}
    )


def _weather_condition_from_context(
    context: RecommendationContext,
) -> WeatherCondition | None:
    weather = context.weather
    if weather is None or weather.status not in {"success", "partial"} or weather.data is None:
        return None
    return WeatherCondition(weather.data.condition)


def _build_response(
    ranked: tuple[RankedCandidate, ...],
    candidates: tuple[ScoringCandidate, ...],
    details_missing_place_ids: frozenset[str],
    visit_at: datetime,
    *,
    weather_ignored: bool,
) -> RecommendationResponse:
    candidate_by_id = {item.place_id: item for item in candidates}
    verified: list[RecommendationItem] = []
    unverified: list[RecommendationItem] = []

    for ranked_item in ranked:
        candidate = candidate_by_id[ranked_item.place_id]
        evidence = build_evidence(ranked_item)
        explanations = build_explanations(evidence)
        item = RecommendationItem(
            place_id=candidate.place_id,
            name=candidate.name,
            category=candidate.category,
            distance_km=round(candidate.distance_km, 2),
            remaining_minutes=_remaining_minutes(candidate, visit_at),
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
                contribution.feature: contribution.score
                for contribution in evidence.contributions
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
    if ranked.feature_scores.get("weather") is None:
        extra.append(
            _WEATHER_IGNORED_WARNING if weather_ignored else _WEATHER_MISSING_WARNING
        )
    if not explanations:
        extra.append(_NO_NOTABLE_EXPLANATION_WARNING)
    return extra


def _remaining_minutes(
    candidate: ScoringCandidate,
    visit_at: datetime,
) -> int | None:
    hours = candidate.operating_hours
    if hours is None or not (hours.open_time <= visit_at.time() < hours.close_time):
        return None
    close_at = datetime.combine(
        visit_at.date(),
        hours.close_time,
        tzinfo=visit_at.tzinfo,
    )
    return max(0, int((close_at - visit_at).total_seconds() // 60))


def _recommendation_reason(ranked: RankedCandidate) -> str:
    return (
        f"거리·날씨·운영시간 조건을 종합한 {ranked.rank}순위 추천이에요."
    )
