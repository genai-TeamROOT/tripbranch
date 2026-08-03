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


@pytest.fixture(autouse=True)
def _reset_concentration_mapping_cache():
    """매핑 캐시는 프로세스 단위라 테스트 간 데이터가 새지 않도록 매번 비운다."""
    from app.agent_context.concentration_proxy import clear_concentration_mapping_cache

    clear_concentration_mapping_cache()
    yield
    clear_concentration_mapping_cache()
