"""일정 편성 모듈의 실행 로직.

역할: SchedulePlanningRequest를 받아 LLM으로 일정을 편성하고 ScheduleResult를
반환한다. 상태 저장소(StateStore)에 의존하지 않는 순수 입력→출력 함수다 —
A(agent_runtime.py)가 D(RecommendationProvider)를 호출하는 것과 동일한 방식으로
이 모듈을 호출한다(docs/design/int-07-schedule.md 6.0절, B의 "판단하지 않는
기억 장치" 원칙과 무관하게 B 코드는 전혀 건드리지 않는다).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from time import perf_counter
from typing import TypeAlias

from app.errors import AppError
from app.providers.protocols import LLMProvider
from app.schedule.schemas import (
    SchedulePartialFillRequest,
    SchedulePlanningRequest,
    target_item_range,
)
from app.schemas import ScheduleItem, ScheduleResult
from app.state.schema import now_kst

Timer: TypeAlias = Callable[[], float]

_NO_CANDIDATES_ROUTE_SUMMARY = (
    "조건에 맞는 곳을 충분히 찾지 못해 일정을 만들지 못했어요. "
    "다른 지역이나 다른 종류의 장소로 다시 요청해볼까요?"
)

# ScheduleLLMPlan.items의 최소 개수가 이번 요청의 time_available에 따라 달라지므로
# (target_item_range(), SCHEDULE-10) 후보 부족 가드도 고정 3이 아니라 그 최솟값을
# 쓴다 — 예를 들어 "2시간 코스 짜줘"는 최소 1개면 충분한데, 후보가 2개뿐이라고
# 무조건 "충분히 찾지 못했다"고 안내하면 실제로는 만들 수 있는 일정도 막힌다.
# 후보가 이 최솟값보다 적으면 LLM이 애초에 그 개수를 만족시킬 방법이 없다 —
# 재시도를 줘도 똑같이 실패해 llm_output_invalid(502)만 두 번 반복하고 끝난다.
# 그래서 이 경우엔 LLM을 아예 부르지 않고 여기서 바로 정규화된 안내로 반환한다
# (SCHEDULE-07, 9절 "D 후보 3개 미만" 미결 사항 해소).


def _parse_hhmm_minutes(hhmm: str) -> int | None:
    """estimated_arrival("HH:MM")을 자정 기준 분 단위 정수로 파싱한다.

    형식이 안 맞으면(LLM이 지시를 안 지킨 방어적 상황) None을 돌려준다 —
    호출부가 이 경우 재계산을 포기하고 원본 값을 그대로 두도록 한다.
    """

    try:
        hour_str, minute_str = hhmm.split(":", 1)
        return int(hour_str) * 60 + int(minute_str)
    except (ValueError, AttributeError):
        return None


def _format_minutes_hhmm(total_minutes: int) -> str:
    wrapped = total_minutes % (24 * 60)
    return f"{wrapped // 60:02d}:{wrapped % 60:02d}"


def _round_up_arrival(hhmm: str) -> str:
    """estimated_arrival("HH:MM")을 다음 10분 단위로 올림한다(예: "11:59" -> "12:00").

    도착시각은 LLM이 시작 시각부터 체류·이동시간을 누적해 계산한 추정치일
    뿐이라(estimated_duration_min/travel_to_next_min 둘 다 아직 실측 Tool이
    없는 LLM 추정값 — travel_to_next_min도 마찬가지다), 11:59처럼 딱 떨어지지
    않는 값보다 10분 단위로 보여주는 게 사용자에게 더 자연스럽게 읽힌다(팀 제안,
    2026-08-12). estimated_duration_min/travel_to_next_min은 세부 소요시간
    정보라 그대로 둔다 — 반올림 대상은 "도착 체크포인트"인 estimated_arrival뿐이다.

    이미 24시(1440분)를 넘기며 자정을 넘어가는 경우 다음날 00:xx로 감싼다.
    형식이 "HH:MM"이 아니면(LLM이 지시를 안 지킨 방어적 상황) 원본을 그대로
    돌려준다 — 화면 표시용 후처리가 튼튼한 값까지 망가뜨리면 안 된다.
    """

    try:
        hour_str, minute_str = hhmm.split(":", 1)
        total_minutes = int(hour_str) * 60 + int(minute_str)
    except (ValueError, AttributeError):
        return hhmm
    rounded = -(-total_minutes // 10) * 10
    rounded %= 24 * 60
    return f"{rounded // 60:02d}:{rounded % 60:02d}"


def _round_up_items_arrival(items: list[ScheduleItem]) -> list[ScheduleItem]:
    """items 각 항목의 estimated_arrival만 10분 단위로 올림한 새 리스트를 만든다."""

    return [
        item.model_copy(update={"estimated_arrival": _round_up_arrival(item.estimated_arrival)})
        for item in items
    ]


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
    request: SchedulePlanningRequest, llm: LLMProvider, *, timer: Timer = perf_counter
) -> ScheduleResult:
    """SchedulePlanningRequest로 LLM을 호출해 ScheduleResult를 만든다.

    visit_datetime이 없으면 현재 시각(KST)을 기준으로 삼는다 — LLM 호출과
    basis_note 둘 다 같은 시각을 쓰도록 여기서 한 번만 결정한다(design doc 9절
    "estimated_arrival 기준 시각" 미결 사항 해소: 상대 표현 대신 항상 구체적인
    시작 시각을 LLM에 준다).

    elapsed_ms는 이 함수 진입부터 결과 조립까지의 처리시간이다 —
    RecommendationResponse.elapsed_ms(app/services/recommendation_pipeline.py)와
    같은 패턴으로 재서, 개발자 화면(카드·감사 패널)이 RECOMMEND와 동일하게
    SCHEDULE의 서버 소요시간도 보여줄 수 있게 한다(RECOMMEND는 이 값이 있는데
    SCHEDULE만 없어 "서버 소요"가 항상 빈 값으로 보이던 걸 정리함).
    """

    started_at = timer()
    effective_visit_datetime = request.visit_datetime or now_kst()

    # 이번 요청의 time_available에 맞는 최소 개수를 구해서 후보 수와 비교한다
    # (SCHEDULE-10). 후보가 그 최솟값보다 적으면 LLM을 부르지 않는다 —
    # ScheduleLLMPlan.items가 그 개수를 애초에 만족시킬 수 없어 호출해도
    # 재시도까지 실패로 끝날 뿐이다(SCHEDULE-07의 가드를 동적 최솟값으로 확장).
    min_items, _max_items = target_item_range(request.conditions.time_available)
    if len(request.candidates) < min_items:
        return ScheduleResult(
            items=[],
            total_duration_min=0,
            route_summary=_NO_CANDIDATES_ROUTE_SUMMARY,
            basis_note=_build_basis_note(effective_visit_datetime),
            elapsed_ms=round((timer() - started_at) * 1000, 2),
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
            elapsed_ms=round((timer() - started_at) * 1000, 2),
        )

    return ScheduleResult(
        items=_round_up_items_arrival(plan.items),
        total_duration_min=plan.total_duration_min,
        route_summary=plan.route_summary,
        basis_note=_build_basis_note(effective_visit_datetime),
        elapsed_ms=round((timer() - started_at) * 1000, 2),
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


def _resync_downstream_arrivals(
    merged: list[ScheduleItem], expected_orders: set[int]
) -> list[ScheduleItem]:
    """교체된 자리(new_items) 뒤에 이어지는 pinned 항목들의 estimated_arrival을
    실제 duration/travel 체인 기준으로 다시 계산한다.

    pinned 항목의 estimated_arrival은 "직전 전체/부분 편성 때 그 앞자리에 있던
    장소" 기준으로 계산된 값이라, 그 앞자리가 이번 REJECT_SPECIFIC으로 새 장소로
    바뀌면(새 장소의 체류·이동 시간이 원래 있던 장소와 다를 수 있으므로) 더 이상
    맞지 않을 수 있다 — travel_to_next_min이 stale해지는 것과 같은 원인이다
    (실사용 리뷰로 발견, 2026-08-13. 관련 수정: 교체 직전 pinned 항목의
    travel_to_next_min 무효화).

    순서대로 훑으면서, 이번에 새로 채워진 자리(new_items)는 LLM이 이미
    pinned 이웃의 도착 시각을 근거로 직접 계산해준 값이니 그대로 앵커로
    신뢰한다(다시 계산하지 않음 — LLM 출력을 임의로 덮어쓰지 않는다). 그 다음에
    오는 pinned 항목들은 앵커의 도착 시각에 앵커 자신의 duration·travel_to_next_min을
    누적해 다시 계산한다. 이 anchor가 실은 그 앞자리부터 안 바뀐 pinned
    항목이라도(즉 이번에 아무것도 안 바뀐 구간) 같은 값·같은 공식으로 다시
    계산하는 것이라 결과가 그대로 재현된다 — 안전하다.

    파싱 실패(anchor의 estimated_arrival이 "HH:MM"이 아닌 방어적 상황)가
    생기면 그 시점부터는 재계산을 포기하고 남은 항목을 원본 그대로 둔다 —
    화면 표시용 후처리가 이미 있는 값까지 망가뜨리면 안 된다는 기존 원칙과
    동일하다.
    """

    result: list[ScheduleItem] = []
    running_minutes: int | None = None
    prev_duration = 0
    prev_travel = 0

    for item in merged:
        is_anchor = not result or item.order in expected_orders
        if is_anchor:
            resolved_item = item
            running_minutes = _parse_hhmm_minutes(item.estimated_arrival)
        elif running_minutes is None:
            # 이전 앵커 파싱이 실패했다 — 더 이상 신뢰할 기준점이 없으니 원본 유지.
            resolved_item = item
        else:
            running_minutes += prev_duration + prev_travel
            resolved_item = item.model_copy(
                update={"estimated_arrival": _format_minutes_hhmm(running_minutes)}
            )
            running_minutes = _parse_hhmm_minutes(resolved_item.estimated_arrival)

        result.append(resolved_item)
        prev_duration = resolved_item.estimated_duration_min
        prev_travel = resolved_item.travel_to_next_min or 0

    return result


def _pinned_only_result(
    pinned_items: list[ScheduleItem],
    visit_datetime: datetime,
    route_summary: str,
    elapsed_ms: float,
) -> ScheduleResult:
    ordered = sorted(pinned_items, key=lambda item: item.order)
    return ScheduleResult(
        items=_round_up_items_arrival(ordered),
        total_duration_min=_total_duration_from_items(ordered) if ordered else 0,
        route_summary=route_summary,
        basis_note=_build_basis_note(visit_datetime),
        elapsed_ms=elapsed_ms,
    )


async def plan_partial_schedule(
    request: SchedulePartialFillRequest, llm: LLMProvider, *, timer: Timer = perf_counter
) -> ScheduleResult:
    """SchedulePartialFillRequest로 일부 슬롯만 새로 채운 ScheduleResult를 만든다.

    (SCHEDULE-09 2단계, SCHEDULE-부분수정-해결방향-설계안.md 3절)

    pinned_items는 LLM에 echo를 요청하지 않고 이 함수가 구조적으로 최종
    결과에 병합한다 — LLM은 target_orders 자리에 들어갈 new_items만
    반환한다. 응답의 order 집합이 target_orders와 정확히 일치하는지 여기서
    직접 검증하고, 불일치하면 llm_output_invalid로 실패 처리한다(개수가
    요청마다 달라 ScheduleLLMPlan처럼 Pydantic Field로 정적 강제할 수 없다 —
    SchedulePartialLLMPlan 참고).

    elapsed_ms는 plan_schedule()과 같은 방식으로 이 함수 진입부터 결과 조립까지
    잰다(SCHEDULE-10 후속, RECOMMEND와 서버 소요시간 표시 방식을 맞춘다).
    """

    started_at = timer()
    effective_visit_datetime = request.visit_datetime or now_kst()

    if not request.target_orders:
        # 파싱 단계(SCHEDULE-09 1단계)가 REJECT_SPECIFIC일 때 항상 target_indices를
        # 채우므로 정상 흐름에서는 발생하지 않는다 — 방어적으로만 처리한다.
        return _pinned_only_result(
            request.pinned_items,
            effective_visit_datetime,
            _NO_FILL_CANDIDATES_ROUTE_SUMMARY,
            round((timer() - started_at) * 1000, 2),
        )

    if not request.candidates:
        # 유지 대상(pinned)과 거절 대상을 제외하고 나니 채울 수 있는 새 후보가
        # 아예 없다 — "일정 전체 실패"가 아니라 "일부만 대체 실패"이므로 pinned은
        # 그대로 살리고 실패 사실만 안내한다(전체 재구성으로 덮어쓰지 않음).
        return _pinned_only_result(
            request.pinned_items,
            effective_visit_datetime,
            _NO_FILL_CANDIDATES_ROUTE_SUMMARY,
            round((timer() - started_at) * 1000, 2),
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

    # 교체된 자리(new_items) 뒤에 이어지는 pinned 항목들의 도착 시각이 새 장소의
    # 실제 체류·이동 시간과 안 맞을 수 있다 — travel_to_next_min 무효화와 같은
    # 원인으로 발견된 별도 증상이다. travel_to_next_min을 아직 무효화하기 전인
    # 지금(원본 값 그대로) 재계산해야 앵커 이후 체인의 누적 합산이 정확하다.
    merged = _resync_downstream_arrivals(merged, expected_orders)

    # pinned 항목의 travel_to_next_min은 "직전 전체/부분 편성 때 그 다음 자리에
    # 있던 장소까지의 이동시간"을 그대로 들고 있다(agent_runtime.py가
    # session_context.shown_recommendations에서 재계산 없이 복사). 이번
    # target_orders 교체로 바로 다음 자리(order+1)가 새 장소로 바뀌었다면 그
    # 값은 더 이상 맞지 않는 이웃을 가리키는 stale 값이다 — LLM은 pinned
    # 항목을 다시 보지 않으므로(에코 신뢰 안 함 원칙) 이 함수가 재계산할 수
    # 없고, 재계산 없이 그대로 두면 잘못된 이동시간이 total_duration_min과
    # 프론트 표시에 그대로 섞여 들어간다. 새 값을 추정하기보다 모른다는 걸
    # 명시적으로 드러내는 게 "구조적 보장 우선" 원칙에 맞아 None으로 무효화한다
    # (실사용 리뷰로 발견, 2026-08-13).
    pinned_orders = {item.order for item in request.pinned_items}
    merged = [
        item.model_copy(update={"travel_to_next_min": None})
        if item.order in pinned_orders and (item.order + 1) in expected_orders
        else item
        for item in merged
    ]

    kept = len(request.pinned_items)
    replaced = len(plan.new_items)
    route_summary = f"{kept}곳은 그대로 유지하고 {replaced}곳을 새로운 장소로 바꿨어요."

    return ScheduleResult(
        items=_round_up_items_arrival(merged),
        total_duration_min=_total_duration_from_items(merged),
        route_summary=route_summary,
        basis_note=_build_basis_note(effective_visit_datetime),
        elapsed_ms=round((timer() - started_at) * 1000, 2),
    )


__all__ = ["plan_schedule", "plan_partial_schedule"]
