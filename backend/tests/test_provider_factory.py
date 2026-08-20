"""app.providers.factory의 Provider 생성 로직 회귀 테스트.

get_llm_provider()가 LLM 전용 타임아웃(resolved_llm_timeout_seconds)을 Tool/DB
쪽 EXTERNAL_API_TIMEOUT_SECONDS와 분리해서 RealGeminiProvider에 전달하는지 검증한다
(2026-08-11 — EXTERNAL_API_TIMEOUT_SECONDS를 Gemini 지연 대응으로 올리면 TourAPI/
Naver/Supabase까지 같은 값을 물려받는 문제로 분리).
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.domain.travel_route import TravelMode
from app.errors import AppError
from app.providers import factory
from app.providers.walking_route import FakeWalkingRouteProvider


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
    assert captured["fast_model_names"] == ["gemini-3.5-flash-lite", "gemini-3.5-flash"]
    assert captured["generation_model_names"] == [
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
    ]


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


def test_get_gemini_audio_transcriber_uses_dedicated_default_model(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _RecordingTranscriber:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(factory, "GeminiAudioTranscriber", _RecordingTranscriber)
    monkeypatch.setattr(
        factory,
        "settings",
        Settings(_env_file=None, provider_mode="real", llm_api_key="present"),
    )

    factory.get_gemini_audio_transcriber()

    assert captured["model_name"] == "gemini-3.5-flash-lite"


def test_get_gemini_audio_transcriber_requires_real_llm(monkeypatch) -> None:
    monkeypatch.setattr(factory, "settings", Settings(_env_file=None, provider_mode="fake"))

    with pytest.raises(AppError, match="Gemini 실연동") as raised:
        factory.get_gemini_audio_transcriber()

    assert raised.value.code == "voice_input_unavailable"


def test_get_walking_route_provider_defaults_to_fake(monkeypatch) -> None:
    captured: dict[str, float] = {}

    class _RecordingFakeWalkingRouteProvider:
        def __init__(self, *, walking_speed_mps: float) -> None:
            captured["walking_speed_mps"] = walking_speed_mps

    monkeypatch.setattr(factory, "FakeWalkingRouteProvider", _RecordingFakeWalkingRouteProvider)
    monkeypatch.setattr(
        factory,
        "settings",
        Settings(_env_file=None, walking_speed_mps=1.1),
    )

    factory.get_walking_route_provider(object())  # type: ignore[arg-type]

    assert captured["walking_speed_mps"] == 1.1


def test_get_walking_route_provider_builds_real_provider(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _RecordingRealKakaoWalkingRouteProvider:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    client = object()
    monkeypatch.setattr(
        factory,
        "RealKakaoWalkingRouteProvider",
        _RecordingRealKakaoWalkingRouteProvider,
    )
    monkeypatch.setattr(
        factory,
        "settings",
        Settings(
            _env_file=None,
            travel_route_provider="real",
            kakao_map_rest_api_key="test-key",
            external_api_timeout_seconds=7.0,
            travel_route_max_concurrency=4,
        ),
    )

    factory.get_walking_route_provider(client)  # type: ignore[arg-type]

    assert captured == {
        "api_key": "test-key",
        "client": client,
        "timeout_seconds": 7.0,
        "max_concurrency": 4,
    }


def _capture_travel_route_tool(monkeypatch, settings_override: Settings) -> dict[object, object]:
    walking_primary = object()
    driving_primary = object()
    captured: dict[object, object] = {}

    class _RecordingTravelRouteTool:
        def __init__(self, providers: dict[object, object]) -> None:
            captured.update(providers)

    monkeypatch.setattr(factory, "TravelRouteTool", _RecordingTravelRouteTool)
    monkeypatch.setattr(factory, "get_walking_route_provider", lambda client: walking_primary)
    monkeypatch.setattr(factory, "get_driving_route_provider", lambda client: driving_primary)
    monkeypatch.setattr(factory, "settings", settings_override)

    factory.get_travel_route_tool(object())  # type: ignore[arg-type]
    return captured


def test_get_travel_route_tool_adds_fallback_only_in_real_mode(monkeypatch) -> None:
    captured = _capture_travel_route_tool(
        monkeypatch,
        Settings(
            _env_file=None,
            travel_route_provider="real",
            walking_speed_mps=1.1,
        ),
    )

    # 등록된 이동수단은 도보와 자동차다 — 대중교통은 Tool이 호출 없이 NO_DATA로 답한다.
    assert list(captured) == [TravelMode.WALKING, TravelMode.DRIVING]
    walking = captured[TravelMode.WALKING]
    assert isinstance(walking.fallback, FakeWalkingRouteProvider)
    assert walking.fallback._walking_speed_mps == 1.1


def test_get_travel_route_tool_gives_driving_no_fallback(monkeypatch) -> None:
    """자동차에는 직선거리 fallback을 두지 않는다.

    fallback이 내는 STRAIGHT_LINE_ESTIMATE는 채점에서 걸러지므로
    (scoring._applied_travel_route) 만들어도 쓰이지 않는다.
    """
    captured = _capture_travel_route_tool(
        monkeypatch,
        Settings(
            _env_file=None,
            travel_route_provider="real",
            travel_route_driving_provider="real",
        ),
    )

    assert captured[TravelMode.DRIVING].fallback is None


def test_get_travel_route_tool_keeps_driving_fake_unless_explicitly_enabled(monkeypatch) -> None:
    """TRAVEL_ROUTE_PROVIDER=real만으로는 자동차(네이버)가 켜지지 않는다.

    이동수단마다 벤더가 달라서, 한 값이 여러 벤더를 켜면 카카오 키만 가진 설정이
    쓰지도 않는 네이버 키를 요구하며 부팅에 실패한다.
    """
    settings_override = Settings(_env_file=None, travel_route_provider="real")

    assert settings_override.travel_route_provider == "real"
    assert settings_override.travel_route_driving_provider == "fake"
