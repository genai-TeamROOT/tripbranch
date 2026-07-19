from __future__ import annotations

from typing import Protocol

from app.schemas import InterpretedConditions, RecommendationResponse


class InterpretProvider(Protocol):
    def interpret(self, user_input: str) -> InterpretedConditions:
        """Return structured trip conditions from free-form input."""


class RecommendationProvider(Protocol):
    def recommendations(self, shown_place_ids: list[str]) -> RecommendationResponse:
        """Return place recommendations, excluding already shown IDs."""
