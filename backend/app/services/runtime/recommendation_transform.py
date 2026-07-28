"""A → D / A → B 변환 함수 모음(부분): 검색 반경 계산, 날씨 조건 추출, 노출 기록 변환.

역할: A가 D(Recommendation)에 넘길 값과 B(State)에 기록할 값을 만드는 변환
함수를 모아둔다. app.services.interpret.state_transform.to_user_conditions()
(B↔A)와 app.services.runtime.context_transform.to_agent_context_request()
(A↔C)와 같은 원칙으로, 이 파일의 각 함수도 정확히 명시된 두 구간만 담당한다 —
서로 다른 변환 지점을 섞지 않는다.
이 파일은 D 내부(app.domain.*, app.services.recommendation_pipeline)를 전혀
import하지 않는다 — D 호출은 app.services.runtime.real_recommendation_provider가
담당한다.
"""

from __future__ import annotations

<<<<<<< HEAD
from app.schemas import RecommendationResponse, UserConditions
from app.services.runtime.context_schemas import RecommendationContext
from app.state.service import RecommendedPlace, RecordRecommendationRequest

# app.agent_context.service._resolve_search_radius_km()와 동일한 값이어야 한다.
# C가 context.places를 조회할 때 실제로 이 공식으로 반경을 계산하므로, A가 D에
# 넘기는 search_radius_km도 같은 값이어야 거리 점수 정규화가 어긋나지 않는다
# (run_recommendation_pipeline_from_context() docstring 참고). C가 공식을 바꾸면
# 이 함수도 같이 바꿔야 한다.
_DEFAULT_RADIUS_KM = 2.0
_WALKING_KM_PER_MINUTE = 0.07  # 70m/min. transport 값과 무관하게 항상 이 속도를 쓴다.
_MIN_RADIUS_KM = 0.3
_MAX_RADIUS_KM = 20.0
=======
from app.place_search_policy import (
    DEFAULT_PLACE_SEARCH_RADIUS_KM,
    MAX_PLACE_SEARCH_RADIUS_KM,
    MIN_PLACE_SEARCH_RADIUS_KM,
    WALKING_SPEED_KM_PER_MINUTE,
)
from app.schemas import RecommendationResponse, Transport, UserConditions
from app.services.runtime.context_schemas import RecommendationContext
from app.state.service import RecommendedPlace, RecordRecommendationRequest

_OTHER_KM_PER_MIN = 20 / 60  # 임시: 대중교통/자동차/미언급 공통 가정(20km/h)
>>>>>>> develop


def to_search_radius_km(conditions: UserConditions) -> float:
    """A의 UserConditions.max_travel_time을 검색 반경(km)으로 변환한다.

    C(app.agent_context.service._resolve_search_radius_km())와 정확히 동일한
    공식이다 — C가 context.places를 조회할 때 이 공식으로 반경을 계산하므로,
    A가 D에 넘기는 값도 같아야 한다. max_travel_time이 없으면 기본 반경
    2.0km을 쓴다. transport는 쓰지 않는다(C도 안 씀 — MVP는 도보 속도만
    가정). 결과는 [0.3, 20.0] 구간으로 clamp한다.
    """
    if conditions.max_travel_time is None:
        return DEFAULT_PLACE_SEARCH_RADIUS_KM

<<<<<<< HEAD
    estimated_radius = conditions.max_travel_time * _WALKING_KM_PER_MINUTE
    return max(_MIN_RADIUS_KM, min(_MAX_RADIUS_KM, estimated_radius))
=======
    speed_km_per_min = (
        WALKING_SPEED_KM_PER_MINUTE
        if conditions.transport is Transport.WALK
        else _OTHER_KM_PER_MIN
    )
    radius = speed_km_per_min * conditions.max_travel_time
    return max(
        MIN_PLACE_SEARCH_RADIUS_KM,
        min(MAX_PLACE_SEARCH_RADIUS_KM, radius),
    )
>>>>>>> develop


def to_weather_condition(context: RecommendationContext) -> str | None:
    """C의 RecommendationContext.weather를 D에 넘길 날씨 조건 문자열로 변환한다.

    status가 "success"일 때만 condition 값(good/neutral/bad)을 반환한다. 그 외
    (no_data/partial/unsupported/unavailable, weather 자체가 없음)는 None을
    반환한다 — D의 explanation.py가 날씨 결측을 이미 warnings로 반영하므로,
    A는 결측 여부를 따로 판단하지 않고 그대로 None을 넘기기만 하면 된다.
    """
    weather = context.weather
    if weather is None or weather.status != "success" or weather.data is None:
        return None
    return weather.data.condition


def to_record_recommendation_request(
    session_id: str,
    run_id: str,
    response: RecommendationResponse,
) -> RecordRecommendationRequest:
    """A→B 변환: D의 RecommendationResponse를 B의 RecordRecommendationRequest로 변환한다.

    recommendations + unverified_recommendations를 배열 순서 그대로 이어붙이고
    1부터 rank를 매긴다. response에 담긴 항목은 전부 이미 "실제로 노출된 것"
    이므로(계산만 하고 안 보여준 건 애초에 response에 없다) 별도 필터링 없이
    그대로 쓴다.
    """
    shown = [*response.recommendations, *response.unverified_recommendations]
    return RecordRecommendationRequest(
        session_id=session_id,
        run_id=run_id,
        recommended=[
            RecommendedPlace(place_id=item.place_id, rank=index + 1)
            for index, item in enumerate(shown)
        ],
    )


__all__ = [
    "to_search_radius_km",
    "to_weather_condition",
    "to_record_recommendation_request",
]
