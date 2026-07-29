"""LLMProvider 계약과 Gemini 실제 구현.

계약: 사용자 자연어 발화를 구조화된 Intent/Conditions(LLMOutput)로 변환한다. 1단계
Intent 분류와 2단계 Intent별 조건 추출을 별도 호출로 나눠 수행한다(설계는
docs/design/intent-definition.md, docs/design/llm-output-schema.md 참고). 구조화 출력
검증 실패는 1회 재시도하고, 그래도 실패하면 AppError(code="llm_output_invalid")를 던진다.
타임아웃/429/5xx 같은 일시적 오류는 지수 백오프로 별도 재시도한다(둘은 독립적인 재시도다 —
검증 재시도는 "응답은 왔지만 스키마가 안 맞음", 백오프 재시도는 "응답 자체가 안 옴"을 다룬다).
"""

from __future__ import annotations

import asyncio
import random
from datetime import date
from typing import TypeVar

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel, ValidationError

from app.errors import AppError, ProviderTimeoutError, ProviderUnavailableError
from app.providers import gemini_prompts
from app.providers.contracts import ProviderResult, ProviderSource, provider_result
from app.schemas import GeneralTopic, IntentClassificationResult, LLMOutput, UserConditions

T = TypeVar("T", bound=BaseModel)


class _GeneralAnswer(BaseModel):
    """generate_general_answer() 전용 구조화 출력 wire 모델. 다른 곳에서 쓰지 않는다."""

    answer: str

# 429(rate limit)와 5xx(서버 과부하/일시 장애)만 재시도 대상. 4xx(인증 실패, 잘못된 요청 등)는
# 재시도해도 같은 결과이므로 즉시 실패시킨다.
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_BACKOFF_BASE_SECONDS = 0.5


def _backoff_seconds(attempt: int) -> float:
    """지수 백오프 + 지터. attempt=0이 첫 번째 재시도 전 대기시간."""
    return _BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0, 0.25)


class RealGeminiProvider:
    """google-genai SDK로 Gemini 구조화 출력을 호출하는 실제 구현.

    다른 Real provider와 달리 공유 httpx.AsyncClient를 받지 않는다 — google-genai가
    자체 비동기 클라이언트를 관리하기 때문(SDK 사용 요구사항에 따른 의도적인 구조 차이).
    """

    def __init__(
        self,
        api_key: str,
        model_name: str,
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
    ) -> None:
        self._client = genai.Client(
            api_key=api_key,
            http_options=genai_types.HttpOptions(timeout=int(timeout_seconds * 1000)),
        )
        self._model_name = model_name
        self._max_retries = max_retries

    async def classify_intent(
        self,
        user_input: str,
        *,
        has_previous_recommendation: bool,
        shown_place_count: int,
    ) -> ProviderResult[IntentClassificationResult]:
        instruction = gemini_prompts.build_intent_classification_instruction(
            has_previous_recommendation=has_previous_recommendation,
            shown_place_count=shown_place_count,
        )
        result = await self._call_structured(
            instruction, user_input, IntentClassificationResult
        )
        return provider_result(result, source=ProviderSource.GEMINI)

    async def extract_recommend_conditions(
        self, user_input: str
    ) -> ProviderResult[LLMOutput]:
        instruction = gemini_prompts.build_recommend_extraction_instruction()
        result = await self._call_structured(instruction, user_input, LLMOutput)
        return provider_result(result, source=ProviderSource.GEMINI)

    async def extract_modify_conditions(
        self, user_input: str, current_conditions: UserConditions
    ) -> ProviderResult[LLMOutput]:
        instruction = gemini_prompts.build_modify_extraction_instruction(
            current_conditions
        )
        result = await self._call_structured(instruction, user_input, LLMOutput)
        return provider_result(result, source=ProviderSource.GEMINI)

    async def extract_info_query(
        self,
        user_input: str,
        *,
        has_previous_recommendation: bool,
        reference_date: date,
    ) -> ProviderResult[LLMOutput]:
        instruction = gemini_prompts.build_info_extraction_instruction(
            has_previous_recommendation=has_previous_recommendation,
            reference_date=reference_date,
        )
        result = await self._call_structured(instruction, user_input, LLMOutput)
        return provider_result(result, source=ProviderSource.GEMINI)

    async def extract_compare_request(
        self, user_input: str, *, shown_place_count: int
    ) -> ProviderResult[LLMOutput]:
        instruction = gemini_prompts.build_compare_extraction_instruction(
            shown_place_count=shown_place_count
        )
        result = await self._call_structured(instruction, user_input, LLMOutput)
        return provider_result(result, source=ProviderSource.GEMINI)

    async def extract_general_request(
        self, user_input: str
    ) -> ProviderResult[LLMOutput]:
        instruction = gemini_prompts.build_general_extraction_instruction()
        result = await self._call_structured(instruction, user_input, LLMOutput)
        return provider_result(result, source=ProviderSource.GEMINI)

    async def generate_general_answer(
        self, topic: GeneralTopic, original_question: str
    ) -> ProviderResult[str]:
        instruction = gemini_prompts.build_general_answer_instruction(topic)
        result = await self._call_structured(instruction, original_question, _GeneralAnswer)
        return provider_result(result.answer, source=ProviderSource.GEMINI)

    async def _call_structured(
        self,
        system_instruction: str,
        user_input: str,
        response_model: type[T],
    ) -> T:
        try:
            return await self._generate(system_instruction, user_input, response_model)
        except ValidationError as exc:
            retry_instruction = system_instruction + gemini_prompts.format_validation_retry_note(
                exc
            )
            try:
                return await self._generate(retry_instruction, user_input, response_model)
            except ValidationError as retry_exc:
                raise AppError(
                    code="llm_output_invalid",
                    message="LLM 응답을 해석하지 못했습니다.",
                    status_code=502,
                    retryable=True,
                    provider="Gemini",
                    details={"validation_error": str(retry_exc)},
                ) from None

    async def _generate(
        self,
        system_instruction: str,
        user_input: str,
        response_model: type[T],
    ) -> T:
        """타임아웃/429/5xx는 지수 백오프로 최대 self._max_retries회 재시도한다."""

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._model_name,
                    contents=user_input,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_schema=response_model,
                        temperature=0.0,
                    ),
                )
            except httpx.TimeoutException:
                if attempt >= self._max_retries:
                    raise ProviderTimeoutError("Gemini") from None
            except genai_errors.APIError as exc:
                if exc.code not in _RETRYABLE_STATUS_CODES or attempt >= self._max_retries:
                    status = f" {exc.status}" if hasattr(exc, "status") else ""
                    retry_note = (
                        f" (재시도 {attempt}회 소진)" if attempt > 0 else " (첫 시도부터 실패)"
                    )
                    detail = f"{exc.code}{status}{retry_note}"
                    raise ProviderUnavailableError("Gemini", detail=detail) from None
            else:
                if response.parsed is not None:
                    return response_model.model_validate(response.parsed)
                # response_schema가 SDK 자동 파싱을 못 한 경우(빈 응답 등)
                # 원문 텍스트로 직접 검증한다.
                return response_model.model_validate_json(response.text or "")

            await asyncio.sleep(_backoff_seconds(attempt))

        raise AssertionError("unreachable: retry loop exited without returning or raising")


__all__ = ["RealGeminiProvider"]
