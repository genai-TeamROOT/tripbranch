"""사용자 입력 해석 API 회귀 테스트.

역할: /api/interpret의 정상 응답과 요청 검증 오류 포맷을 확인한다.
입력: TestClient가 보내는 POST /api/interpret JSON payload.
출력: 해석 조건 JSON과 공통 오류 JSON에 대한 pytest assertion.
호출 시점: 로컬 테스트와 CI에서 pytest 실행 시 호출된다.
TODO: 실제 해석 로직 도입 후 다양한 문장/위치/날씨 케이스를 추가한다.
"""

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
