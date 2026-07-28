"""A → D / A → B 변환 함수 모음(부분): 검색 반경 계산, 날씨 조건 추출, 노출 기록 변환.

역할: A가 D(Recommendation)에 넘길 값과 B(State)에 기록할 값을 만드는 변환
함수를 모아둔다. app.services.interpret.state_transform.to_user_conditions()
(B↔A)와 app.services.runtime.context_transform.to_agent_context_request()
(A↔C)와 같은 원칙으로, 이 파일의 각 함수도 정확히 명시된 두 구간만 담당한다 —
서로 다른 변환 지점을 섞지 않는다.
D가 RecommendationContext를 받아 scoring→evidence→explanation까지 처리하는
공개 진입점(`run_recommendation_pipeline_from_context()`)을 제공했다([TECH-02]).
이 파일은 여전히 D 내부(app.domain.*, app.services.recommendation_pipeline)를
import하지 않는다 — 실제 D 호출 코드는
`app.services.runtime.recommendation_provider.RealRecommendationProvider`에 있다.
"""

from __future__ import annotations

from app.schemas import RecommendationResponse, Transport, UserConditions
from app.services.runtime.context_schemas import RecommendationContext
from app.state.service import RecommendedPlace, RecordRecommendationRequest

_DEFAULT_RADIUS_KM = 1.0
_WALK_KM_PER_MIN = 0.07  # 70m/min
_OTHER_KM_PER_MIN = 20 / 60  # 임시: 대중교통/자동차/미언급 공통 가정(20km/h)
_MIN_RADIUS_KM = 0.1
_MAX_RADIUS_KM = 20.0


def to_search_radius_km(conditions: UserConditions) -> float:
    """A의 UserConditions(max_travel_time + transport)를 검색 반경(km)으로 변환한다.

    TODO(D님 확인 대기): 기본 반경(1.0km)과 이동수단별 속도 가정값이 확정되면
    이 함수만 수정하면 된다. 지금은 도보 70m/min(0.07km/min), 그 외(대중교통/
    자동차/미언급)는 임시로 20km/h 단일값을 쓴다. max_travel_time이 없으면
    conditions-schema.md의 missing_conditions 정책대로 기본 반경(1.0km)을
    그대로 쓴다. 결과는 Tool 제약(NearbyPlaceDetailsQuery: 0 < radius ≤ 20)에
    맞춰 [0.1, 20.0] 구간으로 clamp한다.
    """
    if conditions.max_travel_time is None:
        return _DEFAULT_RADIUS_KM

    speed_km_per_min = (
        _WALK_KM_PER_MIN if conditions.transport is Transport.WALK else _OTHER_KM_PER_MIN
    )
    radius = speed_km_per_min * conditions.max_travel_time
    return max(_MIN_RADIUS_KM, min(_MAX_RADIUS_KM, radius))


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
