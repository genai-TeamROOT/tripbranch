"""FakeLLMProvider 회귀 테스트.

docs/design/test-cases.md의 대표 케이스(TC-01~04 RECOMMEND, TC-07~09 MODIFY, TC-11 GENERAL,
TC-12/13 OUT_OF_SCOPE)와 llm-output-schema.md §7의 needs_clarification 예시를 재현한다.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.providers.gemini_prompts import (
    build_intent_classification_instruction,
    build_modify_extraction_instruction,
    build_schedule_planning_instruction,
)
from app.providers.stub import FakeLLMProvider
from app.schedule.schemas import SchedulePlanningRequest
from app.schemas import (
    CompareCriteria,
    ComparisonItem,
    ComparisonResult,
    ConcentrationIntent,
    Environment,
    GeneralTopic,
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


@pytest.mark.parametrize(
    "user_input",
    ["광화문으로 알려줘", "광화문으로", "종로 대신 광화문", "광화문 근처로"],
)
@pytest.mark.asyncio
async def test_classify_intent_schedule_clarification_answer_stays_schedule(
    user_input: str,
) -> None:
    """D-059: 직전 SCHEDULE 되묻기(장소 모호)에 지명만 답하면 MODIFY가 아니라 SCHEDULE을
    유지해야 한다 — 바꿀 이전 추천 결과 자체가 없다."""
    provider = FakeLLMProvider()

    result = await provider.classify_intent(
        user_input,
        has_previous_recommendation=False,
        shown_place_count=0,
        pending_clarification="location_ambiguous",
        last_intent="SCHEDULE",
    )

    assert result.data.intent is Intent.SCHEDULE


@pytest.mark.asyncio
async def test_classify_intent_schedule_clarification_explicit_restart_not_forced() -> None:
    """되묻기 이어가기 규칙이 명시적 재시작 표현까지 SCHEDULE로 강제하면 안 된다 — 이
    분기를 건너뛰고 나머지 규칙(여기서는 RECOMMEND)이 그대로 판정한다."""
    provider = FakeLLMProvider()

    without_context = await provider.classify_intent(
        "처음부터 다시 짜줘", has_previous_recommendation=False, shown_place_count=0
    )
    with_schedule_clarification = await provider.classify_intent(
        "처음부터 다시 짜줘",
        has_previous_recommendation=False,
        shown_place_count=0,
        pending_clarification="location_ambiguous",
        last_intent="SCHEDULE",
    )

    assert with_schedule_clarification.data.intent is without_context.data.intent


@pytest.mark.asyncio
async def test_classify_intent_location_modify_unaffected_without_schedule_clarification() -> (
    None
):
    """기존 회귀 확인: SCHEDULE 되묻기 컨텍스트가 없으면 "지명+근처/주변" 답변은 그대로
    MODIFY다(D-053)."""
    provider = FakeLLMProvider()

    result = await provider.classify_intent(
        "광화문 근처로",
        has_previous_recommendation=True,
        shown_place_count=5,
    )

    assert result.data.intent is Intent.MODIFY


@pytest.mark.asyncio
async def test_classify_intent_schedule_clarification_wins_over_modify_pattern() -> None:
    """has_previous_recommendation=True라 "지명+근처" MODIFY 조건도 동시에 충족되는
    상황에서, SCHEDULE 되묻기 이어가기 규칙이 우선해야 한다(실제 버그 재현 조건과 동일)."""
    provider = FakeLLMProvider()

    result = await provider.classify_intent(
        "광화문 근처로",
        has_previous_recommendation=True,
        shown_place_count=5,
        pending_clarification="location_ambiguous",
        last_intent="SCHEDULE",
    )

    assert result.data.intent is Intent.SCHEDULE


@pytest.mark.parametrize("user_input", ["넌 누구야?", "이름이 뭐야?", "뭘 할 수 있어?"])
@pytest.mark.asyncio
async def test_classify_intent_service_identity_question_is_general(user_input: str) -> None:
    provider = FakeLLMProvider()

    result = await provider.classify_intent(
        user_input, has_previous_recommendation=False, shown_place_count=0
    )

    assert result.data.intent is Intent.GENERAL


@pytest.mark.asyncio
async def test_extract_general_request_service_identity_topic() -> None:
    provider = FakeLLMProvider()

    output = (await provider.extract_general_request("넌 누구야?")).data

    assert output.intent is Intent.GENERAL
    assert output.general is not None
    assert output.general.topic is GeneralTopic.SERVICE_IDENTITY


@pytest.mark.asyncio
async def test_generate_general_answer_service_identity_mentions_trivy() -> None:
    provider = FakeLLMProvider()

    result = await provider.generate_general_answer(
        GeneralTopic.SERVICE_IDENTITY, "넌 누구야?"
    )

    assert "트리비" in result.data
    assert "국내 여행" in result.data


@pytest.mark.asyncio
async def test_generate_compare_summary_uses_three_to_six_fact_only_lines() -> None:
    provider = FakeLLMProvider()
    comparison = ComparisonResult(
        criteria=CompareCriteria.DISTANCE,
        items=[
            ComparisonItem(
                place_id="p1",
                place_name="경복궁",
                rank=1,
                distance_km=0.2,
                remaining_minutes=120,
                environment_type="outdoor",
            ),
            ComparisonItem(
                place_id="p2",
                place_name="국립민속박물관",
                rank=2,
                distance_km=0.5,
                remaining_minutes=180,
                environment_type="indoor",
            ),
        ],
    )

    result = await provider.generate_compare_summary(comparison)

    assert 3 <= len(result.data.splitlines()) <= 6
    assert "경복궁" in result.data
    # 0.2km를 3.6km/h로 환산해 올림한 값이다(추천 카드와 같은 표기 규칙).
    assert "도보 약 4분" in result.data
    assert "점수" not in result.data


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


@pytest.mark.parametrize(
    ("has_previous_recommendation", "expected"),
    [(False, Intent.RECOMMEND), (True, Intent.MODIFY)],
)
@pytest.mark.parametrize("user_input", ["광화문", "경복궁", "경복궁이요"])
@pytest.mark.asyncio
async def test_classify_intent_bare_place_name_means_nearby_recommendation(
    user_input: str, has_previous_recommendation: bool, expected: Intent
) -> None:
    """단순 지명은 정보 질문으로 가정하지 않고 해당 장소 근처 추천으로 처리한다."""
    provider = FakeLLMProvider()

    result = await provider.classify_intent(
        user_input,
        has_previous_recommendation=has_previous_recommendation,
        shown_place_count=5 if has_previous_recommendation else 0,
    )

    assert result.data.intent is expected


@pytest.mark.parametrize("user_input", ["광화문", "경복궁", "경복궁이요"])
@pytest.mark.asyncio
async def test_classify_intent_bare_place_after_location_clarification_is_modify(
    user_input: str,
) -> None:
    """위치를 물은 직후의 단순 지명은 INFO가 아니라 기존 요청의 위치 답변이다."""
    provider = FakeLLMProvider()

    result = await provider.classify_intent(
        user_input,
        has_previous_recommendation=False,
        shown_place_count=0,
        pending_clarification="location_required",
        last_intent="RECOMMEND",
    )

    assert result.data.intent is Intent.MODIFY


@pytest.mark.asyncio
async def test_classify_intent_bare_place_with_question_stays_info_after_clarification() -> None:
    """위치 되묻기 상태여도 정보 질문까지 MODIFY로 가리면 안 된다."""
    provider = FakeLLMProvider()

    result = await provider.classify_intent(
        "경복궁 오늘 열어?",
        has_previous_recommendation=False,
        shown_place_count=0,
        pending_clarification="location_required",
        last_intent="RECOMMEND",
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
async def test_classify_intent_pure_recommend_after_schedule_is_recommend() -> None:
    """2026-08-12 실사용 재현: 직전 턴이 SCHEDULE로 정상 완료된 상태에서 "지명+근처"에
    조건만 붙인 순수 추천 요청은 MODIFY가 아니라 RECOMMEND다.

    D-053(test_classify_intent_location_with_other_conditions_is_modify)과 대조된다 —
    last_intent가 SCHEDULE이 아니면(일반 RECOMMEND 맥락) 그 테스트처럼 여전히 MODIFY다.
    이 예외를 안 두면 agent_runtime.py의 SCHEDULE-06 재조정 감지가 MODIFY를 SCHEDULE로
    다시 라벨링해서, 단순 추천 요청인데 일정 전체가 재편성돼 버린다.
    """
    provider = FakeLLMProvider()

    result = await provider.classify_intent(
        "경복궁 근처 카페 추천해줘",
        has_previous_recommendation=True,
        shown_place_count=2,
        pending_clarification=None,
        last_intent="SCHEDULE",
    )

    assert result.data.intent is Intent.RECOMMEND


@pytest.mark.asyncio
async def test_classify_intent_explicit_adjustment_after_schedule_stays_modify() -> None:
    """"말고"/"바꿔줘" 같은 명시적 조정 표현이 있으면 SCHEDULE 직후여도 예외를 적용하지
    않는다 — 그건 순수 추천이 아니라 진짜 일정 재조정 요청이라 MODIFY(→ SCHEDULE-06이
    SCHEDULE로 재라벨링)로 그대로 흘러가야 한다."""
    provider = FakeLLMProvider()

    result = await provider.classify_intent(
        "경복궁 근처 카페 말고 맛집",
        has_previous_recommendation=True,
        shown_place_count=2,
        pending_clarification=None,
        last_intent="SCHEDULE",
    )

    assert result.data.intent is Intent.MODIFY


@pytest.mark.asyncio
async def test_classify_intent_explicit_schedule_request_after_schedule_stays_schedule() -> None:
    """발화 자체에 일정/코스 표현이 있으면 직전 턴이 SCHEDULE여도 RECOMMEND 예외보다
    SCHEDULE 판정이 우선한다(판별 우선순위 2번)."""
    provider = FakeLLMProvider()

    result = await provider.classify_intent(
        "경복궁 근처 카페로 일정 짜줘",
        has_previous_recommendation=True,
        shown_place_count=2,
        pending_clarification=None,
        last_intent="SCHEDULE",
    )

    assert result.data.intent is Intent.SCHEDULE


@pytest.mark.asyncio
async def test_extract_modify_conditions_rain_avoids_and_moves_indoor() -> None:
    """MODIFY의 '비와서 실내'는 날씨 ENJOY가 아니라 명확한 회피다."""
    provider = FakeLLMProvider()
    current = UserConditions(search_center="북촌")

    output = (
        await provider.extract_modify_conditions("비와서 실내로 바꿔줘", current)
    ).data

    changes = output.modify.condition_changes
    assert changes.weather is StatedWeather.RAIN
    assert changes.weather_intent is WeatherIntent.AVOID
    assert changes.environment is Environment.INDOOR
    assert set(output.modify.changed_fields) == {
        "weather",
        "weather_intent",
        "environment",
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
async def test_extract_modify_conditions_bare_place_changes_search_center() -> None:
    """이전 추천 뒤 단순 지명도 해당 장소 근처 추천으로 이어진다."""
    provider = FakeLLMProvider()
    current = UserConditions(search_center="경복궁", place_tags=[PlaceTag.CAFE])

    output = (await provider.extract_modify_conditions("광화문", current)).data

    assert output.modify.condition_changes.search_center == "광화문"
    assert output.modify.changed_fields == ["search_center"]


@pytest.mark.asyncio
async def test_extract_recommend_conditions_bare_place_sets_search_center() -> None:
    """첫 턴의 단순 지명도 주변 추천의 검색 중심으로 추출한다."""
    provider = FakeLLMProvider()

    output = (await provider.extract_recommend_conditions("경복궁")).data

    assert output.recommend.conditions.search_center == "경복궁"


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
    assert output.modify.condition_changes.place_types == [PlaceType.ATTRACTION]
    assert output.modify.condition_changes.place_tags == [PlaceTag.PARK]
    assert output.modify.changed_fields == [
        "place_types",
        "place_tags",
        "concentration_intent",
    ]


@pytest.mark.asyncio
async def test_extract_modify_conditions_category_request_replaces_previous_category() -> None:
    """'공원도 추천'의 도는 추가가 아니라 새 추천 유형 강조로 본다."""

    provider = FakeLLMProvider()
    current = UserConditions(place_types=[PlaceType.RESTAURANT], place_tags=[PlaceTag.CAFE])

    output = (await provider.extract_modify_conditions("공원도 추천해줘", current)).data

    assert output.modify.condition_changes.place_types == [PlaceType.ATTRACTION]
    assert output.modify.condition_changes.place_tags == [PlaceTag.PARK]
    assert output.modify.changed_fields == ["place_types", "place_tags"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_input", "expected_types", "expected_tags"),
    [
        (
            "공원도 포함해줘",
            [PlaceType.RESTAURANT, PlaceType.ATTRACTION],
            [PlaceTag.CAFE, PlaceTag.PARK],
        ),
        (
            "카페와 공원 같이 추천해줘",
            [PlaceType.RESTAURANT, PlaceType.ATTRACTION],
            [PlaceTag.CAFE, PlaceTag.PARK],
        ),
        (
            "카페나 공원 추천해줘",
            [PlaceType.RESTAURANT, PlaceType.ATTRACTION],
            [PlaceTag.CAFE, PlaceTag.PARK],
        ),
    ],
)
async def test_extract_modify_conditions_explicit_category_combination_keeps_both(
    user_input: str,
    expected_types: list[PlaceType],
    expected_tags: list[PlaceTag],
) -> None:
    """명시적으로 함께·포함·선택지를 말할 때만 교차 유형을 함께 검색한다."""

    provider = FakeLLMProvider()
    current = UserConditions(place_types=[PlaceType.RESTAURANT], place_tags=[PlaceTag.CAFE])

    output = (await provider.extract_modify_conditions(user_input, current)).data

    assert output.modify.condition_changes.place_types == expected_types
    assert output.modify.condition_changes.place_tags == expected_tags
    assert output.modify.changed_fields == ["place_types", "place_tags"]


def test_modify_instruction_includes_weather_and_concentration_avoid_rules() -> None:
    """Real Gemini MODIFY 프롬프트에도 날씨·혼잡도 회피 규칙을 넣는다."""
    instruction = build_modify_extraction_instruction(UserConditions(search_center="창경궁"))

    assert "비와서 실내로 바꿔줘" in instruction
    assert "반드시 AVOID" in instruction
    assert "concentration_intent 판별:" in instruction
    assert '"조용한 공원 추천해줘"' in instruction
    assert "concentration_intent/transport" in instruction


def test_modify_instruction_distinguishes_category_replacement_and_explicit_addition() -> None:
    instruction = build_modify_extraction_instruction(
        UserConditions(place_types=[PlaceType.RESTAURANT], place_tags=[PlaceTag.CAFE])
    )

    assert '"공원도 추천해줘"' in instruction
    assert '"공원도 포함해줘"' in instruction
    assert '"카페와 공원 같이 추천해줘"' in instruction
    assert 'changed_fields에도 둘 다' in instruction


def test_modify_instruction_marks_location_clarification_answer() -> None:
    instruction = build_modify_extraction_instruction(
        UserConditions(place_tags=[PlaceTag.CAFE]),
        pending_clarification="location_required",
    )

    assert "직전 위치 되묻기 답변 여부: 예" in instruction
    assert 'changed_fields에는 "search_center"만' in instruction


def test_intent_instruction_includes_schedule_clarification_rule() -> None:
    """D-059: SCHEDULE 되묻기 이어가기 규칙과 컨텍스트 플래그가 프롬프트에 반영된다."""
    instruction = build_intent_classification_instruction(
        has_previous_recommendation=False,
        shown_place_count=0,
        pending_clarification="location_ambiguous",
        last_intent="SCHEDULE",
    )

    assert "SCHEDULE 되묻기" in instruction
    assert "직전 턴이 되묻기로 끝났는지: 예" in instruction


def test_intent_instruction_includes_recommend_location_clarification_rule() -> None:
    instruction = build_intent_classification_instruction(
        has_previous_recommendation=False,
        shown_place_count=0,
        pending_clarification="location_required",
        last_intent="RECOMMEND",
    )

    assert "단순 지명 답변" in instruction
    assert "직전 RECOMMEND/MODIFY 요청의 위치 되묻기" in instruction


def test_intent_instruction_hides_clarification_flag_when_absent() -> None:
    instruction = build_intent_classification_instruction(
        has_previous_recommendation=False, shown_place_count=0
    )

    assert "직전 턴이 되묻기로 끝났는지: 아니오" in instruction


def test_intent_instruction_exposes_last_intent() -> None:
    """2026-08-12 후속: last_intent가 컨텍스트 블록에 직접 노출돼야 LLM이 "직전이
    SCHEDULE였다"를 알고 SCHEDULE 예외 규칙을 적용할 수 있다 — "이전 추천 이력
    있음"만으로는 SCHEDULE과 RECOMMEND/MODIFY 이력을 구분할 수 없었다."""
    with_schedule = build_intent_classification_instruction(
        has_previous_recommendation=True, shown_place_count=2, last_intent="SCHEDULE"
    )
    without_last_intent = build_intent_classification_instruction(
        has_previous_recommendation=False, shown_place_count=0
    )

    assert "직전 턴 Intent: SCHEDULE" in with_schedule
    assert "직전 턴 Intent: 없음" in without_last_intent


