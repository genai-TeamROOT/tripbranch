from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.errors import AppError
from app.routes.health import router as health_router
from app.routes.interpret import router as interpret_router
from app.routes.recommendations import router as recommendations_router


def create_app() -> FastAPI:
    app = FastAPI(title="TripBranch API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(exc.code, exc.message, exc.status_code, exc.retryable)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response("invalid_request", "요청 내용을 확인해주세요.", 422)

    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return _error_response("invalid_request", "요청한 API를 찾을 수 없어요.", 404)
        return _error_response("invalid_request", "요청 내용을 확인해주세요.", exc.status_code)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        return _error_response("internal_server_error", "예상치 못한 오류가 발생했어요.", 500)

    app.include_router(health_router, prefix="/api")
    app.include_router(interpret_router, prefix="/api")
    app.include_router(recommendations_router, prefix="/api")
    return app


def _error_response(
    code: str,
    message: str,
    status_code: int,
    retryable: bool = False,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
                "details": None,
            }
        },
    )


app = create_app()
