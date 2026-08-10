"""일정 편성 모듈(app.schedule)의 입력 스키마.

역할: 상태 저장소에 의존하지 않는 신규 모듈이 LLM으로 일정을 편성하는 데
필요한 입력을 정의한다. (docs/design/int-07-schedule.md 6.0~6.1절)

출력 스키마(ScheduleItem/ScheduleResult)는 app.schemas에 있다 — AgentResponse가
그 타입을 참조해야 해서(app.schemas → app.schedule 방향 import가 생기면 순환
참조가 된다), 응답에 실리는 출력 스키마는 RecommendationResponse와 같은 위치인
app.schemas에 두고, 이 모듈에는 이 모듈만 쓰는 입력 스키마만 둔다.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas import RecommendationItem, ScheduleItem, UserConditions


class SchedulePlanningRequest(BaseModel):
    """일정 편성 LLM 호출 입력. (docs/design/int-07-schedule.md 6.1절)"""

    candidates: list[RecommendationItem]
    # D의 공개 응답 스키마(RecommendationItem)를 쓴다. D 내부 도메인 타입
    # (app.domain.scoring.RankedCandidate)은 레이어 경계를 넘어가므로 쓰지 않는다.

    conditions: UserConditions
    # 기존 15개 조건 그대로 사용(time_available, transport 등 이미 있는 필드 재사용)

    visit_datetime: datetime | None = None
    # 방문 예정 시각

    pairwise_distances_km: dict[tuple[str, str], float]
    # app.geo.haversine_km()로 계산해 LLM에 근거로 제공한다. RecommendationItem에는
    # 위경도가 없어(distance_km는 검색 중심 기준 거리) D 응답만으로는 후보 간 거리를
    # 못 구한다 — A가 C의 AgentContextResponse.places(위경도 보유)를 place_id로
    # 매칭해 계산해서 넘긴다. D/C 스키마 변경 불필요. 내부 함수 인자로만 쓰여
    # JSON으로 직렬화되지 않으므로 튜플 키를 그대로 써도 된다.


class ScheduleLLMPlan(BaseModel):
    """generate_schedule_plan() 구조화 출력 전용 모델.

    app.schemas.ScheduleResult에서 basis_note만 뺀 형태다. basis_note는 LLM이
    생성하지 않고 app.schedule.planner가 visit_datetime 값으로 결정적으로
    채운다(docs/design/int-07-schedule.md 6.2.1절) — 이 모델은 LLM 응답 검증에만
    쓰이고 AgentResponse에는 직접 실리지 않는다.

    items에 min_length=3/max_length=5 제약을 건다(SCHEDULE-07, 9절 "3~5개 선택
    지시 미준수" 미결 사항 해소). 이전에는 "후보가 3개 미만이면 매번 검증 실패로
    대화가 끊긴다"는 우려로 제약을 피했지만, app.schedule.planner.plan_schedule()이
    이제 후보 3개 미만이면 LLM을 아예 호출하지 않아 이 제약은 실제로 호출되는
    경로에서는 항상 만족 가능하다. 검증 실패 시 app.providers.gemini.py의
    _call_structured()가 이미 한 번 자동 재시도(오류 안내를 붙여 재요청)하므로
    LLM이 첫 시도에 정확히 지키지 못해도 완전히 하드 실패로 이어지진 않는다.
    """

    items: list[ScheduleItem] = Field(min_length=3, max_length=5)
    total_duration_min: int
    route_summary: str


__all__ = ["SchedulePlanningRequest", "ScheduleLLMPlan"]
