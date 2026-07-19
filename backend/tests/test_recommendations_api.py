# POST /api/recommendations, POST /api/interpret를 TestClient로 호출하는 API 레벨 테스트.
# 응답 스키마에 필요한 필드가 다 있는지, Fake LLM이 대표 입력을 그럴듯하게 구조화하는지 확인.
#
# 이 테스트들은 real datetime.now()가 아니라 app/core/clock.py의 FixedClock을 통해 실행되므로
# (기본 Settings가 PLACE_PROVIDER=fake이면 get_clock()이 항상 FixedClock을 반환) 밤 시간대에
# 돌려도 결과가 비어있지 않다 - 예전에는 datetime.now()를 직접 썼기 때문에 늦은 시각에 실행하면
# 이 테스트가 실패했다(모든 Fake 장소가 이미 영업 종료로 처리됨).

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from app.api.deps import get_clock
from app.core.clock import FixedClock
from app.main import app

STANDARD_RECOMMENDATION_PAYLOAD = {
    "location_query": "경복궁",
    "preferred_categories": ["museum", "cafe"],
    "weather_condition": "neutral",
    "search_radius_km": 5.0,
    "shown_place_ids": [],
}


def test_recommendations_endpoint_returns_two_groups(client: TestClient) -> None:
    response = client.post("/api/recommendations", json=STANDARD_RECOMMENDATION_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert "recommendations" in body
    assert "unverified_recommendations" in body
    assert len(body["recommendations"]) > 0

    item = body["recommendations"][0]
    for field in (
        "place_id",
        "name",
        "category",
        "distance_km",
        "remaining_minutes",
        "environment_type",
        "recommendation_reason",
        "warnings",
        "total_score",
        "score_breakdown",
    ):
        assert field in item


def test_interpret_endpoint_returns_structured_conditions(client: TestClient) -> None:
    response = client.post(
        "/api/interpret",
        json={"user_input": "경복궁 근처에서 비를 피할 수 있는 박물관이나 카페를 찾고 싶어"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["location_query"] == "경복궁"
    assert "museum" in body["preferred_categories"]
    assert "cafe" in body["preferred_categories"]
    assert body["weather_condition"] == "bad"


def test_default_fake_environment_returns_recommendations_regardless_of_wall_clock(
    client: TestClient,
) -> None:
    """Standard input from the spec must yield >=1 recommendation no matter what
    the real system time is when the test happens to run (this is what used to
    fail late at night when the route called datetime.now() directly)."""
    response = client.post(
        "/api/interpret",
        json={"user_input": "경복궁 근처에서 비를 피할 수 있는 박물관이나 카페를 찾고 싶어"},
    )
    conditions = response.json()

    response = client.post(
        "/api/recommendations",
        json={**conditions, "shown_place_ids": []},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["recommendations"]) >= 1


def test_recommendations_change_with_a_different_fixed_clock(client: TestClient) -> None:
    """Overriding the Clock dependency to two different fixed times must
    produce different results -- proving the endpoint reads from the injected
    Clock (not a hardcoded value) while staying fully deterministic."""

    def fixed_at(hour: int) -> FixedClock:
        return FixedClock(datetime(2026, 7, 15, hour, 0, 0))

    try:
        # mid-afternoon: most places open
        app.dependency_overrides[get_clock] = lambda: fixed_at(14)
        afternoon = client.post(
            "/api/recommendations", json=STANDARD_RECOMMENDATION_PAYLOAD
        ).json()

        # early morning: most places closed
        app.dependency_overrides[get_clock] = lambda: fixed_at(7)
        early_morning = client.post(
            "/api/recommendations", json=STANDARD_RECOMMENDATION_PAYLOAD
        ).json()
    finally:
        app.dependency_overrides.pop(get_clock, None)

    afternoon_ids = {item["place_id"] for item in afternoon["recommendations"]}
    early_morning_ids = {item["place_id"] for item in early_morning["recommendations"]}
    assert afternoon_ids != early_morning_ids
