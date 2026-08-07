"""FakeLLMProvider 회귀 테스트.

docs/design/test-cases.md의 대표 케이스(TC-01~04 RECOMMEND, TC-07~09 MODIFY, TC-11 GENERAL,
TC-12/13 OUT_OF_SCOPE)와 llm-output-schema.md §7의 needs_clarification 예시를 재현한다.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.providers.gemini_prompts import build_modify_extraction_instruction
from app.providers.stub import FakeLLMProvider
from app.schedule.schemas import SchedulePlanningRequest
from app.schemas import (
    ConcentrationIntent,
    Environment,
    Intent,
    ModifyType,
    OutOfScopeCategory,
    OutputStatus,
    PlaceTag,
    PlaceType,
    RecommendationItem,
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


@pytest.mark.parametrize(
    "user_input",
    [
        "오늘 오후 종로 일정 짜줘",
        "반나절 코스 만들어줘",
        "경복궁, 인사동 가고 싶은데 어디부터 갈까?",
    ],
)
@pytest.mark.parametrize("has_previous_recommendation", [False, True])
@pytest.mark.asyncio
async def test_classify_intent_schedule_regardless_of_recommendation_history(
    user_input: str, has_previous_recommendation: bool
) -> None:
    """명시적인 일정·코스·방문 순서는 이전 추천 이력과 무관하게 SCHEDULE다."""
    provider = FakeLLMProvider()

    result = await provider.classify_intent(
        user_input,
        has_previous_recommendation=has_previous_recommendation,
        shown_place_count=5 if has_previous_recommendation else 0,
    )

    assert result.data.intent is Intent.SCHEDULE


@pytest.mark.asyncio
async def test_classify_intent_plain_recommendation_is_not_schedule() -> None:
    provider = FakeLLMProvider()

    result = await provider.classify_intent(
        "오늘 갈 만한 곳 추천해줘", has_previous_recommendation=False, shown_place_count=0
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


@pytest.mark.parametrize(
    "user_input",
    [
        "광화문 근처에서",
        "광화문 근처",
        "광화문 근처 어때?",
        "종로3가역 근처에서",
        "북촌 근처에서",
        "광화문으로",
        "광화문에서",
    ],
)
@pytest.mark.asyncio
async def test_classify_intent_location_only_with_history_is_modify(user_input: str) -> None:
    """TP-67: 이전 추천 뒤 위치만 제시하면 새 추천이 아니라 조건 변경이다."""
    provider = FakeLLMProvider()

    result = await provider.classify_intent(
        user_input, has_previous_recommendation=True, shown_place_count=5
    )

    assert result.data.intent is Intent.MODIFY


@pytest.mark.parametrize(
    "user_input",
    [
        "광화문 근처에서",
        "광화문 근처",
        "광화문 근처 어때?",
        "종로3가역 근처에서",
        "북촌 근처에서",
    ],
)
@pytest.mark.asyncio
async def test_classify_intent_location_only_without_history_is_recommend(user_input: str) -> None:
    provider = FakeLLMProvider()

    result = await provider.classify_intent(
        user_input, has_previous_recommendation=False, shown_place_count=0
    )

    assert result.data.intent is Intent.RECOMMEND


@pytest.mark.parametrize("user_input", ["광화문", "경복궁"])
@pytest.mark.parametrize("has_previous_recommendation", [True, False])
@pytest.mark.asyncio
async def test_classify_intent_bare_place_name_is_info_regardless_of_history(
    user_input: str, has_previous_recommendation: bool
) -> None:
    """지명 단독은 이전 추천이 있어도 위치 변경이 아니라 정보 조회다.

    추천을 받은 뒤 "경복궁" 한 마디로 그 장소를 묻는 흐름을 위치 변경이 가리지 않도록,
    위치 변경 판정은 근처/주변이나 조사·어미가 붙은 경우로 한정한다.
    """
    provider = FakeLLMProvider()

    result = await provider.classify_intent(
        user_input,
        has_previous_recommendation=has_previous_recommendation,
        shown_place_count=5 if has_previous_recommendation else 0,
    )

    assert result.data.intent is Intent.INFO


@pytest.mark.parametrize(
    "user_input",
    [
        "경복궁 근처 카페 추천해줘",
        "비 오는데 경복궁 근처 카페 추천해줘",
        "북촌 주변 박물관 보여줘",
    ],
)
@pytest.mark.asyncio
async def test_classify_intent_location_with_other_conditions_is_modify(user_input: str) -> None:
    """D-053: 지명+근처에 다른 조건이 붙어도 이전 추천이 있으면 조건 변경이다.

    실 Gemini(gemini-2.5-flash, 프롬프트 1.0.2)가 "경복궁 근처 카페 추천해줘"를
    MODIFY 5/5로 분류하는 것과 Fake를 맞춘 것이다 — 잔여 조건("카페") 때문에
    RECOMMEND fallback으로 떨어지던 차이를 없앤다.
    """
    provider = FakeLLMProvider()

    result = await provider.classify_intent(
        user_input, has_previous_recommendation=True, shown_place_count=5
    )

    assert result.data.intent is Intent.MODIFY


@pytest.mark.parametrize(
    ("user_input", "expected"),
    [
        ("경복궁 근처 카페 추천해줘", Intent.RECOMMEND),
        ("경복궁 근처에 화장실 있어?", Intent.INFO),
        ("경복궁 근처 동네는 어때?", Intent.GENERAL),
    ],
)
@pytest.mark.asyncio
async def test_classify_intent_location_with_other_conditions_boundaries(
    user_input: str, expected: Intent
) -> None:
    """반대 방향 회귀: 이력이 없으면 RECOMMEND고, 정보/일반 질문은 가려지지 않는다."""
    provider = FakeLLMProvider()

    result = await provider.classify_intent(
        user_input,
        has_previous_recommendation=expected is not Intent.RECOMMEND,
        shown_place_count=5 if expected is not Intent.RECOMMEND else 0,
    )

    assert result.data.intent is expected


@pytest.mark.asyncio
async def test_extract_modify_conditions_rain_avoids_and_moves_indoor() -> None:
    """MODIFY 경로의 날씨 처리는 extract_recommend_conditions와 같은 결이다."""
    provider = FakeLLMProvider()
    current = UserConditions(search_center="북촌")

    output = (
        await provider.extract_modify_conditions("비 오는데 경복궁 근처 카페 추천해줘", current)
    ).data

    changes = output.modify.condition_changes
    assert changes.weather is StatedWeather.RAIN
    assert changes.weather_intent is WeatherIntent.AVOID
    assert changes.environment is Environment.INDOOR
    assert changes.search_center == "경복궁"
    assert set(output.modify.changed_fields) == {
        "weather",
        "weather_intent",
        "environment",
        "search_center",
    }


@pytest.mark.asyncio
async def test_extract_modify_conditions_location_only_changes_search_center() -> None:
    provider = FakeLLMProvider()
    current = UserConditions(
        search_center="경복궁",
        weather=StatedWeather.RAIN,
        weather_intent=WeatherIntent.AVOID,
        environment=Environment.INDOOR,
    )

    output = (await provider.extract_modify_conditions("광화문 근처에서", current)).data

    assert output.modify.modify_type is ModifyType.CHANGE_CONDITION
    assert output.modify.condition_changes.search_center == "광화문"
    assert output.modify.changed_fields == ["search_center"]


@pytest.mark.asyncio
async def test_extract_modify_conditions_quiet_place_avoids_concentration() -> None:
    """MODIFY에서도 '조용한'은 혼잡도 회피(AVOID)로 추출해야 한다.

    RECOMMEND 프롬프트에만 있던 concentration_intent 규칙이 MODIFY에서 빠져
    실제 Gemini가 SEEK를 반환했던 회귀를 막는다.
    """
    provider = FakeLLMProvider()
    current = UserConditions(
        search_center="창경궁",
        concentration_intent=ConcentrationIntent.IGNORE,
    )

    output = (await provider.extract_modify_conditions("좀 조용한 공원 가고싶어", current)).data

    assert output.modify.condition_changes.concentration_intent is ConcentrationIntent.AVOID
    assert output.modify.changed_fields == ["concentration_intent"]


def test_modify_instruction_includes_concentration_avoid_rule() -> None:
    """Real Gemini MODIFY 프롬프트에도 조용한 곳→AVOID 규칙을 반드시 넣는다."""
    instruction = build_modify_extraction_instruction(UserConditions(search_center="창경궁"))

    assert "concentration_intent 판별:" in instruction
    assert '"조용한 공원 추천해줘"' in instruction
    assert "concentration_intent/transport" in instruction


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


def _fake_recommendation_item(place_id: str, name: str) -> RecommendationItem:
    return RecommendationItem(
        place_id=place_id,
        name=name,
        category="attraction",
        distance_km=0.3,
        remaining_minutes=120,
        environment_type="indoor",
        recommendation_reason="테스트용 고정 후보입니다.",
        explanations=[],
        warnings=[],
        score=0.5,
        feature_scores={},
        weights_used={},
    )


@pytest.mark.asyncio
async def test_generate_schedule_plan_selects_up_to_three_candidates() -> None:
    """SCHEDULE-04: 실제 Gemini 없이 candidates 앞쪽 최대 3개로 고정 일정을 만든다."""
    provider = FakeLLMProvider()
    candidates = [
        _fake_recommendation_item(f"place-{i}", f"장소 {i}") for i in range(5)
    ]
    request = SchedulePlanningRequest(
        candidates=candidates,
        conditions=UserConditions(),
        visit_datetime=datetime(2026, 8, 7, 15, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        pairwise_distances_km={},
    )

    result = (await provider.generate_schedule_plan(request)).data

    assert len(result.items) == 3
    assert [item.place_id for item in result.items] == ["place-0", "place-1", "place-2"]
    assert result.items[-1].travel_to_next_min is None
    assert all(
        item.travel_to_next_min is not None for item in result.items[:-1]
    )
    assert result.total_duration_min > 0
    assert result.route_summary
