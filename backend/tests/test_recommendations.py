from fastapi.testclient import TestClient

from app.main import app


def _request(shown_place_ids: list[str] | None = None) -> dict:
    client = TestClient(app)
    response = client.post(
        "/api/recommendations",
        json={
            "location_query": "경복궁",
            "preferred_categories": ["museum", "cafe"],
            "weather_condition": "bad",
            "search_radius_km": 1.0,
            "shown_place_ids": shown_place_ids or [],
        },
    )
    assert response.status_code == 200
    return response.json()


def test_recommendations_return_stub_results() -> None:
    body = _request()

    assert [item["place_id"] for item in body["recommendations"]] == [
        "stub-museum-1",
        "stub-cafe-1",
        "stub-park-1",
    ]
    assert body["unverified_recommendations"][0]["place_id"] == "stub-gallery-1"


def test_recommendations_filter_shown_place_ids() -> None:
    body = _request(["stub-museum-1", "stub-gallery-1"])

    visible_ids = [item["place_id"] for item in body["recommendations"]]
    unverified_ids = [item["place_id"] for item in body["unverified_recommendations"]]
    assert "stub-museum-1" not in visible_ids
    assert "stub-gallery-1" not in unverified_ids
