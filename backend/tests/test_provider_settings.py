from app.config import Settings


def test_provider_mode_applies_to_all_providers() -> None:
    settings = Settings(_env_file=None, provider_mode="real")

    assert settings.resolved_geocoding_provider == "real"
    assert settings.resolved_weather_provider == "real"
    assert settings.resolved_place_provider == "real"
    assert settings.resolved_concentration_provider == "real"


def test_individual_provider_overrides_common_mode() -> None:
    settings = Settings(
        _env_file=None,
        provider_mode="real",
        place_provider="fake",
        concentration_provider="fake",
    )

    assert settings.resolved_geocoding_provider == "real"
    assert settings.resolved_weather_provider == "real"
    assert settings.resolved_place_provider == "fake"
    assert settings.resolved_concentration_provider == "fake"
