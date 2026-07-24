"""사용자 입력 해석 API 라우터.

역할: 프론트엔드의 자연어 여행 요청을 서비스 계층에 전달하고 LLMOutput을 반환한다.
입력: POST /api/interpret JSON body의 InterpretRequest.
출력: LLMOutput(intent + status + intent별 payload + clarification) JSON 응답.
호출 시점: InputPage에서 사용자가 요청을 제출할 때 호출된다.
TODO: 인증, rate limit이 필요해지면 라우터 밖 의존성으로 연결한다.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas import InterpretRequest, LLMOutput
from app.services.interpret import interpret_user_input

router = APIRouter(tags=["interpret"])


@router.post("/interpret", response_model=LLMOutput)
async def interpret(request: InterpretRequest) -> LLMOutput:
    return await interpret_user_input(request)
