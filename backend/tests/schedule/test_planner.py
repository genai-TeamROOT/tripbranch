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
from app.schedule.planner import _round_up_start, plan_partial_schedule, plan_schedule
from app.schedule.schemas import (
    ScheduleLLMItem,
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
    place_id: str, order: int, *, estimated_duration_min: int = 60
) -> ScheduleLLMItem:
    """LLM이 돌려주는 항목. 시각이 없다(TP-215)."""

    return ScheduleLLMItem(
        order=order,
        place_id=place_id,
        place_name=f"장소 {place_id}",
        estimated_duration_min=estimated_duration_min,
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
    assert [item.place_id for item in result.items] == [
        item.place_id for item in _sample_plan().items
    ]
    # 체류 60분 x 3 + 폴백 이동 15분 x 2 (TP-215 — LLM이 준 값이 아니라 계산값)
    assert result.total_duration_min == 210
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


class TestPlanScheduleComputesArrivals:
    """TP-215: 도착시각은 LLM이 만들지 않고 시작 시각 + 누적(체류 + 이동)으로
    계산된다. 거리 정보가 없으면 구간마다 폴백 이동시간(15분)을 쓴다."""

    @pytest.mark.asyncio
    async def test_도착시각이_체류와_이동의_누적과_일치한다(self) -> None:
        plan = ScheduleLLMPlan(
            items=[
                _sample_item("place-1", 1),
                _sample_item("place-2", 2),
                _sample_item("place-3", 3),
            ],
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

        # attraction 정책 체류 60분 + 폴백 이동 15분이 누적된다.
        assert [item.estimated_arrival for item in result.items] == [
            "10:00",
            "11:15",
            "12:30",
        ]
        assert result.total_duration_min == 60 + 15 + 60 + 15 + 60

    @pytest.mark.asyncio
    async def test_비현실적인_체류시간_제안은_정책_범위로_조정된다(self) -> None:
        """LLM이 "관광지 37분"을 줘도 그대로 실리지 않는다 (TP-215)."""

        plan = ScheduleLLMPlan(
            items=[
                _sample_item("place-1", 1, estimated_duration_min=37),
                _sample_item("place-2", 2),
                _sample_item("place-3", 3),
            ],
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

        # attraction 정책은 최소 60분이다(app.schedule.duration).
        assert result.items[0].estimated_duration_min == 60


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
                _sample_item("place-1", 1),
                _sample_item("place-2", 2),
                _sample_item("place-3", 3),
            ],
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
            visit_datetime=datetime(2026, 8, 7, 19, 0, tzinfo=_KST),
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
                _sample_item("place-1", 1),
                _sample_item("place-2", 2),
                _sample_item("place-3", 3),
            ],
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
                _sample_item("place-1", 1),
                _sample_item("place-2", 2),
                _sample_item("place-3", 3),
            ],
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
        # 이동시간은 이번 순서 기준으로 전부 다시 계산된다(TP-215) — 예전처럼
        # stale한 값을 None으로 무효화하고 넘어가지 않는다. 거리 정보가 없으므로
        # 구간마다 폴백(15분)이 들어가고, 마지막 항목만 None이다.
        assert [item.travel_to_next_min for item in result.items] == [15, 15, None]
        # 체류 60분 x 3 + 이동 15분 x 2
        assert result.total_duration_min == 210
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
    async def test_recomputes_every_travel_time_instead_of_invalidating(self) -> None:
        """이동시간은 stale해질 수 없다 — 병합 후 전체 구간을 다시 계산한다(TP-215).

        예전에는 교체된 자리 직전의 pinned 항목이 들고 있던 travel_to_next_min을
        "다음 자리가 바뀌었으니 더는 맞지 않는다"며 None으로 지웠다. 지금은 그
        값을 이번 순서 기준으로 새로 구하므로 지울 것이 없다."""
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
        assert [item.travel_to_next_min for item in result.items] == [15, 15, None]

    @pytest.mark.asyncio
    async def test_downstream_arrivals_follow_the_new_chain(self) -> None:
        """중간 자리가 바뀌면 뒤이어 오는 항목의 도착 시각이 새 체인을 따른다.

        예전에는 LLM이 준 새 항목의 도착 시각을 앵커로 믿고 그 뒤만 다시 맞췄다 —
        앵커 자체가 검증되지 않은 값이었다. 지금은 유지되는 첫 자리의 도착
        시각만 기준점으로 쓰고 나머지는 전부 계산한다(TP-215)."""
        pinned = [
            _pinned("place-1", 1, estimated_arrival="14:00"),
            # place-3의 원래 도착 시각(16:55)은 옛 place-2(체류 90분+이동 10분)
            # 기준으로 계산됐던 값이라, 새 place-2가 다른 체류·이동 시간을 쓰면
            # 더 이상 맞지 않는다.
            _pinned("place-3", 3, estimated_arrival="16:55"),
        ]
        new_item = _sample_item("place-2", 2, estimated_duration_min=120)
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
        # place-1은 그대로 유지되는 첫 자리라 도착 시각이 기준점이 된다.
        assert arrivals["place-1"] == "14:00"
        # place-2는 14:00 + 체류 60분 + 이동 15분.
        assert arrivals["place-2"] == "15:15"
        # place-3은 15:15 + 새 장소 체류 120분 + 이동 15분 = 17:30.
        # 스냅샷으로 들고 있던 16:55가 아니어야 한다.
        assert arrivals["place-3"] == "17:30"

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
        new_item = _sample_item("place-2", 2)
        llm = _RecordingFillLLM(SchedulePartialLLMPlan(new_items=[new_item]))
        request = SchedulePartialFillRequest(
            pinned_items=pinned,
            target_orders=[2],
            candidates=[_candidate("place-2", operating_hours_display="09:00~15:00")],
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


class TestPlanPartialScheduleKeepsTheAnchor:
    """TP-215: 그대로 유지되는 첫 자리의 도착 시각이 시간표의 기준점이다.

    자리 하나를 바꿨다고 일정 전체가 앞뒤로 움직이면 "나머지는 그대로 뒀다"는
    말이 안 맞는다. 그래서 이 값만은 반올림하지 않고 그대로 쓴다."""

    @pytest.mark.asyncio
    async def test_유지되는_첫_자리의_도착_시각에서_이어_계산한다(self) -> None:
        pinned = [_pinned("place-1", 1, estimated_arrival="13:52")]
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

        # 13:52 그대로 + 체류 60분 + 이동 15분 = 15:07
        assert [item.estimated_arrival for item in result.items] == ["13:52", "15:07"]

    @pytest.mark.asyncio
    async def test_대체_후보가_없어_pinned만_남아도_기준점을_지킨다(self) -> None:
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

        assert [item.estimated_arrival for item in result.items] == ["13:52"]


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
        assert [item.place_id for item in result.items] == [
        item.place_id for item in _sample_plan().items
    ]


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


class TestRoundUpStart:
    """_round_up_start()의 경계값 (TP-215).

    항목마다 도착시각을 올리던 것을 시작 시각 한 번으로 옮겼다 — 항목마다 올리면
    화면의 시각이 체류·이동의 누적과 어긋나기 때문이다(planner 주석 참고).
    """

    @pytest.mark.parametrize(
        ("minute", "expected_minute"),
        [
            (59, 0),
            (14, 20),
            (30, 30),  # 이미 10분 단위면 그대로
            (0, 0),
            (1, 10),
        ],
    )
    def test_10분_단위로_올림한다(self, minute: int, expected_minute: int) -> None:
        rounded = _round_up_start(datetime(2026, 8, 7, 13, minute, tzinfo=_KST))
        assert rounded.minute == expected_minute

    def test_자정을_넘기면_날짜가_함께_넘어간다(self) -> None:
        rounded = _round_up_start(datetime(2026, 8, 7, 23, 55, tzinfo=_KST))
        assert rounded == datetime(2026, 8, 8, 0, 0, tzinfo=_KST)

    def test_초가_남아_있으면_다음_단위로_올린다(self) -> None:
        rounded = _round_up_start(datetime(2026, 8, 7, 13, 30, 1, tzinfo=_KST))
        assert rounded == datetime(2026, 8, 7, 13, 40, tzinfo=_KST)


# ------------------------------------------------ 보관함 강제 포함 (SCHEDULE-12)


class _SequenceLLM:
    """호출마다 다른 plan을 돌려주는 더블. must_include 재시도 검증용."""

    def __init__(self, *plans: ScheduleLLMPlan) -> None:
        self._plans = list(plans)
        self.received_requests: list[SchedulePlanningRequest] = []

    @property
    def call_count(self) -> int:
        return len(self.received_requests)

    async def generate_schedule_plan(self, request: SchedulePlanningRequest):
        self.received_requests.append(request)
        plan = self._plans[min(self.call_count - 1, len(self._plans) - 1)]
        return provider_result(plan, source=ProviderSource.FAKE_LLM)


def _plan_of(*place_ids: str) -> ScheduleLLMPlan:
    return ScheduleLLMPlan(
        items=[
            _sample_item(place_id, order) for order, place_id in enumerate(place_ids, start=1)
        ],
        route_summary="테스트 동선 요약",
    )


@pytest.mark.asyncio
async def test_must_include_is_passed_to_llm() -> None:
    """강제 포함 목록이 LLM 요청에 그대로 실린다."""
    llm = _RecordingLLM(_plan_of("place-1", "place-2", "place-3"))
    request = SchedulePlanningRequest(
        candidates=_three_candidates(),
        must_include_place_ids=["place-2"],
        conditions=UserConditions(),
        pairwise_distances_km={},
    )

    result = await plan_schedule(request, llm)

    assert llm.received_request is not None
    assert llm.received_request.must_include_place_ids == ["place-2"]
    assert result.omitted_saved_place_names == []


@pytest.mark.asyncio
async def test_must_include_not_in_candidates_is_dropped_silently() -> None:
    """후보에 없는 id는 강제할 수 없다 — 이름을 모르므로 안내도 여기서 채우지 않는다.

    폐점 하드 필터 등으로 D가 걸러낸 경우다. 안내 문구는 호출부(agent_runtime)가
    보관함에 저장된 이름으로 따로 채운다.
    """
    llm = _RecordingLLM(_plan_of("place-1", "place-2", "place-3"))
    request = SchedulePlanningRequest(
        candidates=_three_candidates(),
        must_include_place_ids=["place-2", "없는-장소"],
        conditions=UserConditions(),
        pairwise_distances_km={},
    )

    result = await plan_schedule(request, llm)

    assert llm.received_request is not None
    assert llm.received_request.must_include_place_ids == ["place-2"]
    assert result.omitted_saved_place_names == []


@pytest.mark.asyncio
async def test_must_include_over_item_cap_is_trimmed_in_saved_order() -> None:
    """상한을 넘으면 담은 순서대로 앞에서부터만 쓰고, 나머지는 이름으로 알린다.

    time_available=100분이면 target_item_range()가 최대 2개다.
    점수 순이 아니라 담은 순으로 자르는 이유는 "왜 그 곳이 빠졌는지" 설명할 수
    있어야 하기 때문이다.
    """
    llm = _RecordingLLM(_plan_of("place-1", "place-2"))
    request = SchedulePlanningRequest(
        candidates=_three_candidates(),
        must_include_place_ids=["place-1", "place-2", "place-3"],
        conditions=UserConditions(time_available=100),
        pairwise_distances_km={},
    )

    result = await plan_schedule(request, llm)

    assert llm.received_request is not None
    assert llm.received_request.must_include_place_ids == ["place-1", "place-2"]
    assert result.omitted_saved_place_names == ["장소 place-3"]


@pytest.mark.asyncio
async def test_must_include_missing_triggers_one_retry() -> None:
    """LLM이 강제 포함을 빠뜨리면 한 번 다시 부른다. 두 번째가 맞으면 안내는 없다."""
    llm = _SequenceLLM(
        _plan_of("place-1", "place-2", "place-3"),
        _plan_of("place-1", "place-2", "place-9"),
    )
    request = SchedulePlanningRequest(
        candidates=[*_three_candidates(), _candidate("place-9")],
        must_include_place_ids=["place-9"],
        conditions=UserConditions(),
        pairwise_distances_km={},
    )

    result = await plan_schedule(request, llm)

    assert llm.call_count == 2
    assert result.omitted_saved_place_names == []
    assert [item.place_id for item in result.items] == ["place-1", "place-2", "place-9"]


@pytest.mark.asyncio
async def test_must_include_missing_after_retry_keeps_result_and_reports() -> None:
    """재시도 후에도 빠지면 502로 죽이지 않고 결과를 살리되 이름을 실어 보낸다.

    plan_partial_schedule()의 하드 실패와 다른 선택이다 — 저쪽은 유지해야 할
    기존 일정이 걸려 있지만, 보관함은 부분 성공이 전체 실패보다 낫다.
    """
    llm = _SequenceLLM(_plan_of("place-1", "place-2", "place-3"))
    request = SchedulePlanningRequest(
        candidates=[*_three_candidates(), _candidate("place-9")],
        must_include_place_ids=["place-9"],
        conditions=UserConditions(),
        pairwise_distances_km={},
    )

    result = await plan_schedule(request, llm)

    assert llm.call_count == 2
    assert result.items != []
    assert result.omitted_saved_place_names == ["장소 place-9"]


@pytest.mark.asyncio
async def test_empty_must_include_does_not_retry() -> None:
    """강제 포함이 없으면 검증도 재시도도 없다 — 기존 동작과 완전히 같다."""
    llm = _SequenceLLM(_plan_of("place-1", "place-2", "place-3"))
    request = SchedulePlanningRequest(
        candidates=_three_candidates(),
        conditions=UserConditions(),
        pairwise_distances_km={},
    )

    result = await plan_schedule(request, llm)

    assert llm.call_count == 1
    assert result.omitted_saved_place_names == []


# ------------------------------------------------ 시각 계산 엔진 (TP-215)


class TestPlanScheduleRejectsUnknownPlaceIds:
    """LLM이 후보에 없는 place_id를 만들어내면 그 항목을 버린다.

    통과시키면 되돌릴 수 없다 — record_recommendation()에 "추천됨"으로 기록되고,
    이후 턴의 제외 목록에 올라 실재하는 장소를 영구히 가린다.
    """

    @pytest.mark.asyncio
    async def test_후보에_없는_항목은_결과에서_빠진다(self) -> None:
        plan = ScheduleLLMPlan(
            items=[
                _sample_item("place-1", 1),
                _sample_item("지어낸-장소", 2),
                _sample_item("place-3", 3),
            ],
            route_summary="테스트 동선 요약",
        )
        llm = _RecordingLLM(plan)
        request = SchedulePlanningRequest(
            candidates=_three_candidates(),
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 9, 2, 13, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_schedule(request, llm)

        assert [item.place_id for item in result.items] == ["place-1", "place-3"]

    @pytest.mark.asyncio
    async def test_남은_항목의_순서를_다시_매긴다(self) -> None:
        """가운데가 빠졌다고 order에 구멍이 나면 프론트 타임라인이 어긋난다."""

        plan = ScheduleLLMPlan(
            items=[
                _sample_item("place-1", 1),
                _sample_item("지어낸-장소", 2),
                _sample_item("place-3", 3),
            ],
            route_summary="테스트 동선 요약",
        )
        llm = _RecordingLLM(plan)
        request = SchedulePlanningRequest(
            candidates=_three_candidates(),
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 9, 2, 13, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_schedule(request, llm)

        assert [item.order for item in result.items] == [1, 2]

    @pytest.mark.asyncio
    async def test_전부_지어낸_값이면_빈_일정으로_안내한다(self) -> None:
        plan = ScheduleLLMPlan(
            items=[_sample_item(f"지어낸-{i}", i) for i in range(1, 4)],
            route_summary="테스트 동선 요약",
        )
        llm = _RecordingLLM(plan)
        request = SchedulePlanningRequest(
            candidates=_three_candidates(),
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 9, 2, 13, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_schedule(request, llm)

        assert result.items == []
        assert result.total_duration_min == 0
        assert "찾지 못해" in result.route_summary

    @pytest.mark.asyncio
    async def test_부분_재편성에서는_하드_실패한다(self) -> None:
        """유지해야 할 기존 일정이 걸려 있어 자리를 비울 수 없다 — 조용히 빼면
        그 뒤 항목들의 순서가 밀려 사용자가 유지하기로 한 일정이 망가진다."""

        llm = _RecordingFillLLM(
            SchedulePartialLLMPlan(new_items=[_sample_item("지어낸-장소", 2)])
        )
        request = SchedulePartialFillRequest(
            pinned_items=[_pinned("place-1", 1), _pinned("place-3", 3)],
            target_orders=[2],
            candidates=[_candidate("place-2")],
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 9, 2, 13, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        with pytest.raises(AppError) as exc_info:
            await plan_partial_schedule(request, llm)

        assert exc_info.value.code == "llm_output_invalid"


class TestPlanScheduleTimelineIntegration:
    """TP-215 완료 조건 — 대기·자정 넘김·결정론을 편성 경로 전체로 확인한다."""

    @pytest.mark.asyncio
    async def test_개장_전에_도착하면_기다렸다가_방문한다(self) -> None:
        plan = ScheduleLLMPlan(
            items=[_sample_item("place-1", 1), _sample_item("place-2", 2)],
            route_summary="테스트 동선 요약",
        )
        llm = _RecordingLLM(plan)
        candidates = [
            _candidate("place-1"),
            _candidate("place-2", operating_hours_display="15:00~21:00"),
        ]
        request = SchedulePlanningRequest(
            candidates=candidates,
            conditions=UserConditions(time_available=150),
            visit_datetime=datetime(2026, 9, 2, 13, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_schedule(request, llm)

        # 13:00 + 체류 60 + 이동 15 = 14:15 도착. 개장은 15:00이다.
        assert result.items[1].estimated_arrival == "14:15"
        # 기다렸다가 여는 시각에 들어가므로 경고를 붙이지 않는다.
        assert result.items[1].warnings == []
        # 대기 45분도 사용자가 실제로 쓰는 시간이라 총합에 들어간다.
        assert result.total_duration_min == 60 + 15 + 45 + 60

    @pytest.mark.asyncio
    async def test_자정을_넘겨도_순서와_시각이_뒤집히지_않는다(self) -> None:
        plan = ScheduleLLMPlan(
            items=[_sample_item("place-1", 1), _sample_item("place-2", 2)],
            route_summary="테스트 동선 요약",
        )
        llm = _RecordingLLM(plan)
        request = SchedulePlanningRequest(
            candidates=[_candidate("place-1"), _candidate("place-2")],
            conditions=UserConditions(time_available=150),
            visit_datetime=datetime(2026, 9, 2, 23, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        result = await plan_schedule(request, llm)

        assert [item.estimated_arrival for item in result.items] == ["23:00", "00:15"]
        # 자정 기준 분으로 비교하면 뒤집히지만(1380 > 15), 실제 소요는 75분이다.
        assert result.total_duration_min == 60 + 15 + 60

    @pytest.mark.asyncio
    async def test_같은_입력이면_같은_시간표가_나온다(self) -> None:
        def _request() -> SchedulePlanningRequest:
            return SchedulePlanningRequest(
                candidates=_three_candidates(),
                conditions=UserConditions(),
                visit_datetime=datetime(2026, 9, 2, 13, 0, tzinfo=_KST),
                pairwise_distances_km={("place-1", "place-2"): 1.2},
            )

        first = await plan_schedule(_request(), _RecordingLLM(_sample_plan()))
        second = await plan_schedule(_request(), _RecordingLLM(_sample_plan()))

        assert [i.estimated_arrival for i in first.items] == [
            i.estimated_arrival for i in second.items
        ]
        assert first.total_duration_min == second.total_duration_min

    @pytest.mark.asyncio
    async def test_거리_정보가_있으면_폴백_대신_그_값을_쓴다(self) -> None:
        llm = _RecordingLLM(_sample_plan())
        request = SchedulePlanningRequest(
            candidates=_three_candidates(),
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 9, 2, 13, 0, tzinfo=_KST),
            # 도보 가정 속도(0.07km/분)로 1.4km는 20분이다.
            pairwise_distances_km={("place-1", "place-2"): 1.4},
        )

        result = await plan_schedule(request, llm)

        assert result.items[0].travel_to_next_min == 20
        # 거리를 모르는 구간은 폴백(15분)이 그대로 쓰인다.
        assert result.items[1].travel_to_next_min == 15

    @pytest.mark.asyncio
    async def test_LLM_호출_횟수가_늘지_않는다(self) -> None:
        llm = _RecordingLLM(_sample_plan())
        request = SchedulePlanningRequest(
            candidates=_three_candidates(),
            conditions=UserConditions(),
            visit_datetime=datetime(2026, 9, 2, 13, 0, tzinfo=_KST),
            pairwise_distances_km={},
        )

        await plan_schedule(request, llm)

        assert llm.call_count == 1
