"""RealGeminiProvider의 재시도 동작 회귀 테스트.

역할: (1) 구조화 출력 검증 실패 시 1회 재시도, (2) 타임아웃/429/5xx 같은 일시적 오류의
지수 백오프 재시도, (3) 4xx 등 비일시적 오류는 즉시 실패를 확인한다. 실제 Gemini API는
호출하지 않고 google-genai 클라이언트 메서드를 mock으로 대체한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from google.genai import errors as genai_errors

from app.errors import AppError, ProviderUnavailableError
from app.providers.gemini import RealGeminiProvider
from app.schemas import Intent, IntentClassificationResult


def _api_error(status_code: int, status: str) -> genai_errors.APIError:
    return genai_errors.APIError(status_code, {"error": {"message": status, "status": status}})


class _FakeResponse:
    def __init__(self, parsed: IntentClassificationResult) -> None:
        self.parsed = parsed
        self.text = None


@pytest.mark.asyncio
async def test_generate_retries_on_transient_5xx_then_succeeds() -> None:
    provider = RealGeminiProvider(
        api_key="dummy", model_names=["dummy"], timeout_seconds=1.0, max_retries=2
    )
    call_count = 0

    async def flaky(*args: object, **kwargs: object) -> _FakeResponse:
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise _api_error(503, "UNAVAILABLE")
        return _FakeResponse(IntentClassificationResult(intent=Intent.RECOMMEND))

    with (
        patch.object(provider._client.aio.models, "generate_content", side_effect=flaky),
        patch("app.providers.gemini.asyncio.sleep", new=AsyncMock()) as mock_sleep,
    ):
        result = await provider._generate("sys", "user", IntentClassificationResult, "test")

    assert result.intent is Intent.RECOMMEND
    assert call_count == 3
    assert mock_sleep.call_count == 2


@pytest.mark.asyncio
async def test_generate_raises_after_exhausting_retries_on_persistent_5xx() -> None:
    provider = RealGeminiProvider(
        api_key="dummy", model_names=["dummy"], timeout_seconds=1.0, max_retries=2
    )

    async def always_unavailable(*args: object, **kwargs: object) -> _FakeResponse:
        raise _api_error(503, "UNAVAILABLE")

    with (
        patch.object(
            provider._client.aio.models, "generate_content", side_effect=always_unavailable
        ),
        patch("app.providers.gemini.asyncio.sleep", new=AsyncMock()) as mock_sleep,
        pytest.raises(ProviderUnavailableError) as exc_info,
    ):
        await provider._generate("sys", "user", IntentClassificationResult, "test")

    assert exc_info.value.status_code == 502
    assert mock_sleep.call_count == 2


@pytest.mark.asyncio
async def test_generate_does_not_retry_non_retryable_4xx() -> None:
    provider = RealGeminiProvider(
        api_key="dummy", model_names=["dummy"], timeout_seconds=1.0, max_retries=2
    )
    call_count = 0

    async def bad_request(*args: object, **kwargs: object) -> _FakeResponse:
        nonlocal call_count
        call_count += 1
        raise _api_error(400, "INVALID_ARGUMENT")

    with (
        patch.object(provider._client.aio.models, "generate_content", side_effect=bad_request),
        patch("app.providers.gemini.asyncio.sleep", new=AsyncMock()) as mock_sleep,
        pytest.raises(ProviderUnavailableError),
    ):
        await provider._generate("sys", "user", IntentClassificationResult, "test")

    assert call_count == 1
    assert mock_sleep.call_count == 0


@pytest.mark.asyncio
async def test_call_structured_retries_once_on_validation_error_then_raises() -> None:
    """구조화 출력 검증 재시도(1회)는 백오프 재시도와 독립적인 별도 경로다."""
    provider = RealGeminiProvider(api_key="dummy", model_names=["dummy"], timeout_seconds=1.0)
    call_count = 0

    async def invalid_then_invalid(
        system_instruction: str, user_input: str, response_model: type, operation: str
    ) -> IntentClassificationResult:
        nonlocal call_count
        call_count += 1
        return response_model.model_validate({"intent": "NOT_A_REAL_INTENT"})

    with patch.object(provider, "_generate", side_effect=invalid_then_invalid):
        with pytest.raises(AppError) as exc_info:
            await provider._call_structured(
                "sys", "user", IntentClassificationResult, operation="test"
            )

    assert exc_info.value.code == "llm_output_invalid"
    assert call_count == 2  # 최초 시도 + 1회 재시도


# --- D-052: 모델 fallback ---


@pytest.mark.asyncio
async def test_generate_succeeds_on_primary_no_fallback_triggered() -> None:
    """1순위 모델이 바로 성공하면 폴백을 시도하지 않는다."""
    provider = RealGeminiProvider(
        api_key="dummy",
        model_names=["primary", "secondary"],
        timeout_seconds=1.0,
        max_retries=1,
    )
    calls: list[str] = []

    async def succeed(*args: object, **kwargs: object) -> _FakeResponse:
        calls.append(kwargs["model"])
        return _FakeResponse(IntentClassificationResult(intent=Intent.RECOMMEND))

    with patch.object(provider._client.aio.models, "generate_content", side_effect=succeed):
        result = await provider._generate("sys", "user", IntentClassificationResult, "test")

    assert result.intent is Intent.RECOMMEND
    assert calls == ["primary"]


@pytest.mark.asyncio
async def test_generate_falls_back_to_second_model_after_primary_exhausts_retries() -> None:
    """1순위 모델 재시도가 소진되면 2순위 모델로 넘어가 성공한다."""
    provider = RealGeminiProvider(
        api_key="dummy",
        model_names=["primary", "secondary"],
        timeout_seconds=1.0,
        max_retries=1,
    )
    calls: list[str] = []

    async def flaky(*args: object, **kwargs: object) -> _FakeResponse:
        model = kwargs["model"]
        calls.append(model)
        if model == "primary":
            raise _api_error(503, "UNAVAILABLE")
        return _FakeResponse(IntentClassificationResult(intent=Intent.RECOMMEND))

    with (
        patch.object(provider._client.aio.models, "generate_content", side_effect=flaky),
        patch("app.providers.gemini.asyncio.sleep", new=AsyncMock()),
    ):
        result = await provider._generate("sys", "user", IntentClassificationResult, "test")

    assert result.intent is Intent.RECOMMEND
    # primary: max_retries+1(=2)회 소진, secondary: 1회 성공
    assert calls == ["primary", "primary", "secondary"]


@pytest.mark.asyncio
async def test_generate_raises_after_all_models_exhausted() -> None:
    """모든 모델이 다 소진되면 오늘과 동일한 ProviderUnavailableError를 던진다
    (폴백을 추가해도 외부 계약이 안 바뀐다는 회귀 가드)."""
    provider = RealGeminiProvider(
        api_key="dummy",
        model_names=["primary", "secondary"],
        timeout_seconds=1.0,
        max_retries=1,
    )
    calls: list[str] = []

    async def always_unavailable(*args: object, **kwargs: object) -> _FakeResponse:
        calls.append(kwargs["model"])
        raise _api_error(503, "UNAVAILABLE")

    with (
        patch.object(
            provider._client.aio.models, "generate_content", side_effect=always_unavailable
        ),
        patch("app.providers.gemini.asyncio.sleep", new=AsyncMock()),
        pytest.raises(ProviderUnavailableError) as exc_info,
    ):
        await provider._generate("sys", "user", IntentClassificationResult, "test")

    assert exc_info.value.status_code == 502
    # 두 모델 각각 max_retries+1(=2)회씩 소진.
    assert calls == ["primary", "primary", "secondary", "secondary"]


@pytest.mark.asyncio
async def test_generate_does_not_fall_back_on_non_retryable_4xx() -> None:
    """4xx는 모델을 바꿔도 같은 이유로 실패하므로 폴백하지 않고 즉시 실패한다."""
    provider = RealGeminiProvider(
        api_key="dummy",
        model_names=["primary", "secondary"],
        timeout_seconds=1.0,
        max_retries=1,
    )
    calls: list[str] = []

    async def bad_request(*args: object, **kwargs: object) -> _FakeResponse:
        calls.append(kwargs["model"])
        raise _api_error(400, "INVALID_ARGUMENT")

    with (
        patch.object(provider._client.aio.models, "generate_content", side_effect=bad_request),
        patch("app.providers.gemini.asyncio.sleep", new=AsyncMock()) as mock_sleep,
        pytest.raises(ProviderUnavailableError),
    ):
        await provider._generate("sys", "user", IntentClassificationResult, "test")

    assert calls == ["primary"]
    assert mock_sleep.call_count == 0


@pytest.mark.asyncio
async def test_generate_logs_fallback_transition_and_exhaustion(caplog) -> None:
    """폴백 전환 시 WARNING, 전 모델 소진 시 ERROR 로그가 실제로 남는지 확인한다
    (D-052가 해결하려던 "무로그 502" 문제를 직접 증명하는 테스트)."""
    provider = RealGeminiProvider(
        api_key="dummy",
        model_names=["primary", "secondary"],
        timeout_seconds=1.0,
        max_retries=0,
    )

    async def always_unavailable(*args: object, **kwargs: object) -> _FakeResponse:
        raise _api_error(503, "UNAVAILABLE")

    with (
        patch.object(
            provider._client.aio.models, "generate_content", side_effect=always_unavailable
        ),
        patch("app.providers.gemini.asyncio.sleep", new=AsyncMock()),
        caplog.at_level("WARNING", logger="app.providers.gemini"),
        pytest.raises(ProviderUnavailableError),
    ):
        await provider._generate("sys", "user", IntentClassificationResult, "test")

    warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any(
        "primary" in r.getMessage() and "secondary" in r.getMessage() for r in warning_records
    )
    assert any("전 모델 소진" in r.getMessage() for r in error_records)
