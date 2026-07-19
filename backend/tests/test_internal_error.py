# 예상하지 못한 일반 Exception도 공통 envelope(internal_server_error, 500)로 나오는지 검증.
# TestClient 기본값은 서버에서 발생한 예외를 다시 던져버리므로(raise_server_exceptions=True),
# 이 테스트에서만 raise_server_exceptions=False로 별도 클라이언트를 만든다.

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import get_recommendation_service
from app.main import app


class _ExplodingRecommendationService:
    async def recommend(self, *args, **kwargs):
        raise RuntimeError("boom: simulated unexpected failure")


def test_unexpected_exception_returns_common_envelope() -> None:
    app.dependency_overrides[get_recommendation_service] = lambda: _ExplodingRecommendationService()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/api/recommendations",
            json={"location_query": "경복궁", "search_radius_km": 1.0},
        )
    finally:
        app.dependency_overrides.pop(get_recommendation_service, None)

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_server_error"
    assert body["error"]["retryable"] is False
