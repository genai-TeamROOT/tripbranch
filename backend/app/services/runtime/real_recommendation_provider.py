"""RecommendationProvider Protocol을 만족하는 실제 D(Recommendation) 호출 구현체.

역할: C가 만든 RecommendationContext를 D의 공개 진입점
(app.services.recommendation_pipeline.run_recommendation_pipeline_from_context())에
그대로 넘겨 실제 추천 결과를 받는다. D 내부(candidate_mapper/scoring/evidence/
explanation)는 이 진입점 하나만 거쳐 호출하고 직접 import하지 않는다.
AppError는 여기서 잡지 않고 그대로 전파한다 — RecommendationProvider Protocol의
반환 타입에 에러 variant가 없고, app.main의 전역 exception_handler(AppError)가
처리하도록 하는 게 기존 코드베이스 관례(run_recommendation_pipeline())와 일치한다.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from app.agent_context.enrichment_schemas import CandidateEnrichmentResponse
from app.domain.models import PlaceEvidenceMatch
from app.domain.travel_route import TravelRoute
from app.providers.place_evidence import PlaceEvidenceProvider
from app.schemas import (
    ConcentrationIntent,
    RecommendationResponse,
    UserConditions,
)
from app.services.recommendation_pipeline import (
    PreparedRecommendationResult,
    merge_prepared_recommendations,
    prepare_recommendation_from_context,
    rerank_with_concentration,
    resolve_origin_name,
    resolve_weather_condition,
    score_prepared_recommendation,
)
from app.services.runtime.context_schemas import RecommendationContext
from app.services.runtime.recommendation_transform import to_search_radius_km, to_travel_mode

_KST = ZoneInfo("Asia/Seoul")
logger = logging.getLogger(__name__)

_RECOMMENDATION_LIMIT = 5


def _measured_routes_for(
    conditions: UserConditions,
    travel_routes: tuple[TravelRoute, ...],
) -> tuple[TravelRoute, ...]:
    """실측을 거리 Feature에 쓸 수 있는 요청인지 판정한다.

    거리 점수의 분모는 검색 반경을 이동수단 속도로 되돌린 값이라(`scoring.py::
    _travel_minutes_budget()`), 반경을 만든 속도와 실측한 이동수단의 속도가 같은
    요청에서만 분자와 단위가 맞는다. 그 두 선택을 한 조건으로 묶는 것이
    `to_travel_mode()`이므로, 그것이 이동수단을 정하지 못한 요청(None)만 버린다.

    조건을 여기 다시 적지 않는 이유가 그것이다 — 같은 판정이 두 군데 있으면
    한쪽만 바뀌었을 때 조용히 어긋난다. 새 이동수단은 속도
    (`TRAVEL_SPEED_KM_PER_MINUTE`)만 채우면 여기까지 자동으로 열린다.

    지금 버려지는 것은 이동시간을 말했지만 이동수단을 말하지 않은 요청이다.
    반경이 20km/h 가정으로 커져 있는데 그 20km/h가 무엇인지 발화에 없어서
    `to_travel_mode()`가 조회 자체를 건너뛰므로, 애초에 실측이 오지 않는다.

    속도가 아직 없는 이동수단(대중교통)은 **여기서 막지 않는다.** 그런 경로가
    채점까지 오면 `_travel_minutes_budget()`이 KeyError로 멈추는 편이 낫다는 것이
    이미 선 결정이다(place_search_policy.TRAVEL_SPEED_KM_PER_MINUTE 주석). 여기서
    조용히 걸러내면 그 신호가 사라진다 — 지금은 Provider가 미등록이라 실측 자체가
    오지 않으므로 실제로 그 경로는 만들어지지 않는다.
    """
    return travel_routes if to_travel_mode(conditions) is not None else ()


class RealRecommendationProvider:
    """RecommendationProvider Protocol 구현체 — D의 공개 진입점만 호출한다."""

    # 클래스 기본값으로 둔다. 이 클래스를 상속해 __init__을 부르지 않는
    # 테스트 대역(tests/test_agent_runtime.py)이 있어, 인스턴스 속성으로만
    # 두면 그쪽이 깨진다.
    _place_evidence: PlaceEvidenceProvider | None = None

    def __init__(
        self,
        place_evidence: PlaceEvidenceProvider | None = None,
    ) -> None:
        """취향 근거 Provider는 선택이다.

        None이면 채점이 taste Feature를 아예 쓰지 않는다. 임베딩 모델이 선택
        의존성이고 서버 상주 비용(실측 RSS 537MB)이 있어, 모델을 올릴 수 없는
        배포에서도 추천은 그대로 동작해야 하기 때문이다.

        도보 경로와 달리 A가 조회해 넘기지 않고 D가 직접 부른다 — 취향 발화는
        `conditions.taste_query`로 이미 도착해 있고, 이 값을 쓰는 곳이 D의 점수
        계산뿐이라 A가 중계할 이유가 없다.
        """
        self._place_evidence = place_evidence

    def merge_prepared(
        self,
        results: Sequence[PreparedRecommendationResult],
    ) -> PreparedRecommendationResult:
        return merge_prepared_recommendations(results)

    async def prepare(
        self,
        conditions: UserConditions,
        context: RecommendationContext,
        excluded_place_ids: list[str],
        *,
        visit_at: datetime,
        ignore_operating_hours: bool = False,
    ) -> PreparedRecommendationResult:
        return await prepare_recommendation_from_context(
            context,
            conditions=conditions,
            visit_at=visit_at,
            shown_place_ids=frozenset(excluded_place_ids),
            ignore_operating_hours=ignore_operating_hours,
        )

    async def score_prepared(
        self,
        conditions: UserConditions,
        prepared: PreparedRecommendationResult,
        *,
        travel_routes: tuple[TravelRoute, ...] = (),
        limit: int = _RECOMMENDATION_LIMIT,
    ) -> RecommendationResponse:
        return await score_prepared_recommendation(
            prepared,
            search_radius_km=to_search_radius_km(conditions),
            recommendation_limit=limit,
            travel_routes=_measured_routes_for(conditions, travel_routes),
            taste_matches=await self._taste_matches_for(conditions, prepared),
        )

    async def _taste_matches_for(
        self,
        conditions: UserConditions,
        prepared: PreparedRecommendationResult,
    ) -> dict[str, PlaceEvidenceMatch] | None:
        """취향 근거를 하드 필터 통과 후보 범위 안에서만 찾는다.

        None을 돌려주면 채점이 taste Feature를 쓰지 않는다. 빈 dict는 "취향을
        말했는데 근거를 못 찾았다"라 Feature가 켜지고 모든 후보가 0점이 된다 —
        둘을 구분해야 취향 미언급 요청의 가중치가 바뀌지 않는다.

        검색 실패는 추천 전체를 막지 않는다. 취향은 순위를 다듬는 축이지
        후보를 만드는 축이 아니라서, 실패하면 취향 없이 채점하는 편이 낫다.
        """
        if self._place_evidence is None or not conditions.taste_query:
            return None

        place_ids = [
            item.candidate.place_id
            for item in prepared.preparation.eligible_candidates
        ]
        if not place_ids:
            return None

        try:
            result = await self._place_evidence.search(
                conditions.taste_query, place_ids
            )
        except Exception:
            logger.exception("취향 근거 검색 실패 — 취향 없이 채점한다")
            return None
        return result.data

    async def recommend(
        self,
        conditions: UserConditions,
        context: RecommendationContext,
        excluded_place_ids: list[str],
        limit: int = _RECOMMENDATION_LIMIT,
        ignore_operating_hours: bool = False,
    ) -> RecommendationResponse:
        prepared = await self.prepare(
            conditions,
            context,
            visit_at=datetime.now(_KST),
            excluded_place_ids=excluded_place_ids,
            ignore_operating_hours=ignore_operating_hours,
        )
        return await self.score_prepared(conditions, prepared, limit=limit)

    async def rerank_with_concentration(
        self,
        conditions: UserConditions,
        context: RecommendationContext,
        first_pass: RecommendationResponse,
        concentration: CandidateEnrichmentResponse,
    ) -> RecommendationResponse:
        """D-040/D-051: 2차 Scoring. A는 concentration_intent가 AVOID/SEEK일 때만 이
        메서드를 호출한다(agent_runtime.py의 `_CONCENTRATION_RANK_INTENTS` 게이트) —
        그 외 값이 들어오면 방향을 정할 수 없으므로 AVOID(한적한 곳 선호)로 취급한다.

        날씨 판정은 1차 `recommend()`와 동일하게 `resolve_weather_condition()`으로
        여기서 다시 계산한다 — 호출부(agent_runtime.py)가 C의 옛 3단계 판정을 직접
        읽어 넘기던 방식(`to_weather_condition()`)은 1차와 2차의 판정이 갈라질 수
        있어 폐기했다. `context`는 1차 호출에 쓴 것과 같은 RecommendationContext여야
        한다.
        """
        seek = conditions.concentration_intent is ConcentrationIntent.SEEK
        weather_condition, weather_reason = resolve_weather_condition(context, conditions)
        return await rerank_with_concentration(
            first_pass,
            weather_condition,
            concentration,
            seek=seek,
            weather_reason=weather_reason,
            # 날씨 판정과 같은 이유로 여기서 context에서 다시 뽑는다 — 1차와 2차가
            # 같은 기준점 이름을 써야 근거 문장이 갈리지 않는다.
            origin_name=resolve_origin_name(context),
        )


__all__ = ["RealRecommendationProvider"]