def test_intent_instruction_includes_pure_recommend_after_schedule_exception() -> None:
    """SCHEDULE 직후 순수 추천 요청을 MODIFY로 잘못 묶지 않도록 안내하는 예외 규칙과
    경계 사례가 프롬프트에 들어있는지 확인한다."""
    instruction = build_intent_classification_instruction(
        has_previous_recommendation=True, shown_place_count=2, last_intent="SCHEDULE"
    )

    assert "직전 턴 Intent가 SCHEDULE이고" in instruction
    assert "경복궁 근처 카페 추천해줘" in instruction
    assert "카페들을 추천해서 일정 다시 짜줘" in instruction


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
    assert output.modify.target_indices == []


@pytest.mark.asyncio
async def test_extract_modify_conditions_reject_specific_single_target() -> None:
    """SCHEDULE-09: 순번 하나 + 거절 신호가 함께 있으면 REJECT_SPECIFIC."""
    provider = FakeLLMProvider()

    output = (
        await provider.extract_modify_conditions(
            "두 번째는 별로야",
            UserConditions(search_center="경복궁"),
            shown_place_count=3,
        )
    ).data

    assert output.status is OutputStatus.COMPLETE
    assert output.modify.modify_type is ModifyType.REJECT_SPECIFIC
    assert output.modify.target_indices == [2]
    assert output.modify.condition_changes is None


