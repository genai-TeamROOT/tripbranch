from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.providers.factory import validate_provider_config


def test_provider_mode_applies_to_all_providers() -> None:
    settings = Settings(_env_file=None, provider_mode="real")

    assert settings.resolved_geocoding_provider == "real"
    assert settings.resolved_weather_provider == "real"
    assert settings.resolved_place_provider == "real"
    assert settings.resolved_concentration_provider == "real"
    assert settings.resolved_holiday_provider == "real"
    assert settings.resolved_llm_provider == "real"


def test_individual_provider_overrides_common_mode() -> None:
    settings = Settings(
        _env_file=None,
        provider_mode="real",
        place_provider="fake",
        concentration_provider="fake",
        holiday_provider="fake",
        llm_provider="fake",
    )

    assert settings.resolved_geocoding_provider == "real"
    assert settings.resolved_weather_provider == "real"
    assert settings.resolved_place_provider == "fake"
    assert settings.resolved_concentration_provider == "fake"
    assert settings.resolved_holiday_provider == "fake"
    assert settings.resolved_llm_provider == "fake"


def test_resolved_llm_timeout_falls_back_to_external_api_timeout() -> None:
    """LLM_API_TIMEOUT_SECONDS 미설정 시 EXTERNAL_API_TIMEOUT_SECONDS를 그대로 쓴다
    (하위 호환 — 기존에 EXTERNAL_API_TIMEOUT_SECONDS만 설정해 쓰던 환경도 그대로
    동작해야 한다)."""
    settings = Settings(_env_file=None, external_api_timeout_seconds=25.0)

    assert settings.llm_api_timeout_seconds is None
    assert settings.resolved_llm_timeout_seconds == 25.0


def test_resolved_llm_timeout_uses_dedicated_value_when_set() -> None:
    """LLM_API_TIMEOUT_SECONDS를 설정하면 EXTERNAL_API_TIMEOUT_SECONDS와 분리된다
    (2026-08-11 — Gemini 지연 대응으로 EXTERNAL_API_TIMEOUT_SECONDS를 올리면
    TourAPI/Naver/Supabase까지 같은 값을 물려받는 문제로 분리)."""
    settings = Settings(
        _env_file=None,
        external_api_timeout_seconds=10.0,
        llm_api_timeout_seconds=25.0,
    )

    assert settings.resolved_llm_timeout_seconds == 25.0
    assert settings.external_api_timeout_seconds == 10.0


def test_resolved_llm_models_defaults_to_single_primary_model() -> None:
    """LLM_FALLBACK_MODEL_NAMES 미설정 시 1순위 모델 하나짜리 리스트 — 기존 동작과 동일."""
    settings = Settings(_env_file=None, llm_model_name="gemini-2.5-flash")

    assert settings.resolved_llm_models == ["gemini-2.5-flash"]


def test_resolved_llm_models_appends_fallbacks_in_order() -> None:
    settings = Settings(
        _env_file=None,
        llm_model_name="gemini-2.5-flash",
        llm_fallback_model_names="gemini-2.0-flash, gemini-1.5-flash",
    )

    assert settings.resolved_llm_models == [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
    ]


def test_resolved_llm_models_drops_blank_entries() -> None:
    """트레일링 콤마·빈 항목은 방어적으로 무시한다."""
    settings = Settings(
        _env_file=None,
        llm_model_name="gemini-2.5-flash",
        llm_fallback_model_names="gemini-2.0-flash,,  ,",
    )

    assert settings.resolved_llm_models == ["gemini-2.5-flash", "gemini-2.0-flash"]


