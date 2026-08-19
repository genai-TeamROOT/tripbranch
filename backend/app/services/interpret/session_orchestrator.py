"""세션의 최신 컨텍스트(GPS 포함)를 확보한다.

역할: Intent 분류/조건 추출 전에, 세션의 현재 상태(SessionContextResponse)를 최신 GPS
정보까지 반영해서 확보한다. B(Agent State)의 get_session_context()/update_api_context()를
조합해서 쓴다.
입력: session_id(없으면 새 세션), device_location("위도,경도" 문자열 — api_context.gps_location과
동일 포맷).
출력: 최신 SessionContextResponse.

알려진 한계(TODO, interpret 통합 시 해결): get_session_context()/update_api_context()는
세션을 새로 만들지 않는다(B 계약상 read-only). 세션은 오직 apply()만 생성한다. 따라서
session_id가 아직 없는 최초 턴에서는 이 함수가 GPS를 심을 세션이 없어 gps_expired=True인
채로 그대로 반환한다 — 그 턴의 apply()가 세션을 만든 뒤, 곧바로 이어서
update_api_context()를 한 번 더 호출해 GPS를 심는 후속 처리가 필요하다. 이 후속 처리는
interpret.py 통합 작업(다음 세션)에서 연결한다.

(2026-08-05, D-038) 과거에는 GPS와 함께 날씨(api_context.api_weather)도 여기서
조회·저장했으나, 이 값을 실제로 읽는 소비자가 backend/frontend 어디에도 없어 제거했다
— 실제 RECOMMEND 날씨 Feature는 C의 context.weather 경로(weather_intent 게이팅)를 통해
완전히 별도로 확보된다. 상세 근거는 decision-log.md D-038 참고.
"""

from __future__ import annotations

from app.state.schema import now_kst
from app.state.service import (
    SessionContextResponse,
    UpdateApiContextRequest,
    get_session_context,
    update_api_context,
)
from app.state.store import StateStore


async def ensure_current_context(
    session_id: str | None,
    device_location: str | None,
    *,
    store: StateStore | None = None,
) -> SessionContextResponse:
    """GPS를 최신화한 SessionContextResponse를 반환한다."""

    context = get_session_context(session_id, store=store)

    should_update_gps = (
        context.session_exists
        and device_location is not None
        and (context.api_context.gps_expired or context.api_context.gps_location != device_location)
    )
    if should_update_gps:
        update_api_context(
            UpdateApiContextRequest(
                session_id=context.session_id,
                gps_location=device_location,
                gps_location_updated_at=now_kst(),
            ),
            store=store,
        )
        context = get_session_context(context.session_id, store=store)

    return context


__all__ = ["ensure_current_context"]
