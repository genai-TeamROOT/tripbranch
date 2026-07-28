"""정규화 조건에 따른 C Tool 실행 계획을 검증한다."""

from app.agent_context.schemas import UserConditions
from app.agent_context.tool_rules import (
    TOOL_EXECUTION_RULE_VERSION,
    ContextTool,
    build_tool_execution_plan,
)


def test_default_plan_collects_required_recommendation_context() -> None:
    plan = build_tool_execution_plan(UserConditions())

    assert plan.rule_version == TOOL_EXECUTION_RULE_VERSION
    assert plan.tools == frozenset(
        {
            ContextTool.RESOLVE_LOCATION,
            ContextTool.SEARCH_PLACES,
            ContextTool.GET_WEATHER,
            ContextTool.GET_HOLIDAYS,
        }
    )


def test_weather_ignore_skips_only_weather_tool() -> None:
    plan = build_tool_execution_plan(UserConditions(weather_intent="IGNORE"))

    assert not plan.requires(ContextTool.GET_WEATHER)
    assert plan.requires(ContextTool.RESOLVE_LOCATION)
    assert plan.requires(ContextTool.SEARCH_PLACES)
    assert plan.requires(ContextTool.GET_HOLIDAYS)


def test_initial_plan_never_fetches_concentration() -> None:
    plan = build_tool_execution_plan(
        UserConditions(
            place_types=["attraction"],
            place_tags=["궁궐"],
        )
    )

    assert not plan.requires(ContextTool.GET_CONCENTRATION)
