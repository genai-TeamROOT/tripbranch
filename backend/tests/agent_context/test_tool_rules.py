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


def test_weather_no_mention_fetches_weather_tool() -> None:
    plan = build_tool_execution_plan(UserConditions(weather_intent="NO_MENTION"))

    assert plan.requires(ContextTool.GET_WEATHER)
    assert plan.requires(ContextTool.RESOLVE_LOCATION)
    assert plan.requires(ContextTool.SEARCH_PLACES)
    assert plan.requires(ContextTool.GET_HOLIDAYS)
def test_contract_accepts_no_mention_before_a_starts_sending_it() -> None:
    """C가 A보다 먼저 값을 받아들여야 한다.

    C의 UserConditions는 Literal이라 모르는 값이 오면 ValidationError로 요청 전체가
    깨진다. A가 NO_MENTION을 보내기 시작하는 시점에 C가 준비돼 있지 않으면 배포 순서에
    따라 서비스가 멈춘다(concentration_intent 때 같은 과도기가 있었다).
    """
    conditions = UserConditions(weather_intent="NO_MENTION")

    assert conditions.weather_intent == "NO_MENTION"


def test_weather_intent_absent_still_fetches_weather() -> None:
    """값이 없으면 언급이 없는 것으로 본다 — NO_MENTION과 같게 조회한다."""
    plan = build_tool_execution_plan(UserConditions(weather_intent=None))

    assert plan.requires(ContextTool.GET_WEATHER)


def test_weather_avoid_and_enjoy_skip_fetch_and_use_stated_weather() -> None:
    """사용자가 날씨를 말했으면 조회하지 않는다.

    AVOID/ENJOY는 발화에 날씨가 있다는 뜻이라 API를 부를 이유가 없다. 그 값은 A가
    `run_recommendation_pipeline_from_context(weather_condition=...)`으로 D에 직접
    넘긴다(PR #99) — C가 조회를 생략해도 날씨가 점수에서 빠지지 않는다.
    """
    for intent in ("AVOID", "ENJOY"):
        plan = build_tool_execution_plan(UserConditions(weather_intent=intent))
        assert not plan.requires(ContextTool.GET_WEATHER), intent
        # 날씨만 생략하고 나머지는 그대로다.
        assert plan.requires(ContextTool.RESOLVE_LOCATION), intent
        assert plan.requires(ContextTool.SEARCH_PLACES), intent
        assert plan.requires(ContextTool.GET_HOLIDAYS), intent


def test_initial_plan_never_fetches_concentration() -> None:
    plan = build_tool_execution_plan(
        UserConditions(
            place_types=["attraction"],
            place_tags=["궁궐"],
        )
    )

    assert not plan.requires(ContextTool.GET_CONCENTRATION)
