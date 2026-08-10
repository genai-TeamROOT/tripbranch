"""일정 편성 모듈의 실행 로직.

역할: SchedulePlanningRequest를 받아 LLM으로 일정을 편성하고 ScheduleResult를
반환한다. 상태 저장소(StateStore)에 의존하지 않는 순수 입력→출력 함수다 —
A(agent_runtime.py)가 D(RecommendationProvider)를 호출하는 것과 동일한 방식으로
이 모듈을 호출한다(docs/design/int-07-schedule.md 6.0절, B의 "판단하지 않는
기억 장치" 원칙과 무관하게 B 코드는 전혀 건드리지 않는다).
"""

from __future__ import annotations

from datetime import datetime

from app.providers.protocols import LLMProvider
from app.schedule.schemas import SchedulePlanningRequest
from app.schemas import ScheduleResult
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


__all__ = ["plan_schedule"]
