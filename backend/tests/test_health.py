# GET /api/health가 { "status": "ok" }를 200으로 반환하는지 확인하는 최소 스모크 테스트.

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
