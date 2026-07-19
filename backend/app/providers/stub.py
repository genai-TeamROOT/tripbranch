from __future__ import annotations

from app.schemas import InterpretedConditions, RecommendationResponse
from app.services.interpret import interpret_user_input
from app.services.recommendations import get_stub_recommendations


class StubTripProvider:
    def interpret(self, user_input: str) -> InterpretedConditions:
        return interpret_user_input(user_input)

    def recommendations(self, shown_place_ids: list[str]) -> RecommendationResponse:
        return get_stub_recommendations(shown_place_ids)
