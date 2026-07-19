# RealLlmProvider placeholder - 실제 LLM API 연동 위치.
# TODO: interpret() 구현. structured output/function calling으로 InterpretedInput과
# 동일한 필드를 강제하는 프롬프트/스키마를 설계할 것. 프롬프트 구성과 응답 파싱은 이 클래스 안에만
# 둘 것.

from __future__ import annotations

from app.domain.models import InterpretedInput


class RealLlmProvider:
    """TODO: implement against a real LLM API to turn free-text input into
    InterpretedInput (structured output / function calling recommended).
    Keep prompt construction and response parsing in this class only."""

    def __init__(self, api_key: str | None, timeout_seconds: float) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    async def interpret(self, user_input: str) -> InterpretedInput:
        raise NotImplementedError("RealLlmProvider is not implemented yet.")