@pytest.mark.asyncio
async def test_extract_modify_conditions_reject_specific_multiple_targets() -> None:
    """SCHEDULE-09: 순번을 여러 개 언급하면 모두 담는다."""
    provider = FakeLLMProvider()

    output = (
        await provider.extract_modify_conditions(
            "두 번째랑 세 번째 다 별로야",
            UserConditions(search_center="경복궁"),
            shown_place_count=3,
        )
    ).data

    assert output.modify.modify_type is ModifyType.REJECT_SPECIFIC
    assert output.modify.target_indices == [2, 3]


@pytest.mark.asyncio
async def test_extract_modify_conditions_reject_specific_out_of_range_asks_clarification() -> None:
    """SCHEDULE-09: 노출된 항목 수를 벗어나는 순번이면 needs_clarification.

    COMPARE의 shown_place_count 범위 검증과 동일한 패턴이다.
    """
    provider = FakeLLMProvider()

    output = (
        await provider.extract_modify_conditions(
            "세 번째는 별로야",
            UserConditions(search_center="경복궁"),
            shown_place_count=2,
        )
    ).data

    assert output.status is OutputStatus.NEEDS_CLARIFICATION
    assert output.modify is None
    assert output.clarification is not None
    assert "2개" in output.clarification.message


@pytest.mark.asyncio
async def test_extract_modify_conditions_exclusion_pattern_keeps_mentioned_index() -> None:
    """SCHEDULE-09 후속: "N번째 말고는 다 ~"는 언급된 순번을 남기고 나머지
    전부를 거부한다 — target_indices는 언급된 순번의 여집합이다(직접 지목과
    정반대 방향)."""
    provider = FakeLLMProvider()

    output = (
        await provider.extract_modify_conditions(
            "두 번째 말고는 다 마음에 안 들어",
            UserConditions(search_center="경복궁"),
            shown_place_count=3,
        )
    ).data

    assert output.status is OutputStatus.COMPLETE
    assert output.modify.modify_type is ModifyType.REJECT_SPECIFIC
    assert output.modify.target_indices == [1, 3]
    assert output.modify.condition_changes is None


