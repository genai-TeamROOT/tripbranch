"""to_search_radius_km/to_travel_mode/to_concentration_entries/
to_record_recommendation_request 단위 테스트.

날씨 조건 변환(옛 to_weather_condition())은 D-051로 D에 이관돼 제거됐다 —
resolve_weather_condition()에 대한 검증은 test_real_recommendation_provider.py와
test_recommendation_pipeline.py가 담당한다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent_context.service import _resolve_search_radius_km as _c_resolve_search_radius_km
from app.domain.travel_route import TravelMode
from app.place_search_policy import DEFAULT_PLACE_SEARCH_RADIUS_KM
from app.schemas import (
    RecommendationItem,
    RecommendationResponse,
    Transport,
    UserConditions,
)
from app.services.runtime.context_schemas import RecommendationContext
from app.services.runtime.recommendation_transform import (
    to_concentration_entries,
    to_record_recommendation_request,
    to_search_radius_km,
    to_travel_mode,
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


class TestToTravelMode:
    """실측 이동수단 선택. 반경 산정과 같은 조건을 봐야 단위가 맞는다."""

    def test_walk_uses_walking(self) -> None:
        conditions = UserConditions(transport=Transport.WALK, max_travel_time=30)
        assert to_travel_mode(conditions) is TravelMode.WALKING

    @pytest.mark.parametrize("transport", [Transport.WALK, Transport.PUBLIC, Transport.CAR, None])
    def test_no_travel_time_uses_walking_like_the_default_radius(
        self,
        transport: Transport | None,
    ) -> None:
        """이동시간 미언급은 기본 반경(도보 기준)이므로 이동수단과 무관하게 도보로 잰다.

        이 케이스는 카드 이전 동작과 같아야 한다 — 그때도 D가 도보 실측을 받았다.
        """
        assert to_travel_mode(UserConditions(transport=transport)) is TravelMode.WALKING

    def test_public_uses_transit(self) -> None:
        conditions = UserConditions(transport=Transport.PUBLIC, max_travel_time=30)
        assert to_travel_mode(conditions) is TravelMode.TRANSIT

    def test_car_uses_driving(self) -> None:
        conditions = UserConditions(transport=Transport.CAR, max_travel_time=30)
        assert to_travel_mode(conditions) is TravelMode.DRIVING

    def test_unstated_transport_with_travel_time_has_no_mode(self) -> None:
        """20km/h 가정이 대중교통인지 자동차인지 발화에 없으므로 실측하지 않는다."""
        assert to_travel_mode(UserConditions(max_travel_time=30)) is None


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
