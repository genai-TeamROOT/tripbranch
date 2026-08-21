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

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from sse_starlette import EventSourceResponse, ServerSentEvent

from app.agent_context.factory import get_context_provider
from app.agent_context.info_schemas import InfoContextRequest
from app.auth.dependency import OptionalPrincipal
from app.errors import AppError
from app.observability.api_usage import create_external_client
from app.schemas import (
    AgentRequest,
    AgentResponse,
    RecommendationPlaceDetailRequest,
    RecommendationPlaceDetailResponse,
)
from app.services.runtime.agent_runtime import run_agent
from app.services.runtime.info_response_transform import to_info_place_card
from app.state.session import new_trace_id

router = APIRouter(tags=["chat"])
logger = logging.getLogger(__name__)


@router.post("/chat", response_model=AgentResponse)
async def chat(request: AgentRequest, principal: OptionalPrincipal) -> AgentResponse:
    return await run_agent(request, principal=principal)


@router.post("/chat/place-details", response_model=RecommendationPlaceDetailResponse)
async def recommendation_place_details(
    request: RecommendationPlaceDetailRequest,
) -> RecommendationPlaceDetailResponse:
    """추천 카드 한 곳의 C PlaceDetails를 LLM 없이 조회한다.

    C의 INFO 경로는 이름으로 장소를 해석하므로, 응답의 ``place_id``가 추천 카드의
    ID와 다르면 화면에 싣지 않는다. 동명 장소의 상세가 잘못 열리는 것보다, 상세
    정보 없음으로 남기는 편이 안전하다.
    """

    async with create_external_client() as client:
        context_provider = get_context_provider(client)
        info_response = await context_provider.fetch_info_context(
            InfoContextRequest(
                request_id=new_trace_id(),
                place_name=request.place_name,
                place_context="from_recommendation",
                question_type="general_info",
            )
        )

    place_card = to_info_place_card(info_response)
    if info_response.status == "unavailable":
        return RecommendationPlaceDetailResponse(
            status="unavailable",
            requested_place_id=request.place_id,
        )
    if place_card is None or place_card.place_id != request.place_id:
        if place_card is not None:
            logger.warning(
                "추천 카드 상세 ID 불일치: requested=%s resolved=%s name=%s",
                request.place_id,
                place_card.place_id,
                request.place_name,
            )
        return RecommendationPlaceDetailResponse(
            status="no_data",
            requested_place_id=request.place_id,
        )
    return RecommendationPlaceDetailResponse(
        status="success",
        requested_place_id=request.place_id,
        place_card=place_card,
    )


@router.post("/chat/stream")
async def chat_stream(
    request: AgentRequest, http_request: Request, principal: OptionalPrincipal
) -> EventSourceResponse:
    """Agent의 진행 상태와 스트리밍 가능한 LLM 답변을 SSE로 순서대로 전달한다.

    기존 /chat 단발 JSON 계약은 유지한다. 스트리밍 도중에는 HTTP 예외 핸들러가 이미
    응답을 시작한 뒤라 상태 코드를 바꿀 수 없으므로, AppError는 error 이벤트의 기존
    code/message/retryable 형태로 전달한다.
    """

    async def event_stream() -> AsyncIterator[ServerSentEvent]:
        queue: asyncio.Queue[tuple[str, dict[str, object]]] = asyncio.Queue()
        started_at = time.monotonic()

        async def emit(event: str, payload: dict[str, object]) -> None:
            await queue.put(
                (
                    event,
                    {
                        "elapsed_ms": int((time.monotonic() - started_at) * 1000),
                        **payload,
                    },
                )
            )

        task = asyncio.create_task(
            run_agent(
                request,
                principal=principal,
                stream_event_sink=emit,
                stream_recommendation_summary=True,
            )
        )
        try:
            while not task.done() or not queue.empty():
                if await http_request.is_disconnected():
                    task.cancel()
                    return
                try:
                    event, payload = await asyncio.wait_for(queue.get(), timeout=0.1)
                except TimeoutError:
                    continue
                yield ServerSentEvent(event=event, data=json.dumps(payload, ensure_ascii=False))

            try:
                response = await task
            except AppError as exc:
                yield ServerSentEvent(
                    event="error",
                    data=json.dumps(
                        {
                            "elapsed_ms": int((time.monotonic() - started_at) * 1000),
                            "code": exc.code,
                            "message": exc.message,
                            "retryable": exc.retryable,
                            "details": {"provider": exc.provider, "upstream": exc.details},
                        },
                        ensure_ascii=False,
                    ),
                )
                return
            except Exception:
                # SSE는 이미 200 응답을 시작했으므로 전역 예외 핸들러가 JSON 오류로
                # 바꿀 수 없다. 서버 로그에는 원인을 남기고, 프론트에는 기존 공통
                # 오류 계약과 같은 형태의 error 이벤트를 보낸다.
                logger.exception("스트리밍 채팅 처리 실패")
                yield ServerSentEvent(
                    event="error",
                    data=json.dumps(
                        {
                            "elapsed_ms": int((time.monotonic() - started_at) * 1000),
                            "code": "internal_server_error",
                            "message": "요청을 처리하지 못했어요. 잠시 후 다시 시도해주세요.",
                            "retryable": True,
                            "details": None,
                        },
                        ensure_ascii=False,
                    ),
                )
                return

            yield ServerSentEvent(
                event="done",
                data=json.dumps(
                    {
                        "elapsed_ms": int((time.monotonic() - started_at) * 1000),
                        "response": response.model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                ),
            )
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    return EventSourceResponse(
        event_stream(),
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
