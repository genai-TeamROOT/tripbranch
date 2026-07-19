"""임시 Trip provider 구현체.

역할: provider 인터페이스 뒤에서 현재 stub 서비스를 호출하는 어댑터 역할을 한다.
입력: 자유 형식 사용자 입력과 이미 노출된 place_id 목록.
출력: InterpretedConditions 또는 RecommendationResponse 모델.
호출 시점: 향후 DI나 테스트에서 provider 형태로 stub 동작이 필요할 때 호출된다.
TODO: 실제 provider 구현이 생기면 테스트용 fake와 운영용 구현을 분리한다.
"""

from __future__ import annotations

from app.schemas import InterpretedConditions, RecommendationResponse
from app.services.interpret import interpret_user_input
from app.services.recommendations import get_stub_recommendations


class StubTripProvider:
    def interpret(self, user_input: str) -> InterpretedConditions:
        return interpret_user_input(user_input)

    def recommendations(self, shown_place_ids: list[str]) -> RecommendationResponse:
        return get_stub_recommendations(shown_place_ids)
