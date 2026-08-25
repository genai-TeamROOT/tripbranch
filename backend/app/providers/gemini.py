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
from collections.abc import AsyncIterator
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

# 폴백 모델 보정 — gemini-2.5-flash-lite는 thinking이 기본 꺼져 있어 0을 걸어도 동작이
# 같고(미설정과 budget=0의 68건 예측이 한 건도 다르지 않다), 512를 줘야 대화 이력에
# 의존하는 판정(MODIFY/COMPARE/되묻기)이 산다 — 채점 대상 64건에서 56→59, 대조쌍
# 12건에서 9→12. 즉 예산의 최적값은 모델마다 반대다.
#
# 측정한 범위가 classify_intent뿐이라 그 호출에만 건다. 조건 추출·일정 편성은 폴백
# 모델로 재본 적이 없어 호출부가 정한 값을 그대로 둔다.
# 근거: backend/test_results/intent_experiments_2026-08.md §4
_MODEL_BUDGET_OVERRIDES: dict[tuple[str, str], int] = {
    ("gemini-2.5-flash-lite", "classify_intent"): 512,
}

# `thinking_budget`에 **숫자 0**을 실으면 400 INVALID_ARGUMENT를 돌려주는 모델.
# 400은 비재시도 오류라 폴백도 못 타고 즉시 실패한다(_try_model 참고) — 0이 숫자로
# 실리는 순간 그 호출은 죽는다. 세대별이 아니라 모델별이다.
# 근거: backend/test_results/intent_experiments_2026-08.md §5 (2026-08-14, eae832f)
#
# 실 API 재확인(2026-08-24) — 거부되는 것은 "0"뿐이다:
#   thinking_budget=0        → 400 INVALID_ARGUMENT
#   thinking_budget=512      → 성공   (숫자 자체가 문제인 것이 아니다)
#   thinking_level=MINIMAL   → 성공   (지금 우리가 실제로 보내는 값)
#
# **그래서 이 목록은 더 이상 "thinking을 끄지 않는" 근거가 아니다.** 예전에는 이
# 목록에 걸리면 thinking_config를 아예 싣지 않았는데, 그러면 400은 피하지만 "thinking
# 끄기"도 함께 사라진다. fast 모델이 gemini-3.5-flash-lite가 된 뒤(2026-08-18)
# `classify_intent`·`extract_recommend_conditions`에서 실제로 그 일이 일어났고,
# 코드가 바뀐 게 아니라 모델만 바뀐 것이라 아무도 알아채지 못했다.
#
# 지금은 `_thinking_config_for()`가 0을 숫자가 아니라 `thinking_level=MINIMAL`로
# 바꿔 보내므로 400이 날 입력을 애초에 만들지 않는다. 목록은 **실측으로 얻은 사실**
# 이라 지우지 않고, 그 사실을 지키는 불변식
# (`test_zero_budget_is_never_sent_as_a_number`)이 이 상수를 직접 읽어 검증한다 —
# 모델이 늘어나면 목록에만 추가하면 테스트가 따라온다.
#
# 참고로 이 변경의 목적은 속도가 아니다. gemini-3.5-flash-lite는 thinking 기본값이
# 이미 가벼워서 MINIMAL을 걸어도 지연이 같다(classify_intent 15회 중앙값
# 958ms → 949ms, -0.9%). 목적은 "기본 thinking이 무거운 모델로 바꾸는 순간 최적화가
# 조용히 사라지는" 구조를 없애는 것이다. 상세는 D-076와
# scripts/measure_fast_thinking_level.py.
_REJECTS_ZERO_THINKING_BUDGET = frozenset(
    {
        "gemini-3.5-flash-lite",
        "gemini-3.6-flash",
    }
)


def _resolve_thinking_budget(model_name: str, operation: str, requested: int | None) -> int | None:
    """호출부가 요청한 thinking 예산을 모델 특성에 맞춰 보정한다.

    None을 돌려주면 thinking_config를 아예 싣지 않아 모델 기본 동작이 된다.
    실측으로 확인한 조합만 보정하고, 모르는 모델에는 요청값을 그대로 통과시킨다.
    """
    override = _MODEL_BUDGET_OVERRIDES.get((model_name, operation))
    if override is not None:
        return override
    return requested


