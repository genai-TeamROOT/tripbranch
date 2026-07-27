import pytest

from app.domain.agent_context import AgentToolContext, context_value
from app.providers.contracts import ProviderSource, provider_result
from app.tools.contracts import ToolError, ToolStatus


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


def test_no_data_context_normalizes_tool_specific_empty_value() -> None:
    value = context_value(
        status=ToolStatus.NO_DATA,
        data=(),
        error=None,
    )

    assert value.data is None
    assert value.error is None


@pytest.mark.parametrize("status", [ToolStatus.SUCCESS, ToolStatus.PARTIAL])
def test_usable_context_requires_data(status: ToolStatus) -> None:
    with pytest.raises(ValueError, match="data가 필요합니다"):
        context_value(status=status, data=None, error=None)


@pytest.mark.parametrize("status", [ToolStatus.SUCCESS, ToolStatus.PARTIAL])
def test_usable_context_rejects_top_level_error(status: ToolStatus) -> None:
    with pytest.raises(ValueError, match="error를 포함할 수 없습니다"):
        context_value(
            status=status,
            data="usable",
            error=_error(),
        )


@pytest.mark.parametrize(
    "status",
    [ToolStatus.UNAVAILABLE, ToolStatus.UNSUPPORTED],
)
def test_blocked_context_requires_error_and_rejects_data(
    status: ToolStatus,
) -> None:
    with pytest.raises(ValueError, match="error가 필요합니다"):
        context_value(status=status, data=None, error=None)

    with pytest.raises(ValueError, match="data를 포함할 수 없습니다"):
        context_value(status=status, data="unexpected", error=_error())


def _error() -> ToolError:
    return ToolError(
        code="unavailable",
        message="테스트 오류",
        cause="upstream_error",
        retryable=True,
    )
