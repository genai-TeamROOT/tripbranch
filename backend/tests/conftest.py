from __future__ import annotations

import os

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def isolate_regular_tests_from_real_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """명시적 Smoke·Inspection 외 일반 테스트의 외부 호출을 차단한다."""
    if (
        os.getenv("RUN_REAL_PROVIDER_TESTS") == "true"
        or os.getenv("RUN_REAL_PROVIDER_INSPECTION") == "true"
    ):
        return

    monkeypatch.setattr(settings, "provider_mode", "fake")
    monkeypatch.setattr(settings, "llm_provider", None)
    monkeypatch.setattr(settings, "geocoding_provider", None)
    monkeypatch.setattr(settings, "local_search_provider", None)
    monkeypatch.setattr(settings, "weather_provider", None)
    monkeypatch.setattr(settings, "place_provider", None)
    monkeypatch.setattr(settings, "concentration_provider", None)
    monkeypatch.setattr(settings, "holiday_provider", None)
