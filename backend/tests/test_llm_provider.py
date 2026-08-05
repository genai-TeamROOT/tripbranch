"""FakeLLMProvider 회귀 테스트.

docs/design/test-cases.md의 대표 케이스(TC-01~04 RECOMMEND, TC-07~09 MODIFY, TC-11 GENERAL,
TC-12/13 OUT_OF_SCOPE)와 llm-output-schema.md §7의 needs_clarification 예시를 재현한다.
"""

from __future__ import annotations

import pytest

from app.providers.stub import FakeLLMProvider
from app.schemas import (
    Environment,
    Intent,
    ModifyType,
    OutOfScopeCategory,
    OutputStatus,
    PlaceTag,
    PlaceType,
    StatedWeather,
    UserConditions,
    WeatherIntent,
)


@pytest.mark.asyncio
async def test_classify_intent_tc01_recommend() -> None:
    provider = FakeLLMProvider()

    result = await provider.classify_intent(
        "경복궁 근처 카페 추천해줘",
        has_previous_recommendation=False,
        shown_place_count=0,
    )

    assert result.data.intent is Intent.RECOMMEND


@pytest.mark.asyncio
async def test_extract_recommend_conditions_tc01_search_center_and_tags() -> None:
    provider = FakeLLMProvider()

    output = (
        await provider.extract_recommend_conditions("경복궁 근처 카페 추천해줘")
    ).data

    assert output.intent is Intent.RECOMMEND
    assert output.recommend is not None
    assert output.recommend.conditions.search_center == "경복궁"
    assert output.recommend.conditions.place_types == [PlaceType.RESTAURANT]
    assert output.recommend.conditions.place_tags == [PlaceTag.CAFE]


@pytest.mark.asyncio
async def test_extract_recommend_conditions_tc02_weather_avoid_indoor() -> None:
    provider = FakeLLMProvider()

    output = (
        await provider.extract_recommend_conditions("비 오는데 갈 만한 곳 추천")
    ).data

    conditions = output.recommend.conditions
    assert conditions.weather is StatedWeather.RAIN
    assert conditions.weather_intent is WeatherIntent.AVOID
    assert conditions.environment is Environment.INDOOR
    assert conditions.place_types == []


@pytest.mark.asyncio
async def test_extract_recommend_conditions_tc03_multiple_types() -> None:
    provider = FakeLLMProvider()

    output = (
        await provider.extract_recommend_conditions("박물관이나 카페 가고 싶어")
    ).data

    conditions = output.recommend.conditions
    assert PlaceType.CULTURAL_FACILITY in conditions.place_types
    assert PlaceType.RESTAURANT in conditions.place_types
    assert PlaceTag.MUSEUM in conditions.place_tags
    assert PlaceTag.CAFE in conditions.place_tags


@pytest.mark.asyncio
async def test_extract_recommend_conditions_tc04_no_conditions() -> None:
    provider = FakeLLMProvider()

    output = (await provider.extract_recommend_conditions("추천해줘")).data

    conditions = output.recommend.conditions
    assert conditions.search_center is None
    assert conditions.place_types == []
    assert conditions.place_tags == []
    assert conditions.weather_intent is WeatherIntent.NO_MENTION


@pytest.mark.asyncio
async def test_extract_recommend_conditions_ambiguous_snow_needs_clarification() -> None:
    """llm-output-schema.md §7의 needs_clarification 예시 재현."""
    provider = FakeLLMProvider()

    output = (
        await provider.extract_recommend_conditions("눈 오는데 카페 추천해줘")
    ).data

    assert output.status is OutputStatus.NEEDS_CLARIFICATION
    assert output.clarification is not None
    assert output.clarification.ambiguous_fields[0].field == "weather_intent"


@pytest.mark.asyncio
async def test_classify_intent_modify_requires_previous_recommendation() -> None:
    """TC-14: 추천 이력 없이 MODIFY 패턴 입력 -> RECOMMEND로 처리."""
    provider = FakeLLMProvider()

    with_history = await provider.classify_intent(
        "다른 곳 보여줘", has_previous_recommendation=True, shown_place_count=3
    )
    without_history = await provider.classify_intent(
        "다른 곳 보여줘", has_previous_recommendation=False, shown_place_count=0
    )

    assert with_history.data.intent is Intent.MODIFY
    assert without_history.data.intent is Intent.RECOMMEND


@pytest.mark.asyncio
async def test_extract_modify_conditions_tc07_reject_all() -> None:
    provider = FakeLLMProvider()

    output = (
        await provider.extract_modify_conditions(
            "다른 곳 보여줘", UserConditions(search_center="경복궁")
        )
    ).data

    assert output.modify.modify_type is ModifyType.REJECT_ALL
    assert output.modify.condition_changes is None
    assert output.modify.changed_fields == []


@pytest.mark.asyncio
async def test_extract_modify_conditions_tc08_change_condition_budget() -> None:
    provider = FakeLLMProvider()
    current = UserConditions(search_center="경복궁", place_types=[PlaceType.RESTAURANT])

    output = (
        await provider.extract_modify_conditions("무료인 곳으로", current)
    ).data

    assert output.modify.modify_type is ModifyType.CHANGE_CONDITION
    assert output.modify.condition_changes.budget == "free"
    # search_center는 changed_fields에 없으므로 Keep 대상이지만, condition_changes
    # 자체에는 null로 정리되어 담긴다(ModifyPayload 검증기가 강제) — 실제 Keep 처리는
    # state_transform.py가 changed_fields만 읽어서 수행한다.
    assert output.modify.condition_changes.search_center is None
    assert output.modify.changed_fields == ["budget"]


@pytest.mark.asyncio
async def test_extract_modify_conditions_tc09_change_search_center() -> None:
    provider = FakeLLMProvider()
    current = UserConditions(search_center="경복궁")

    output = (
        await provider.extract_modify_conditions("인사동 근처로 바꿔줘", current)
    ).data

    assert output.modify.condition_changes.search_center == "인사동"
    assert output.modify.changed_fields == ["search_center"]


@pytest.mark.asyncio
async def test_classify_intent_tc11_general_place_knowledge() -> None:
    provider = FakeLLMProvider()

    result = await provider.classify_intent(
        "경복궁은 언제 지어졌어?", has_previous_recommendation=False, shown_place_count=0
    )

    assert result.data.intent is Intent.GENERAL


@pytest.mark.asyncio
async def test_classify_intent_tc12_out_of_scope_harmful() -> None:
    provider = FakeLLMProvider()

    result = await provider.classify_intent(
        "이 씨발 놈아", has_previous_recommendation=False, shown_place_count=0
    )

    assert result.data.intent is Intent.OUT_OF_SCOPE
    assert result.data.out_of_scope_category is OutOfScopeCategory.HARMFUL


@pytest.mark.asyncio
async def test_classify_intent_tc13_out_of_scope_unrelated() -> None:
    provider = FakeLLMProvider()

    result = await provider.classify_intent(
        "주식 추천해줘", has_previous_recommendation=False, shown_place_count=0
    )

    assert result.data.intent is Intent.OUT_OF_SCOPE
    assert result.data.out_of_scope_category is OutOfScopeCategory.UNRELATED
