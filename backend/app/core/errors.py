# 앱 전역에서 사용하는 예외 타입(AppError)과 에러 코드 -> HTTP 상태코드 매핑.
# 사용법: services/domain 어디서든 `raise AppError(code="location_not_found", message=...)` 형태로
# 던지면 app/main.py의 exception_handler가 공통 { "error": {...} } 포맷으로 변환해 응답한다.
# 새 에러 상황이 생기면 ErrorCode Literal과 ERROR_STATUS_CODES에 코드를 추가할 것
# (코드 추가 없이 임의 문자열을 code로 넘기면 타입체커가 잡아준다).

"""Common application error type and the shared error response envelope.

Every raised AppError is converted by the handler registered in
app/main.py into:

{
  "error": {
    "code": "...",
    "message": "...",
    "retryable": bool,
    "details": null | {...}
  }
}
"""

from __future__ import annotations

from typing import Any, Literal

ErrorCode = Literal[
    "invalid_request",
    "location_not_found",
    "location_ambiguous",
    "llm_interpretation_failed",
    "weather_unavailable",
    "place_provider_unavailable",
    "recommendation_not_found",
    "internal_server_error",
]

# HTTP status code per error code.
ERROR_STATUS_CODES: dict[ErrorCode, int] = {
    "invalid_request": 400,
    "location_not_found": 404,
    "location_ambiguous": 409,
    "llm_interpretation_failed": 502,
    "weather_unavailable": 502,
    "place_provider_unavailable": 502,
    "recommendation_not_found": 404,
    "internal_server_error": 500,
}


class AppError(Exception):
    """Raise this anywhere in services/domain to produce a well-formed API
    error response. `details` must never contain secrets, API keys, or raw
    upstream response bodies in production; the global handler strips
    `details` in non-local environments regardless."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        details: Any = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details
        # Normally the HTTP status is derived from `code`. `status_code` is an
        # explicit escape hatch for cases where the same code legitimately
        # maps to a different status depending on context (e.g. reusing
        # "invalid_request" for an unmatched /api/* path at 404 instead of
        # its default 400, per the fixed 8-code error contract).
        self.status_code = status_code if status_code is not None else ERROR_STATUS_CODES[code]
