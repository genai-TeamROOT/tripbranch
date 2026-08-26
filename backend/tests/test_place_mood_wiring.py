"""장소 분위기 Provider 조립 테스트 — 스위치와 인코더 부재 처리."""

from __future__ import annotations

import httpx
import pytest

from app.providers import factory
from app.providers.place_mood import PlaceMoodProvider


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))


def test_disabled_flag_returns_none(monkeypatch, client) -> None:
    monkeypatch.setattr(factory.settings, "place_mood_enabled", False)
    assert factory.get_place_mood_provider(client) is None


def test_missing_supabase_config_returns_none_without_crashing(
    monkeypatch, client, caplog
) -> None:
    """설정 하나 때문에 서버 전체가 안 뜨면 안 된다. 대신 이유는 남긴다."""
    monkeypatch.setattr(factory.settings, "place_mood_enabled", True)
    monkeypatch.setattr(factory.settings, "supabase_url", "")
    monkeypatch.setattr(factory.settings, "supabase_secret_key", "")

    with caplog.at_level("WARNING"):
        assert factory.get_place_mood_provider(client) is None

    assert "PLACE_MOOD_ENABLED" in caplog.text


def test_enabled_builds_provider(monkeypatch, client) -> None:
    monkeypatch.setattr(factory.settings, "place_mood_enabled", True)
    monkeypatch.setattr(factory.settings, "supabase_url", "https://x.supabase.co")
    monkeypatch.setattr(factory.settings, "supabase_secret_key", "secret")
    monkeypatch.setattr(factory.settings, "place_mood_warmup_enabled", False)
    monkeypatch.setattr(factory, "_get_mood_encoder", lambda: None)

    provider = factory.get_place_mood_provider(client)

    assert isinstance(provider, PlaceMoodProvider)


def test_provider_is_built_even_without_the_encoder(monkeypatch, client) -> None:
    """SigLIP이 없어도 발화 경로는 돌아야 하므로 Provider 자체는 만든다."""
    monkeypatch.setattr(factory.settings, "place_mood_enabled", True)
    monkeypatch.setattr(factory.settings, "supabase_url", "https://x.supabase.co")
    monkeypatch.setattr(factory.settings, "supabase_secret_key", "secret")
    monkeypatch.setattr(factory, "_get_mood_encoder", lambda: None)

    provider = factory.get_place_mood_provider(client)

    assert provider is not None
    assert provider.photo_search_available is False


def test_warmup_runs_only_when_enabled(monkeypatch) -> None:
    calls: list[str] = []

    class _Encoder:
        def warmup_in_background(self):
            calls.append("warmup")

    monkeypatch.setattr(
        "app.providers.place_mood_encoder.get_shared_encoder", lambda: _Encoder()
    )

    monkeypatch.setattr(factory.settings, "place_mood_warmup_enabled", False)
    factory._get_mood_encoder()
    assert calls == []

    monkeypatch.setattr(factory.settings, "place_mood_warmup_enabled", True)
    factory._get_mood_encoder()
    assert calls == ["warmup"]
