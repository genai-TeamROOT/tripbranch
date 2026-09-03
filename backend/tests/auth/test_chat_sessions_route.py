"""GET /api/sessions · PATCH /api/state/{session_id}/title — 채팅 히스토리. (TP-222 후속)

사이드바의 채팅 히스토리는 그동안 localStorage 목업이었고 **항목을 추가하는
코드가 아예 없어** 늘 비어 있었다. 이 파일은 그 목록이 실제 대화에서 나오고,
남의 대화가 섞이지 않는지를 본다.

가장 중요한 것 셋이다 — "남의 목록이 안 보인다", "남의 대화 이름을 못 바꾼다",
"제목이 저절로 바뀌지 않는다".
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth.principal import Principal
from app.main import app
from app.state import service as state_service
from tests.auth.conftest import make_token

ME = "3f1a9c04-0000-4000-8000-000000000001"
OTHER = "3f1a9c04-0000-4000-8000-000000000002"


def _headers(signing_key, sub: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(signing_key, sub=sub)}"}


def _start_chat(sub: str, *inputs: str, place: str | None = None) -> str:
    """세션을 만들고 대화를 몇 턴 넣는다. 첫 입력이 제목이 된다."""
    owner = Principal(user_id=sub, is_anonymous=True)
    applied = state_service.apply(
        state_service.StateApplyRequest(intent="RECOMMEND", confirmed=True),
        principal=owner,
    )
    for index, user_input in enumerate(inputs):
        state_service.append_conversation_turn(
            state_service.AppendConversationTurnRequest(
                session_id=applied.session_id,
                turn=state_service.ConversationTurn(
                    user_input=user_input,
                    assistant_message="네",
                    intent="RECOMMEND",
                    place_names=[place] if place and index == len(inputs) - 1 else [],
                ),
            )
        )
    return applied.session_id


# ---------------------------------------------------------------- 목록

def test_토큰_없이_목록을_부르면_401(signing_key) -> None:
    assert TestClient(app).get("/api/sessions").status_code == 401


def test_내_대화가_제목과_함께_나온다(signing_key) -> None:
    _start_chat(ME, "비 오는데 실내 어디 갈까", place="국립중앙박물관")

    response = TestClient(app).get("/api/sessions", headers=_headers(signing_key, ME))

    assert response.status_code == 200
    sessions = response.json()["sessions"]
    assert sessions[0]["title"] == "비 오는데 실내 어디 갈까"
    assert sessions[0]["place_name"] == "국립중앙박물관"


# 이 파일에서 가장 중요한 테스트다.
def test_남의_대화는_목록에_안_섞인다(signing_key) -> None:
    _start_chat(OTHER, "남의 대화")
    _start_chat(ME, "내 대화")

    response = TestClient(app).get("/api/sessions", headers=_headers(signing_key, ME))

    titles = [item["title"] for item in response.json()["sessions"]]
    assert "내 대화" in titles
    assert "남의 대화" not in titles


def test_대화를_시작하지_않은_세션은_목록에_없다(signing_key) -> None:
    """세션은 만들어졌지만 아무 말도 안 한 경우다 — 사용자가 보기에 대화가 아니다.

    인메모리 저장소가 테스트 사이에 남으므로 목록 전체를 비교하지 않고 이
    세션이 빠졌는지만 본다.
    """
    empty_session = _start_chat(ME)  # 턴 없음
    talked_session = _start_chat(ME, "진짜 대화")

    sessions = (
        TestClient(app).get("/api/sessions", headers=_headers(signing_key, ME)).json()["sessions"]
    )

    listed = {item["session_id"] for item in sessions}
    assert talked_session in listed
    assert empty_session not in listed


def test_최근_대화가_앞에_온다(signing_key) -> None:
    _start_chat(ME, "먼저 한 대화")
    _start_chat(ME, "나중에 한 대화")

    sessions = (
        TestClient(app).get("/api/sessions", headers=_headers(signing_key, ME)).json()["sessions"]
    )

    assert sessions[0]["title"] == "나중에 한 대화"


# recent_turns는 MAX_RECENT_TURNS(=5)개만 남는다. 제목을 그 배열에서 파생하면
# 대화를 이어갈수록 사이드바의 제목이 저절로 바뀐다 — 그래서 컬럼에 박는다.
def test_대화가_길어져도_제목이_바뀌지_않는다(signing_key) -> None:
    _start_chat(ME, "첫 질문", "둘", "셋", "넷", "다섯", "여섯", "일곱")

    sessions = (
        TestClient(app).get("/api/sessions", headers=_headers(signing_key, ME)).json()["sessions"]
    )

    assert sessions[0]["title"] == "첫 질문"


# ---------------------------------------------------------------- 이름 바꾸기

def test_이름을_바꾸면_목록에_반영된다(signing_key) -> None:
    session_id = _start_chat(ME, "원래 제목")
    client = TestClient(app)

    response = client.patch(
        f"/api/state/{session_id}/title",
        json={"title": "내가 정한 이름"},
        headers=_headers(signing_key, ME),
    )

    assert response.status_code == 200
    sessions = client.get("/api/sessions", headers=_headers(signing_key, ME)).json()["sessions"]
    assert sessions[0]["title"] == "내가 정한 이름"


def test_이름을_바꾼_뒤_대화를_이어가도_그_이름이_남는다(signing_key) -> None:
    session_id = _start_chat(ME, "원래 제목")
    client = TestClient(app)
    client.patch(
        f"/api/state/{session_id}/title",
        json={"title": "내가 정한 이름"},
        headers=_headers(signing_key, ME),
    )

    state_service.append_conversation_turn(
        state_service.AppendConversationTurnRequest(
            session_id=session_id,
            turn=state_service.ConversationTurn(user_input="이어서", assistant_message="네"),
        )
    )

    sessions = client.get("/api/sessions", headers=_headers(signing_key, ME)).json()["sessions"]
    assert sessions[0]["title"] == "내가 정한 이름"


def test_남의_대화_이름은_못_바꾼다(signing_key) -> None:
    session_id = _start_chat(OTHER, "남의 대화")

    response = TestClient(app).patch(
        f"/api/state/{session_id}/title",
        json={"title": "가로채기"},
        headers=_headers(signing_key, ME),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "session_ownership_mismatch"


def test_없는_대화_이름을_바꾸면_404(signing_key) -> None:
    response = TestClient(app).patch(
        "/api/state/sess_없는세션/title",
        json={"title": "아무거나"},
        headers=_headers(signing_key, ME),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"


# ---------------------------------------------------------------- 지난 대화 열기


def test_지난_대화를_열면_주고받은_말이_나온다(signing_key) -> None:
    session_id = _start_chat(ME, "비 오는 날 갈 곳", "실내가 좋아")

    response = TestClient(app).get(f"/api/sessions/{session_id}", headers=_headers(signing_key, ME))

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "비 오는 날 갈 곳"
    assert [turn["user_input"] for turn in body["turns"]] == ["비 오는 날 갈 곳", "실내가 좋아"]


# 이 파일에서 두 번째로 중요한 테스트다. TTL을 적용하면 목록의 거의 모든 항목이
# 열리지 않는다 — 세션은 30분이면 만료되는데 히스토리는 그보다 오래된 대화를
# 보여주는 것이 목적이다.
def test_만료된_대화도_내용은_열린다(signing_key) -> None:
    from datetime import timedelta

    from app.state.schema import now_kst
    from app.state.store import get_store

    session_id = _start_chat(ME, "아주 오래된 질문")
    store = get_store()
    state = store.get_state(session_id)
    assert state is not None
    state.last_active_at = now_kst() - timedelta(days=3)
    store.save_state(state)

    response = TestClient(app).get(f"/api/sessions/{session_id}", headers=_headers(signing_key, ME))

    assert response.status_code == 200
    assert response.json()["turns"][0]["user_input"] == "아주 오래된 질문"
    # 다만 이어서 대화할 수는 없다 — 화면이 그 사실을 밝혀야 한다.
    assert response.json()["resumable"] is False


def test_남의_대화는_열리지_않는다(signing_key) -> None:
    session_id = _start_chat(OTHER, "남의 대화")

    response = TestClient(app).get(f"/api/sessions/{session_id}", headers=_headers(signing_key, ME))

    assert response.status_code == 403


def test_신원이_안_붙은_세션은_열리지_않는다(signing_key) -> None:
    """verify_ownership은 user_id가 비면 통과시키지만, 여기는 '내 대화'만 다룬다."""
    applied = state_service.apply(
        state_service.StateApplyRequest(intent="RECOMMEND", confirmed=True)
    )
    state_service.append_conversation_turn(
        state_service.AppendConversationTurnRequest(
            session_id=applied.session_id,
            turn=state_service.ConversationTurn(user_input="주인 없는 대화"),
        )
    )

    response = TestClient(app).get(
        f"/api/sessions/{applied.session_id}", headers=_headers(signing_key, ME)
    )

    assert response.status_code == 403
