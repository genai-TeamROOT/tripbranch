"""orchestrator.build_interpretation()의 Intent별 분기 회귀 테스트.

SCHEDULE-04 이전에는 이 파일이 없었다 — SCHEDULE 분기가 extract_recommend_
conditions()를 재사용하도록 바뀌면서(docs/design/int-07-schedule.md 4절) 그
바꿔치기 로직을 직접 검증할 테스트가 필요해졌다.
"""

from __future__ import annotations

import pytest

from app.providers.stub import FakeLLMProvider
from app.schemas import Intent, InterpretRequest, OutputStatus, PlaceTag
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
