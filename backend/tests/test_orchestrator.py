"""orchestrator.build_interpretation()의 Intent별 분기 회귀 테스트.

SCHEDULE-04 이전에는 이 파일이 없었다 — SCHEDULE 분기가 extract_recommend_
conditions()를 재사용하도록 바뀌면서(docs/design/int-07-schedule.md 4절) 그
바꿔치기 로직을 직접 검증할 테스트가 필요해졌다.
"""

from __future__ import annotations

import pytest

from app.providers.stub import FakeLLMProvider
from app.schemas import Intent, InterpretRequest, OutputStatus, PlaceTag, UserConditions
from app.services.interpret.orchestrator import build_interpretation


@pytest.mark.asyncio
async def test_schedule_reuses_recommend_condition_extraction() -> None:
    """SCHEDULE도 RECOMMEND와 같은 15개 조건 추출을 타되, intent만 SCHEDULE로
    바꿔치기된다(6.1절 "기존 15개 조건 그대로 사용")."""
    request = InterpretRequest(
        user_input="경복궁 근처에서 반나절 코스 짜줘",
        has_previous_recommendation=False,
        shown_place_count=0,
        current_conditions=None,
    )

    output = await build_interpretation(request, FakeLLMProvider())

    assert output.intent is Intent.SCHEDULE
    assert output.status is OutputStatus.COMPLETE
    assert output.recommend is not None
    assert output.recommend.conditions.search_center == "경복궁"


@pytest.mark.asyncio
async def test_schedule_can_still_need_clarification() -> None:
    """추출 단계의 되묻기(예: 눈 관련 모호함)도 RECOMMEND와 동일하게 그대로
    전달돼야 한다 — intent 바꿔치기가 status/clarification까지 지우면 안 된다."""
    request = InterpretRequest(
        user_input="눈 오는 날 코스 짜줘",
        has_previous_recommendation=False,
        shown_place_count=0,
        current_conditions=None,
    )

    output = await build_interpretation(request, FakeLLMProvider())

    assert output.intent is Intent.SCHEDULE
    assert output.status is OutputStatus.NEEDS_CLARIFICATION
    assert output.clarification is not None


@pytest.mark.asyncio
async def test_schedule_with_cafe_marker_sets_place_tags() -> None:
    request = InterpretRequest(
        user_input="카페 위주로 일정 짜줘",
        has_previous_recommendation=False,
        shown_place_count=0,
        current_conditions=None,
    )

    output = await build_interpretation(request, FakeLLMProvider())

    assert output.intent is Intent.SCHEDULE
    assert output.recommend is not None
    assert PlaceTag.CAFE in output.recommend.conditions.place_tags


# --- 케이스 4/5(PR 4, docs/design/clarification-options.md): 목적어 없는
# "처음부터 다시" 선제 차단. classify_intent()를 부르지 않고 결정적으로 되묻는지 —
# FakeLLMProvider가 이 발화를 어떻게 분류할지와 무관하게 항상 되물어야 한다.


@pytest.mark.asyncio
async def test_bare_restart_during_schedule_location_ask_triggers_clarification() -> None:
    """케이스 4: SCHEDULE 위치 되묻기 중 목적어 없는 "처음부터 다시"."""
    request = InterpretRequest(
        user_input="처음부터 다시",
        has_previous_recommendation=False,
        shown_place_count=0,
        current_conditions=UserConditions(time_available=240),
        pending_clarification="location_required",
        last_intent="SCHEDULE",
    )

    output = await build_interpretation(request, FakeLLMProvider())

    assert output.intent is Intent.SCHEDULE
    assert output.status is OutputStatus.NEEDS_CLARIFICATION
    assert output.clarification is not None
    assert output.clarification.code == "schedule_bare_restart"
    option_ids = {option.id for option in output.clarification.options}
    assert option_ids == {"restart", "keep_asking"}


