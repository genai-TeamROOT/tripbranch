from app.domain.agent_context import AgentToolContext, context_value
from app.providers.contracts import ProviderSource, provider_result
from app.tools.contracts import ToolStatus


def test_agent_context_aggregates_metadata_and_warnings() -> None:
    location_metadata = provider_result(
        "location",
        source=ProviderSource.FAKE_GEOCODING,
    ).metadata
    weather_metadata = provider_result(
        "weather",
        source=ProviderSource.FAKE_WEATHER,
    ).metadata

    context = AgentToolContext(
        location=context_value(
            status=ToolStatus.SUCCESS,
            data="location",
            error=None,
            provider_metadata=(location_metadata,),
        ),
        weather=context_value(
            status=ToolStatus.PARTIAL,
            data="weather",
            error=None,
            warnings=("partial_data",),
            provider_metadata=(weather_metadata,),
        ),
    )

    assert [item.source for item in context.provider_metadata] == [
        ProviderSource.FAKE_GEOCODING,
        ProviderSource.FAKE_WEATHER,
    ]
    assert context.warnings == ("partial_data",)
