"""응답 피드백(좋아요/싫어요) API 라우터.

역할: 사용자가 특정 응답(run_id)에 대해 남긴 좋아요/싫어요를 기록·조회한다.
입력: POST /api/feedback JSON body의 RecordFeedbackRequest,
      GET /api/feedback/dislikes?limit=
출력: RecordFeedbackResponse / DislikeFeedbackResponse.
호출 시점: POST는 프론트가 답변 카드의 좋아요/싫어요 버튼 클릭을 처리할 때.
      GET dislikes는 프롬프트 개선을 위해 나쁜 답변을 찾아볼 때(개발자용,
      아직 전용 화면은 없음 — dev 패널이나 직접 호출로 확인).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.auth.dependency import OptionalPrincipal
from app.state import service as state_service

router = APIRouter(tags=["feedback"])


@router.post("/feedback", response_model=state_service.RecordFeedbackResponse)
async def record_feedback(
    request: state_service.RecordFeedbackRequest, principal: OptionalPrincipal
) -> state_service.RecordFeedbackResponse:
    return state_service.record_feedback(request)


@router.get("/feedback/dislikes", response_model=state_service.DislikeFeedbackResponse)
async def get_dislike_feedback(
    principal: OptionalPrincipal, limit: int = 50
) -> state_service.DislikeFeedbackResponse:
    return state_service.get_dislike_feedback(limit=limit)
