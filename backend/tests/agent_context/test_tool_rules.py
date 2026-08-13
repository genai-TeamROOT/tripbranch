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


def test_weather_avoid_and_enjoy_skip_weather_tool_when_stated() -> None:
    """발화에서 날씨 값을 뽑았으면 API를 부를 이유가 없다. D가 그 값으로 판정한다."""
    for intent in ("AVOID", "ENJOY"):
        plan = build_tool_execution_plan(
            UserConditions(weather_intent=intent, weather="rain")
        )
        assert not plan.requires(ContextTool.GET_WEATHER), intent
        assert plan.requires(ContextTool.RESOLVE_LOCATION), intent
        assert plan.requires(ContextTool.SEARCH_PLACES), intent
        assert plan.requires(ContextTool.GET_HOLIDAYS), intent


def test_weather_avoid_and_enjoy_fetch_weather_when_value_missing() -> None:
    """의도만 있고 날씨 값이 없으면 조회해서 채운다.

    5단계(rain/snow/hot/cold/good)로 표현되지 않는 발화가 있다 — 실측(2026-08-05)에서
    "날씨 안 좋으니까 실내로", "바람 많이 부는데" 등 6건 중 3건이 AVOID인데 weather가
    비어 있었다. 조회하지 않으면 날씨를 분명히 말한 사용자에게만 날씨 Feature가
    빠지고 가중치 0.4가 다른 항목으로 재분배된다.
    """
    for intent in ("AVOID", "ENJOY"):
        plan = build_tool_execution_plan(
            UserConditions(weather_intent=intent, weather=None)
        )
        assert plan.requires(ContextTool.GET_WEATHER), intent


def test_initial_plan_never_fetches_concentration() -> None:
    plan = build_tool_execution_plan(
        UserConditions(
            place_types=["attraction"],
            place_tags=["궁궐"],
        )
    )

    assert not plan.requires(ContextTool.GET_CONCENTRATION)
