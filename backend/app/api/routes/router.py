# 개별 routes/*.py의 APIRouter를 모아 "/api" prefix로 묶는 조립 지점.
# 새 리소스(라우트 파일)를 추가하면 이 파일에도 include_router로 등록해야 한다.

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import health, interpret, not_found, recommendations

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(interpret.router)
api_router.include_router(recommendations.router)
# Must stay last: catches any /api/* path not matched above (see not_found.py).
api_router.include_router(not_found.router)
