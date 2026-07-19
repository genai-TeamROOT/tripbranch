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

export const apiClient = {
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
};
