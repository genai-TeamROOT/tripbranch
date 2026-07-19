# 모든 API 오류 응답이 공유하는 공통 포맷( { "error": {code, message, retryable, details} } ).
# 사용법: 직접 이 모델을 라우트에서 생성하지 않는다 - AppError를 raise하면 main.py의
# exception_handler가 이 스키마 형태로 자동 변환한다.

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.core.errors import ErrorCode


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    retryable: bool = False
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
