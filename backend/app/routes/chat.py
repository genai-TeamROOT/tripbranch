"""통합 Chat API 라우터.

역할: 프론트 실사용 흐름(HomePage/ChatPage)이 호출하는 단일 진입점. Intent 분류부터
      B/C/D 조정과 챗봇 메시지 조립까지를 `run_agent()`에 그대로 위임한다.
입력: POST /api/chat JSON body의 AgentRequest(user_input, session_id, device_location).
출력: AgentResponse (LLMOutput + 병합된 SessionState + 추천 결과 + 챗봇 메시지).
호출 시점: 사용자가 HomePage에서 추천을 시작하거나 ChatPage에서 후속 발화를 보낼 때.

`/api/agent-debug`와 같은 구현을 공유하지만 용도가 다르다 — 이 라우트는 실사용
경로이고, agent-debug는 개발용 패널 전용으로 남긴다.
TODO: 응답을 공개용으로 좁힌다. 지금은 프론트 전환 비용을 줄이려고 AgentResponse를
      그대로 내보내지만, llm_output 전체와 B의 내부 state까지 공개 계약에 고정되는
      형태라 D-016 확정 시 필요한 필드만 남긴다.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas import AgentRequest, AgentResponse
from app.services.runtime.agent_runtime import run_agent

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=AgentResponse)
async def chat(request: AgentRequest) -> AgentResponse:
    return await run_agent(request)
