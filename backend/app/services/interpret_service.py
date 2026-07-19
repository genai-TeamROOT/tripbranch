# 자유 입력 텍스트 -> 구조화된 조건(InterpretedInput) 흐름을 조합하는 서비스.
# 빈 입력 검증(AppError invalid_request)과 LlmProvider 예외를
# AppError(llm_interpretation_failed)로 감싸는 책임을 가진다.
# 사용법: api/deps.py에서 LlmProvider를 주입받아 생성되고, api/routes/interpret.py가 호출한다.

from __future__ import annotations

from app.core.errors import AppError
from app.domain.models import InterpretedInput
from app.providers.protocols.llm import LlmProvider


class InterpretService:
    def __init__(self, llm_provider: LlmProvider) -> None:
        self._llm_provider = llm_provider

    async def interpret(self, user_input: str) -> InterpretedInput:
        if not user_input or not user_input.strip():
            raise AppError(code="invalid_request", message="입력 내용이 비어 있어요.")

        try:
            return await self._llm_provider.interpret(user_input)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code="llm_interpretation_failed",
                message="입력을 이해하지 못했어요. 다시 시도해주세요.",
                retryable=True,
            ) from exc
