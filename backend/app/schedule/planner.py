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
    resolved_request = (
        request
        if request.visit_datetime is not None
        else request.model_copy(update={"visit_datetime": effective_visit_datetime})
    )

    plan = (await llm.generate_schedule_plan(resolved_request)).data

    return ScheduleResult(
        items=plan.items,
        total_duration_min=plan.total_duration_min,
        route_summary=plan.route_summary,
        basis_note=_build_basis_note(effective_visit_datetime),
    )


__all__ = ["plan_schedule"]
