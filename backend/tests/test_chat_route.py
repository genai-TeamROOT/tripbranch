"""통합 Chat API 라우터 테스트.

역할: POST /api/chat이 run_agent()에 요청을 그대로 위임하고 AgentResponse를
      반환하는지 검증한다. Runtime 내부 동작은 test_agent_runtime.py가 담당하므로
      여기서는 라우팅과 요청 전달만 확인한다(실제 Provider를 호출하지 않는다).
입력: TestClient가 보내는 POST /api/chat 요청.
출력: 상태 코드와 응답 payload에 대한 assertion.
호출 시점: 로컬 테스트와 CI에서 pytest 실행 시.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.routes.chat as chat_route
from app.agent_context.info_schemas import InfoContextResponse, PlaceCard, PlaceInfoResult
from app.main import app
from app.schemas import (
    AgentRequest,
    AgentResponse,
    Intent,
    LLMOutput,
    OutputStatus,
)
from app.state.schema import UserConditions as StateUserConditions
from app.state.service import ApiContextView, StateApplyResponse


def _fake_response(session_id: str = "sess_test") -> AgentResponse:
    return AgentResponse(
        llm_output=LLMOutput(intent=Intent.GENERAL, status=OutputStatus.COMPLETE),
        state=StateApplyResponse(
            session_id=session_id,
            run_id="run_test",
            session_created=True,
            user_conditions=StateUserConditions(),
            api_context=ApiContextView(),
            condition_version=1,
            condition_changed=False,
        ),
        recommendations=None,
        message="테스트 응답",
    )


@pytest.fixture
def captured(monkeypatch) -> list[AgentRequest]:
    seen: list[AgentRequest] = []

    async def fake_run_agent(request: AgentRequest, *, principal=None) -> AgentResponse:
        seen.append(request)
        return _fake_response()

    monkeypatch.setattr(chat_route, "run_agent", fake_run_agent)
    return seen


def test_chat_delegates_to_run_agent(captured) -> None:
    client = TestClient(app)

    response = client.post("/api/chat", json={"user_input": "경복궁 근처 카페 추천해줘"})

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "테스트 응답"
    assert body["state"]["session_id"] == "sess_test"
    assert len(captured) == 1
    assert captured[0].user_input == "경복궁 근처 카페 추천해줘"


def test_chat_passes_session_and_device_location(captured) -> None:
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={
            "user_input": "다른 곳 보여줘",
            "session_id": "sess_prev",
            "device_location": "37.5788,126.9770",
        },
    )

    assert response.status_code == 200
    assert captured[0].session_id == "sess_prev"
    assert captured[0].device_location == "37.5788,126.9770"


def test_chat_rejects_empty_user_input(captured) -> None:
    client = TestClient(app)

    response = client.post("/api/chat", json={"user_input": ""})

    assert response.status_code == 422
    assert captured == []


def test_recommendation_place_details_returns_matched_c_place_card(monkeypatch) -> None:
    captured_requests = []

    class FakeContextProvider:
        async def fetch_info_context(self, request):
            captured_requests.append(request)
            return InfoContextResponse(
                request_id=request.request_id,
                status="success",
                result=PlaceInfoResult(
                    status="success",
                    question_type="general_info",
                    place_id="126508",
                    fields={"overview": "조선 왕조의 법궁"},
                    place_card=PlaceCard(
                        place_id="126508",
                        place_name="경복궁",
                        thumbnail_url="https://example.test/gyeongbokgung.jpg",
                        overview="조선 왕조의 법궁",
                        operating_hours="09:00~18:00",
                    ),
                ),
            )

    monkeypatch.setattr(chat_route, "get_context_provider", lambda client: FakeContextProvider())
    client = TestClient(app)

    response = client.post(
        "/api/chat/place-details",
        json={"place_id": "126508", "place_name": "경복궁"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "requested_place_id": "126508",
        "place_card": {
            "question_type": "general_info",
            "answer_fields": {"overview": "조선 왕조의 법궁"},
            "place_id": "126508",
            "place_name": "경복궁",
            "thumbnail_url": "https://example.test/gyeongbokgung.jpg",
            "overview": "조선 왕조의 법궁",
            "operating_hours": "09:00~18:00",
            "rest_date": None,
            "parking": None,
            "parking_fee": None,
            "fee": None,
            "baby_carriage": None,
            "pet": None,
            "credit_card": None,
            "restroom": None,
            "homepage": None,
            "population_current_level": None,
            "population_observed_at": None,
            "population_forecasts": [],
            "concentration_forecasts": [],
        },
    }
    assert len(captured_requests) == 1
    assert captured_requests[0].place_context == "from_recommendation"
    assert captured_requests[0].question_type == "general_info"


def test_recommendation_place_details_hides_mismatched_place_card(monkeypatch) -> None:
    class FakeContextProvider:
        async def fetch_info_context(self, request):
            return InfoContextResponse(
                request_id=request.request_id,
                status="success",
                result=PlaceInfoResult(
                    status="success",
                    question_type="general_info",
                    place_id="other-place",
                    fields={},
                    place_card=PlaceCard(place_id="other-place", place_name="동명 장소"),
                ),
            )

    monkeypatch.setattr(chat_route, "get_context_provider", lambda client: FakeContextProvider())
    client = TestClient(app)

    response = client.post(
        "/api/chat/place-details",
        json={"place_id": "126508", "place_name": "경복궁"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "no_data",
        "requested_place_id": "126508",
        "place_card": None,
    }
