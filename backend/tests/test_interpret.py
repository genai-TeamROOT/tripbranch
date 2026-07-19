from fastapi.testclient import TestClient

from app.main import app


def test_interpret_returns_stub_conditions() -> None:
    client = TestClient(app)

    response = client.post("/api/interpret", json={"user_input": "비 피할 곳 추천해줘"})

    assert response.status_code == 200
    assert response.json() == {
        "location_query": "경복궁",
        "preferred_categories": ["museum", "cafe"],
        "weather_condition": "bad",
        "search_radius_km": 1.0,
    }


def test_interpret_rejects_empty_input() -> None:
    client = TestClient(app)

    response = client.post("/api/interpret", json={"user_input": ""})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
