"""세션의 최신 컨텍스트(GPS·날씨 포함)를 확보한다.

역할: Intent 분류/조건 추출 전에, 세션의 현재 상태(SessionContextResponse)를 최신 GPS·날씨
정보까지 반영해서 확보한다. B(Agent State)의 get_session_context()/update_api_context()를
조합해서 쓴다.
입력: session_id(없으면 새 세션), device_location("위도,경도" 문자열 — api_context.gps_location과
동일 포맷), 날씨 조회에 쓸 WeatherProvider.
출력: 최신 SessionContextResponse.

알려진 한계(TODO, interpret 통합 시 해결): get_session_context()/update_api_context()는
세션을 새로 만들지 않는다(B 계약상 read-only). 세션은 오직 apply()만 생성한다. 따라서
session_id가 아직 없는 최초 턴에서는 이 함수가 GPS를 심을 세션이 없어 gps_expired=True인
채로 그대로 반환한다 — 그 턴의 apply()가 세션을 만든 뒤, 곧바로 이어서
update_api_context()를 한 번 더 호출해 GPS를 심는 후속 처리가 필요하다. 이 후속 처리는
interpret.py 통합 작업(다음 세션)에서 연결한다.
"""

from __future__ import annotations

from datetime import datetime

from app.providers.protocols import WeatherProvider
from app.state.schema import now_kst
from app.state.service import (
    SessionContextResponse,
    UpdateApiContextRequest,
    get_session_context,
    update_api_context,
)
from app.state.store import StateStore
from app.tools.contracts import ToolStatus
from app.tools.weather_forecast import GetWeatherForecastTool, WeatherForecastQuery


async def ensure_current_context(
    session_id: str | None,
    device_location: str | None,
    weather_provider: WeatherProvider,
    *,
    visit_at: datetime | None = None,
    store: StateStore | None = None,
) -> SessionContextResponse:
    """GPS·날씨를 최신화한 SessionContextResponse를 반환한다."""

    context = get_session_context(session_id, store=store)

    if context.session_exists and context.api_context.gps_expired and device_location:
        update_api_context(
            UpdateApiContextRequest(
                session_id=context.session_id,
                gps_location=device_location,
                gps_location_updated_at=now_kst(),
            ),
            store=store,
        )
        context = get_session_context(context.session_id, store=store)

    gps_location = context.api_context.gps_location
    if not gps_location:
        # GPS 없음 — 호출자가 missing_conditions(GPS 알럿)로 판단한다. 여기서는 LLM
        # 호출로 진행하지 않고 있는 그대로의 컨텍스트만 반환한다.
        return context

    if context.api_context.weather_expired:
        context = await _refresh_weather(
            context, gps_location, weather_provider, visit_at=visit_at, store=store
        )

    return context


async def _refresh_weather(
    context: SessionContextResponse,
    gps_location: str,
    weather_provider: WeatherProvider,
    *,
    visit_at: datetime | None,
    store: StateStore | None,
) -> SessionContextResponse:
    latitude, longitude = _parse_location(gps_location)
    result = await GetWeatherForecastTool(weather_provider).execute(
        WeatherForecastQuery(latitude, longitude, visit_at=visit_at)
    )
    if result.status is not ToolStatus.SUCCESS or result.forecast is None:
        # api_weather는 선택 정보(가중치 제외로 처리) — 실패해도 조용히 넘어간다.
        return context

    update_api_context(
        UpdateApiContextRequest(
            session_id=context.session_id,
            api_weather=result.forecast.condition.value,
            api_weather_updated_at=now_kst(),
        ),
        store=store,
    )
    return get_session_context(context.session_id, store=store)


def _parse_location(gps_location: str) -> tuple[float, float]:
    latitude_str, longitude_str = gps_location.split(",")
    return float(latitude_str), float(longitude_str)


__all__ = ["ensure_current_context"]