@pytest.mark.asyncio
async def test_extract_modify_conditions_exclusion_pattern_multiple_kept() -> None:
    """SCHEDULE-09 후속: 남길 순번을 여러 개 언급해도 나머지 전부가 여집합이 된다."""
    provider = FakeLLMProvider()

    output = (
        await provider.extract_modify_conditions(
            "두 번째랑 세 번째 말고는 다 별로야",
            UserConditions(search_center="경복궁"),
            shown_place_count=5,
        )
    ).data

    assert output.modify.modify_type is ModifyType.REJECT_SPECIFIC
    assert output.modify.target_indices == [1, 4, 5]


@pytest.mark.asyncio
async def test_extract_modify_conditions_exclusion_pattern_out_of_range() -> None:
    """SCHEDULE-09 후속: 남기겠다는 순번 자체가 노출 범위를 벗어나면 되묻는다."""
    provider = FakeLLMProvider()

    output = (
        await provider.extract_modify_conditions(
            "세 번째 말고는 다 별로야",
            UserConditions(search_center="경복궁"),
            shown_place_count=2,
        )
    ).data

    assert output.status is OutputStatus.NEEDS_CLARIFICATION
    assert output.modify is None
    assert output.clarification is not None
    assert "2개" in output.clarification.message


@pytest.mark.asyncio
async def test_extract_modify_conditions_name_reference_direct() -> None:
    """SCHEDULE-09 후속(이름 지목): 순번 대신 노출된 항목 이름을 직접 언급해도
    같은 순번으로 매칭돼야 한다."""
    provider = FakeLLMProvider()

    output = (
        await provider.extract_modify_conditions(
            "두가헌 레스토랑은 빼줘",
            UserConditions(search_center="경복궁"),
            shown_place_count=3,
            shown_place_names=["경복궁", "두가헌 레스토랑", "갤러리조선"],
        )
    ).data

    assert output.status is OutputStatus.COMPLETE
    assert output.modify.modify_type is ModifyType.REJECT_SPECIFIC
    assert output.modify.target_indices == [2]


