"""추천 API Fake Provider 파이프라인 회귀 테스트.

역할: /api/recommendations의 Tool·Scoring 결과와 이미 노출된 장소 필터링을 검증한다.
입력: TestClient가 보내는 POST /api/recommendations JSON payload.
출력: 추천/검증 불가 목록과 place_id 필터링에 대한 pytest assertion.
호출 시점: 로컬 테스트와 CI에서 pytest 실행 시 호출된다.
TODO: 실제 provider 도입 후 랭킹, 검증 불가, 빈 결과 케이스를 확장한다.
"""

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


def test_recommendations_return_fake_pipeline_results() -> None:
    body = _request()

    assert [item["place_id"] for item in body["recommendations"]] == [
        "fake-museum-1",
        "fake-cafe-1",
    ]
    assert body["unverified_recommendations"] == []
    assert len(body["recommendations"]) <= 5


def test_recommendations_filter_shown_place_ids() -> None:
    body = _request(["fake-museum-1"])

    visible_ids = [item["place_id"] for item in body["recommendations"]]
    unverified_ids = [item["place_id"] for item in body["unverified_recommendations"]]
    assert "fake-museum-1" not in visible_ids
    assert "fake-museum-1" not in unverified_ids
