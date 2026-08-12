"""일정 편성 모듈의 실행 로직.

역할: SchedulePlanningRequest를 받아 LLM으로 일정을 편성하고 ScheduleResult를
반환한다. 상태 저장소(StateStore)에 의존하지 않는 순수 입력→출력 함수다 —
A(agent_runtime.py)가 D(RecommendationProvider)를 호출하는 것과 동일한 방식으로
이 모듈을 호출한다(docs/design/int-07-schedule.md 6.0절, B의 "판단하지 않는
기억 장치" 원칙과 무관하게 B 코드는 전혀 건드리지 않는다).
"""

from __future__ import annotations

from datetime import datetime

from app.errors import AppError
from app.providers.protocols import LLMProvider
from app.schedule.schemas import SchedulePartialFillRequest, SchedulePlanningRequest
from app.schemas import ScheduleItem, ScheduleResult
from app.state.schema import now_kst

_NO_CANDIDATES_ROUTE_SUMMARY = (
    "조건에 맞는 곳을 충분히 찾지 못해 일정을 만들지 못했어요. "
    "다른 지역이나 다른 종류의 장소로 다시 요청해볼까요?"
)

# ScheduleLLMPlan.items에 min_length=3 제약을 걸어둔 상태라(app/schedule/schemas.py),
# 후보가 3개 미만이면 LLM이 애초에 그 제약을 만족시킬 방법이 없다 — 재시도를 줘도
# 똑같이 실패해 llm_output_invalid(502)만 두 번 반복하고 끝난다. 그래서 이 경우엔
# LLM을 아예 부르지 않고 여기서 바로 정규화된 안내로 반환한다(SCHEDULE-07, 9절
# "D 후보 3개 미만" 미결 사항 해소).
_MIN_CANDIDATES_FOR_SCHEDULE = 3


def _build_basis_note(visit_datetime: datetime) -> str:
    """D 피드백 반영 — 근거 데이터(운영시간·날씨)가 단일 시각 기준이라 뒷 순서
    스탑에는 부정확할 수 있다는 걸 사용자에게 알리는 고정 안내 문구.

    LLM이 생성하지 않고 이 함수가 결정적으로 채운다(docs/design/
    int-07-schedule.md 6.2.1절) — 스탑별 재계산은 이번 범위 밖.
    """

    formatted = visit_datetime.strftime("%H:%M")
    return (
        f"이 정보는 {formatted} 기준으로 계산됐어요. "
        "실제 방문 시간에는 운영시간·날씨 상황이 달라질 수 있어요."
    )


async def plan_schedule(
    request: SchedulePlanningRequest, llm: LLMProvider
) -> ScheduleResult:
    """SchedulePlanningRequest로 LLM을 호출해 ScheduleResult를 만든다.

    visit_datetime이 없으면 현재 시각(KST)을 기준으로 삼는다 — LLM 호출과
    basis_note 둘 다 같은 시각을 쓰도록 여기서 한 번만 결정한다(design doc 9절
    "estimated_arrival 기준 시각" 미결 사항 해소: 상대 표현 대신 항상 구체적인
    시작 시각을 LLM에 준다).
    """

    effective_visit_datetime = request.visit_datetime or now_kst()

    # 후보가 3개 미만이면 LLM을 부르지 않는다 — ScheduleLLMPlan.items의
    # min_length=3 제약을 애초에 만족시킬 수 없어 호출해도 재시도까지 실패로
    # 끝날 뿐이다(SCHEDULE-07).
    if len(request.candidates) < _MIN_CANDIDATES_FOR_SCHEDULE:
        return ScheduleResult(
            items=[],
            total_duration_min=0,
            route_summary=_NO_CANDIDATES_ROUTE_SUMMARY,
            basis_note=_build_basis_note(effective_visit_datetime),
        )

    resolved_request = (
        request
        if request.visit_datetime is not None
        else request.model_copy(update={"visit_datetime": effective_visit_datetime})
    )

    plan = (await llm.generate_schedule_plan(resolved_request)).data

    # LLM이 items는 빈 배열로 주면서 total_duration_min/route_summary는 그럴듯한
    # 문장으로 채워 보내는 비일관 응답이 실제로 관측됐다(2026-08-10 real Gemini
    # 수동 테스트, SCHEDULE-06 후속). SCHEDULE-07부터 ScheduleLLMPlan.items에
    # min_length=3 제약이 걸려 있어 실제 Gemini 경로에서는 이 분기가 원칙적으로
    # 발생하지 않지만(검증 실패 시 gemini.py의 재시도 후에도 실패하면 예외로
    # 올라간다), FakeLLMProvider 등 스키마 검증을 안 거치는 테스트 더블까지
    # 방어하기 위해 남겨둔다.
    if not plan.items:
        return ScheduleResult(
            items=[],
            total_duration_min=0,
            route_summary=_NO_CANDIDATES_ROUTE_SUMMARY,
            basis_note=_build_basis_note(effective_visit_datetime),
        )

    return ScheduleResult(
        items=plan.items,
        total_duration_min=plan.total_duration_min,
        route_summary=plan.route_summary,
        basis_note=_build_basis_note(effective_visit_datetime),
    )