def _thinking_config_for(thinking_budget: int | None) -> genai_types.ThinkingConfig | None:
    """thinking_budget 인자를 실제 SDK에 넘길 ThinkingConfig로 변환한다.

    (2026-08-18 추가) Gemini 3.x부터 숫자 기반 thinking_budget은 레거시
    취급이고, Google은 thinking_level(MINIMAL/LOW/MEDIUM/HIGH) 사용을
    권장한다 — 같은 요청에 thinking_budget과 thinking_level을 함께 넘기면
    400 오류가 나므로 항상 하나만 채운다. 이 코드베이스는 지금까지
    thinking_budget에 0 또는 None만 넘겨왔다(그 외 값은 쓰인 적 없음) —
    0("완전히 끔")은 가장 가까운 대응인 MINIMAL로 변환하고, None은 지금과
    동일하게 아무것도 안 넣어 모델 자체 기본값을 그대로 둔다.

    모델을 gemini-2.5-flash → gemini-3.5-flash로 바꾼 뒤 응답이 전반적으로
    느려진 문제의 일부가 이 부분이다 — 예전엔 thinking_budget=0이 SCHEDULE
    2곳과 classify_intent/extract_recommend_conditions에서 thinking을
    확실히 껐지만, 레거시 파라미터가 새 모델에서도 여전히 그대로 작동한다는
    보장이 없어 이 네 곳부터 명시적으로 고쳤다.

    (2026-08-20 해소) 문장 생성·요약류(답변·요약 5곳 — generate_general_answer/
    stream_general_answer/generate_recommendation_summary/
    stream_recommendation_summary/stream_info_answer/generate_compare_summary)는
    gemini-2.5-flash 기준 "모델 기본값이 가볍다"는 가정으로 의도적으로 손대지
    않았던 곳들인데, gemini-3.5-flash의 기본값은 MEDIUM(항상 켜짐)이라 그 가정이
    깨져 GENERAL 인사말 응답에도 6~7초 TTFT가 걸리는 게 실사용에서 확인됐다.
    scripts/compare_answer_thinking_budget.py로 5개 케이스 × 3회 실측한 결과
    thinking_budget=0이 평균 3.9배 빠르면서(예: 5.9초→1.3초) 답변 문구는 페르소나·
    자기소개("트리비")·문장 수 규칙을 그대로 지켰다(수동 확인, "문장 생성·요약류는
    품질 저하 리스크"라는 우려가 이 케이스들에서는 근거로 뒷받침되지 않음). 결과:
    test_results/answer_thinking_budget_latency.csv. 이 5곳도 이제 thinking_budget=0을
    쓴다 — 남은 호출부는 없다.
    """
    if thinking_budget is None:
        return None
    if thinking_budget <= 0:
        # 여기가 400을 막는 지점이다. 숫자 0을 그대로 실으면
        # _REJECTS_ZERO_THINKING_BUDGET의 모델들이 400으로 즉시 죽는다 — 0은 항상
        # thinking_level로 바꿔 내보내고, 숫자로는 절대 흘리지 않는다.
        return genai_types.ThinkingConfig(thinking_level=genai_types.ThinkingLevel.MINIMAL)
    # 0/None 외의 값은 지금까지 쓰인 적이 없다 — 필요해지면 그때 thinking_level
    # 값으로 다시 매핑 기준을 정한다. 양수는 위 목록의 모델에서도 정상 동작한다
    # (2026-08-24 실측: thinking_budget=512는 두 모델 모두 성공).
    return genai_types.ThinkingConfig(thinking_budget=thinking_budget)


def _backoff_seconds(attempt: int) -> float:
    """지수 백오프 + 지터. attempt=0이 첫 번째 재시도 전 대기시간."""
    return _BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0, 0.25)