def test_resolved_role_based_llm_models_use_independent_routes() -> None:
    settings = Settings(
        _env_file=None,
        llm_fast_model_name="gemini-3.5-flash-lite",
        llm_fast_fallback_model_names="gemini-3.5-flash",
        llm_generation_model_name="gemini-3.5-flash",
        llm_generation_fallback_model_names="gemini-3.5-flash-lite",
    )

    assert settings.resolved_llm_fast_models == [
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash",
    ]
    assert settings.resolved_llm_generation_models == [
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
    ]
    assert settings.resolved_gemini_audio_model_name == "gemini-3.5-flash-lite"


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider_mode": "Real"},
        {"provider_mode": "stub"},
        {"provider_mode": "ral"},
        {"place_provider": "reall"},
    ],
)
def test_invalid_provider_settings_fail_at_construction(overrides: dict[str, str]) -> None:
    """오타/옛 이름은 Settings 생성 시점(=프로세스 시작)에 즉시 실패해야 한다."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


def test_fake_weather_settings_hold_kma_codes() -> None:
    """D-051: 설정도 판정(good/neutral/bad)이 아니라 기상청 코드를 받는다.

    이 값이 실제로 fake의 사실을 움직이는지는
    `test_provider_contracts.py::test_fake_weather_provider_emits_facts_d_can_judge`가
    확인한다.
    """
    settings = Settings(
        _env_file=None,
        fake_weather_sky_code="4",
        fake_weather_precipitation_type="1",
    )

    assert settings.fake_weather_sky_code == "4"
    assert settings.fake_weather_precipitation_type == "1"


@pytest.mark.parametrize(
    "overrides",
    [
        {"recommendation_result_limit": 0},
        {"recommendation_result_limit": 21},
        {"recommendation_candidate_limit": 0},
        {"recommendation_candidate_limit": 21},
        {
            "recommendation_result_limit": 6,
            "recommendation_candidate_limit": 5,
        },
    ],
)
def test_invalid_recommendation_limits_fail_at_construction(
    overrides: dict[str, int],
) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


def test_validate_provider_config_allows_fake_mode_without_keys() -> None:
    validate_provider_config(Settings(_env_file=None, provider_mode="fake"))


def test_validate_provider_config_reports_every_missing_key_at_once() -> None:
    settings = Settings(_env_file=None, provider_mode="real")

    with pytest.raises(ValueError) as error:
        validate_provider_config(settings)

    message = str(error.value)
    for variable_name in (
        "LLM_API_KEY",
        "WEATHER_API_KEY",
        "TOUR_API_SERVICE_KEY",
        "NAVER_MAP_CLIENT_ID",
        "NAVER_MAP_CLIENT_SECRET",
    ):
        assert variable_name in message
    # 세 provider가 공유하는 키는 한 번만 나열한다.
    assert message.count("TOUR_API_SERVICE_KEY") == 1


def test_validate_provider_config_ignores_keys_for_fake_providers() -> None:
    settings = Settings(
        _env_file=None,
        provider_mode="fake",
        weather_provider="real",
        weather_api_key="present",
    )

    validate_provider_config(settings)


def test_validate_provider_config_flags_only_the_real_provider() -> None:
    settings = Settings(_env_file=None, provider_mode="fake", llm_provider="real")

    with pytest.raises(ValueError) as error:
        validate_provider_config(settings)

    message = str(error.value)
    assert "LLM_API_KEY" in message
    assert "WEATHER_API_KEY" not in message


def test_validate_provider_config_rejects_duplicate_fallback_model() -> None:
    """역할별 폴백에 1순위와 같은 모델이 들어가면 부팅 시 막는다."""
    settings = Settings(
        _env_file=None,
        provider_mode="real",
        llm_api_key="present",
        weather_api_key="present",
        TOUR_API_SERVICE_KEY="present",
        naver_map_client_id="present",
        naver_map_client_secret="present",
        naver_local_search_client_id="present",
        naver_local_search_client_secret="present",
        llm_fast_model_name="gemini-3.5-flash-lite",
        llm_fast_fallback_model_names="gemini-3.5-flash,gemini-3.5-flash-lite",
    )

    with pytest.raises(ValueError) as error:
        validate_provider_config(settings)

    assert "gemini-3.5-flash-lite" in str(error.value)


def test_validate_provider_config_allows_distinct_fallback_models() -> None:
    settings = Settings(
        _env_file=None,
        provider_mode="real",
        llm_api_key="present",
        weather_api_key="present",
        TOUR_API_SERVICE_KEY="present",
        naver_map_client_id="present",
        naver_map_client_secret="present",
        naver_local_search_client_id="present",
        naver_local_search_client_secret="present",
        llm_fast_model_name="gemini-3.5-flash-lite",
        llm_fast_fallback_model_names="gemini-3.5-flash",
        llm_generation_model_name="gemini-3.5-flash",
        llm_generation_fallback_model_names="gemini-3.5-flash-lite",
    )

    validate_provider_config(settings)


def test_env_file_is_resolved_relative_to_backend_package() -> None:
    """실행 위치가 아니라 backend/.env를 절대경로로 가리켜야 한다.

    상대경로면 저장소 루트에서 서버를 띄웠을 때 .env를 읽지 못하고 오류 없이
    전 Provider가 fake로 뜬다(npm run dev가 그렇게 실행되던 회귀).
    """
    import app.config as config_module

    env_file = Path(config_module.Settings.model_config["env_file"])

    assert env_file.is_absolute()
    assert env_file.name == ".env"
    assert env_file.parent == Path(config_module.__file__).resolve().parent.parent
