# LlmProvider 계약: 자유 입력 텍스트를 InterpretedInput으로 구조화.
# 사용법: 새 LLM을 붙일 땐 interpret() 하나만 이 시그니처로 구현하면 서비스/API 계층은
# 전혀 손댈 필요가 없다.

from __future__ import annotations

from typing import Protocol

from app.domain.models import InterpretedInput


class LlmProvider(Protocol):
    async def interpret(self, user_input: str) -> InterpretedInput:
        """Turn free-text user input into structured search conditions."""
        ...
