"""app.providers.factory의 Provider 생성 로직 회귀 테스트.

get_llm_provider()가 LLM 전용 타임아웃(resolved_llm_timeout_seconds)을 Tool/DB
쪽 EXTERNAL_API_TIMEOUT_SECONDS와 분리해서 RealGeminiProvider에 전달하는지 검증한다
(2026-08-11 — EXTERNAL_API_TIMEOUT_SECONDS를 Gemini 지연 대응으로 올리면 TourAPI/
Naver/Supabase까지 같은 값을 물려받는 문제로 분리).
"""

from __future__ import annotations

from app.config import Settings
from app.providers import factory


def test_get_llm_provider_uses_dedicated_llm_timeout_when_set(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _RecordingRealGeminiProvider:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(factory, "RealGeminiProvider", _RecordingRealGeminiProvider)
    monkeypatch.setattr(
        factory,
        "settings",
        Settings(
            _env_file=None,
            provider_mode="real",
            llm_api_key="present",
            external_api_timeout_seconds=10.0,
            llm_api_timeout_seconds=25.0,
        ),
    )

    factory.get_llm_provider()

    assert captured["timeout_seconds"] == 25.0


def test_get_llm_provider_falls_back_to_external_api_timeout_when_unset(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _RecordingRealGeminiProvider:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(factory, "RealGeminiProvider", _RecordingRealGeminiProvider)
    monkeypatch.setattr(
        factory,
        "settings",
        Settings(
            _env_file=None,
            provider_mode="real",
            llm_api_key="present",
            external_api_timeout_seconds=10.0,
        ),
    )

    factory.get_llm_provider()

    assert captured["timeout_seconds"] == 10.0
