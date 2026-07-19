"""사용자 자연어 입력을 추천 조건으로 해석하는 임시 서비스.

역할: 현재는 고정된 stub 조건을 반환해 프론트엔드 흐름과 API 계약을 검증한다.
입력: 사용자가 입력한 자유 형식 여행 요청 문자열.
출력: InterpretedConditions 모델.
호출 시점: /api/interpret 라우터와 StubTripProvider에서 호출된다.
TODO: 실제 LLM/룰 기반 해석기로 교체하고 신뢰도/근거 정보를 추가한다.
"""

from __future__ import annotations

from app.schemas import InterpretedConditions


def interpret_user_input(user_input: str) -> InterpretedConditions:
    return InterpretedConditions(
        location_query="경복궁",
        preferred_categories=["museum", "cafe"],
        weather_condition="bad",
        search_radius_km=1.0,
    )
