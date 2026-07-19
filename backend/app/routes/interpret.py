from __future__ import annotations

from fastapi import APIRouter

from app.schemas import InterpretedConditions, InterpretRequest
from app.services.interpret import interpret_user_input

router = APIRouter(tags=["interpret"])


@router.post("/interpret", response_model=InterpretedConditions)
async def interpret(request: InterpretRequest) -> InterpretedConditions:
    return interpret_user_input(request.user_input)
