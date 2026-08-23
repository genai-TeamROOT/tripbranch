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
    PlaceType,
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


# 단어 하나짜리 질의("조용한")는 문장형 리뷰 텍스트와 임베딩이 잘 안 맞는다.
# place_tag도 place_type도 모르는 요청의 마지막 폴백 — 아예 안 붙이는 것보다는
# 낫다(실측: 경복궁 카페 30곳에서 "조용한" 1곳 컷 통과 → "조용한 곳" 6곳).
_GENERIC_TASTE_SUFFIX = "곳"

# place_tag가 비었을 때 쓸 place_type의 한국어 라벨.
#
# "식당"/"레스토랑"처럼 넓은 유형을 말한 발화는 place_tags가 비고 place_types만
# 채워진다(태그는 한식·카페 같은 세분류만 있다). 그때 일반 접미어로 떨어지면
# 개선 효과를 거의 못 받아서, 유형명을 대신 붙인다.
#
# **라벨은 후보를 여러 개 실측해서 골랐다**(2026-08-23, 경복궁 반경 3km,
# 질의 "조용한", 컷 0.43 통과 수 / 매칭 수. 원자료는
# test_results/taste_query_enrichment.csv):
#
#   attraction         곳 9/95   → 관광지 28/95  (명소 27, 볼거리 19)
#   cultural_facility  곳 7/74   → 문화시설 14/74 (전시 17, 박물관 21)
#   shopping           곳 4/310  → 상점 14/310  (쇼핑 6, 쇼핑몰 6)
#   restaurant         곳 11/154 → 맛집 63/154  (음식점 29, 식당 21)
#
# **통과 수가 제일 큰 라벨을 그냥 고르지는 않았다.** cultural_facility는
# "박물관"(21건)이 수치상 제일 높은데도 "문화시설"(14건)을 택했다 — 인용문을
# 열어보니 "박물관"은 조용함이 아니라 박물관다움("알찬 박물관!", "퀄리티가
# 괜찮은 박물관")을 끌어왔다. 문화시설의 **일부 하위종**이라 도서관·갤러리
# 후보를 박물관 쪽으로 잘못 당긴다. 반면 restaurant의 "맛집"은 음식점 전반에
# 두루 쓰이는 리뷰 단어라 같은 왜곡이 없었다 — 인용문이 "조용하고 디저트도
# 맛있는", "한적한 공간", "고요한 안식처"처럼 조용함을 그대로 짚었다.
#
# festival·leisure는 **일부러 뺐다.** 효과가 없거나 오히려 나빠서다
# (축제 곳 1/19 → 축제 0/19 · 행사 0/19, 레저는 후보 6곳 전부 어느 라벨로도 0).
# 여기 없는 유형은 일반 접미어로 떨어진다.
_PLACE_TYPE_TASTE_LABELS: dict[PlaceType, str] = {
    PlaceType.ATTRACTION: "관광지",
    PlaceType.CULTURAL_FACILITY: "문화시설",
    PlaceType.SHOPPING: "상점",
    PlaceType.RESTAURANT: "맛집",
}


def _enrich_taste_query(conditions: UserConditions) -> str:
    """검색 질의에 장소 유형을 붙여 문장형 리뷰 텍스트와 임베딩이 더 잘
    맞게 만든다.

    실측(2026-08-23, 경복궁 반경 3km 카페 30곳, `search_place_evidence`
    p_min_similarity=0.0): "조용한"은 컷(0.43) 통과 1/30곳(평균 0.31)뿐인데
    "조용한 카페"로 place_tag를 붙이면 25/30곳(평균 0.48)으로 뛴다. 종로 4개
    지점 전부에서 같은 폭으로 재현된다(0~1곳 → 19~25곳). 컷을
    낮추는 대신 이 방법을 쓰는 이유는 장소 유형이 하드 필터 단계에서 이미
    확정된 값이라 새 정보를 만드는 게 아니고, 컷을 낮출 때처럼 관련 없는
    약한 매치를 끌어들이는 부작용도 없기 때문이다.

    붙일 말은 좁은 것부터 고른다 — place_tag(카페·박물관 등 세분류)가 있으면
    그걸 쓰고, 없으면 place_type의 라벨(`_PLACE_TYPE_TASTE_LABELS`), 그것도
    없으면 일반 접미어다.
    """
    if conditions.place_tags:
        return f"{conditions.taste_query} {' '.join(conditions.place_tags)}"
    type_labels = [
        label
        for place_type in conditions.place_types
        if (label := _PLACE_TYPE_TASTE_LABELS.get(place_type)) is not None
    ]
    if type_labels:
        return f"{conditions.taste_query} {' '.join(type_labels)}"
    return f"{conditions.taste_query} {_GENERIC_TASTE_SUFFIX}"


def _log_taste_matches(
    query: str, candidate_count: int, matches: dict[str, PlaceEvidenceMatch]
) -> None:
    """취향 검색이 무엇을 찾았는지 한 줄로 남긴다.

    "taste가 0으로 나온다"는 관찰만으로는 검색이 아예 실패한 것인지, 컷을 넘는
    근거가 없어서 0점이 된 것인지 구분이 안 된다 — 이 로그로 그 둘을 가른다.

    **인용문은 찍지 않는다.** 같은 내용이 `RecommendationItem.taste_evidence`로
    응답에 실려 개발자 디버그 화면에 나오므로 로그로 반복하면 중복이다. 여기
    남기는 건 화면에 안 나오는 값(실제로 나간 **보강된 질의**와 후보 수)뿐이다.
    """
    logger.info(
        "취향 근거 검색: 질의=%r 후보=%d곳 → 매칭 %d곳%s",
        query,
        candidate_count,
        len(matches),
        "" if matches else " (컷 0.43 이상 근거 없음)",
    )


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

        enriched_query = _enrich_taste_query(conditions)
        try:
            result = await self._place_evidence.search(enriched_query, place_ids)
        except Exception:
            logger.exception("취향 근거 검색 실패 — 취향 없이 채점한다")
            return None
        _log_taste_matches(enriched_query, len(place_ids), result.data)
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
