# GET /api/health - 서버 생존 확인용 엔드포인트.
# 사용법: 로드밸런서/모니터링, 프론트 개발 중 백엔드가 떴는지 확인할 때 curl로 호출.
# 응답 스키마 변경 없이 계속 { "status": "ok" } 형태를 유지하는 게 좋다(외부 헬스체크 계약).

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    return HealthResponse(status="ok")
