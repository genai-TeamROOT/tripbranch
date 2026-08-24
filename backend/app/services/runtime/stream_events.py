"""SSE 관측 이벤트 발신 공용 헬퍼.

`agent_runtime.py`에 있던 것을 그대로 옮겼다 — 인텐트 라우팅 그래프
(`graph/`, docs/design/langgraph-adoption.md)가 같은 sink를 써야 하는데,
`agent_runtime`이 그래프를 import하므로 반대 방향 import는 순환이 된다.
동작은 바뀌지 않았고 정의 위치만 바뀌었다.

계약: `app/routes/chat.py`의 `emit()`이 이 타입의 콜백이다 — 이벤트 이름과
payload를 받아 asyncio.Queue에 넣고, SSE 엔드포인트가 빼서 내보낸다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.schemas import Intent

StreamEventSink = Callable[[str, dict[str, object]], Awaitable[None]]

T = TypeVar("T")

# SCHEDULE 편성(generate_schedule_plan)처럼 단일 LLM 호출 하나가 오래(수십 초) 걸리는
# 구간에서, 로딩 화면이 이 구간 전체를 아무 갱신 없이 멈춰 보이는 문제를 완화한다
# (실사용 피드백, 2026-08-13 — "일정 생성이 로딩 마지막에 혼자 너무 오래 머무른다").
# 진짜 진행 단계를 아는 게 아니라 "아직 살아있다"를 주기적으로 알리는 heartbeat다.
SCHEDULING_HEARTBEAT_MESSAGES = (
    "장소 순서를 계산하고 있어요.",
    "이동 동선을 정리하고 있어요.",
    "체류 시간과 도착 시각을 맞추고 있어요.",
    "조금만 더 기다려주세요, 거의 다 됐어요.",
)
SCHEDULING_HEARTBEAT_INTERVAL_SECONDS = 6.0


async def emit_stream_event(
    sink: StreamEventSink | None, event: str, payload: dict[str, object]
) -> None:
    """SSE 경로의 관측 이벤트를 전달한다. 단발 /api/chat에서는 아무 일도 하지 않는다."""

    if sink is not None:
        await sink(event, payload)


async def emit_progress(sink: StreamEventSink | None, stage: str, message: str) -> None:
    await emit_stream_event(sink, "progress", {"stage": stage, "message": message})


async def begin_streamed_message(
    sink: StreamEventSink | None, *, intent: Intent, progress_message: str
) -> None:
    """LLM 답변이 시작되기 전, 로딩 말풍선을 먼저 연다.

    RECOMMEND/MODIFY도 카드(result)를 첫 텍스트 조각 뒤에 보내므로, GENERAL/INFO와
    마찬가지로 이 이벤트가 프론트의 움직이는 점 표시를 연다.
    """

    await emit_progress(sink, "composing_message", progress_message)
    await emit_stream_event(sink, "message_start", {"intent": intent.value})


async def await_with_heartbeat(
    awaitable: Awaitable[T],
    *,
    sink: StreamEventSink | None,
    stage: str,
    messages: tuple[str, ...] = SCHEDULING_HEARTBEAT_MESSAGES,
    interval_seconds: float = SCHEDULING_HEARTBEAT_INTERVAL_SECONDS,
) -> T:
    """awaitable이 끝날 때까지 progress 이벤트를 주기적으로 흘려보내며 기다린다.

    부수 효과: 프론트([client.ts]의 armInactivityTimer)가 progress 이벤트마다
    45초 무활동 타이머를 다시 세우므로, 편성이 오래 걸려도(폴백 모델까지
    타면 60초대) 클라이언트가 먼저 연결을 끊는 일을 줄여준다.
    """
    task = asyncio.ensure_future(awaitable)
    tick = 0
    try:
        while True:
            done, _pending = await asyncio.wait({task}, timeout=interval_seconds)
            if task in done:
                return task.result()
            await emit_progress(sink, stage, messages[tick % len(messages)])
            tick += 1
    finally:
        if not task.done():
            task.cancel()


__all__ = [
    "SCHEDULING_HEARTBEAT_INTERVAL_SECONDS",
    "SCHEDULING_HEARTBEAT_MESSAGES",
    "StreamEventSink",
    "await_with_heartbeat",
    "begin_streamed_message",
    "emit_progress",
    "emit_stream_event",
]
