from __future__ import annotations

from app.schemas import InterpretedConditions


def interpret_user_input(user_input: str) -> InterpretedConditions:
    return InterpretedConditions(
        location_query="경복궁",
        preferred_categories=["museum", "cafe"],
        weather_condition="bad",
        search_radius_km=1.0,
    )
