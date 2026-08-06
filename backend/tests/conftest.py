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

    # Package B의 STATE_STORE_BACKEND는 provider_mode와 별개 축이라 위 patch로는
    # 안 잡힌다. .env에 STATE_STORE_BACKEND=supabase가 남아있으면(실사용 전환 중
    # 흔히 발생) 일반 테스트가 실제 네트워크를 타거나 InMemory 전용 메서드(clear()
    # 등)를 호출하는 테스트가 깨진다 — 여기서도 강제로 memory로 고정한다.
    monkeypatch.setattr(settings, "state_store_backend", "memory")


@pytest.fixture(autouse=True)
def _reset_concentration_mapping_cache():
    """매핑 캐시는 프로세스 단위라 테스트 간 데이터가 새지 않도록 매번 비운다."""
    from app.agent_context.concentration_proxy import clear_concentration_mapping_cache

    clear_concentration_mapping_cache()
    yield
    clear_concentration_mapping_cache()
