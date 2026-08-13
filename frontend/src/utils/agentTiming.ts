import type { AgentProgressEvent, AgentStageTiming } from "../types";

export interface StreamFirstTokenTiming {
  messageStartElapsedMs: number | null;
  firstMessageDeltaElapsedMs: number | null;
}

/**
 * SSE progress 이벤트의 서버 경과 시간을 단계별 구간으로 변환한다.
 * 다음 단계가 시작된 시점을 앞 단계의 종료로 보고, 마지막 단계는 done 이벤트 시점에
 * 닫는다. 따라서 네트워크 수신 시간 대신 서버에서 실제로 측정한 시간을 표시한다.
 */
export function buildAgentStageTimings(
  progressEvents: AgentProgressEvent[],
  completedElapsedMs: number,
  streamTiming?: StreamFirstTokenTiming,
): AgentStageTiming[] {
  return progressEvents.map((event, index) => {
    const nextStartedAt = progressEvents[index + 1]?.elapsed_ms ?? completedElapsedMs;
    const timeToFirstTokenMs =
      event.stage === "composing_message" &&
      streamTiming?.messageStartElapsedMs != null &&
      streamTiming.firstMessageDeltaElapsedMs != null
        ? Math.max(0, streamTiming.firstMessageDeltaElapsedMs - streamTiming.messageStartElapsedMs)
        : undefined;
    return {
      stage: event.stage,
      message: event.message,
      started_at_ms: event.elapsed_ms,
      duration_ms: Math.max(0, nextStartedAt - event.elapsed_ms),
      ...(timeToFirstTokenMs !== undefined ? { time_to_first_token_ms: timeToFirstTokenMs } : {}),
    };
  });
}
