"""세션 상태 조회/삭제 라우터 테스트.

역할: GET/DELETE /api/state/{session_id}가 B 서비스에 위임되는지 검증한다.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.state import service as state_service


def test_get_state_returns_session_context() -> None:
    client = TestClient(app)

    applied = state_service.apply(
        state_service.StateApplyRequest(intent="RECOMMEND", confirmed=True)
    )

    response = client.get(f"/api/state/{applied.session_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == applied.session_id
    assert body["session_exists"] is True


def test_delete_state_removes_session() -> None:
    client = TestClient(app)

    applied = state_service.apply(
        state_service.StateApplyRequest(intent="RECOMMEND", confirmed=True)
    )
    session_id = applied.session_id

    delete_response = client.delete(f"/api/state/{session_id}")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"session_id": session_id, "deleted": True}

    get_response = client.get(f"/api/state/{session_id}")
    assert get_response.status_code == 200
    assert get_response.json()["session_exists"] is False
