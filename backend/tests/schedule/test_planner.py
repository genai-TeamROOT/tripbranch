"""app.schedule.planner.plan_schedule() 회귀 테스트.

계약 문서: docs/design/int-07-schedule.md 6절(모듈 설계), 6.2.1절(basis_note),
9절("estimated_arrival 기준 시각" 미결 사항 — visit_datetime 없으면 현재 시각
fallback으로 해소, "D 후보 3개 미만" 미결 사항 — SCHEDULE-07로 해소).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.errors import AppError
from app.providers.contracts import ProviderSource, provider_result
from app.schedule.associations import CoVisitedHint
from app.schedule.planner import _round_up_arrival, plan_partial_schedule, plan_schedule
from app.schedule.schemas import (
    ScheduleLLMPlan,
    SchedulePartialFillRequest,
    SchedulePartialLLMPlan,
    SchedulePlanningRequest,
)
from app.schemas import RecommendationItem, ScheduleItem, UserConditions

_KST = ZoneInfo("Asia/Seoul")


def _candidate(place_id: str, *, operating_hours_display: str | None = None) -> RecommendationItem:
    return RecommendationItem(
        place_id=place_id,
        name=f"장소 {place_id}",
        category="attraction",
        distance_km=0.3,
        remaining_minutes=120,
        operating_hours_display=operating_hours_display,
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


def _sample_item(
    place_id: str, order: int, *, estimated_arrival: str = "15:00"
) -> ScheduleItem:
    return ScheduleItem(
        order=order,
        place_id=place_id,
        place_name=f"장소 {place_id}",
        estimated_arrival=estimated_arrival,
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
        "이 정보는 현재시각(15:30) 기준으로 계산됐어요. "
        "실제 방문 시간에는 운영시간·날씨 상황이 달라질 수 있어요."
    )
    assert result.items == _sample_plan().items
    assert result.total_duration_min == 60
    assert result.route_summary == "테스트 동선 요약"


@pytest.mark.asyncio
async def test_plan_schedule_measures_elapsed_ms() -> None:
    """RecommendationResponse.elapsed_ms(recommendation_pipeline.py)와 같은 패턴으로
    plan_schedule() 진입부터 결과 조립까지의 처리시간을 잰다 — 개발자 화면이
    SCHEDULE도 RECOMMEND처럼 "서버 소요"를 보여줄 수 있게 한다."""
    llm = _RecordingLLM(_sample_plan())
    request = SchedulePlanningRequest(
        candidates=_three_candidates(),
        conditions=UserConditions(),
        visit_datetime=datetime(2026, 8, 7, 15, 30, tzinfo=_KST),
        pairwise_distances_km={},
    )
    fake_ticks = iter([0.0, 0.25])

    result = await plan_schedule(request, llm, timer=lambda: next(fake_ticks))

    assert result.elapsed_ms == 250.0


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

    ScheduleLLMPlan.items에는 min_length=1이 걸려 있어(SCHEDULE-10) 일반적인
    생성 경로로는 이런 객체(items=[])를 더 이상 만들 수 없다(검증 실패 → 재시도
    → 그래도 실패하면 예외). 이 테스트는 검증을 우회하는 model_construct()로
    "어떤 경로로든 비일관 객체가 들어왔을 때"의 방어 로직 자체를 계속 검증한다."""
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
    assert "현재시각(15:00)" in result.basis_note
    assert result.elapsed_ms >= 0


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