@pytest.mark.asyncio
async def test_object_ful_restart_during_schedule_location_ask_falls_through() -> None:
    """목적어가 붙으면("처음부터 다시 짜줘") 케이스 4가 아니라 평소 classify_intent()
    경로를 타야 한다 — D-053 등 기존 규칙과 충돌하지 않는다."""
    request = InterpretRequest(
        user_input="처음부터 다시 짜줘",
        has_previous_recommendation=False,
        shown_place_count=0,
        current_conditions=UserConditions(time_available=240),
        pending_clarification="location_required",
        last_intent="SCHEDULE",
    )

    output = await build_interpretation(request, FakeLLMProvider())

    assert output.clarification is None or output.clarification.code != "schedule_bare_restart"


@pytest.mark.asyncio
async def test_bare_restart_during_active_search_uses_condition_phrase() -> None:
    """케이스 5: RECOMMEND 진행 중(되묻기 아님) 목적어 없는 "처음부터 다시"는 현재
    조건을 되묻기 문구/버튼에 그대로 반영한다."""
    request = InterpretRequest(
        user_input="처음부터 다시",
        has_previous_recommendation=True,
        shown_place_count=5,
        current_conditions=UserConditions(search_center="경복궁"),
        pending_clarification=None,
        last_intent="RECOMMEND",
    )

    output = await build_interpretation(request, FakeLLMProvider())

    assert output.status is OutputStatus.NEEDS_CLARIFICATION
    assert output.clarification is not None
    assert output.clarification.code == "bare_restart_active"
    assert output.clarification.message == (
        "경복궁 근처로 다시 알아볼까요, 아니면 새로운 목적지로 찾아볼까요?"
    )
    keep_context = next(o for o in output.clarification.options if o.id == "keep_context")
    assert keep_context.label == "경복궁 근처로 다시 찾아주세요"
    full_reset = next(o for o in output.clarification.options if o.id == "full_reset")
    assert full_reset.label == "새로 시작할게요"


@pytest.mark.asyncio
async def test_bare_restart_during_active_search_without_conditions_uses_generic_phrase() -> None:
    """조건이 전부 비어 있으면(장소/날씨/카테고리 언급 없음) 범용 문구로 폴백한다."""
    request = InterpretRequest(
        user_input="처음부터 다시",
        has_previous_recommendation=True,
        shown_place_count=5,
        current_conditions=UserConditions(),
        pending_clarification=None,
        last_intent="MODIFY",
    )

    output = await build_interpretation(request, FakeLLMProvider())

    assert output.clarification is not None
    assert output.clarification.message == "다시 알아볼까요, 아니면 새로운 목적지로 찾아볼까요?"
    keep_context = next(o for o in output.clarification.options if o.id == "keep_context")
    assert keep_context.label == "이대로 다시 찾아주세요"


@pytest.mark.asyncio
async def test_bare_restart_after_schedule_completed_triggers_clarification() -> None:
    """SCHEDULE이 되묻기 없이 완료된 뒤(pending_clarification=None)의 "처음부터
    다시"는 케이스 4(SCHEDULE 위치 되묻기 전용)에도, 케이스 5(RECOMMEND/MODIFY
    전용)에도 안 걸린다 — 아무 규칙도 없으면 SCHEDULE-06이 무조건 같은 조건으로
    재편성을 시도해 후보 부족 시 실패 문구로 샌다(실사용 재현, 2026-08-13).
    SCHEDULE 전용 되묻기로 잡아야 한다."""
    request = InterpretRequest(
        user_input="처음부터 다시",
        has_previous_recommendation=True,
        shown_place_count=3,
        current_conditions=UserConditions(search_center="경복궁"),
        pending_clarification=None,
        last_intent="SCHEDULE",
    )

    output = await build_interpretation(request, FakeLLMProvider())

    assert output.intent is Intent.SCHEDULE
    assert output.status is OutputStatus.NEEDS_CLARIFICATION
    assert output.clarification is not None
    assert output.clarification.code == "schedule_bare_restart_completed"
    assert output.clarification.message == (
        "경복궁 근처로 다시 짜드릴까요, 아니면 새로운 목적지로 찾아볼까요?"
    )
    option_ids = {option.id for option in output.clarification.options}
    assert option_ids == {"retry_schedule", "full_reset"}