@pytest.mark.asyncio
async def test_extract_modify_conditions_name_reference_exclusion() -> None:
    """SCHEDULE-09 후속(이름 지목): "N 말고는 다 별로야"도 이름으로 지목할 수
    있다 — 여집합 규칙과 결합된다."""
    provider = FakeLLMProvider()

    output = (
        await provider.extract_modify_conditions(
            "두가헌 레스토랑 말고는 다 별로야",
            UserConditions(search_center="경복궁"),
            shown_place_count=3,
            shown_place_names=["경복궁", "두가헌 레스토랑", "갤러리조선"],
        )
    ).data

    assert output.modify.modify_type is ModifyType.REJECT_SPECIFIC
    assert output.modify.target_indices == [1, 3]


@pytest.mark.asyncio
async def test_extract_modify_conditions_name_and_ordinal_combined() -> None:
    """SCHEDULE-09 후속(이름 지목): 순번과 이름을 섞어 언급해도 모두 담긴다."""
    provider = FakeLLMProvider()

    output = (
        await provider.extract_modify_conditions(
            "첫 번째랑 갤러리조선 빼줘",
            UserConditions(search_center="경복궁"),
            shown_place_count=3,
            shown_place_names=["경복궁", "두가헌 레스토랑", "갤러리조선"],
        )
    ).data

    assert output.modify.modify_type is ModifyType.REJECT_SPECIFIC
    assert output.modify.target_indices == [1, 3]