class TestPlanScheduleRoundsArrivalUpToTenMinutes:
    """SCHEDULE-11(팀 제안, 2026-08-12): 도착시각(estimated_arrival)만 10분 단위로
    올림한다. 체류시간(estimated_duration_min)·이동시간(travel_to_next_min)은
    LLM 추정치를 그대로 보여준다 — 반올림 대상이 아니다."""

    @pytest.mark.asyncio
    async def test_어중간한_도착시각을_10분_단위로_올린다(self) -> None:
        plan = ScheduleLLMPlan(
            items=[
                _sample_item("place-1", 1, estimated_arrival="11:59"),
                _sample_item("place-2", 2, estimated_arrival="14:14"),
                _sample_item("place-3", 3, estimated_arrival="15:30"),
            ],
            total_duration_min=180,
            route_summary="테스트 동선 요약",
        )
        llm = _RecordingLLM(plan)
        request = SchedulePlanningRequest(
            candidates=_three_candidates(),
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 7, 10, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_schedule(request, llm)

        assert [item.estimated_arrival for item in result.items] == [
            "12:00",
            "14:20",
            "15:30",
        ]

    @pytest.mark.asyncio
    async def test_체류시간과_이동시간은_건드리지_않는다(self) -> None:
        item = ScheduleItem(
            order=1,
            place_id="place-1",
            place_name="장소 place-1",
            estimated_arrival="11:59",
            estimated_duration_min=37,
            travel_to_next_min=13,
            reason="테스트 이유",
        )
        plan = ScheduleLLMPlan(
            items=[item, _sample_item("place-2", 2), _sample_item("place-3", 3)],
            total_duration_min=180,
            route_summary="테스트 동선 요약",
        )
        llm = _RecordingLLM(plan)
        request = SchedulePlanningRequest(
            candidates=_three_candidates(),
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 7, 10, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_schedule(request, llm)

        assert result.items[0].estimated_arrival == "12:00"
        assert result.items[0].estimated_duration_min == 37
        assert result.items[0].travel_to_next_min == 13


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
        assert result.elapsed_ms >= 0
        assert "현재시각(15:00)" in result.basis_note

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


class TestPlanScheduleCandidateGuardIsDynamic:
    """SCHEDULE-10: 후보 부족 가드의 최솟값이 고정 3이 아니라 target_item_range()가
    계산한 값을 쓴다 — time_available이 짧으면(예: 90분) 최솟값이 1로 낮아져,
    후보가 3개 미만이어도 LLM을 정상 호출해야 한다."""

    @pytest.mark.asyncio
    async def test_짧은_시간이면_후보_한개로도_LLM을_부른다(self) -> None:
        one_item_plan = ScheduleLLMPlan(
            items=[_sample_item("place-1", 1)],
            total_duration_min=60,
            route_summary="테스트 동선 요약",
        )
        llm = _RecordingLLM(one_item_plan)
        request = SchedulePlanningRequest(
            candidates=[_candidate("place-1")],
            conditions=UserConditions(time_available=90),
            visit_datetime=datetime(2026, 8, 7, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_schedule(request, llm)

        assert llm.call_count == 1
        assert len(result.items) == 1

    @pytest.mark.asyncio
    async def test_짧은_시간이어도_후보가_아예_없으면_여전히_스킵한다(self) -> None:
        llm = _RecordingLLM(_sample_plan())
        request = SchedulePlanningRequest(
            candidates=[],
            conditions=UserConditions(time_available=90),
            visit_datetime=datetime(2026, 8, 7, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_schedule(request, llm)

        assert llm.call_count == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_시간_제한이_없으면_여전히_3개_미만에서_스킵한다(self) -> None:
        """기존 SCHEDULE-07 동작(시간 제한 없을 때 최소 3개) 회귀 방지."""
        llm = _RecordingLLM(_sample_plan())
        request = SchedulePlanningRequest(
            candidates=[_candidate("place-1"), _candidate("place-2")],
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 7, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_schedule(request, llm)

        assert llm.call_count == 0
        assert result.items == []


class TestPlanScheduleFlagsClosedStops:
    """폐점 후보를 일정에 넣을 때 estimated_arrival 기준으로 운영시간과 대조해
    구조적으로 경고를 붙인다. 프롬프트에 운영시간을 함께 전달해 LLM이 애초에
    피하도록 유도하지만(build_schedule_planning_instruction), 그 지시만으로는
    부족하다고 판단해(6.2.1절 — 근거 데이터가 단일 시각 기준) planner.py가
    응답을 받은 뒤 다시 결정적으로 검사한다. (docs/design/int-07-schedule.md
    9절 "폐점 스탑 감지" 항목 해소)"""

    @pytest.mark.asyncio
    async def test_도착_예정_시각이_마감_이후면_경고를_붙인다(self) -> None:
        plan = ScheduleLLMPlan(
            items=[
                _sample_item("place-1", 1, estimated_arrival="19:00"),
                _sample_item("place-2", 2),
                _sample_item("place-3", 3),
            ],
            total_duration_min=180,
            route_summary="테스트 동선 요약",
        )
        llm = _RecordingLLM(plan)
        candidates = [
            _candidate("place-1", operating_hours_display="09:00~18:00"),
            _candidate("place-2"),
            _candidate("place-3"),
        ]
        request = SchedulePlanningRequest(
            candidates=candidates,
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 7, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_schedule(request, llm)

        assert result.items[0].warnings == [
            "운영시간(09:00~18:00) 기준으로 도착 예정 시각(19:00)엔 운영 중이 아닐 수 있어요. "
            "방문 전에 다시 확인해주세요."
        ]
        assert result.items[1].warnings == []
        assert result.items[2].warnings == []

    @pytest.mark.asyncio
    async def test_운영시간_내_도착이면_경고가_없다(self) -> None:
        plan = ScheduleLLMPlan(
            items=[
                _sample_item("place-1", 1, estimated_arrival="10:00"),
                _sample_item("place-2", 2),
                _sample_item("place-3", 3),
            ],
            total_duration_min=180,
            route_summary="테스트 동선 요약",
        )
        llm = _RecordingLLM(plan)
        candidates = [
            _candidate("place-1", operating_hours_display="09:00~18:00"),
            _candidate("place-2"),
            _candidate("place-3"),
        ]
        request = SchedulePlanningRequest(
            candidates=candidates,
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 7, 9, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_schedule(request, llm)

        assert result.items[0].warnings == []

    @pytest.mark.asyncio
    async def test_운영시간_미확인_후보는_경고하지_않는다(self) -> None:
        """operating_hours_display가 None(운영시간 자체를 모름)이면 폐점이라고
        단정할 근거가 없다 — scoring.py의 "운영시간 미확인은 폐점이 아니다"
        원칙과 동일하게, 검사 대상에서 제외한다."""
        llm = _RecordingLLM(_sample_plan())
        request = SchedulePlanningRequest(
            candidates=_three_candidates(),
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 7, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_schedule(request, llm)

        assert all(item.warnings == [] for item in result.items)

    @pytest.mark.asyncio
    async def test_24시간_운영은_경고하지_않는다(self) -> None:
        plan = ScheduleLLMPlan(
            items=[
                _sample_item("place-1", 1, estimated_arrival="23:50"),
                _sample_item("place-2", 2),
                _sample_item("place-3", 3),
            ],
            total_duration_min=180,
            route_summary="테스트 동선 요약",
        )
        llm = _RecordingLLM(plan)
        candidates = [
            _candidate("place-1", operating_hours_display="24시간"),
            _candidate("place-2"),
            _candidate("place-3"),
        ]
        request = SchedulePlanningRequest(
            candidates=candidates,
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 7, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_schedule(request, llm)

        assert result.items[0].warnings == []


class _RecordingFillLLM:
    """generate_schedule_fill()에 실제로 어떤 request가 넘어오는지 기록하는 더블."""

    def __init__(self, plan: SchedulePartialLLMPlan) -> None:
        self._plan = plan
        self.received_request: SchedulePartialFillRequest | None = None
        self.call_count = 0

    async def generate_schedule_fill(self, request: SchedulePartialFillRequest):
        self.received_request = request
        self.call_count += 1
        return provider_result(self._plan, source=ProviderSource.FAKE_LLM)


def _pinned(place_id: str, order: int, *, estimated_arrival: str = "14:00") -> ScheduleItem:
    return ScheduleItem(
        order=order,
        place_id=place_id,
        place_name=f"장소 {place_id}",
        estimated_arrival=estimated_arrival,
        estimated_duration_min=60,
        travel_to_next_min=15,
        reason="기존 일정 유지",
    )


class TestPlanPartialSchedule:
    """SCHEDULE-09 2단계: 일부 자리만 새로 채우는 plan_partial_schedule() 회귀 테스트.

    (SCHEDULE-부분수정-해결방향-설계안.md 3절)
    """

    @pytest.mark.asyncio
    async def test_merges_pinned_and_new_items_in_order(self) -> None:
        pinned = [_pinned("place-1", 1), _pinned("place-3", 3)]
        new_item = _sample_item("place-2", 2)
        llm = _RecordingFillLLM(SchedulePartialLLMPlan(new_items=[new_item]))
        request = SchedulePartialFillRequest(
            pinned_items=pinned,
            target_orders=[2],
            candidates=[_candidate("place-2")],
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 11, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_partial_schedule(request, llm)

        assert [item.place_id for item in result.items] == ["place-1", "place-2", "place-3"]
        assert [item.order for item in result.items] == [1, 2, 3]
        assert result.route_summary == "2곳은 그대로 유지하고 1곳을 새로운 장소로 바꿨어요."
        # place-1(order 1)의 travel_to_next_min은 원래 "직전 편성 때 order 2에
        # 있던 장소"까지의 값(15)이었는데, 이번에 order 2가 새 장소(place-2)로
        # 교체됐으므로 더 이상 맞지 않는 stale 값이다 — 재계산할 수 없으니
        # None으로 무효화되는 게 맞는다(실사용 리뷰로 발견한 버그의 회귀 테스트).
        # place-3(order 3)은 다음 자리(order 4)가 애초에 없어(마지막 항목)
        # target_orders와 무관하므로 원래 값(15)이 그대로 유지된다 — 이 helper의
        # 기본값이 실제 "마지막 항목=None" 규칙과는 다르지만, 여기서 검증하려는
        # 건 "무효화 대상이 아닌 pinned 항목은 안 건드린다"는 것이다.
        assert result.items[0].travel_to_next_min is None
        assert result.items[2].travel_to_next_min == 15
        # 체류시간 합(60*3) + 마지막을 제외한 이동시간 합(travel_to_next_min: None+None+15)
        assert result.total_duration_min == 60 * 3 + 15
        assert "현재시각(15:00)" in result.basis_note
        assert result.elapsed_ms >= 0

    @pytest.mark.asyncio
    async def test_pinned_places_are_removed_from_fill_candidates(self) -> None:
        """유지 대상이 후보에 섞여 있으면 후보에서 빼고 LLM에 넘긴다.

        섞인 채로 넘기면 그 자리에 같은 장소가 다시 뽑혀 한 일정에 중복으로
        들어간다. 프롬프트도 "pinned_items의 place_id를 다시 고르지 마세요"라고
        지시하지만(fill.md) LLM 지시는 구조적 보장이 아니다.

        지금까지는 호출부의 제외 목록(recommended ∪ rejected)이 pinned를 먼저
        걸러내 드러나지 않았다 — 그 목록이 무엇을 담는지에 편성 정확성이
        딸려 있으면 안 된다.
        """
        pinned = [_pinned("place-1", 1), _pinned("place-3", 3)]
        llm = _RecordingFillLLM(SchedulePartialLLMPlan(new_items=[_sample_item("place-2", 2)]))
        request = SchedulePartialFillRequest(
            pinned_items=pinned,
            target_orders=[2],
            # place-1은 pinned인데 후보에도 들어 있다.
            candidates=[_candidate("place-1"), _candidate("place-2")],
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 11, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_partial_schedule(request, llm)

        assert llm.received_request is not None
        assert [c.place_id for c in llm.received_request.candidates] == ["place-2"]
        assert [item.place_id for item in result.items] == ["place-1", "place-2", "place-3"]

    @pytest.mark.asyncio
    async def test_pinned_only_when_every_candidate_is_pinned(self) -> None:
        """후보가 전부 유지 대상이면 채울 수 있는 새 장소가 없다 — LLM을 부르지
        않고 pinned만 살려 안내한다(후보 0건과 같은 처리)."""
        pinned = [_pinned("place-1", 1), _pinned("place-3", 3)]
        llm = _RecordingFillLLM(SchedulePartialLLMPlan(new_items=[_sample_item("place-1", 2)]))
        request = SchedulePartialFillRequest(
            pinned_items=pinned,
            target_orders=[2],
            candidates=[_candidate("place-1"), _candidate("place-3")],
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 11, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_partial_schedule(request, llm)

        assert llm.call_count == 0
        assert [item.place_id for item in result.items] == ["place-1", "place-3"]

    @pytest.mark.asyncio
    async def test_invalidates_stale_travel_time_when_last_slot_is_replaced(self) -> None:
        """교체된 자리가 마지막 order여도 그 직전 pinned 항목의 travel_to_next_min이
        무효화된다 — 무효화 조건이 "다음 자리가 target_orders에 있는지"만 보므로
        가운데 슬롯 교체와 동일하게 동작해야 한다."""
        pinned = [_pinned("place-1", 1), _pinned("place-2", 2)]
        new_item = _sample_item("place-3", 3)
        llm = _RecordingFillLLM(SchedulePartialLLMPlan(new_items=[new_item]))
        request = SchedulePartialFillRequest(
            pinned_items=pinned,
            target_orders=[3],
            candidates=[_candidate("place-3")],
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 11, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_partial_schedule(request, llm)

        assert [item.place_id for item in result.items] == ["place-1", "place-2", "place-3"]
        # place-1(order 1)은 다음 자리(order 2)가 그대로 유지됐으니 안 건드린다.
        assert result.items[0].travel_to_next_min == 15
        # place-2(order 2)는 다음 자리(order 3)가 교체됐으니 무효화된다.
        assert result.items[1].travel_to_next_min is None

    @pytest.mark.asyncio
    async def test_resyncs_downstream_pinned_arrival_after_middle_slot_replaced(self) -> None:
        """중간 자리가 새 장소로 바뀌면 그 새 장소의 실제 체류·이동 시간이 원래
        있던 장소와 다를 수 있다 — 뒤이어 오는 pinned 항목의 도착 시각을 새
        체인 기준으로 다시 계산해야 한다(그대로 두면 stale한 시각이 표시됨)."""
        pinned = [
            _pinned("place-1", 1, estimated_arrival="14:00"),
            # place-3의 원래 도착 시각(16:55)은 옛 place-2(체류 90분+이동 10분)
            # 기준으로 계산됐던 값이라, 새 place-2가 다른 체류·이동 시간을 쓰면
            # 더 이상 맞지 않는다.
            _pinned("place-3", 3, estimated_arrival="16:55"),
        ]
        new_item = ScheduleItem(
            order=2,
            place_id="place-2",
            place_name="장소 place-2",
            estimated_arrival="15:30",
            estimated_duration_min=45,
            travel_to_next_min=20,
            reason="테스트 이유",
        )
        llm = _RecordingFillLLM(SchedulePartialLLMPlan(new_items=[new_item]))
        request = SchedulePartialFillRequest(
            pinned_items=pinned,
            target_orders=[2],
            candidates=[_candidate("place-2")],
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 11, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_partial_schedule(request, llm)

        arrivals = {item.place_id: item.estimated_arrival for item in result.items}
        # place-1은 앵커(첫 항목)라 그대로 유지.
        assert arrivals["place-1"] == "14:00"
        # place-2는 새로 채워진 자리라 LLM이 준 값을 그대로 신뢰(앵커).
        assert arrivals["place-2"] == "15:30"
        # place-3은 앵커(place-2) 도착 15:30 + 체류 45분 + 이동 20분 = 16:35,
        # 10분 단위 올림으로 16:40 — stale했던 16:55가 아니어야 한다.
        assert arrivals["place-3"] == "16:40"

    @pytest.mark.asyncio
    async def test_measures_elapsed_ms(self) -> None:
        """plan_schedule()과 같은 패턴으로 timer 주입값을 그대로 반영한다."""
        pinned = [_pinned("place-1", 1), _pinned("place-3", 3)]
        new_item = _sample_item("place-2", 2)
        llm = _RecordingFillLLM(SchedulePartialLLMPlan(new_items=[new_item]))
        request = SchedulePartialFillRequest(
            pinned_items=pinned,
            target_orders=[2],
            candidates=[_candidate("place-2")],
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 11, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )
        fake_ticks = iter([0.0, 0.1])

        result = await plan_partial_schedule(request, llm, timer=lambda: next(fake_ticks))

        assert result.elapsed_ms == 100.0

    @pytest.mark.asyncio
    async def test_no_fresh_candidates_keeps_pinned_only(self) -> None:
        """대체할 새 후보가 없으면 "일정 전체 실패"가 아니라 pinned만 그대로 유지한다."""
        pinned = [_pinned("place-1", 1), _pinned("place-3", 3)]
        llm = _RecordingFillLLM(SchedulePartialLLMPlan(new_items=[]))
        request = SchedulePartialFillRequest(
            pinned_items=pinned,
            target_orders=[2],
            candidates=[],
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 11, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_partial_schedule(request, llm)

        assert llm.call_count == 0
        assert [item.place_id for item in result.items] == ["place-1", "place-3"]
        assert "그대로 유지" in result.route_summary
        assert result.elapsed_ms >= 0

    @pytest.mark.asyncio
    async def test_raises_when_llm_returns_wrong_orders(self) -> None:
        """LLM이 target_orders와 다른 order를 반환하면(개수 불일치 포함)
        pinned를 신뢰할 수 없는 상태로 병합하지 않고 명확히 실패시킨다."""
        pinned = [_pinned("place-1", 1), _pinned("place-3", 3)]
        wrong_item = _sample_item("place-2", 99)  # target_orders=[2]와 불일치
        llm = _RecordingFillLLM(SchedulePartialLLMPlan(new_items=[wrong_item]))
        request = SchedulePartialFillRequest(
            pinned_items=pinned,
            target_orders=[2],
            candidates=[_candidate("place-2")],
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 11, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        with pytest.raises(AppError) as exc_info:
            await plan_partial_schedule(request, llm)

        assert exc_info.value.code == "llm_output_invalid"

    @pytest.mark.asyncio
    async def test_새로_채운_자리도_운영시간_기준으로_검사한다(self) -> None:
        """pinned 항목은 candidates에 없어(REJECT_SPECIFIC 부분 재편성 특성상 이번
        요청의 candidates는 새로 채울 자리의 후보만 담고 있다) 검사 대상이
        아니지만, 새로 채운 자리(new_items)는 이번 candidates에 있으므로 그대로
        검사된다."""
        pinned = [_pinned("place-1", 1), _pinned("place-3", 3)]
        new_item = _sample_item("place-2", 2, estimated_arrival="20:00")
        llm = _RecordingFillLLM(SchedulePartialLLMPlan(new_items=[new_item]))
        request = SchedulePartialFillRequest(
            pinned_items=pinned,
            target_orders=[2],
            candidates=[_candidate("place-2", operating_hours_display="09:00~18:00")],
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 11, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_partial_schedule(request, llm)

        by_place = {item.place_id: item for item in result.items}
        assert by_place["place-2"].warnings != []
        assert by_place["place-1"].warnings == []
        assert by_place["place-3"].warnings == []

    @pytest.mark.asyncio
    async def test_empty_target_orders_returns_pinned_unchanged(self) -> None:
        """방어적 분기 — 정상 흐름(REJECT_SPECIFIC 파싱)에서는 발생하지 않는다."""
        pinned = [_pinned("place-1", 1), _pinned("place-2", 2)]
        llm = _RecordingFillLLM(SchedulePartialLLMPlan(new_items=[]))
        request = SchedulePartialFillRequest(
            pinned_items=pinned,
            target_orders=[],
            candidates=[_candidate("place-3")],
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 11, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_partial_schedule(request, llm)

        assert llm.call_count == 0
        assert [item.place_id for item in result.items] == ["place-1", "place-2"]


class TestPlanPartialScheduleRoundsArrivalUpToTenMinutes:
    """SCHEDULE-11(팀 제안, 2026-08-12): pinned 항목·새로 채운 항목 모두 최종
    결과에서는 도착시각이 10분 단위로 올림돼 있어야 한다."""

    @pytest.mark.asyncio
    async def test_pinned과_새_항목_도착시각_모두_올림한다(self) -> None:
        pinned = [_pinned("place-1", 1, estimated_arrival="13:52")]
        new_item = _sample_item("place-2", 2, estimated_arrival="15:07")
        llm = _RecordingFillLLM(SchedulePartialLLMPlan(new_items=[new_item]))
        request = SchedulePartialFillRequest(
            pinned_items=pinned,
            target_orders=[2],
            candidates=[_candidate("place-2")],
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 11, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_partial_schedule(request, llm)

        assert [item.estimated_arrival for item in result.items] == ["14:00", "15:10"]

    @pytest.mark.asyncio
    async def test_대체_후보가_없어_pinned만_유지할_때도_올림한다(self) -> None:
        pinned = [_pinned("place-1", 1, estimated_arrival="13:52")]
        llm = _RecordingFillLLM(SchedulePartialLLMPlan(new_items=[]))
        request = SchedulePartialFillRequest(
            pinned_items=pinned,
            target_orders=[2],
            candidates=[],
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 11, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_partial_schedule(request, llm)

        assert [item.estimated_arrival for item in result.items] == ["14:00"]


class TestCoVisitedFetcherWiring:
    """place_associations(D-088) 연동은 opt-in이다 — co_visited_fetcher를 안 넘기면
    plan_schedule()은 기존과 완전히 동일하게 동작해야 한다. 실패 시에도 SCHEDULE
    전체를 막지 않고 힌트 없이 계속돼야 한다."""

    @pytest.mark.asyncio
    async def test_fetcher를_안_넘기면_co_visited_hints가_비어있다(self) -> None:
        llm = _RecordingLLM(_sample_plan())
        request = SchedulePlanningRequest(
            candidates=_three_candidates(),
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 26, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        await plan_schedule(request, llm)

        assert llm.received_request is not None
        assert llm.received_request.co_visited_hints == []

    @pytest.mark.asyncio
    async def test_fetcher가_반환한_힌트가_LLM_요청에_실린다(self) -> None:
        llm = _RecordingLLM(_sample_plan())
        request = SchedulePlanningRequest(
            candidates=_three_candidates(),
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 26, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )
        expected_hint = CoVisitedHint(from_place_id="place-1", to_place_id="place-2", rank=1)
        received_place_ids: list[str] = []

        async def fake_fetcher(place_ids, settings):
            received_place_ids.extend(place_ids)
            return [expected_hint]

        await plan_schedule(request, llm, co_visited_fetcher=fake_fetcher, settings=Settings())

        assert llm.received_request is not None
        assert llm.received_request.co_visited_hints == [expected_hint]
        assert sorted(received_place_ids) == ["place-1", "place-2", "place-3"]

    @pytest.mark.asyncio
    async def test_fetcher가_예외를_던져도_일정_편성은_그대로_진행된다(self) -> None:
        llm = _RecordingLLM(_sample_plan())
        request = SchedulePlanningRequest(
            candidates=_three_candidates(),
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 26, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        async def failing_fetcher(place_ids, settings):
            raise RuntimeError("네트워크 실패 흉내")

        result = await plan_schedule(
            request, llm, co_visited_fetcher=failing_fetcher, settings=Settings()
        )

        assert llm.received_request is not None
        assert llm.received_request.co_visited_hints == []
        assert result.items == _sample_plan().items


class TestCoVisitedFetcherWiringForPartialSchedule:
    """plan_partial_schedule()도 같은 opt-in 계약을 따른다 — 다만 조회 대상
    place_id는 candidates뿐 아니라 pinned_items까지 합친 집합이어야 한다."""

    @pytest.mark.asyncio
    async def test_fetcher를_안_넘기면_co_visited_hints가_비어있다(self) -> None:
        pinned_items = [_pinned("place-1", 1), _pinned("place-3", 3)]
        new_item = _sample_item("place-2", 2)
        llm = _RecordingFillLLM(SchedulePartialLLMPlan(new_items=[new_item]))
        request = SchedulePartialFillRequest(
            pinned_items=pinned_items,
            target_orders=[2],
            candidates=[_candidate("place-2")],
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 26, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        await plan_partial_schedule(request, llm)

        assert llm.received_request is not None
        assert llm.received_request.co_visited_hints == []

    @pytest.mark.asyncio
    async def test_pinned과_candidates_place_id를_합쳐서_조회한다(self) -> None:
        pinned_items = [_pinned("place-1", 1), _pinned("place-3", 3)]
        new_item = _sample_item("place-2", 2)
        llm = _RecordingFillLLM(SchedulePartialLLMPlan(new_items=[new_item]))
        request = SchedulePartialFillRequest(
            pinned_items=pinned_items,
            target_orders=[2],
            candidates=[_candidate("place-2")],
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 26, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )
        expected_hint = CoVisitedHint(from_place_id="place-1", to_place_id="place-2", rank=1)
        received_place_ids: list[str] = []

        async def fake_fetcher(place_ids, settings):
            received_place_ids.extend(place_ids)
            return [expected_hint]

        await plan_partial_schedule(
            request, llm, co_visited_fetcher=fake_fetcher, settings=Settings()
        )

        assert llm.received_request is not None
        assert llm.received_request.co_visited_hints == [expected_hint]
        assert sorted(received_place_ids) == ["place-1", "place-2", "place-3"]

    @pytest.mark.asyncio
    async def test_fetcher가_예외를_던져도_부분_재편성은_그대로_진행된다(self) -> None:
        pinned_items = [_pinned("place-1", 1)]
        new_item = _sample_item("place-2", 2)
        llm = _RecordingFillLLM(SchedulePartialLLMPlan(new_items=[new_item]))
        request = SchedulePartialFillRequest(
            pinned_items=pinned_items,
            target_orders=[2],
            candidates=[_candidate("place-2")],
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 8, 26, 15, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        async def failing_fetcher(place_ids, settings):
            raise RuntimeError("네트워크 실패 흉내")

        result = await plan_partial_schedule(
            request, llm, co_visited_fetcher=failing_fetcher, settings=Settings()
        )

        assert llm.received_request is not None
        assert llm.received_request.co_visited_hints == []
        assert result.items[-1].place_id == "place-2"


class TestRoundUpArrival:
    """_round_up_arrival()의 경계값 — plan_schedule()/plan_partial_schedule() 통합
    테스트로는 다루기 번거로운 자정 넘김·이미 정각·잘못된 형식 케이스만 단위로 확인한다."""

    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("11:59", "12:00"),
            ("14:14", "14:20"),
            ("15:30", "15:30"),  # 이미 10분 단위면 그대로
            ("00:00", "00:00"),
            ("09:01", "09:10"),
        ],
    )
    def test_10분_단위로_올림한다(self, given: str, expected: str) -> None:
        assert _round_up_arrival(given) == expected

    def test_자정을_넘기면_다음날_00시대로_감싼다(self) -> None:
        assert _round_up_arrival("23:55") == "00:00"

    def test_형식이_깨진_값은_그대로_돌려준다(self) -> None:
        assert _round_up_arrival("점심시간") == "점심시간"
