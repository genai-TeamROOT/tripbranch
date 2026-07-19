// 공통 fetch 래퍼(apiClient)와 ApiError 클래스. 모든 API 호출은 이 모듈을 거쳐야 하며,
// 각 페이지에서 직접 fetch()를 호출하지 않는다. VITE_API_BASE_URL이 없으면 same-origin
// "/api"를 사용(개발 중엔 Vite 프록시가 백엔드로 전달).
// 사용법: 새 API가 필요하면 이 client의 get/post를 이용해 api/ 아래 새 파일을 만들 것.
// 백엔드 공통 에러 포맷({error:{code,message,retryable,details}})을 ApiError로 변환해 던진다.

import type { ApiErrorBody } from "../types/domain";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";

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
      message: "서버에 연결할 수 없어요. 네트워크 상태를 확인해주세요.",
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
        message: "알 수 없는 오류가 발생했어요.",
        retryable: false,
        details: null,
      },
    );
  }

  return data as T;
}

export const apiClient = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
};
