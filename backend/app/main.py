"""TripBranch API 애플리케이션 조립 지점.

역할: FastAPI 인스턴스, 공통 예외 응답, CORS, 라우터 등록을 구성한다.
입력: ASGI 서버나 테스트 클라이언트가 전달하는 HTTP 요청.
출력: JSON API 응답과 FastAPI 앱 객체.
호출 시점: uvicorn 실행, 테스트 클라이언트 생성, 앱 부팅 시 호출된다.
TODO: 실제 운영 환경별 CORS/로깅/관측 설정이 필요해지면 여기에서 연결한다.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.errors import AppError
from app.providers.factory import validate_provider_config
from app.providers.tour_category_registry import get_tour_category_registry
from app.routes.agent import router as agent_router
from app.routes.chat import router as chat_router
from app.routes.dev import router as dev_router
from app.routes.health import router as health_router
from app.routes.interpret import router as interpret_router
from app.routes.recommendations import router as recommendations_router
from app.routes.state import router as state_router
from app.routes.transcribe import router as transcribe_router
from app.services.runtime.llm_execution import get_llm_execution_metadata

# uvicorn이 핸들러를 붙여둔 logger를 그대로 쓴다 — 앱 전용 logger를 만들면 별도
# 로깅 설정 없이는 서버 콘솔에 아무것도 보이지 않는다.
logger = logging.getLogger("uvicorn.error")


_APP_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def _running_under_uvicorn() -> bool:
    """uvicorn이 로깅 설정을 마친 상태인지 확인한다.

    uvicorn 기본 설정은 uvicorn.error에 level만 주고 핸들러는 부모인 uvicorn에
    두므로 두 곳을 함께 본다. root까지 올라가면 pytest가 붙인 핸들러를 uvicorn의
    것으로 오인해 테스트 로깅을 건드리게 되므로 root는 보지 않는다.
    """
    return any(
        logging.getLogger(name).handlers for name in ("uvicorn.error", "uvicorn")
    )


def _configure_app_logging() -> None:
    """app.* logger에 타임스탬프가 붙는 핸들러를 붙인다.

    uvicorn은 uvicorn/uvicorn.error/uvicorn.access에만 핸들러를 붙이고 root에는
    붙이지 않는다. 그래서 app.providers.* 로그는 표준 lastResort 핸들러로 떨어져
    레벨 표시 없이 맨 문자열로 나온다. 게다가 uvicorn 기본 포매터에는 시각이 없어
    핸들러를 그대로 빌려와도 "새벽 몇 시에 났는지"를 알 수 없다 — provider 장애
    추적에는 그게 핵심이라 시각을 포함한 자체 포매터를 쓴다.
    """
    app_logger = logging.getLogger("app")
    if app_logger.handlers or not _running_under_uvicorn():
        # uvicorn 없이 임포트된 경우(테스트 등)엔 기존 동작을 그대로 둔다.
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_APP_LOG_FORMAT))
    app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)
    # root로 다시 올려보내면 같은 줄이 두 번 찍힐 수 있다.
    app_logger.propagate = False


def _log_provider_modes() -> None:
    """부팅 시 각 Provider의 Fake/Real 모드를 남긴다.

    .env를 읽지 못하면 오류 없이 전부 fake로 뜨기 때문에, 실데이터로 띄웠다고
    생각한 서버가 실은 stub 응답을 주는 상황을 로그만 보고 알 수 있게 한다.
    """
    modes = {
        "llm": settings.resolved_llm_provider,
        "place": settings.resolved_place_provider,
        "geocoding": settings.resolved_geocoding_provider,
        "weather": settings.resolved_weather_provider,
        "concentration": settings.resolved_concentration_provider,
        "holiday": settings.resolved_holiday_provider,
        # 공통 PROVIDER_MODE를 상속하지 않아 resolved_* 변형이 없다(config.py).
        "travel_route": settings.travel_route_provider,
    }
    summary = ", ".join(f"{name}={mode}" for name, mode in modes.items())
    logger.info(
        "Provider 모드: %s, place_details_source=%s",
        summary,
        settings.resolved_place_details_source,
    )
    if all(mode == "fake" for mode in modes.values()):
        logger.warning(
            "모든 Provider가 fake입니다. 실데이터로 띄우려면 backend/.env의 "
            "PROVIDER_MODE를 확인하세요(백엔드는 backend/ 에서 실행해야 합니다)."
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # uvicorn의 로깅 설정이 끝난 뒤여야 핸들러를 빌려올 수 있다.
    _configure_app_logging()
    # 오설정을 첫 요청의 익명 500이 아니라 부팅 실패로 드러낸다.
    validate_provider_config()
    _log_provider_modes()
    app.state.tour_category_registry = get_tour_category_registry()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="TripBranch API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        # AppError는 provider/도메인 오류가 모두 거쳐가는 단일 지점이다 — 여기서
        # 로그를 남기지 않으면 502 등이 클라이언트 응답만 나가고 서버 로그엔 아무
        # 흔적도 안 남는다(D-052에서 발견).
        logger.error(
            "AppError: code=%s provider=%s status=%s path=%s details=%s",
            exc.code,
            exc.provider,
            exc.status_code,
            request.url.path,
            exc.details,
        )
        details: dict[str, object] | None = None
        if exc.provider or exc.details:
            details = {"provider": exc.provider, "upstream": exc.details}
        llm_execution = get_llm_execution_metadata()
        if llm_execution is not None:
            if details is None:
                details = {}
            details["llm_execution"] = llm_execution.model_dump()
        return _error_response(
            exc.code, exc.message, exc.status_code, exc.retryable, details=details
        )

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
    app.include_router(agent_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    app.include_router(transcribe_router, prefix="/api")
    app.include_router(state_router, prefix="/api")
    # 개발자 Ops 패널은 DB 쓰기까지 하는 엔드포인트를 갖는다. 설정 플래그로
    # 막는 대신 로컬이 아니면 라우트를 아예 등록하지 않아 존재 자체를 없앤다.
    if settings.app_env == "local":
        app.include_router(dev_router, prefix="/api")
    return app


def _error_response(
    code: str,
    message: str,
    status_code: int,
    retryable: bool = False,
    details: object | None = None,
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


app = create_app()