# SCHEDULE-09 2단계 — 부분 재편성(REJECT_SPECIFIC) 전용.
_NO_FILL_CANDIDATES_ROUTE_SUMMARY = (
    "대체할 새로운 곳을 찾지 못해 나머지 일정은 그대로 유지했어요. "
    "조건을 조금 넓혀서 다시 요청해볼까요?"
)


def _total_duration_from_items(items: list[ScheduleItem]) -> int:
    """items의 체류시간 합 + 마지막을 제외한 이동시간 합.

    LLM이 부분 재편성에서는 전체 route 관점의 total_duration_min을 직접
    계산해주지 않으므로(new_items만 보고 있어 pinned_items를 포함한 전체를
    모른다) planner.py가 병합 후 항목 값만으로 직접 계산한다.
    """
    duration_sum = sum(item.estimated_duration_min for item in items)
    travel_sum = sum(
        item.travel_to_next_min for item in items if item.travel_to_next_min is not None
    )
    return duration_sum + travel_sum


def _pinned_only_result(
    pinned_items: list[ScheduleItem], visit_datetime: datetime, route_summary: str
) -> ScheduleResult:
    ordered = sorted(pinned_items, key=lambda item: item.order)
    return ScheduleResult(
        items=ordered,
        total_duration_min=_total_duration_from_items(ordered) if ordered else 0,
        route_summary=route_summary,
        basis_note=_build_basis_note(visit_datetime),
    )


async def plan_partial_schedule(
    request: SchedulePartialFillRequest, llm: LLMProvider
) -> ScheduleResult:
    """SchedulePartialFillRequest로 일부 슬롯만 새로 채운 ScheduleResult를 만든다.

    (SCHEDULE-09 2단계, SCHEDULE-부분수정-해결방향-설계안.md 3절)

    pinned_items는 LLM에 echo를 요청하지 않고 이 함수가 구조적으로 최종
    결과에 병합한다 — LLM은 target_orders 자리에 들어갈 new_items만
    반환한다. 응답의 order 집합이 target_orders와 정확히 일치하는지 여기서
    직접 검증하고, 불일치하면 llm_output_invalid로 실패 처리한다(개수가
    요청마다 달라 ScheduleLLMPlan처럼 Pydantic Field로 정적 강제할 수 없다 —
    SchedulePartialLLMPlan 참고).
    """

    effective_visit_datetime = request.visit_datetime or now_kst()

    if not request.target_orders:
        # 파싱 단계(SCHEDULE-09 1단계)가 REJECT_SPECIFIC일 때 항상 target_indices를
        # 채우므로 정상 흐름에서는 발생하지 않는다 — 방어적으로만 처리한다.
        return _pinned_only_result(
            request.pinned_items, effective_visit_datetime, _NO_FILL_CANDIDATES_ROUTE_SUMMARY
        )

    if not request.candidates:
        # 유지 대상(pinned)과 거절 대상을 제외하고 나니 채울 수 있는 새 후보가
        # 아예 없다 — "일정 전체 실패"가 아니라 "일부만 대체 실패"이므로 pinned은
        # 그대로 살리고 실패 사실만 안내한다(전체 재구성으로 덮어쓰지 않음).
        return _pinned_only_result(
            request.pinned_items, effective_visit_datetime, _NO_FILL_CANDIDATES_ROUTE_SUMMARY
        )

    resolved_request = (
        request
        if request.visit_datetime is not None
        else request.model_copy(update={"visit_datetime": effective_visit_datetime})
    )

    plan = (await llm.generate_schedule_fill(resolved_request)).data

    expected_orders = set(request.target_orders)
    actual_orders = {item.order for item in plan.new_items}
    if actual_orders != expected_orders or len(plan.new_items) != len(request.target_orders):
        raise AppError(
            code="llm_output_invalid",
            message="일정 재구성 응답을 해석하지 못했습니다.",
            status_code=502,
            retryable=True,
            provider="Gemini",
            details={
                "expected_orders": sorted(expected_orders),
                "actual_orders": sorted(actual_orders),
            },
        )

    merged = sorted([*request.pinned_items, *plan.new_items], key=lambda item: item.order)
    kept = len(request.pinned_items)
    replaced = len(plan.new_items)
    route_summary = f"{kept}곳은 그대로 유지하고 {replaced}곳을 새로운 장소로 바꿨어요."

    return ScheduleResult(
        items=merged,
        total_duration_min=_total_duration_from_items(merged),
        route_summary=route_summary,
        basis_note=_build_basis_note(effective_visit_datetime),
    )


__all__ = ["plan_schedule", "plan_partial_schedule"]
