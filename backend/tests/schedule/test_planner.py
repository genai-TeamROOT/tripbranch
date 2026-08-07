"""app.schedule.planner.plan_schedule() 회귀 테스트.

계약 문서: docs/design/int-07-schedule.md 6절(모듈 설계), 6.2.1절(basis_note),
9절("estimated_arrival 기준 시각" 미결 사항 — visit_datetime 없으면 현재 시각
fallback으로 해소).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.providers.contracts import ProviderSource, provider_result
from app.schedule.planner import plan_schedule
from app.schedule.schemas import ScheduleLLMPlan, SchedulePlanningRequest
from app.schemas import RecommendationItem, ScheduleItem, UserConditions

_KST = ZoneInfo("Asia/Seoul")


def _candidate(place_id: str) -> RecommendationItem:
    return RecommendationItem(
        place_id=place_id,
        name=f"장소 {place_id}",
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


class _RecordingLLM:
    """generate_schedule_plan()에 실제로 어떤 request가 넘어오는지 기록하는 더블."""

    def __init__(self, plan: ScheduleLLMPlan) -> None:
        self._plan = plan
        self.received_request: SchedulePlanningRequest | None = None

    async def generate_schedule_plan(self, request: SchedulePlanningRequest):
        self.received_request = request
        return provider_result(self._plan, source=ProviderSource.FAKE_LLM)


def _sample_plan() -> ScheduleLLMPlan:
    return ScheduleLLMPlan(
        items=[
            ScheduleItem(
                order=1,
                place_id="place-1",
                place_name="장소 place-1",
                estimated_arrival="15:00",
                estimated_duration_min=60,
                travel_to_next_min=None,
                reason="테스트 이유",
            )
        ],
        total_duration_min=60,
        route_summary="테스트 동선 요약",
    )


@pytest.mark.asyncio
async def test_plan_schedule_fills_basis_note_from_visit_datetime() -> None:
    """basis_note는 LLM이 만들지 않고 planner가 visit_datetime으로 결정적으로 채운다."""
    llm = _RecordingLLM(_sample_plan())
    request = SchedulePlanningRequest(
        candidates=[_candidate("place-1")],
        conditions=UserConditions(),
        visit_datetime=datetime(2026, 8, 7, 15, 30, tzinfo=_KST),
        pairwise_distances_km={},
    )

    result = await plan_schedule(request, llm)

    assert result.basis_note == (
        "이 정보는 15:30 기준으로 계산됐어요. "
        "실제 방문 시간에는 운영시간·날씨 상황이 달라질 수 있어요."
    )
    assert result.items == _sample_plan().items
    assert result.total_duration_min == 60
    assert result.route_summary == "테스트 동선 요약"


@pytest.mark.asyncio
async def test_plan_schedule_falls_back_to_now_when_visit_datetime_missing() -> None:
    """visit_datetime이 없으면 현재 시각(KST)을 기준으로 LLM 호출과 basis_note 둘
    다에 일관되게 쓴다(9절 미결 사항 해소)."""
    llm = _RecordingLLM(_sample_plan())
    request = SchedulePlanningRequest(
        candidates=[_candidate("place-1")],
        conditions=UserConditions(),
        visit_datetime=None,
        pairwise_distances_km={},
    )

    result = await plan_schedule(request, llm)

    assert llm.received_request is not None
    assert llm.received_request.visit_datetime is not None
    resolved_hhmm = llm.received_request.visit_datetime.strftime("%H:%M")
    assert resolved_hhmm in result.basis_note


@pytest.mark.asyncio
async def test_plan_schedule_passes_candidates_and_distances_through_untouched() -> None:
    llm = _RecordingLLM(_sample_plan())
    request = SchedulePlanningRequest(
        candidates=[_candidate("place-1"), _candidate("place-2")],
        conditions=UserConditions(),
        visit_datetime=datetime(2026, 8, 7, 15, 0, tzinfo=_KST),
        pairwise_distances_km={("place-1", "place-2"): 1.2},
    )

    await plan_schedule(request, llm)

    assert llm.received_request is not None
    assert [c.place_id for c in llm.received_request.candidates] == ["place-1", "place-2"]
    assert llm.received_request.pairwise_distances_km == {("place-1", "place-2"): 1.2}
