"""응답 피드백 라우터 테스트.

역할: POST /api/feedback이 B 서비스에 위임되는지 검증한다.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.state import feedback as feedback_module
from app.state.store import get_store


def test_post_feedback_records_rating() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/feedback",
        json={"session_id": "sess_route_test", "run_id": "run_1", "rating": "like"},
    )

    assert response.status_code == 200
    assert "recorded_at" in response.json()

    [saved] = feedback_module.get_feedback(get_store(), "sess_route_test")
    assert saved.rating == "like"


def test_post_feedback_rejects_invalid_rating() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/feedback",
        json={"session_id": "sess_route_test2", "run_id": "run_1", "rating": "neutral"},
    )

    assert response.status_code == 422


def test_get_dislikes_returns_recorded_dislike() -> None:
    client = TestClient(app)

    client.post(
        "/api/feedback",
        json={"session_id": "sess_dislike_route", "run_id": "run_x", "rating": "dislike"},
    )

    response = client.get("/api/feedback/dislikes")

    assert response.status_code == 200
    items = response.json()["items"]
    assert any(
        item["session_id"] == "sess_dislike_route" and item["run_id"] == "run_x"
        for item in items
    )
