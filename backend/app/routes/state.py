"""세션 상태 조회/삭제 + 장소 보관함 API 라우터.

역할: 별도 추천 호출 없이도 현재 세션 상태를 확인하고, 필요 시 세션을 정리하며,
사용자가 추천 카드에서 담은 장소를 보관함에 넣고 뺀다(SCHEDULE-12).
입력: GET/DELETE /api/state/{session_id},
      GET/POST /api/state/{session_id}/saved-places,
      DELETE /api/state/{session_id}/saved-places/{place_id}
출력: SessionContextResponse / DeleteSessionResponse / SavedPlacesResponse.
호출 시점: 프론트가 상태 동기화·채팅 초기화를 수행할 때, 또는 사용자가 추천
카드의 담기 버튼을 누를 때.

보관함 담기·빼기는 인텐트 분류를 거치지 않는다 — 버튼 클릭은 해석할 여지가
없는 결정적 동작이라 LLM을 태울 이유가 없고, /api/chat을 통하면 오분류 위험과
지연이 그대로 붙는다(SCHEDULE-12 설계안 2절).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.auth.dependency import OptionalPrincipal, RequiredPrincipal
from app.state import service as state_service

router = APIRouter(tags=["state"])


class RenameSessionRequest(BaseModel):
    title: str


@router.get("/sessions", response_model=state_service.ChatSessionsResponse)
async def list_sessions(principal: RequiredPrincipal) -> state_service.ChatSessionsResponse:
    """내 대화 목록. 사이드바 채팅 히스토리가 쓴다. (TP-222 후속)

    경로가 /state/{session_id} 아래가 아닌 이유는 이 목록이 특정 세션에 속하지
    않기 때문이다 — 넣었다면 /state/{session_id}가 "sessions"를 session_id로
    받아 삼켰을 것이다.

    /preferences와 같이 RequiredPrincipal을 쓴다. 신원이 곧 조회 키라, 토큰이
    없으면 누구의 목록인지가 정해지지 않는다.
    """
    return state_service.list_user_sessions(principal.user_id)


@router.get("/sessions/{session_id}", response_model=state_service.ChatSessionDetail)
async def get_session_detail(
    session_id: str, principal: RequiredPrincipal
) -> state_service.ChatSessionDetail:
    """지난 대화 하나. 사이드바에서 한 줄을 눌렀을 때 쓴다. (TP-222 후속)

    /state/{session_id}와 달리 **TTL을 적용하지 않는다.** 채팅 히스토리는 30분보다
    오래된 대화를 보여주는 것이 목적이라, 만료를 없는 것으로 취급하면 목록의 거의
    모든 항목이 열리지 않는다.
    """
    return state_service.get_user_session_detail(session_id, principal)


@router.patch(
    "/state/{session_id}/title",
    response_model=state_service.ChatSessionSummary,
)
async def rename_session(
    session_id: str,
    request: RenameSessionRequest,
    principal: RequiredPrincipal,
) -> state_service.ChatSessionSummary:
    """대화 이름을 바꾼다.

    여기는 경로에 session_id가 들어오므로 남의 대화를 지목할 수 있다 —
    서비스가 소유권을 대조한다.
    """
    return state_service.rename_session(session_id, request.title, principal=principal)


@router.get("/state/{session_id}", response_model=state_service.SessionContextResponse)
async def get_state(
    session_id: str, principal: OptionalPrincipal
) -> state_service.SessionContextResponse:
    return state_service.get_session_context(session_id, principal=principal)


@router.delete("/state/{session_id}", response_model=state_service.DeleteSessionResponse)
async def delete_state(
    session_id: str, principal: OptionalPrincipal
) -> state_service.DeleteSessionResponse:
    return state_service.delete_session(session_id, principal=principal)


@router.get(
    "/state/{session_id}/saved-places",
    response_model=state_service.SavedPlacesResponse,
)
async def get_saved_places(
    session_id: str, principal: OptionalPrincipal
) -> state_service.SavedPlacesResponse:
    return state_service.get_saved_places(session_id, principal=principal)


@router.post(
    "/state/{session_id}/saved-places",
    response_model=state_service.SavedPlacesResponse,
)
async def save_place(
    session_id: str,
    request: state_service.SavePlaceRequest,
    principal: OptionalPrincipal,
) -> state_service.SavedPlacesResponse:
    return state_service.save_place(session_id, request, principal=principal)


@router.delete(
    "/state/{session_id}/saved-places/{place_id}",
    response_model=state_service.SavedPlacesResponse,
)
async def remove_saved_place(
    session_id: str, place_id: str, principal: OptionalPrincipal
) -> state_service.SavedPlacesResponse:
    return state_service.remove_saved_place(session_id, place_id, principal=principal)
