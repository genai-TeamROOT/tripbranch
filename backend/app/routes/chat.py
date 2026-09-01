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
from app.providers.factory import (
    get_google_translate_provider,
    get_llm_provider,
    get_place_details_repository,
)
from app.schemas import (
    AgentRequest,
    AgentResponse,
    PlacePreferenceInsight,
    RecommendationPlaceDetailRequest,
    RecommendationPlaceDetailResponse,
)
from app.services.runtime.agent_runtime import run_agent
from app.services.runtime.follow_up_suggester import suggest_follow_ups
from app.services.runtime.info_response_transform import to_info_place_card
from app.services.runtime.localization import (
    localize_follow_ups_for_user,
    localize_request_for_runtime,
    localize_response_for_user,
)
from app.state.session import new_trace_id

router = APIRouter(tags=["chat"])
logger = logging.getLogger(__name__)


async def _request_for_runtime(request: AgentRequest) -> AgentRequest:
    """영어 입력만 한국어 Agent Runtime 사본으로 변환한다."""

    if request.language != "en":
        return request
    async with create_external_client() as client:
        return await localize_request_for_runtime(request, get_google_translate_provider(client))


async def _response_for_user(response: AgentResponse, *, language: str) -> AgentResponse:
    """영어 화면에 보이는 답변·카드 문장을 번역한다."""

    if language != "en":
        return response
    async with create_external_client() as client:
        return await localize_response_for_user(
            response, language=language, translator=get_google_translate_provider(client)
        )


async def _follow_ups_for_user(
    request: AgentRequest, response: AgentResponse, *, runtime_request: AgentRequest
) -> list[str]:
    """`done` 뒤에 이어 보낼 후속 질문 문구를 만든다.

    Runtime 안이 아니라 여기서 부르는 이유는 순서 때문이다 — 이 호출은 답변이 이미
    화면에 다 뜬 뒤에 도는데, `done`보다 앞에 두면 그 시간만큼 턴이 안 끝나 답변과
    카드 아래에 로딩 말풍선이 한 번 더 뜬 것처럼 보인다(D-102).

    입력은 **한국어 사본**(`runtime_request`, `response`)이다. 화면에 나가는 문구는
    그 결과를 다시 영어로 옮긴 것이다 — Runtime이 한국어로만 도는 전제를 여기서도
    지킨다.
    """

    suggestions = await suggest_follow_ups(runtime_request, response, llm=get_llm_provider())
    if request.language != "en" or not suggestions:
        return suggestions
    async with create_external_client() as client:
        return await localize_follow_ups_for_user(
            suggestions,
            language=request.language,
            translator=get_google_translate_provider(client),
        )


@router.post("/chat", response_model=AgentResponse)
async def chat(request: AgentRequest, principal: OptionalPrincipal) -> AgentResponse:
    runtime_request = await _request_for_runtime(request)
    response = await run_agent(runtime_request, principal=principal)
    return await _response_for_user(response, language=request.language)


@router.post("/chat/place-details", response_model=RecommendationPlaceDetailResponse)
async def recommendation_place_details(
    request: RecommendationPlaceDetailRequest,
) -> RecommendationPlaceDetailResponse:
    """추천/INFO 카드 한 곳의 C PlaceDetails를 LLM 없이 조회한다.

    C의 INFO 경로는 이름으로 장소를 해석한다. 요청이 ``place_id``를 명시한
    경우(추천 카드 클릭)에만 응답의 ``place_id``와 대조해, 다르면 화면에 싣지
    않는다 — 동명 장소의 상세가 잘못 열리는 것보다 상세 정보 없음이 안전하다.
    혼잡도·행사 INFO 카드는 ``place_id`` 없이 이름으로만 조회하며, 이 경우 대조를
    건너뛴다(애초에 이름으로 해석된 장소라 이름 재해석이 일관된다).
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
    if place_card is None:
        return RecommendationPlaceDetailResponse(
            status="no_data",
            requested_place_id=request.place_id,
        )
    # place_id를 명시한 요청(추천 카드 클릭)에만 동명 안전장치로 대조한다.
    if request.place_id is not None and place_card.place_id != request.place_id:
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
    if place_card.place_id:
        async with create_external_client() as client:
            preference_repository = get_place_details_repository(client)
            if preference_repository is not None:
                try:
                    insights = await preference_repository.find_preference_insights(place_card.place_id)
                    place_card = place_card.model_copy(
                        update={
                            "preference_insights": [
                                PlacePreferenceInsight.model_validate(insight) for insight in insights
                            ]
                        }
                    )
                except Exception:
                    logger.exception("상세 카드 취향 근거 조회 실패 — 기본 카드로 응답한다")
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
        task: asyncio.Task[AgentResponse] | None = None

        async def emit(event: str, payload: dict[str, object]) -> None:
            # 영어 응답은 마지막에 문장 묶음을 한 번에 번역한다. Runtime의 한국어
            # message_delta/result를 먼저 내보내면 화면에 한국어가 잠깐 보이고 카드도
            # 번역 전 상태로 고정되므로, 진행 단계만 유지하고 이 세 이벤트는 숨긴다.
            if request.language == "en" and event in {"message_start", "message_delta", "result"}:
                return
            await queue.put(
                (
                    event,
                    {
                        "elapsed_ms": int((time.monotonic() - started_at) * 1000),
                        **payload,
                    },
                )
            )

        try:
            runtime_request = await _request_for_runtime(request)
            task = asyncio.create_task(
                run_agent(
                    runtime_request,
                    principal=principal,
                    stream_event_sink=emit,
                    stream_recommendation_summary=True,
                    # 후속 질문은 done 뒤에 따로 만든다(_follow_ups_for_user).
                    generate_follow_ups=False,
                )
            )
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
                # **한국어 사본을 따로 붙잡아 둔다.** 후속 질문을 만드는 입력이
                # 이쪽이어야 한다 — 번역본을 넘기면 한국어 지침에 영어 답변이
                # 들어가고, 그렇게 나온 문구를 다시 ko→en으로 한 번 더 번역하게
                # 된다. 한국어 요청이면 두 이름이 같은 객체를 가리킨다.
                runtime_response = await task
                response = await _response_for_user(
                    runtime_response, language=request.language
                )
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

            # **done 뒤에 보낸다.** 화면은 done에서 턴을 끝내 로딩을 감추고 입력창을
            # 풀고, 버튼만 조금 늦게 붙는다. 만들지 못했으면 이벤트를 아예 보내지
            # 않는다 — 빈 목록을 보내도 화면이 할 일이 없다.
            try:
                suggestions = await _follow_ups_for_user(
                    request, runtime_response, runtime_request=runtime_request
                )
            except Exception:
                # suggest_follow_ups()가 자체적으로 삼키지만 번역까지 포함한 이
                # 구간 전체를 한 번 더 감싼다. 이미 done을 보낸 뒤라 여기서 예외가
                # 새면 완결된 턴이 스트림 오류로 뒤집힌다.
                logger.warning("후속 질문 전달 실패(답변에는 영향 없음)", exc_info=True)
                suggestions = []
            if suggestions:
                yield ServerSentEvent(
                    event="follow_ups",
                    data=json.dumps(
                        {
                            "elapsed_ms": int((time.monotonic() - started_at) * 1000),
                            "suggestions": suggestions,
                        },
                        ensure_ascii=False,
                    ),
                )
        finally:
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    return EventSourceResponse(
        event_stream(),
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