@pytest.mark.asyncio
async def test_extract_modify_conditions_missing_names_falls_back_to_ordinal_only() -> None:
    """SCHEDULE-09 후속(이름 지목): shown_place_names가 없으면(과거 세션 등)
    기존 순번 기반 동작만 그대로 유지된다 — 새 기능이 하위 호환을 깨지 않는다."""
    provider = FakeLLMProvider()

    output = (
        await provider.extract_modify_conditions(
            "두 번째는 별로야",
            UserConditions(search_center="경복궁"),
            shown_place_count=3,
        )
    ).data

    assert output.modify.modify_type is ModifyType.REJECT_SPECIFIC
    assert output.modify.target_indices == [2]


def test_modify_instruction_includes_shown_place_names_when_provided() -> None:
    """SCHEDULE-09 후속(이름 지목): 이름 목록이 있으면 프롬프트에 번호 매긴
    목록으로 포함된다."""
    instruction = build_modify_extraction_instruction(
        UserConditions(search_center="경복궁"),
        shown_place_count=3,
        shown_place_names=["경복궁", "두가헌 레스토랑", "갤러리조선"],
    )

    assert "1. 경복궁" in instruction
    assert "2. 두가헌 레스토랑" in instruction
    assert "3. 갤러리조선" in instruction


