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
import json
import logging
import random
import time
from datetime import date
from typing import TypeVar

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel, Field, ValidationError

from app.errors import AppError, ProviderTimeoutError, ProviderUnavailableError
from app.observability.api_usage import record_call
from app.providers import gemini_prompts
from app.providers.contracts import ProviderResult, ProviderSource, provider_result
from app.schedule.schemas import (
    ScheduleLLMPlan,
    SchedulePartialFillRequest,
    SchedulePartialLLMPlan,
    SchedulePlanningRequest,
)
from app.schemas import (
    ComparisonResult,
    GeneralTopic,
    Intent,
    IntentClassificationResult,
    LLMOutput,
    RecommendationItem,
    RecommendationResponse,
    UserConditions,
)
from app.services.runtime.llm_execution import record_llm_call

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)


class _GeneralAnswer(BaseModel):
    """generate_general_answer() 전용 구조화 출력 wire 모델. 다른 곳에서 쓰지 않는다."""

    answer: str


class _RecommendationSummary(BaseModel):
    """generate_recommendation_summary() 전용 wire 모델."""

    message: str


class _ComparisonSummary(BaseModel):
    """generate_compare_summary() 전용 wire 모델.

    줄 수를 구조화 출력 단계에서 제한해, 프롬프트 지시만으로는 보장되지 않는
    3~6줄 요구사항을 실제 응답 계약으로 강제한다.
    """

    lines: list[str] = Field(min_length=3, max_length=6)


# 429(rate limit)와 5xx(서버 과부하/일시 장애)만 재시도 대상. 4xx(인증 실패, 잘못된 요청 등)는
# 재시도해도 같은 결과이므로 즉시 실패시킨다.
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_BACKOFF_BASE_SECONDS = 0.5


def _backoff_seconds(attempt: int) -> float:
    """지수 백오프 + 지터. attempt=0이 첫 번째 재시도 전 대기시간."""
    return _BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0, 0.25)


def _record_gemini_call(
    model_name: str, started: float, *, ok: bool, status: str
) -> None:
    """Gemini 호출 한 번을 관측 집계에 남긴다(추천 판정과 무관)."""
    record_call(
        "gemini",
        model_name,
        ok=ok,
        latency_ms=(time.perf_counter() - started) * 1000,
        status=status,
    )


class _RetryableExhaustedError(Exception):
    """한 모델의 재시도 예산이 소진됐다는 내부 신호(폴백 대상) — 사용자에게 그대로
    노출되지 않는다. _generate()가 이 예외를 잡아 다음 모델로 넘어가거나, 마지막
    모델이면 감싸고 있는 원본 오류를 그대로 raise한다. 4xx 같은 비재시도 오류는 이
    래퍼 없이 ProviderUnavailableError를 바로 던져 폴백 없이 즉시 실패한다."""

    def __init__(self, original: ProviderTimeoutError | ProviderUnavailableError) -> None:
        self.original = original


