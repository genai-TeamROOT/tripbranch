# /api/* 경로 중 다른 라우터가 처리하지 못한 나머지를 공통 에러 포맷의 404로 응답하는 catch-all.
# Starlette의 기본 404는 exception handler를 거치지 않고 PlainTextResponse를 바로 내려버려서
# (health/interpret/recommendations 어디에도 안 걸리는 /api/nope 같은 요청이) 공통 에러 envelope를
# 우회하게 된다 - 그걸 막기 위한 라우트다.
# 사용법: router.py에서 반드시 다른 모든 /api 라우터를 include한 "다음"에 이 라우터를 등록할 것
# (라우트 매칭은 등록 순서를 따르므로, 먼저 등록하면 실제 엔드포인트보다 이게 먼저 매치되어 버린다).

from __future__ import annotations

from fastapi import APIRouter

from app.core.errors import AppError

router = APIRouter(tags=["not-found"])


@router.api_route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
async def api_not_found(full_path: str) -> None:
    raise AppError(
        code="invalid_request",
        message="요청하신 API 경로를 찾을 수 없어요.",
        status_code=404,
    )
