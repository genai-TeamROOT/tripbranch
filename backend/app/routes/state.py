"""세션 상태 조회/삭제 API 라우터.

역할: 별도 추천 호출 없이도 현재 세션 상태를 확인하고, 필요 시 세션을 정리한다.
입력: GET/DELETE /api/state/{session_id}
출력: GET은 SessionContextResponse, DELETE는 DeleteSessionResponse.
호출 시점: 프론트가 상태 동기화 또는 채팅 초기화를 명시적으로 수행할 때.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.auth.dependency import OptionalPrincipal
from app.state import service as state_service

router = APIRouter(tags=["state"])


@router.get("/state/{session_id}", response_model=state_service.SessionContextResponse)
async def get_state(
    session_id: str, principal: OptionalPrincipal
) -> state_service.SessionContextResponse:
    return state_service.get_session_context(session_id)


@router.delete("/state/{session_id}", response_model=state_service.DeleteSessionResponse)
async def delete_state(
    session_id: str, principal: OptionalPrincipal
) -> state_service.DeleteSessionResponse:
    return state_service.delete_session(session_id)
