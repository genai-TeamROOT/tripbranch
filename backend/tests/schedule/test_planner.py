"""app.schedule.planner.plan_schedule() 회귀 테스트.

계약 문서: docs/design/int-07-schedule.md 6절(모듈 설계), 6.2.1절(basis_note),
9절("estimated_arrival 기준 시각" 미결 사항 — visit_datetime 없으면 현재 시각
fallback으로 해소, "D 후보 3개 미만" 미결 사항 — SCHEDULE-07로 해소).
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
        self.call_count = 0

    async def generate_schedule_plan(self, request: SchedulePlanningRequest):
        self.received_request = request
        self.call_count += 1
        return provider_result(self._plan, source=ProviderSource.FAKE_LLM)


def _sample_item(place_id: str, order: int) -> ScheduleItem:
    return ScheduleItem(
        order=order,
        place_id=place_id,
        place_name=f"장소 {place_id}",
        estimated_arrival="15:00",
        estimated_duration_min=60,
        travel_to_next_min=None,
        reason="테스트 이유",
    )


def _sample_plan() -> ScheduleLLMPlan:
    """ScheduleLLMPlan.items는 min_length=3 제약이 있어(SCHEDULE-07) 3개로 채운다."""
    return ScheduleLLMPlan(
        items=[
            _sample_item("place-1", 1),
            _sample_item("place-2", 2),
            _sample_item("place-3", 3),
        ],
        total_duration_min=60,
        route_summary="테스트 동선 요약",
    )


def _three_candidates() -> list[RecommendationItem]:
    return [_candidate("place-1"), _candidate("place-2"), _candidate("place-3")]


@pytest.mark.asyncio
async def test_plan_schedule_fills_basis_note_from_visit_datetime() -> None:
    """basis_note는 LLM이 만들지 않고 planner가 visit_datetime으로 결정적으로 채운다."""
    llm = _RecordingLLM(_sample_plan())
    request = SchedulePlanningRequest(
        candidates=_three_candidates(),
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
        candidates=_three_candidates(),
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
async def test_plan_schedule_normalizes_inconsistent_empty_plan() -> None:
    """LLM이 items는 빈 배열이면서 route_summary/total_duration_min은 그럴듯한
    문장으로 채워 보내는 비일관 응답을 실제로 준 적이 있다(2026-08-10 real Gemini
    수동 테스트). items가 비면 나머지 필드도 결정적으로 덮어써야 한다.

    SCHEDULE-07부터 ScheduleLLMPlan.items에 min_length=3이 걸려 있어 일반적인
    생성 경로로는 이런 객체를 더 이상 만들 수 없다(검증 실패 → 재시도 → 그래도
    실패하면 예외). 이 테스트는 검증을 우회하는 model_construct()로 "어떤 경로로든
    비일관 객체가 들어왔을 때"의 방어 로직 자체를 계속 검증한다."""
    inconsistent_plan = ScheduleLLMPlan.model_construct(
        items=[],
        total_duration_min=180,
        route_summary="장소 세 곳을 도는 알찬 코스예요.",
    )
    llm = _RecordingLLM(inconsistent_plan)
    request = SchedulePlanningRequest(
        candidates=_three_candidates(),
        conditions=UserConditions(),
        visit_datetime=datetime(2026, 8, 7, 15, 0, tzinfo=_KST),
        pairwise_distances_km={},
    )

    result = await plan_schedule(request, llm)

    assert result.items == []
    assert result.total_duration_min == 0
    assert result.route_summary == (
        "조건에 맞는 곳을 충분히 찾지 못해 일정을 만들지 못했어요. "
        "다른 지역이나 다른 종류의 장소로 다시 요청해볼까요?"
    )
    # basis_note는 items 유무와 무관하게 계속 채워진다
    assert "15:00 기준" in result.basis_note


@pytest.mark.asyncio
async def test_plan_schedule_passes_candidates_and_distances_through_untouched() -> None:
    llm = _RecordingLLM(_sample_plan())
    request = SchedulePlanningRequest(
        candidates=_three_candidates(),
        conditions=UserConditions(),
        visit_datetime=datetime(2026, 8, 7, 15, 0, tzinfo=_KST),
        pairwise_distances_km={("place-1", "place-2"): 1.2},
    )

    await plan_schedule(request, llm)

    assert llm.received_request is not None
    assert [c.place_id for c in llm.received_request.candidates] == [
        "place-1",
        "place-2",
        "place-3",
    ]
    assert llm.received_request.pairwise_distances_km == {("place-1", "place-2"): 1.2}


class TestPlanScheduleSkipsLLMWhenCandidatesTooFew:
    """SCHEDULE-07: 후보가 3개 미만이면 LLM을 아예 부르지 않는다 — 9절 "D 후보
    3개 미만" 미결 사항 해소. ScheduleLLMPlan.items의 min_length=3 제약을 애초에
    만족시킬 수 없는 상황에서 굳이 호출·재시도·실패를 반복하지 않는다."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("candidate_count", [0, 1, 2])
    async def test_llm_never_called(self, candidate_count: int) -> None:
        llm = _RecordingLLM(_sample_plan())
        request = SchedulePlanningRequest(
            candidates=[_candidate(f"place-{i}") for i in range(candidate_count)],
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 7, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_schedule(request, llm)

        assert llm.call_count == 0
        assert llm.received_request is None
        assert result.items == []
        assert result.total_duration_min == 0
        assert result.route_summary == (
            "조건에 맞는 곳을 충분히 찾지 못해 일정을 만들지 못했어요. "
            "다른 지역이나 다른 종류의 장소로 다시 요청해볼까요?"
        )
        assert "15:00 기준" in result.basis_note

    @pytest.mark.asyncio
    async def test_llm_called_when_exactly_three_candidates(self) -> None:
        """경계값: 정확히 3개면 스킵하지 않고 정상 호출한다."""
        llm = _RecordingLLM(_sample_plan())
        request = SchedulePlanningRequest(
            candidates=_three_candidates(),
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 7, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        await plan_schedule(request, llm)

        assert llm.call_count == 1
