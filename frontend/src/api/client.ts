/*
 * 역할: TripBranch 백엔드와 통신하는 공통 fetch 래퍼.
 * 입력: API path, 요청 body, fetch 옵션.
 * 출력: 파싱된 JSON 응답 또는 표준화된 ApiError.
 * 호출 시점: endpoint별 API 함수가 HTTP 요청을 보낼 때 호출된다.
 * TODO: 인증, timeout, abort, retry 정책이 필요해지면 이 계층에서 추가한다.
 */

import type { ApiErrorBody } from "../types";

const rawBaseUrl = import.meta.env.VITE_API_BASE_URL || "/api";
const API_BASE_URL = rawBaseUrl.replace(/\/$/, "");

export class ApiError extends Error {
  code: string;
  retryable: boolean;
  details: unknown;

  constructor(body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.code = body.code;
    this.retryable = body.retryable;
    this.details = body.details;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...options?.headers },
    });
  } catch {
    throw new ApiError({
      code: "internal_server_error",
      message: "서버에 연결할 수 없어요.",
      retryable: true,
      details: null,
    });
  }

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const errorBody = data?.error as ApiErrorBody | undefined;
    throw new ApiError(
      errorBody ?? {
        code: "internal_server_error",
        message: "요청을 처리하지 못했어요.",
        retryable: false,
        details: null,
      },
    );
  }

  return data as T;
}

/** POST 본문을 유지한 SSE 응답 파서. EventSource는 GET만 지원해 채팅 요청에 맞지 않는다. */
export async function streamPost<T>(
  path: string,
  body: unknown,
  onEvent: (event: string, data: T) => void,
): Promise<void> {
  const controller = new AbortController();
  // 서버가 첫 progress를 보낸 뒤 프로세스 재시작·네트워크 단절 등으로 다음 이벤트를
  // 못 보내면 fetch 스트림은 닫히지 않은 채 대기할 수 있다. 단순 ping이 아니라 실제
  // 업무 이벤트(progress/result/delta/done/error) 기준으로만 시간을 갱신한다.
  let inactivityTimer: ReturnType<typeof setTimeout> | null = null;
  let inactivityTimedOut = false;
  const armInactivityTimer = () => {
    if (inactivityTimer) clearTimeout(inactivityTimer);
    inactivityTimer = setTimeout(() => {
      inactivityTimedOut = true;
      controller.abort();
    }, 45_000);
  };

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } catch {
    throw new ApiError({
      code: "internal_server_error",
      message: "서버에 연결할 수 없어요.",
      retryable: true,
      details: null,
    });
  }

  if (!response.ok || !response.body) {
    const data = await response.json().catch(() => null);
    const errorBody = data?.error as ApiErrorBody | undefined;
    throw new ApiError(
      errorBody ?? {
        code: "internal_server_error",
        message: "요청을 처리하지 못했어요.",
        retryable: false,
        details: null,
      },
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const consumeFrame = (frame: string) => {
    const lines = frame.replace(/\r/g, "").split("\n");
    const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
    const data = lines
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (event && data) {
      armInactivityTimer();
      onEvent(event, JSON.parse(data) as T);
    }
  };

  armInactivityTimer();
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
      // sse-starlette는 환경에 따라 CRLF(\r\n)를 쓸 수 있다. 프레임 경계를 찾기 전에
      // LF로 통일하지 않으면 "\r\n\r\n"을 "\n\n"으로 인식하지 못해 이벤트가
      // 마지막까지 화면에 전달되지 않는다.
      buffer = buffer.replace(/\r\n/g, "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        consumeFrame(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf("\n\n");
      }
      if (done) break;
    }
    if (buffer.trim()) consumeFrame(buffer);
  } catch (error) {
    if (inactivityTimedOut) {
      throw new ApiError({
        code: "stream_inactive",
        message: "응답 연결이 45초 동안 멈췄어요. 다시 시도해주세요.",
        retryable: true,
        details: null,
      });
    }
    throw error;
  } finally {
    if (inactivityTimer) clearTimeout(inactivityTimer);
  }
}

export const apiClient = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
};
