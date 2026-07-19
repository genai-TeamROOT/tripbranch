# FastAPI 앱 조립 지점(create_app). 라우터 등록, CORS, 공통 에러 핸들러(AppError/Exception),
# 로깅 초기화, (선택적) 프론트 정적 파일 마운트를 여기서 한 번에 구성한다.
# 사용법: `uvicorn app.main:app --reload`로 실행하거나, backend/package.json의 `npm run dev`를 사용.
# TODO: 인증/미들웨어가 필요해지면 create_app() 안에 add_middleware 호출을 추가할 것
# (현재는 CORS만 있고 인증은 MVP 범위 밖).

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes.router import api_router
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import configure_logging
from app.core.static import mount_frontend_if_built


def _error_envelope(
    *, status_code: int, code: ErrorCode, message: str, retryable: bool, details: Any
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
                "details": details,
            }
        },
    )


def _sanitize_validation_errors(errors: list[dict]) -> list[dict]:
    """Strip pydantic's "input"/"url" keys (which echo back the raw
    submitted value / a docs link) before including errors in the response
    -- keep only field location, message, and error type."""
    return [
        {"loc": list(err.get("loc", [])), "msg": err.get("msg"), "type": err.get("type")}
        for err in errors
    ]


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.app_env)

    app = FastAPI(title="TripBranch API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        details = exc.details if not settings.is_production else None
        return _error_envelope(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
            details=details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = _sanitize_validation_errors(exc.errors()) if not settings.is_production else None
        return _error_envelope(
            status_code=422,
            code="invalid_request",
            message="요청 내용을 확인해주세요.",
            retryable=False,
            details=details,
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        # Covers Starlette/FastAPI's own HTTPException raises (e.g. 405 on a
        # matched route with the wrong method). Unmatched /api/* paths are
        # handled by api/routes/not_found.py instead, since Starlette's
        # default "no route matched" response bypasses exception handlers
        # entirely and never reaches here.
        code: ErrorCode = "invalid_request" if exc.status_code < 500 else "internal_server_error"
        message = exc.detail if isinstance(exc.detail, str) else "요청을 처리할 수 없어요."
        return _error_envelope(
            status_code=exc.status_code,
            code=code,
            message=message,
            retryable=False,
            details=None,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        details = str(exc) if not settings.is_production else None
        return _error_envelope(
            status_code=500,
            code="internal_server_error",
            message="예상치 못한 오류가 발생했어요.",
            retryable=False,
            details=details,
        )

    app.include_router(api_router)

    # Kept separate from API/recommendation code; no-op until frontend/dist exists.
    mount_frontend_if_built(app)

    return app


app = create_app()