def _record_gemini_call(model_name: str, started: float, *, ok: bool, status: str) -> None:
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
        model_names: list[str] | None = None,
        *,
        fast_model_names: list[str] | None = None,
        generation_model_names: list[str] | None = None,
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
    ) -> None:
        """역할별 모델 묶음을 설정한다.

        ``model_names``는 D-052 이전 단일 모델 생성자 호출과 테스트를 위한 호환
        인자다. 실제 앱 팩토리는 ``fast_model_names``와
        ``generation_model_names``를 각각 넘긴다.
        """
        legacy_models = model_names or []
        self._fast_model_names = fast_model_names or legacy_models
        self._generation_model_names = generation_model_names or legacy_models
        if not self._fast_model_names or not self._generation_model_names:
            raise ValueError("빠른 판단·응답 생성 모델은 각각 최소 1개 이상이어야 합니다.")
        self._client = genai.Client(
            api_key=api_key,
            http_options=genai_types.HttpOptions(timeout=int(timeout_seconds * 1000)),
        )
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
        conversation_place_name: str | None = None,
    ) -> ProviderResult[IntentClassificationResult]:
        instruction = gemini_prompts.build_intent_classification_instruction(
            has_previous_recommendation=has_previous_recommendation,
            shown_place_count=shown_place_count,
            pending_clarification=pending_clarification,
            last_intent=last_intent,
            shown_place_names=shown_place_names,
            conversation_place_name=conversation_place_name,
        )
        # thinking_budget=0 — SCHEDULE(generate_schedule_plan/fill)에 적용한 것과 같은
        # 이유. classify_intent는 정해진 스키마 중 하나를 고르는 얕은 판단이라 thinking
        # 없이도 규칙 기반 판별이 가능하다고 보고 실측(2026-08-13, 10개 대표 질문×2회,
        # scripts/compare_classify_extract_thinking_budget.py)으로 확인했다 — 평균
        # 3609ms→1561ms(2.3배), 정확도는 90%(18/20)로 thinking_on과 동일하게 유지됨
        # (유일한 오답 케이스도 thinking_on/off 양쪽에서 똑같이 틀려 이 변경과 무관한
        # 기존 프롬프트 이슈로 확인). 결과: test_results/classify_extract_thinking_budget.csv.
        result = await self._call_structured(
            instruction,
            user_input,
            IntentClassificationResult,
            operation="classify_intent",
            thinking_budget=0,
            model_names=self._fast_model_names,
        )
        return provider_result(result, source=ProviderSource.GEMINI)

    async def extract_recommend_conditions(self, user_input: str) -> ProviderResult[LLMOutput]:
        instruction = gemini_prompts.build_recommend_extraction_instruction()
        # thinking_budget=0 — classify_intent()와 같은 이유로 실측 확인
        # (평균 3122ms→1745ms, 1.8배, search_center 추출 정확도 4/4로 동일 유지).
        result = await self._call_structured(
            instruction,
            user_input,
            LLMOutput,
            operation="extract_recommend_conditions",
            thinking_budget=0,
            model_names=self._fast_model_names,
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
            model_names=self._fast_model_names,
        )
        return provider_result(result, source=ProviderSource.GEMINI)

    async def extract_info_query(
        self,
        user_input: str,
        *,
        has_previous_recommendation: bool,
        reference_date: date,
        conversation_place_name: str | None = None,
    ) -> ProviderResult[LLMOutput]:
        instruction = gemini_prompts.build_info_extraction_instruction(
            has_previous_recommendation=has_previous_recommendation,
            reference_date=reference_date,
            conversation_place_name=conversation_place_name,
        )
        result = await self._call_structured(
            instruction,
            user_input,
            LLMOutput,
            operation="extract_info_query",
            model_names=self._fast_model_names,
        )
        return provider_result(result, source=ProviderSource.GEMINI)

    async def extract_compare_request(
        self,
        user_input: str,
        *,
        shown_place_count: int,
        shown_place_names: list[str] | None = None,
    ) -> ProviderResult[LLMOutput]:
        instruction = gemini_prompts.build_compare_extraction_instruction(
            shown_place_count=shown_place_count,
            shown_place_names=shown_place_names,
        )
        result = await self._call_structured(
            instruction,
            user_input,
            LLMOutput,
            operation="extract_compare_request",
            model_names=self._fast_model_names,
        )
        return provider_result(result, source=ProviderSource.GEMINI)

    async def extract_general_request(self, user_input: str) -> ProviderResult[LLMOutput]:
        instruction = gemini_prompts.build_general_extraction_instruction()
        result = await self._call_structured(
            instruction,
            user_input,
            LLMOutput,
            operation="extract_general_request",
            model_names=self._fast_model_names,
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
            model_names=self._generation_model_names,
            # thinking_budget=0 — 답변·요약 계열 5곳에 공통 적용(2026-08-20 실측).
            # gemini-2.5-flash → gemini-3.5-flash 전환 후 기본 thinking이 MEDIUM(항상
            # 켜짐)으로 바뀌어 간단한 인사말에도 6~7초가 걸렸다(실사용 확인). 이 5곳만
            # thinking_budget을 안 넣은 채 남아 있었다(_thinking_config_for() docstring
            # 참고 — 그때는 "품질 저하 리스크"로 의도적으로 제외했던 곳들).
            # scripts/compare_answer_thinking_budget.py로 5개 케이스 × 3회 실측한 결과
            # 평균 3.9배 빨라졌고(예: general_identity 5.9초→1.3초), 답변 문구는
            # 페르소나·자기소개("트리비")·문장 수 규칙을 그대로 지켰다(수동 확인,
            # 결과: test_results/answer_thinking_budget_latency.csv).
            thinking_budget=0,
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
            model_names=self._generation_model_names,
            # thinking_budget=0 — generate_general_answer()와 같은 이유로 실측 확인.
            thinking_budget=0,
        )
        return provider_result(result.message, source=ProviderSource.GEMINI)

    async def stream_recommendation_summary(
        self, intent: Intent, recommendations: RecommendationResponse
    ) -> AsyncIterator[str]:
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
        async for text in self._stream_text(
            instruction=instruction,
            user_input=json.dumps(payload, ensure_ascii=False),
            operation="stream_recommendation_summary",
            model_names=self._generation_model_names,
            # thinking_budget=0 — generate_general_answer()와 같은 이유로 실측 확인.
            thinking_budget=0,
        ):
            yield text

    async def stream_general_answer(
        self, topic: GeneralTopic, original_question: str
    ) -> AsyncIterator[str]:
        """GENERAL 자유 답변을 Gemini 스트림으로 전달한다."""

        async for text in self._stream_text(
            instruction=gemini_prompts.build_general_answer_instruction(topic),
            user_input=original_question,
            operation="stream_general_answer",
            model_names=self._generation_model_names,
            # thinking_budget=0 — generate_general_answer()와 같은 이유로 실측 확인.
            thinking_budget=0,
        ):
            yield text

    async def stream_info_answer(
        self,
        *,
        place_name: str,
        question_type: str,
        specific_question: str | None,
        fields: dict[str, str],
    ) -> AsyncIterator[str]:
        """C가 검증한 장소 INFO 필드만 근거로 답변을 스트리밍한다."""

        payload = {
            "place_name": place_name,
            "specific_question": specific_question,
            "fields": fields,
        }
        async for text in self._stream_text(
            instruction=gemini_prompts.build_info_answer_instruction(question_type),
            user_input=json.dumps(payload, ensure_ascii=False),
            operation="stream_info_answer",
            model_names=self._generation_model_names,
            # thinking_budget=0 — generate_general_answer()와 같은 이유로 실측 확인.
            thinking_budget=0,
        ):
            yield text

    async def _stream_text(
        self,
        *,
        instruction: str,
        user_input: str,
        operation: str,
        model_names: list[str] | None = None,
        thinking_budget: int | None = None,
    ) -> AsyncIterator[str]:
        """일반 텍스트 Gemini 스트림의 모델 폴백·관측을 공통 처리한다.

        첫 조각을 보낸 뒤 다른 모델로 옮기면 문장이 중복될 수 있다. 따라서 그 이후
        오류는 호출자에게 전파해 이미 전달된 텍스트를 보존한다.

        thinking_budget은 _call_structured()와 같은 규칙으로 모델별 보정을 거친다
        (_resolve_thinking_budget()/_thinking_config_for() 참고).
        """

        selected_models = model_names or self._generation_model_names
        attempted_models: list[str] = []
        last_error: ProviderTimeoutError | ProviderUnavailableError | None = None

        for model_name in selected_models:
            attempted_models.append(model_name)
            started = time.perf_counter()
            emitted = False
            resolved_budget = _resolve_thinking_budget(model_name, operation, thinking_budget)
            try:
                stream = await self._client.aio.models.generate_content_stream(
                    model=model_name,
                    contents=user_input,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=instruction,
                        temperature=0.0,
                        thinking_config=_thinking_config_for(resolved_budget),
                    ),
                )
                async for chunk in stream:
                    text = getattr(chunk, "text", None)
                    if not text:
                        continue
                    emitted = True
                    yield text
            except httpx.TimeoutException:
                _record_gemini_call(model_name, started, ok=False, status="timeout")
                last_error = ProviderTimeoutError("Gemini")
            except genai_errors.APIError as exc:
                status_code = getattr(exc, "code", None)
                _record_gemini_call(
                    model_name,
                    started,
                    ok=False,
                    status=str(status_code or "api_error"),
                )
                if status_code not in _RETRYABLE_STATUS_CODES:
                    record_llm_call(
                        operation=operation,
                        attempted_models=attempted_models,
                        served_model=None,
                        # 스트리밍은 모델별 재시도 루프가 없다 — 실패하면 그대로
                        # 다음 모델로 넘어가므로 항상 0이다.
                        retry_count=0,
                    )
                    raise ProviderUnavailableError("Gemini", detail=str(exc)) from None
                last_error = ProviderUnavailableError("Gemini", detail=str(exc))
            else:
                _record_gemini_call(model_name, started, ok=True, status="success")
                record_llm_call(
                    operation=operation,
                    attempted_models=attempted_models,
                    served_model=model_name,
                    retry_count=0,
                )
                return

            if emitted:
                record_llm_call(
                    operation=operation,
                    attempted_models=attempted_models,
                    served_model=model_name,
                    retry_count=0,
                )
                raise last_error

            logger.warning(
                "Gemini 스트림 시작 실패, 다음 모델로 폴백: operation=%s model=%s",
                operation,
                model_name,
            )

        record_llm_call(
            operation=operation,
            attempted_models=attempted_models,
            served_model=None,
            retry_count=0,
        )
        assert last_error is not None
        raise last_error

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
            model_names=self._generation_model_names,
            # thinking_budget=0 — generate_general_answer()와 같은 이유로 실측 확인.
            thinking_budget=0,
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
        instruction = gemini_prompts.build_schedule_planning_instruction(
            time_available_min=request.conditions.time_available
        )
        context = gemini_prompts.format_schedule_planning_context(request, start_time)
        # thinking_budget=0 — 일정 편성은 구조화 출력이 무거워(3~5개 항목×6개 필드)
        # thinking이 지연시간의 상당 부분을 차지하는 것으로 보여 꺼서 응답 속도를
        # 줄인다(실사용 지연시간 개선 검토, 2026-08-13). 라우트 선택 근거는
        # pairwise_distances_km·조건을 프롬프트에 이미 명시적으로 주고 있어
        # thinking 없이도 규칙 기반 선택이 가능하다고 판단 — 다만 품질 저하가
        # 관측되면 0보다 큰 낮은 예산으로 조정할 수 있다(_call_structured 참고).
        result = await self._call_structured(
            instruction,
            context,
            ScheduleLLMPlan,
            operation="generate_schedule_plan",
            thinking_budget=0,
            model_names=self._generation_model_names,
        )
        return provider_result(result, source=ProviderSource.GEMINI)

    async def generate_schedule_fill(
        self, request: SchedulePartialFillRequest
    ) -> ProviderResult[SchedulePartialLLMPlan]:
        assert request.visit_datetime is not None
        start_time = request.visit_datetime.strftime("%H:%M")
        instruction = gemini_prompts.build_schedule_fill_instruction()
        context = gemini_prompts.format_schedule_fill_context(request, start_time)
        # thinking_budget=0 — generate_schedule_plan()과 같은 이유.
        result = await self._call_structured(
            instruction,
            context,
            SchedulePartialLLMPlan,
            operation="generate_schedule_fill",
            thinking_budget=0,
            model_names=self._generation_model_names,
        )
        return provider_result(result, source=ProviderSource.GEMINI)

    async def _call_structured(
        self,
        system_instruction: str,
        user_input: str,
        response_model: type[T],
        *,
        operation: str,
        thinking_budget: int | None = None,
        model_names: list[str] | None = None,
    ) -> T:
        """호출별 thinking 예산과 모델 목록을 함께 전달한다.

        기본값 None이면 해당 모델의 기본 동작을 유지한다. thinking_budget=0은
        "완전히 끔"이 목적이지만, 실제로 어떤 값이 API에 실리는지는
        _try_model()의 _resolve_thinking_budget()/_thinking_config_for() 조합이
        모델·호출 종류별로 결정한다 — 일부 모델(Flash-Lite 등)은 thinking_budget=0
        자체를 거부해 thinking_config를 생략하고, 나머지는 Gemini 3.x 권장 방식인
        thinking_level=MINIMAL로 변환된다(2026-08-18,
        _thinking_config_for() docstring 참고). model_names를 넘기면 이번 호출에서만
        그 모델 목록을 쓴다(폴백 순서 포함) — 넘기지 않으면 생성자가 정한 기본
        목록(D-052 fast/generation 구분)을 쓴다.
        """
        generate_kwargs = {"model_names": model_names} if model_names is not None else {}
        try:
            return await self._generate(
                system_instruction,
                user_input,
                response_model,
                operation,
                thinking_budget=thinking_budget,
                **generate_kwargs,
            )
        except ValidationError as exc:
            retry_instruction = system_instruction + gemini_prompts.format_validation_retry_note(
                exc
            )
            try:
                return await self._generate(
                    retry_instruction,
                    user_input,
                    response_model,
                    operation,
                    thinking_budget=thinking_budget,
                    **generate_kwargs,
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
        *,
        thinking_budget: int | None = None,
        model_names: list[str] | None = None,
    ) -> T:
        """1순위 모델부터 순서대로 시도한다(D-052). 각 모델에서 타임아웃/429/5xx는
        _try_model()이 지수 백오프로 재시도하고, 그 예산이 소진되면 다음 모델로
        넘어간다. 마지막 모델까지 소진되면 오늘과 동일하게 ProviderTimeoutError/
        ProviderUnavailableError를 던진다. 4xx 등 비재시도 오류는 모델을 바꿔도
        결과가 같으므로 _try_model()에서 폴백 없이 즉시 실패한다(아래로 그대로
        전파됨 — 이 메서드는 잡지 않는다).
        """

        operation_started = time.perf_counter()
        last_error: ProviderTimeoutError | ProviderUnavailableError | None = None

        selected_models = model_names or self._generation_model_names
        attempted_models: list[str] = []
        for model_index, model_name in enumerate(selected_models):
            attempted_models.append(model_name)
            try:
                result, retry_count = await self._try_model(
                    model_name,
                    system_instruction,
                    user_input,
                    response_model,
                    operation=operation,
                    thinking_budget=thinking_budget,
                )
            except _RetryableExhaustedError as exc:
                last_error = exc.original
                is_last_model = model_index == len(selected_models) - 1
                if is_last_model:
                    record_llm_call(
                        operation=operation,
                        attempted_models=attempted_models,
                        served_model=None,
                        latency_ms=round((time.perf_counter() - operation_started) * 1000),
                        # 이 모델에서 재시도를 전부 소진했다는 뜻이라 그 값 자체다.
                        retry_count=self._max_retries,
                    )
                    logger.error(
                        "Gemini 전 모델 소진, 최종 실패 (models=%s): %s",
                        selected_models,
                        last_error,
                    )
                    raise last_error from None
                logger.warning(
                    "Gemini 모델 %s 재시도 소진, %s로 폴백: %s",
                    model_name,
                    selected_models[model_index + 1],
                    last_error,
                )
                continue
            except ProviderUnavailableError:
                # 4xx 등 비재시도 오류는 모델을 바꿔도 해결되지 않아 즉시 끝난다 —
                # _try_model()이 첫 시도에서 바로 던지므로 재시도는 없었다.
                record_llm_call(
                    operation=operation,
                    attempted_models=attempted_models,
                    served_model=None,
                    latency_ms=round((time.perf_counter() - operation_started) * 1000),
                    retry_count=0,
                )
                raise
            except ValidationError:
                # Gemini는 응답했지만 구조화 스키마 검증에 실패한 경우다. 뒤의
                # _call_structured() 보정 재시도와 구분할 수 있게 모델을 남긴다.
                # 몇 번째 시도에서 검증이 깨졌는지는 _try_model() 밖으로 안 나와
                # retry_count를 알 수 없다 — None으로 둔다.
                record_llm_call(
                    operation=operation,
                    attempted_models=attempted_models,
                    served_model=model_name,
                    latency_ms=round((time.perf_counter() - operation_started) * 1000),
                )
                raise

            record_llm_call(
                operation=operation,
                attempted_models=attempted_models,
                served_model=model_name,
                latency_ms=round((time.perf_counter() - operation_started) * 1000),
                retry_count=retry_count,
            )
            if model_index > 0:
                logger.warning(
                    "Gemini 폴백 모델로 응답 성공 (served_by=%s, primary=%s)",
                    model_name,
                    selected_models[0],
                )
            return result

        raise AssertionError("unreachable: model loop exited without returning or raising")

    async def _try_model(
        self,
        model_name: str,
        system_instruction: str,
        user_input: str,
        response_model: type[T],
        *,
        operation: str,
        thinking_budget: int | None = None,
    ) -> tuple[T, int]:
        """모델 하나에 대해서만 타임아웃/429/5xx를 지수 백오프로 최대
        self._max_retries회 재시도한다. 재시도가 소진되면 _RetryableExhaustedError로
        감싸 던져 호출부(_generate)가 다음 모델로 넘어갈지 판단하게 한다. 4xx 등
        비재시도 오류는 감싸지 않고 ProviderUnavailableError를 바로 던진다 —
        모델을 바꿔도 같은 이유로 실패할 것이므로 폴백 대상이 아니다.

        반환값은 (결과, 이 모델에서 실제로 재시도한 횟수)다. 성공이 몇 번째
        시도에서 났는지를 호출부가 감사 기록(retry_count)에 남기기 위해서다 —
        재시도가 성공하면 로그도 안 남고 attempted_models도 안 늘어나, 이 값이
        없으면 "모델이 원래 느렸다"와 "타임아웃 후 재시도로 늦게 성공했다"를
        구분할 방법이 없다(D-076 검토 후속).

        thinking_budget이 None이면 GenerateContentConfig에 thinking_config를
        아예 안 넣어 모델 자체 기본 동작을 그대로 둔다 — 이 기본값이 어떤 값인지는
        모델마다 다르다(gemini-2.5-flash는 가벼운 동적 thinking이었지만,
        gemini-3.5-flash는 기본이 MEDIUM이라 더 무겁다, 2026-08-18). thinking_budget이
        None이 아니면 먼저 _resolve_thinking_budget()으로 모델·호출 종류에 맞춰
        보정한다 — override 테이블(예: gemini-2.5-flash-lite의 classify_intent) 또는
        thinking_budget=0을 거부하는 모델(Flash-Lite 계열)이면 None으로 바꿔
        thinking_config 자체를 생략한다(근거:
        backend/test_results/intent_experiments_2026-08.md §4, §5). 그렇게 보정된
        값을 _thinking_config_for()에 넘겨 실제 ThinkingConfig로 바꾼다 — 0은 레거시
        thinking_budget이 아니라 thinking_level=MINIMAL로 변환한다(레거시 파라미터를
        Gemini 3.x에서 계속 믿을 수 없어졌기 때문, 자세한 배경은
        _thinking_config_for() docstring 참고). 폴백으로 넘어가면 model_name이
        바뀌므로 같은 요청 안에서도 모델마다 다른 thinking_config가 실릴 수 있다.
        """

        resolved_budget = _resolve_thinking_budget(model_name, operation, thinking_budget)
        thinking_config = _thinking_config_for(resolved_budget)

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
                        thinking_config=thinking_config,
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
                    return response_model.model_validate(response.parsed), attempt
                # response_schema가 SDK 자동 파싱을 못 한 경우(빈 응답 등)
                # 원문 텍스트로 직접 검증한다.
                return response_model.model_validate_json(response.text or ""), attempt

            await asyncio.sleep(_backoff_seconds(attempt))

        raise AssertionError("unreachable: retry loop exited without returning or raising")


__all__ = ["RealGeminiProvider"]
