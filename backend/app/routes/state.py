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

from app.auth.dependency import OptionalPrincipal
from app.state import service as state_service

router = APIRouter(tags=["state"])


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
