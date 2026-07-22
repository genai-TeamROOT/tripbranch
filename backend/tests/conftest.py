from __future__ import annotations

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def isolate_regular_tests_from_real_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """로컬 .env가 real이어도 일반 테스트에서는 외부 API를 호출하지 않는다."""
    monkeypatch.setattr(settings, "provider_mode", "fake")
    monkeypatch.setattr(settings, "geocoding_provider", None)
    monkeypatch.setattr(settings, "weather_provider", None)
    monkeypatch.setattr(settings, "place_provider", None)
    monkeypatch.setattr(settings, "concentration_provider", None)
