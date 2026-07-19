# GET /api/health 응답 스키마. 필드가 하나뿐이라 단순하지만, 외부 헬스체크 도구가
# 이 계약(status 필드)에 의존할 수 있으니 필드명은 함부로 바꾸지 말 것.

from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str = "ok"
