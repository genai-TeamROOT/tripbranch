"""통합 Chat API 라우터 테스트.

역할: POST /api/chat이 run_agent()에 요청을 그대로 위임하고 AgentResponse를
      반환하는지 검증한다. Runtime 내부 동작은 test_agent_runtime.py가 담당하므로
      여기서는 라우팅과 요청 전달만 확인한다(실제 Provider를 호출하지 않는다).
입력: TestClient가 보내는 POST /api/chat 요청.
출력: 상태 코드와 응답 payload에 대한 assertion.
호출 시점: 로컬 테스트와 CI에서 pytest 실행 시.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import app.routes.chat as chat_route
from app.agent_context.info_schemas import InfoContextResponse, PlaceCard, PlaceInfoResult
from app.agent_context.schemas import Coordinates
from app.main import app
from app.providers.contracts import ProviderSource, provider_result
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


def test_chat_translates_english_at_route_boundary_without_changing_runtime_contract(
    captured, monkeypatch
) -> None:
    seen_languages: list[str] = []

    async def fake_request_for_runtime(request: AgentRequest) -> AgentRequest:
        seen_languages.append(request.language)
        return request.model_copy(update={"user_input": "경복궁 근처 실내 박물관 추천"})

    async def fake_response_for_user(response: AgentResponse, *, language: str) -> AgentResponse:
        seen_languages.append(language)
        return response.model_copy(update={"message": "Try an indoor museum near Gyeongbokgung."})

    monkeypatch.setattr(chat_route, "_request_for_runtime", fake_request_for_runtime)
    monkeypatch.setattr(chat_route, "_response_for_user", fake_response_for_user)
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={"user_input": "Find an indoor museum near Gyeongbokgung", "language": "en"},
    )

    assert response.status_code == 200
    assert captured[0].user_input == "경복궁 근처 실내 박물관 추천"
    assert captured[0].language == "en"
    assert response.json()["message"] == "Try an indoor museum near Gyeongbokgung."
    assert seen_languages == ["en", "en"]


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
                    destination_coordinates=Coordinates(latitude=37.5796, longitude=126.977),
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
            "latitude": 37.5796,
            "longitude": 126.977,
            "thumbnail_url": "https://example.test/gyeongbokgung.jpg",
            "photos": [],
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
            "preference_insights": [],
            "population_current_level": None,
            "population_current_message": None,
            "population_observed_at": None,
            "population_peak_forecast_summary": None,
            "population_forecasts": [],
            "concentration_forecasts": [],
            "realtime_area_name": None,
            "realtime_observed_at": None,
            "realtime_source_url": None,
            "realtime_map_url": None,
            "realtime_detail_items": [],
        },
    }
    assert len(captured_requests) == 1
    assert captured_requests[0].place_context == "from_recommendation"
    assert captured_requests[0].question_type == "general_info"


def test_recommendation_place_details_by_name_only_skips_id_match(monkeypatch) -> None:
    """혼잡도·행사 카드처럼 place_id 없이 이름으로 조회하면 대조를 건너뛰고 성공한다."""

    class FakeContextProvider:
        async def fetch_info_context(self, request):
            return InfoContextResponse(
                request_id=request.request_id,
                status="success",
                result=PlaceInfoResult(
                    status="success",
                    question_type="general_info",
                    place_id="126508",
                    fields={},
                    destination_coordinates=Coordinates(latitude=37.5796, longitude=126.977),
                    place_card=PlaceCard(place_id="126508", place_name="창덕궁"),
                ),
            )

    monkeypatch.setattr(chat_route, "get_context_provider", lambda client: FakeContextProvider())
    client = TestClient(app)

    response = client.post("/api/chat/place-details", json={"place_name": "창덕궁"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["requested_place_id"] is None
    assert body["place_card"]["place_id"] == "126508"
    assert body["place_card"]["latitude"] == 37.5796
    assert body["place_card"]["longitude"] == 126.977


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


# --- SSE: 후속 질문은 done 뒤에 온다 (D-102) ---------------------------------


def _sse_events(body: str) -> list[tuple[str, dict]]:
    """SSE 본문을 (이벤트 이름, payload) 순서대로 푼다."""

    events: list[tuple[str, dict]] = []
    for frame in body.replace("\r\n", "\n").split("\n\n"):
        lines = [line for line in frame.split("\n") if line]
        name = next((line[6:].strip() for line in lines if line.startswith("event:")), None)
        data = "\n".join(line[5:].strip() for line in lines if line.startswith("data:"))
        if name and data:
            events.append((name, json.loads(data)))
    return events


@pytest.fixture
def streaming(monkeypatch) -> list[str]:
    """run_agent와 후속 질문 LLM을 대역으로 바꾼다. 만들어진 문구를 돌려준다."""

    generated = ["여기 주차되나요?", "다른 곳도 보여줘"]

    async def fake_run_agent(request: AgentRequest, **kwargs) -> AgentResponse:
        # 라우트가 Runtime 쪽 생성을 껐는지 여기서 잠근다 — 켜진 채로 두면 done이
        # 그 호출을 기다려 로딩이 한 번 더 뜬 것처럼 보인다.
        assert kwargs["generate_follow_ups"] is False
        return _fake_response()

    class _FollowUpLLM:
        async def generate_follow_up_suggestions(self, **kwargs):
            return provider_result(list(generated), source=ProviderSource.FAKE_LLM)

    monkeypatch.setattr(chat_route, "run_agent", fake_run_agent)
    monkeypatch.setattr(chat_route, "get_llm_provider", lambda: _FollowUpLLM())
    return generated


def test_stream_sends_follow_ups_after_done(streaming) -> None:
    """순서가 계약이다 — 화면은 done에서 로딩을 감추고 버튼만 뒤늦게 붙인다."""
    client = TestClient(app)

    response = client.post("/api/chat/stream", json={"user_input": "경복궁 근처 카페 추천해줘"})

    assert response.status_code == 200
    names = [name for name, _ in _sse_events(response.text)]
    assert names[-2:] == ["done", "follow_ups"]
    payload = dict(_sse_events(response.text))["follow_ups"]
    assert payload["suggestions"] == ["여기 주차되나요?", "다른 곳도 보여줘"]


def test_stream_omits_the_event_when_there_is_nothing_to_suggest(streaming) -> None:
    """빈 목록을 보내도 화면이 할 일이 없다 — 이벤트 자체를 생략한다."""
    streaming.clear()
    client = TestClient(app)

    response = client.post("/api/chat/stream", json={"user_input": "경복궁 근처 카페 추천해줘"})

    names = [name for name, _ in _sse_events(response.text)]
    assert names[-1] == "done"
    assert "follow_ups" not in names


def test_stream_still_completes_when_follow_ups_blow_up(monkeypatch) -> None:
    """done을 이미 보낸 뒤라, 여기서 예외가 새면 완결된 턴이 오류로 뒤집힌다."""

    async def fake_run_agent(request: AgentRequest, **kwargs) -> AgentResponse:
        return _fake_response()

    def exploding_llm():
        raise RuntimeError("provider 조립 실패")

    monkeypatch.setattr(chat_route, "run_agent", fake_run_agent)
    monkeypatch.setattr(chat_route, "get_llm_provider", exploding_llm)
    client = TestClient(app)

    response = client.post("/api/chat/stream", json={"user_input": "경복궁 근처 카페 추천해줘"})

    names = [name for name, _ in _sse_events(response.text)]
    assert names[-1] == "done"
    assert "error" not in names
