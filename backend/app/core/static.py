# 빌드된 프론트엔드(frontend/dist)를 FastAPI가 정적 파일로 서빙하기 위한 선택적 마운트 코드.
# 사용법: app/main.py에서 mount_frontend_if_built(app)을 호출. frontend/dist가 없으면(로컬 개발 중)
# 아무 동작도 하지 않는다 - 이 경우 Vite 개발 서버가 프론트를 서빙하고 /api만 프록시로 넘어온다.
# 의도적으로 API/추천 로직과 완전히 분리해뒀다: 나중에 프론트를 별도 배포(예: Vercel)하게 되면
# 이 파일과 main.py의 호출 한 줄만 지우면 된다.
#
# 라우팅 규칙(반드시 이 순서로 등록되어야 함 - main.py 참고):
#   /docs, /openapi.json, /redoc  -> FastAPI가 앱 생성 시 이미 등록 (가장 먼저 매치)
#   /api/*                        -> api_router (health/interpret/recommendations + 404 catch-all)
#   /assets/*                     -> 빌드된 정적 자산 (StaticFiles, 경로 순회 방어 포함)
#   그 외 모든 경로                 -> 존재하는 정적 파일이면 그대로,
#                                     아니면 index.html (SPA fallback)
#
# React Router 클라이언트 경로(/confirm, /results 등)를 새로고침하거나 직접 접근해도
# FastAPI가 index.html을 돌려줘야 React Router가 정상적으로 화면을 그릴 수 있다.

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

FRONTEND_DIST_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"
INDEX_HTML_PATH = FRONTEND_DIST_DIR / "index.html"
ASSETS_DIR = FRONTEND_DIST_DIR / "assets"

# Top-level path segments that must never fall back to index.html, even if
# route registration order ever changes. /api is handled by api_router's own
# catch-all before this module's route is reached; this is a defensive
# second layer, not the primary mechanism.
RESERVED_PREFIXES = frozenset({"api", "docs", "openapi.json", "redoc"})


def mount_frontend_if_built(app: FastAPI) -> None:
    if not INDEX_HTML_PATH.is_file():
        return

    if ASSETS_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str, request: Request) -> FileResponse:
        first_segment = full_path.split("/", 1)[0]
        if first_segment in RESERVED_PREFIXES:
            raise HTTPException(status_code=404)

        if full_path:
            candidate = (FRONTEND_DIST_DIR / full_path).resolve()
            is_within_dist = (
                candidate == FRONTEND_DIST_DIR or FRONTEND_DIST_DIR in candidate.parents
            )
            if is_within_dist and candidate.is_file():
                return FileResponse(candidate)

        return FileResponse(INDEX_HTML_PATH)
