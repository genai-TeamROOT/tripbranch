"""A의 정규화 조건을 C가 실행할 Tool 계획으로 변환한다."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.agent_context.schemas import UserConditions

TOOL_EXECUTION_RULE_VERSION = "context-tool-plan-v1"

# 날씨 조회를 생략하는 weather_intent 값. "상관없다고 명시함"만 해당한다.
_WEATHER_SKIP_INTENTS = frozenset({"IGNORE"})


class ContextTool(StrEnum):
    """초기 추천 Context 수집 단계에서 선택할 수 있는 Tool."""

    RESOLVE_LOCATION = "resolve_location"
    SEARCH_PLACES = "search_places"
    GET_WEATHER = "get_weather"
    GET_HOLIDAYS = "get_holidays"
    GET_CONCENTRATION = "get_concentration"


@dataclass(frozen=True)
class ToolExecutionPlan:
    """한 번의 초기 Context 요청에서 실행할 Tool 집합."""

    tools: frozenset[ContextTool]
    rule_version: str = TOOL_EXECUTION_RULE_VERSION

    def requires(self, tool: ContextTool) -> bool:
        return tool in self.tools


def build_tool_execution_plan(conditions: UserConditions) -> ToolExecutionPlan:
    """MVP 조건에 따라 초기 Context 수집 Tool을 선택한다.

    위치·장소·공휴일은 추천과 운영정보 판단에 항상 필요하다. 날씨는
    weather_intent가 NO_MENTION(미언급)일 때만 조회한다 — AVOID/ENJOY는
    사용자 발화 weather를 직접 쓰고, IGNORE는 명시적 무관 요청이므로 조회를
    생략한다. Concentration은 D가 선정한 상위 후보를 보강하는 후조회이므로
    초기 계획에 포함하지 않는다.
    """

    tools = {
        ContextTool.RESOLVE_LOCATION,
        ContextTool.SEARCH_PLACES,
        ContextTool.GET_HOLIDAYS,
    }
    if conditions.weather_intent in (None, "NO_MENTION"):
        tools.add(ContextTool.GET_WEATHER)
    return ToolExecutionPlan(tools=frozenset(tools))


def _requires_weather(weather_intent: str | None) -> bool:
    """날씨를 조회할지 판단한다.

    "상관없다"고 명시한 요청만 생략한다. 언급이 없는 경우(NO_MENTION)는 조회한다 —
    사용자가 말하지 않았다고 날씨를 무시하면, 비 오는 날 야외 장소를 그대로 추천하게
    된다(int-01-recommend.md §10).

    IGNORE는 원래 "언급 없음"과 "무관하다고 명시함"을 겸했다. 둘의 동작이 반대라 A가
    NO_MENTION을 분리했다. 값 하나를 제외하는 형태로 두면 값이 늘 때마다 우연히
    맞기를 기대하게 되므로, 생략 대상을 명시적으로 나열한다.
    """
    return weather_intent not in _WEATHER_SKIP_INTENTS


__all__ = [
    "ContextTool",
    "TOOL_EXECUTION_RULE_VERSION",
    "ToolExecutionPlan",
    "build_tool_execution_plan",
]