def test_modify_instruction_omits_shown_place_names_block_when_absent() -> None:
    """이름이 없으면 목록 블록 자체가 생략된다 — Gemini가 없는 이름으로
    엉뚱하게 매칭 시도하는 걸 막는다."""
    instruction = build_modify_extraction_instruction(
        UserConditions(search_center="경복궁"), shown_place_count=3
    )

    assert "노출된 항목 목록 (순번. 이름)" not in instruction


@pytest.mark.asyncio
async def test_classify_intent_name_reference_routes_to_modify() -> None:
    """SCHEDULE-09 후속(이름 지목): 순번 없이 이름 + 거절 신호만 있어도
    classify_intent()가 MODIFY로 분류해야 extract_modify_conditions()까지
    도달한다."""
    provider = FakeLLMProvider()

    result = (
        await provider.classify_intent(
            "두가헌 레스토랑은 빼줘",
            has_previous_recommendation=True,
            shown_place_count=3,
            shown_place_names=["경복궁", "두가헌 레스토랑", "갤러리조선"],
        )
    ).data

    assert result.intent is Intent.MODIFY


@pytest.mark.asyncio
async def test_extract_modify_conditions_ordinal_without_reject_cue_stays_reject_all() -> None:
    """SCHEDULE-09: 순번 언급이 있어도 거절 신호가 없으면 REJECT_SPECIFIC로 오분류하지 않는다."""
    provider = FakeLLMProvider()

    output = (
        await provider.extract_modify_conditions(
            "다른 곳 보여줘", UserConditions(search_center="경복궁"), shown_place_count=3
        )
    ).data

    assert output.modify.modify_type is ModifyType.REJECT_ALL
    assert output.modify.target_indices == []


def test_modify_instruction_includes_reject_specific_rule_and_shown_count() -> None:
    """SCHEDULE-09: Real Gemini MODIFY 프롬프트에도 REJECT_SPECIFIC/target_indices
    판별 규칙과 노출 항목 수가 반드시 들어간다."""
    instruction = build_modify_extraction_instruction(
        UserConditions(search_center="창경궁"), shown_place_count=3
    )

    assert "REJECT_SPECIFIC" in instruction
    assert "target_indices" in instruction
    assert "현재 노출된 일정/추천 항목 수: 3" in instruction


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


class TestBuildSchedulePlanningInstructionDynamicCount:
    """SCHEDULE-10: 활동 가능 시간(time_available_min)에 따라 프롬프트의 목표
    개수 지시가 달라진다 — 짧은 시간에도 3~5개를 고정 지시하던 문제 해소."""

    def test_시간_제한이_없으면_기존_3에서_5개_문구를_쓴다(self):
        instruction = build_schedule_planning_instruction(time_available_min=None)
        assert "3~5개" in instruction
        assert "3개 이상 5개 이하" in instruction
        assert "3~4시간 내외로 구성" in instruction

    def test_두시간_미만이면_한두개_문구를_쓴다(self):
        instruction = build_schedule_planning_instruction(time_available_min=90)
        assert "1~2개" in instruction
        assert "1개 이상 2개 이하" in instruction
        assert "3~5개" not in instruction
        assert "활동 가능 시간이 90분" in instruction

    def test_두시간_이상_세시간반_미만이면_두네개_문구를_쓴다(self):
        instruction = build_schedule_planning_instruction(time_available_min=180)
        assert "2~4개" in instruction
        assert "2개 이상 4개 이하" in instruction

    def test_세시간반_이상이면_다시_3에서_5개_문구를_쓴다(self):
        instruction = build_schedule_planning_instruction(time_available_min=240)
        assert "3~5개" in instruction
        assert "활동 가능 시간이 240분" in instruction

    def test_짧은_시간에는_체류시간_비현실적_단축_경고_문구가_있다(self):
        instruction = build_schedule_planning_instruction(time_available_min=90)
        assert "비현실적으로 짧게" in instruction
