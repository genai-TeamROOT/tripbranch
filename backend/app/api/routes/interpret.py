# POST /api/interpret - 사용자의 자유 입력 텍스트를 구조화된 검색 조건으로 변환.
# InterpretService(LlmProvider 주입)에 위임만 하고, 응답 스키마 매핑만 이 파일에서 처리한다.
# 사용법: 프론트 InputPage에서 사용자가 텍스트를 제출하면 이 엔드포인트를 호출한다.
# TODO: 실제 LLM 연동 시 응답 지연이 커질 수 있으니, 타임아웃/스트리밍 여부를 여기서 결정할 것.

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_interpret_service
from app.schemas.common import ErrorResponse
from app.schemas.interpret import InterpretRequest, InterpretResponse
from app.services.interpret_service import InterpretService

router = APIRouter(tags=["interpret"])


@router.post(
    "/interpret",
    response_model=InterpretResponse,
    responses={"default": {"model": ErrorResponse, "description": "Common error envelope"}},
)
async def interpret_user_input(
    request: InterpretRequest,
    service: InterpretService = Depends(get_interpret_service),
) -> InterpretResponse:
    result = await service.interpret(request.user_input)
    return InterpretResponse(
        location_query=result.location_query,
        preferred_categories=result.preferred_categories,
        weather_condition=result.weather_condition,
        search_radius_km=result.search_radius_km,
    )
