"""A → D / A → B 변환 함수 모음(부분): 검색 반경 계산, 혼잡도 항목 변환, 노출 기록 변환.

날씨 조건 변환(옛 `to_weather_condition()`)은 D-051로 D에 이관돼 제거됐다 — D가
`resolve_weather_condition()`으로 직접 판정한다(services/recommendation_pipeline.py).

역할: A가 D(Recommendation)에 넘길 값과 B(State)에 기록할 값을 만드는 변환
함수를 모아둔다. app.services.interpret.state_transform.to_user_conditions()
(B↔A)와 app.services.runtime.context_transform.to_agent_context_request()
(A↔C)와 같은 원칙으로, 이 파일의 각 함수도 정확히 명시된 두 구간만 담당한다 —
서로 다른 변환 지점을 섞지 않는다.
이 파일은 D 내부(app.domain.*, app.services.recommendation_pipeline)를 전혀
import하지 않는다 — D 호출은 app.services.runtime.real_recommendation_provider가
담당한다. 예외는 순수 도메인 계약인 app.domain.travel_route(TravelMode)뿐이다.

to_travel_mode()는 A→C(경로 Tool 질의)에 쓰이지만 여기 둔다. 반경 산정과 같은
조건을 봐야만 실측 이동수단과 거리 점수 분모의 단위가 맞기 때문에(D-042 성격의
조용한 불일치를 막는다), 두 함수를 떼어놓지 않는 것을 우선했다.
"""

from __future__ import annotations

from app.domain.travel_route import TravelMode
from app.place_search_policy import (
    DEFAULT_PLACE_SEARCH_RADIUS_KM,
    MAX_PLACE_SEARCH_RADIUS_KM,
    MIN_PLACE_SEARCH_RADIUS_KM,
    WALKING_SPEED_KM_PER_MINUTE,
)
from app.schemas import (
    RecommendationResponse,
    Transport,
    UserConditions,
)
from app.services.runtime.context_schemas import RecommendationContext
from app.state.service import RecommendedPlace, RecordRecommendationRequest

# A가 D에 넘기는 search_radius_km은 C가 실제 후보를 조회한 반경과 일관돼야
# 거리 점수 정규화가 어긋나지 않는다. 공통 기본값과 최소·최대 범위는
# place_search_policy에서 함께 관리한다.
_OTHER_KM_PER_MIN = 20 / 60  # 임시: 대중교통/자동차/미언급 공통 가정(20km/h)


def _radius_uses_walking_speed(conditions: UserConditions) -> bool:
    """검색 반경이 도보 속도로 만들어지는 요청인지 판정한다.

    반경 산정(to_search_radius_km)과 실측 이동수단 선택(to_travel_mode)이 같은
    조건을 봐야 한다 — 거리 점수의 분모가 반경을 이동수단 속도로 되돌린 값이라
    (scoring.py::_travel_minutes_budget) 둘이 어긋나면 분자와 단위가 맞지 않는다.
    """
    return conditions.transport is Transport.WALK or conditions.max_travel_time is None


def to_travel_mode(conditions: UserConditions) -> TravelMode | None:
    """실측 경로를 어떤 이동수단으로 조회할지 정한다. None이면 조회하지 않는다.

    반경이 도보 속도로 만들어진 요청(도보 명시 또는 이동시간 미언급의 기본
    반경)은 도보로 조회한다.

    이동수단을 말하지 않고 이동시간만 말한 요청은 반경이 20km/h 가정으로
    커져 있지만(_OTHER_KM_PER_MIN) 그 20km/h가 대중교통인지 자동차인지는
    발화에 없다. 무엇으로 재야 할지 모르므로 실측하지 않는다 — 지금도 그
    경우 D가 도보 실측을 버리므로(real_recommendation_provider.py의
    _walking_routes_for) 결과는 같고, 낭비 호출만 사라진다.
    """
    if _radius_uses_walking_speed(conditions):
        return TravelMode.WALKING
    if conditions.transport is Transport.PUBLIC:
        return TravelMode.TRANSIT
    if conditions.transport is Transport.CAR:
        return TravelMode.DRIVING
    return None


def to_search_radius_km(conditions: UserConditions) -> float:
    """A의 이동시간과 이동수단 조건을 검색 반경(km)으로 변환한다.

    max_travel_time이 없으면 공통 기본 반경을 사용한다. 도보는 70m/min,
    그 외 이동수단과 미언급은 임시로 20km/h를 적용하고, 결과는 공통
    최소·최대 검색 반경 구간으로 제한한다.
    """
    if conditions.max_travel_time is None:
        return DEFAULT_PLACE_SEARCH_RADIUS_KM

    speed_km_per_min = (
        WALKING_SPEED_KM_PER_MINUTE
        if _radius_uses_walking_speed(conditions)
        else _OTHER_KM_PER_MIN
    )
    radius = speed_km_per_min * conditions.max_travel_time
    return max(
        MIN_PLACE_SEARCH_RADIUS_KM,
        min(MAX_PLACE_SEARCH_RADIUS_KM, radius),
    )


def to_concentration_entries(context: RecommendationContext) -> list[object] | None:
    """C의 RecommendationContext.concentration을 D에 넘길 형태로 변환한다.

    (A 제안, D/C 확인 필요 — concentration-conditions.md §2.3/§4.2) 반환 타입은
    잠정이다: 원본 리스트를 그대로 넘길지, place_name으로 매핑한 dict로 바꿀지는
    D의 Scoring 입력 형태에 맞춰 확정한다.

    C가 아직 RecommendationContext에 concentration 필드를 추가하지 않은
    과도기에는(a-c-context-contract-draft.md §5.1 제안 상태) getattr 기본값으로
    안전하게 None을 반환한다 — 필드 자체가 없어도 AttributeError로 죽지 않는다.
    C가 필드를 추가하면 이 함수는 코드 변경 없이 정상 동작하기 시작한다.

    status가 "success"/"partial"일 때만 데이터를 반환한다. 그 외(no_data/
    unavailable, concentration 자체가 없음)는 None을 반환해, D가
    weather/remaining_operating_time 결측과 동일한 redistribute_weights()
    경로로 concentration 가중치를 재분배하게 한다.
    """
    concentration = getattr(context, "concentration", None)
    if concentration is None:
        return None
    if concentration.status not in ("success", "partial") or concentration.data is None:
        return None
    return list(concentration.data)


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
            RecommendedPlace(
                place_id=item.place_id,
                rank=index + 1,
                distance_km=item.distance_km,
                remaining_minutes=item.remaining_minutes,
                environment_type=item.environment_type,
            )
            for index, item in enumerate(shown)
        ],
    )


__all__ = [
    "to_search_radius_km",
    "to_concentration_entries",
    "to_record_recommendation_request",
]