class RealGeminiProvider:
    """google-genai SDK로 Gemini 구조화 출력을 호출하는 실제 구현.

    다른 Real provider와 달리 공유 httpx.AsyncClient를 받지 않는다 — google-genai가
    자체 비동기 클라이언트를 관리하기 때문(SDK 사용 요구사항에 따른 의도적인 구조 차이).
    """

    def __init__(
        self,
        api_key: str,
        model_names: list[str],
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
    ) -> None:
        if not model_names:
            raise ValueError("model_names는 최소 1개 이상이어야 합니다.")
        self._client = genai.Client(
            api_key=api_key,
            http_options=genai_types.HttpOptions(timeout=int(timeout_seconds * 1000)),
        )
        self._model_names = model_names
        self._max_retries = max_retries

    async def classify_intent(
        self,
        user_input: str,
        *,
        has_previous_recommendation: bool,
        shown_place_count: int,
        pending_clarification: str | None = None,
        last_intent: str | None = None,
        shown_place_names: list[str] | None = None,
    ) -> ProviderResult[IntentClassificationResult]:
        instruction = gemini_prompts.build_intent_classification_instruction(
            has_previous_recommendation=has_previous_recommendation,
            shown_place_count=shown_place_count,
            pending_clarification=pending_clarification,
            last_intent=last_intent,
            shown_place_names=shown_place_names,
        )
        result = await self._call_structured(
            instruction,
            user_input,
            IntentClassificationResult,
            operation="classify_intent",
        )
        return provider_result(result, source=ProviderSource.GEMINI)

    async def extract_recommend_conditions(
        self, user_input: str
    ) -> ProviderResult[LLMOutput]:
        instruction = gemini_prompts.build_recommend_extraction_instruction()
        result = await self._call_structured(
            instruction,
            user_input,
            LLMOutput,
            operation="extract_recommend_conditions",
        )
        return provider_result(result, source=ProviderSource.GEMINI)

    async def extract_modify_conditions(
        self,
        user_input: str,
        current_conditions: UserConditions,
        *,
        pending_clarification: str | None = None,
        shown_place_count: int = 0,
        shown_place_names: list[str] | None = None,
    ) -> ProviderResult[LLMOutput]:
        instruction = gemini_prompts.build_modify_extraction_instruction(
            current_conditions,
            pending_clarification=pending_clarification,
            shown_place_count=shown_place_count,
            shown_place_names=shown_place_names,
        )
        result = await self._call_structured(
            instruction,
            user_input,
            LLMOutput,
            operation="extract_modify_conditions",
        )
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
        result = await self._call_structured(
            instruction,
            user_input,
            LLMOutput,
            operation="extract_info_query",
        )
        return provider_result(result, source=ProviderSource.GEMINI)

    async def extract_compare_request(
        self, user_input: str, *, shown_place_count: int
    ) -> ProviderResult[LLMOutput]:
        instruction = gemini_prompts.build_compare_extraction_instruction(
            shown_place_count=shown_place_count
        )
        result = await self._call_structured(
            instruction,
            user_input,
            LLMOutput,
            operation="extract_compare_request",
        )
        return provider_result(result, source=ProviderSource.GEMINI)

    async def extract_general_request(
        self, user_input: str
    ) -> ProviderResult[LLMOutput]:
        instruction = gemini_prompts.build_general_extraction_instruction()
        result = await self._call_structured(
            instruction,
            user_input,
            LLMOutput,
            operation="extract_general_request",
        )
        return provider_result(result, source=ProviderSource.GEMINI)

    async def generate_general_answer(
        self, topic: GeneralTopic, original_question: str
    ) -> ProviderResult[str]:
        instruction = gemini_prompts.build_general_answer_instruction(topic)
        result = await self._call_structured(
            instruction,
            original_question,
            _GeneralAnswer,
            operation="generate_general_answer",
        )
        return provider_result(result.answer, source=ProviderSource.GEMINI)

    async def generate_recommendation_summary(
        self, intent: Intent, recommendations: RecommendationResponse
    ) -> ProviderResult[str]:
        instruction = gemini_prompts.build_recommendation_summary_instruction(intent)
        payload = {
            "recommendations": [
                self._recommendation_summary_item(item)
                for item in [
                    *recommendations.recommendations,
                    *recommendations.unverified_recommendations,
                ]
            ]
        }
        result = await self._call_structured(
            instruction,
            json.dumps(payload, ensure_ascii=False),
            _RecommendationSummary,
            operation="generate_recommendation_summary",
        )
        return provider_result(result.message, source=ProviderSource.GEMINI)

    async def generate_compare_summary(
        self, comparison: ComparisonResult
    ) -> ProviderResult[str]:
        """C가 반환한 공개 비교 사실만 Gemini에 전달해 설명 문장을 생성한다."""

        instruction = gemini_prompts.build_compare_summary_instruction(comparison.criteria)
        result = await self._call_structured(
            instruction,
            comparison.model_dump_json(exclude_none=True),
            _ComparisonSummary,
            operation="generate_compare_summary",
        )
        return provider_result("\n".join(result.lines), source=ProviderSource.GEMINI)

    @staticmethod
    def _recommendation_summary_item(item: RecommendationItem) -> dict[str, object]:
        """추천 요약 LLM에 넘겨도 되는 사용자-facing 필드만 남긴다."""

        return {
            "name": item.name,
            "category": item.category,
            "distance_km": item.distance_km,
            "remaining_minutes": item.remaining_minutes,
            "recommendation_reason": item.recommendation_reason,
            "explanations": item.explanations,
        }

    async def generate_schedule_plan(
        self, request: SchedulePlanningRequest
    ) -> ProviderResult[ScheduleLLMPlan]:
        # visit_datetime은 app.schedule.planner가 fallback(현재 시각)까지 반영해서
        # 넘겨준다 — 여기서는 이미 값이 있다고 가정하고 표시 형식만 맞춘다.
        assert request.visit_datetime is not None
        start_time = request.visit_datetime.strftime("%H:%M")
        instruction = gemini_prompts.build_schedule_planning_instruction()
        context = gemini_prompts.format_schedule_planning_context(request, start_time)
        result = await self._call_structured(
            instruction,
            context,
            ScheduleLLMPlan,
            operation="generate_schedule_plan",
        )
        return provider_result(result, source=ProviderSource.GEMINI)

    async def generate_schedule_fill(
        self, request: SchedulePartialFillRequest
    ) -> ProviderResult[SchedulePartialLLMPlan]:
        assert request.visit_datetime is not None
        start_time = request.visit_datetime.strftime("%H:%M")
        instruction = gemini_prompts.build_schedule_fill_instruction()
        context = gemini_prompts.format_schedule_fill_context(request, start_time)
        result = await self._call_structured(
            instruction,
            context,
            SchedulePartialLLMPlan,
            operation="generate_schedule_fill",
        )
        return provider_result(result, source=ProviderSource.GEMINI)

    async def _call_structured(
        self,
        system_instruction: str,
        user_input: str,
        response_model: type[T],
        *,
        operation: str,
    ) -> T:
        try:
            return await self._generate(system_instruction, user_input, response_model, operation)
        except ValidationError as exc:
            retry_instruction = system_instruction + gemini_prompts.format_validation_retry_note(
                exc
            )
            try:
                return await self._generate(
                    retry_instruction, user_input, response_model, operation
                )
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
        operation: str,
    ) -> T:
        """1순위 모델부터 순서대로 시도한다(D-052). 각 모델에서 타임아웃/429/5xx는
        _try_model()이 지수 백오프로 재시도하고, 그 예산이 소진되면 다음 모델로
        넘어간다. 마지막 모델까지 소진되면 오늘과 동일하게 ProviderTimeoutError/
        ProviderUnavailableError를 던진다. 4xx 등 비재시도 오류는 모델을 바꿔도
        결과가 같으므로 _try_model()에서 폴백 없이 즉시 실패한다(아래로 그대로
        전파됨 — 이 메서드는 잡지 않는다).
        """

        last_error: ProviderTimeoutError | ProviderUnavailableError | None = None

        attempted_models: list[str] = []
        for model_index, model_name in enumerate(self._model_names):
            attempted_models.append(model_name)
            try:
                result = await self._try_model(
                    model_name, system_instruction, user_input, response_model
                )
            except _RetryableExhaustedError as exc:
                last_error = exc.original
                is_last_model = model_index == len(self._model_names) - 1
                if is_last_model:
                    record_llm_call(
                        operation=operation,
                        attempted_models=attempted_models,
                        served_model=None,
                    )
                    logger.error(
                        "Gemini 전 모델 소진, 최종 실패 (models=%s): %s",
                        self._model_names,
                        last_error,
                    )
                    raise last_error from None
                logger.warning(
                    "Gemini 모델 %s 재시도 소진, %s로 폴백: %s",
                    model_name,
                    self._model_names[model_index + 1],
                    last_error,
                )
                continue
            except ProviderUnavailableError:
                # 4xx 등 비재시도 오류는 모델을 바꿔도 해결되지 않아 즉시 끝난다.
                record_llm_call(
                    operation=operation,
                    attempted_models=attempted_models,
                    served_model=None,
                )
                raise
            except ValidationError:
                # Gemini는 응답했지만 구조화 스키마 검증에 실패한 경우다. 뒤의
                # _call_structured() 보정 재시도와 구분할 수 있게 모델을 남긴다.
                record_llm_call(
                    operation=operation,
                    attempted_models=attempted_models,
                    served_model=model_name,
                )
                raise

            record_llm_call(
                operation=operation,
                attempted_models=attempted_models,
                served_model=model_name,
            )
            if model_index > 0:
                logger.warning(
                    "Gemini 폴백 모델로 응답 성공 (served_by=%s, primary=%s)",
                    model_name,
                    self._model_names[0],
                )
            return result

        raise AssertionError("unreachable: model loop exited without returning or raising")

    async def _try_model(
        self,
        model_name: str,
        system_instruction: str,
        user_input: str,
        response_model: type[T],
    ) -> T:
        """모델 하나에 대해서만 타임아웃/429/5xx를 지수 백오프로 최대
        self._max_retries회 재시도한다. 재시도가 소진되면 _RetryableExhaustedError로
        감싸 던져 호출부(_generate)가 다음 모델로 넘어갈지 판단하게 한다. 4xx 등
        비재시도 오류는 감싸지 않고 ProviderUnavailableError를 바로 던진다 —
        모델을 바꿔도 같은 이유로 실패할 것이므로 폴백 대상이 아니다.
        """

        for attempt in range(self._max_retries + 1):
            # google-genai는 자체 전송 계층을 써서 MeteredTransport를 거치지 않는다.
            # 재시도 한 번도 별개의 과금·쿼터 소모라 시도 단위로 센다.
            started = time.perf_counter()
            try:
                response = await self._client.aio.models.generate_content(
                    model=model_name,
                    contents=user_input,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_schema=response_model,
                        temperature=0.0,
                    ),
                )
            except httpx.TimeoutException:
                _record_gemini_call(model_name, started, ok=False, status="timeout")
                if attempt >= self._max_retries:
                    raise _RetryableExhaustedError(ProviderTimeoutError("Gemini")) from None
            except genai_errors.APIError as exc:
                _record_gemini_call(model_name, started, ok=False, status=str(exc.code))
                if exc.code not in _RETRYABLE_STATUS_CODES:
                    status = f" {exc.status}" if hasattr(exc, "status") else ""
                    detail = f"{exc.code}{status} (첫 시도부터 실패)"
                    raise ProviderUnavailableError("Gemini", detail=detail) from None
                if attempt >= self._max_retries:
                    status = f" {exc.status}" if hasattr(exc, "status") else ""
                    detail = f"{exc.code}{status} (재시도 {attempt}회 소진)"
                    raise _RetryableExhaustedError(
                        ProviderUnavailableError("Gemini", detail=detail)
                    ) from None
            else:
                _record_gemini_call(model_name, started, ok=True, status="ok")
                if response.parsed is not None:
                    return response_model.model_validate(response.parsed)
                # response_schema가 SDK 자동 파싱을 못 한 경우(빈 응답 등)
                # 원문 텍스트로 직접 검증한다.
                return response_model.model_validate_json(response.text or "")

            await asyncio.sleep(_backoff_seconds(attempt))

        raise AssertionError("unreachable: retry loop exited without returning or raising")


__all__ = ["RealGeminiProvider"]
