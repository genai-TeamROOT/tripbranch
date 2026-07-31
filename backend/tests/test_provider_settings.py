from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.domain.models import WeatherCondition
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


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider_mode": "Real"},
        {"provider_mode": "stub"},
        {"provider_mode": "ral"},
        {"place_provider": "reall"},
        {"fake_weather_condition": "sunny"},
    ],
)
def test_invalid_provider_settings_fail_at_construction(overrides: dict[str, str]) -> None:
    """오타/옛 이름은 Settings 생성 시점(=프로세스 시작)에 즉시 실패해야 한다."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


def test_fake_weather_condition_is_parsed_as_enum() -> None:
    settings = Settings(_env_file=None, fake_weather_condition="bad")

    assert settings.fake_weather_condition is WeatherCondition.BAD


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
