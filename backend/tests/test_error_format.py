# 공통 에러 응답 포맷( { "error": {code, message, retryable, details} } ) 검증.
# invalid_request(공백 입력)와 location_not_found(존재하지 않는 지명) 케이스를 API 레벨에서 확인.
# 이 파일은 서비스/도메인 계층에서 발생하는 AppError뿐 아니라, FastAPI 자체가 만드는
# RequestValidationError(422)와 매칭되는 라우트가 없는 경로(404)도 같은 envelope로
# 나오는지 함께 검증한다 - 그렇지 않으면 클라이언트가 두 가지 다른 에러 형식을 파싱해야 한다.

from __future__ import annotations

from fastapi.testclient import TestClient


def _assert_common_envelope(body: dict) -> None:
    assert set(body.keys()) == {"error"}
    error = body["error"]
    assert set(error.keys()) == {"code", "message", "retryable", "details"}
    assert isinstance(error["code"], str)
    assert isinstance(error["message"], str)
    assert isinstance(error["retryable"], bool)


def test_invalid_request_error_envelope(client: TestClient) -> None:
    response = client.post("/api/interpret", json={"user_input": " "})

    assert response.status_code == 400
    body = response.json()
    _assert_common_envelope(body)
    assert body["error"]["code"] == "invalid_request"
    assert body["error"]["retryable"] is False


def test_location_not_found_error_envelope(client: TestClient) -> None:
    response = client.post(
        "/api/recommendations",
        json={
            "location_query": "존재하지않는위치12345",
            "preferred_categories": ["cafe"],
            "search_radius_km": 1.0,
        },
    )

    assert response.status_code == 404
    body = response.json()
    _assert_common_envelope(body)
    assert body["error"]["code"] == "location_not_found"
    assert body["error"]["retryable"] is False


def test_missing_required_field_returns_common_envelope(client: TestClient) -> None:
    response = client.post("/api/interpret", json={})

    assert response.status_code == 422
    body = response.json()
    _assert_common_envelope(body)
    assert body["error"]["code"] == "invalid_request"
    assert body["error"]["retryable"] is False


def test_invalid_enum_value_returns_common_envelope(client: TestClient) -> None:
    response = client.post(
        "/api/recommendations",
        json={
            "location_query": "경복궁",
            "weather_condition": "sunny",  # not one of good/neutral/bad
            "search_radius_km": 1.0,
        },
    )

    assert response.status_code == 422
    body = response.json()
    _assert_common_envelope(body)
    assert body["error"]["code"] == "invalid_request"


def test_zero_or_negative_search_radius_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/recommendations",
        json={"location_query": "경복궁", "search_radius_km": 0},
    )

    assert response.status_code == 422
    body = response.json()
    _assert_common_envelope(body)
    assert body["error"]["code"] == "invalid_request"


def test_unknown_api_path_returns_common_json_404(client: TestClient) -> None:
    response = client.get("/api/nope")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    _assert_common_envelope(body)
    assert body["error"]["code"] == "invalid_request"
    assert body["error"]["retryable"] is False


def test_unknown_api_path_rejects_other_methods_too(client: TestClient) -> None:
    response = client.post("/api/nope", json={})

    assert response.status_code == 404
    body = response.json()
    _assert_common_envelope(body)
