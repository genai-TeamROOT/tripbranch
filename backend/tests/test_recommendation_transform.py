"""to_search_radius_km/to_weather_condition/to_concentration_entries/
to_record_recommendation_request 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.agent_context.service import _resolve_search_radius_km as _c_resolve_search_radius_km
from app.domain.models import WeatherCondition
from app.place_search_policy import DEFAULT_PLACE_SEARCH_RADIUS_KM
from app.schemas import (
    RecommendationItem,
    RecommendationResponse,
    StatedWeather,
    Transport,
    UserConditions,
    WeatherIntent,
)
from app.services.runtime.context_schemas import (
    ContextError,
    ContextValue,
    RecommendationContext,
    WeatherForecast,
)
from app.services.runtime.recommendation_transform import (
    to_concentration_entries,
    to_record_recommendation_request,
    to_scoring_weather_condition,
    to_search_radius_km,
    to_weather_condition,
)


def _item(place_id: str) -> RecommendationItem:
    return RecommendationItem(
        place_id=place_id,
        name=f"장소-{place_id}",
        category="cafe",
        distance_km=0.3,
        remaining_minutes=60,
        environment_type="indoor",
        recommendation_reason="테스트용",
        explanations=[],
        warnings=[],
        score=0.5,
        feature_scores={},
        weights_used={},
    )


class TestToSearchRadiusKm:
    def test_max_travel_time_none_returns_default(self) -> None:
        assert to_search_radius_km(UserConditions()) == pytest.approx(
            DEFAULT_PLACE_SEARCH_RADIUS_KM
        )

    def test_uses_70m_per_min(self) -> None:
        conditions = UserConditions(transport=Transport.WALK, max_travel_time=30)
        assert to_search_radius_km(conditions) == pytest.approx(2.1)

    @pytest.mark.parametrize("transport", [Transport.PUBLIC, Transport.CAR, None])
    def test_non_walking_transport_uses_temporary_speed(
        self,
        transport: Transport | None,
    ) -> None:
        conditions = UserConditions(transport=transport, max_travel_time=30)
        assert to_search_radius_km(conditions) == pytest.approx(10.0)

    def test_clamped_to_upper_bound(self) -> None:
        conditions = UserConditions(max_travel_time=1000)
        assert to_search_radius_km(conditions) == pytest.approx(20.0)

    def test_clamped_to_lower_bound(self) -> None:
        conditions = UserConditions(transport=Transport.WALK, max_travel_time=1)
        assert to_search_radius_km(conditions) == pytest.approx(0.3)

    def test_zero_max_travel_time_is_normalized_to_none_before_reaching_this_function(
        self,
    ) -> None:
        """UserConditions가 0을 None으로 정규화하므로, 여기서는 기본 반경이 나온다."""
        conditions = UserConditions(max_travel_time=0)
        assert conditions.max_travel_time is None
        assert to_search_radius_km(conditions) == pytest.approx(
            DEFAULT_PLACE_SEARCH_RADIUS_KM
        )

    @pytest.mark.parametrize("max_travel_time", [None, 1, 5, 15, 30, 60, 200, 1000])
    def test_matches_c_formula(self, max_travel_time: int | None) -> None:
        """C(app.agent_context.service._resolve_search_radius_km())와 동일한 값이어야 한다.

        이 테스트가 실패하면 C가 공식을 바꾼 것이다 — to_search_radius_km()도
        같이 맞춰야 한다.
        """
        conditions = UserConditions(
            transport=Transport.WALK,
            max_travel_time=max_travel_time,
        )
        expected = _c_resolve_search_radius_km(
            max_travel_time,
            default_radius_km=DEFAULT_PLACE_SEARCH_RADIUS_KM,
        )
        assert to_search_radius_km(conditions) == pytest.approx(expected)


class TestToWeatherCondition:
    def test_success_returns_condition(self) -> None:
        context = RecommendationContext(
            weather=ContextValue(
                status="success",
                data=WeatherForecast(condition="good", forecast_for=datetime.now(UTC)),
            )
        )
        assert to_weather_condition(context) == "good"

    def test_partial_returns_condition(self) -> None:
        context = RecommendationContext(
            weather=ContextValue(
                status="partial",
                data=WeatherForecast(condition="neutral", forecast_for=datetime.now(UTC)),
            )
        )
        assert to_weather_condition(context) == "neutral"

    def test_unavailable_returns_none(self) -> None:
        context = RecommendationContext(
            weather=ContextValue(
                status="unavailable",
                error=ContextError(code="weather_unavailable", message="실패", retryable=True),
            )
        )
        assert to_weather_condition(context) is None

    def test_no_data_returns_none(self) -> None:
        context = RecommendationContext(weather=ContextValue(status="no_data"))
        assert to_weather_condition(context) is None

    def test_missing_weather_returns_none(self) -> None:
        context = RecommendationContext()
        assert to_weather_condition(context) is None


class TestToScoringWeatherCondition:
    def test_weather_mentioned_uses_user_stated_weather(self) -> None:
        context = RecommendationContext()
        conditions = UserConditions(
            weather=StatedWeather.RAIN,
            weather_intent=WeatherIntent.AVOID,
        )
        assert to_scoring_weather_condition(conditions, context) is WeatherCondition.BAD

    def test_no_mention_uses_context_weather(self) -> None:
        context = RecommendationContext(
            weather=ContextValue(
                status="success",
                data=WeatherForecast(condition="neutral", forecast_for=datetime.now(UTC)),
            )
        )
        conditions = UserConditions(weather_intent=WeatherIntent.NO_MENTION)
        assert to_scoring_weather_condition(conditions, context) is WeatherCondition.NEUTRAL

    def test_ignore_disables_weather_feature(self) -> None:
        context = RecommendationContext(
            weather=ContextValue(
                status="success",
                data=WeatherForecast(condition="good", forecast_for=datetime.now(UTC)),
            )
        )
        conditions = UserConditions(weather_intent=WeatherIntent.IGNORE)
        assert to_scoring_weather_condition(conditions, context) is None


class TestToConcentrationEntries:
    """RecommendationContext는 아직 concentration 필드가 없다(C 미구현,
    concentration-conditions.md §1.2). 필드가 생긴 뒤의 상태는 SimpleNamespace로
    흉내 내고, 지금 상태(필드 자체가 없음)는 실제 RecommendationContext로 확인한다.
    """

    def test_field_missing_returns_none(self) -> None:
        context = RecommendationContext()
        assert to_concentration_entries(context) is None

    def test_success_returns_entries(self) -> None:
        entries = [{"place_name": "경복궁", "concentration_rate": 42.0}]
        context = SimpleNamespace(concentration=SimpleNamespace(status="success", data=entries))
        assert to_concentration_entries(context) == entries

    def test_partial_returns_entries(self) -> None:
        entries = [{"place_name": "창덕궁", "concentration_rate": 58.0}]
        context = SimpleNamespace(concentration=SimpleNamespace(status="partial", data=entries))
        assert to_concentration_entries(context) == entries

    def test_no_data_returns_none(self) -> None:
        context = SimpleNamespace(concentration=SimpleNamespace(status="no_data", data=None))
        assert to_concentration_entries(context) is None

    def test_unavailable_returns_none(self) -> None:
        context = SimpleNamespace(concentration=SimpleNamespace(status="unavailable", data=None))
        assert to_concentration_entries(context) is None

    def test_concentration_none_returns_none(self) -> None:
        context = SimpleNamespace(concentration=None)
        assert to_concentration_entries(context) is None


class TestToRecordRecommendationRequest:
    def test_ranks_recommendations_then_unverified_in_order(self) -> None:
        response = RecommendationResponse(
            recommendations=[_item("a"), _item("b")],
            unverified_recommendations=[_item("c")],
            elapsed_ms=0,
        )

        request = to_record_recommendation_request("sess_1", "run_1", response)

        assert request.session_id == "sess_1"
        assert request.run_id == "run_1"
        assert [(p.place_id, p.rank) for p in request.recommended] == [
            ("a", 1),
            ("b", 2),
            ("c", 3),
        ]

    def test_empty_response_produces_empty_recommended(self) -> None:
        response = RecommendationResponse(
            recommendations=[], unverified_recommendations=[], elapsed_ms=0
        )
        request = to_record_recommendation_request("sess_1", "run_1", response)
        assert request.recommended == []
