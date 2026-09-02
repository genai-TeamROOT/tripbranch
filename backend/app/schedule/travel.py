"""일정 구간 이동시간을 추정하고, 확정된 구간만 실측으로 덮는다. (TP-216)

**왜 별도 모듈인가.** 시간표 계산기(`timeline.py`)는 이동시간을 콜러블로 주입받는
동기 함수다(TP-215). 실측은 외부 API 호출이라 비동기이고, 어느 구간을 잴지는
LLM이 순서를 정한 뒤에야 정해진다. 그래서 "순서가 정해진 뒤 필요한 구간만 미리
확정해 표로 만들고, 시간표에는 그 표를 읽는 콜러블을 넘긴다"로 나눈다.
`timeline.py`는 이 카드에서 한 줄도 바뀌지 않는다.

**속도 상수를 어디서 가져오는가.** `place_search_policy`의 값을 mps로 환산해
넘긴다. `Settings.walking_speed_mps`(1.2 = 4.32km/h)와
`Settings.driving_speed_mps`(5.5 = 19.8km/h)를 쓰지 않는 이유는 검색 반경을 만든
가정과 분모를 맞추기 위해서다 — 차이가 3% 남짓이라 화면으로도 테스트로도 안 잡히지만,
`place_search_policy.NON_WALKING_SPEED_KM_PER_MINUTE` 주석이 못 박은 불변식이
조용히 깨진다. `estimate_schedule_travel_edges()`가 속도를 인자로 받고 설정을 직접
읽지 않는 설계라 호출자 쪽에서 닫을 수 있다.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from app.config import Settings
from app.domain.schedule_travel import (
    ScheduleTravelCandidate,
    ScheduleTravelEdge,
    ScheduleTravelPair,
)
from app.place_search_policy import (
    NON_WALKING_SPEED_KM_PER_MINUTE,
    WALKING_SPEED_KM_PER_MINUTE,
)
from app.schedule.timeline import TravelMinutes
from app.schemas import UserConditions
from app.tools.schedule_travel import (
    estimate_schedule_travel_edges,
    measure_schedule_travel_edges,
)
from app.tools.travel_route import TravelRouteTool

logger = logging.getLogger(__name__)


def _to_mps(km_per_minute: float) -> float:
    """km/분 → m/초."""

    return km_per_minute * 1000.0 / 60.0


# 반경 산정과 같은 가정을 mps로 옮긴 값. 여기서만 환산하고 다른 곳에 복사하지 않는다.
WALKING_SPEED_MPS = _to_mps(WALKING_SPEED_KM_PER_MINUTE)
NON_WALKING_SPEED_MPS = _to_mps(NON_WALKING_SPEED_KM_PER_MINUTE)


def consecutive_pairs(place_ids: Sequence[str]) -> tuple[ScheduleTravelPair, ...]:
    """방문 순서에서 실제로 쓰이는 방향 구간만 뽑는다.

    후보 전체의 행렬을 만들지 않는다 — 후보 10곳이면 방향 간선이 90개이고,
    TP-191(D-113)이 정확히 그 비용 때문에 실측 대상을 좁혔다. 일정이 3~5곳이면
    구간은 2~4개다.
    """

    return tuple(
        ScheduleTravelPair(from_place_id=first, to_place_id=second)
        for first, second in zip(place_ids, place_ids[1:], strict=False)
        if first != second
    )


def travel_minutes_from_edges(edges: Sequence[ScheduleTravelEdge]) -> TravelMinutes:
    """구간 표를 읽는 콜러블. 표에 없는 구간은 None을 돌려준다.

    **방향을 지킨다.** 직선거리 행렬(`estimated_travel_minutes()`)은 방향이 없어
    양쪽 키를 다 봤지만, 실측은 왕복이 다를 수 있어 반대 방향으로 대신 답하지 않는다.
    없으면 None이고, 시간표가 폴백값(15분)으로 메운다.
    """

    by_pair = {(edge.from_place_id, edge.to_place_id): edge for edge in edges}

    def resolve(from_place_id: str, to_place_id: str) -> int | None:
        edge = by_pair.get((from_place_id, to_place_id))
        return None if edge is None else max(1, edge.duration_min)

    return resolve


async def resolve_schedule_travel_edges(
    *,
    candidates: Sequence[ScheduleTravelCandidate],
    place_ids: Sequence[str],
    conditions: UserConditions,
    settings: Settings,
    travel_route_tool: TravelRouteTool | None,
) -> tuple[ScheduleTravelEdge, ...]:
    """확정된 방문 순서의 구간 이동정보를 만든다. 실패해도 예외를 올리지 않는다.

    추정을 먼저 만들고, 경로 Tool이 주어졌을 때만 그 위를 실측으로 덮는다
    (TP-219의 `measure_schedule_travel_edges()`). 실측하지 못한 구간은 추정값 그대로
    남고 `source`·`confidence`에 그 사실이 실린다 — 조용히 사라지거나 0분이 되지
    않는다.

    좌표가 없으면 빈 결과를 돌려준다. 그러면 시간표가 구간마다 폴백값을 쓰므로
    편성 자체는 막히지 않는다(기존 동작과 같다).
    """

    if not candidates or len(place_ids) < 2:
        return ()

    pairs = consecutive_pairs(place_ids)
    if not pairs:
        return ()

    try:
        estimated = estimate_schedule_travel_edges(
            candidates=candidates,
            pairs=pairs,
            transport=conditions.transport,
            walking_speed_mps=WALKING_SPEED_MPS,
            transit_speed_mps=NON_WALKING_SPEED_MPS,
            driving_speed_mps=NON_WALKING_SPEED_MPS,
            walk_transfer_threshold_min=settings.schedule_walk_transfer_threshold_min,
        )
    except ValueError:
        # 후보 목록이 잘못 만들어진 경우(중복 place_id 등)까지 편성을 막지 않는다.
        logger.warning("schedule_travel.estimate_failed", exc_info=True)
        return ()

    if travel_route_tool is None or not estimated.edges:
        return estimated.edges

    try:
        measured = await measure_schedule_travel_edges(
            tool=travel_route_tool,
            candidates=candidates,
            estimated_edges=estimated.edges,
            max_measured_segments=settings.schedule_max_measured_segments,
        )
    except Exception:
        # 실측이 통째로 실패해도 추정값으로 일정을 낸다("구조적 보장 우선").
        logger.warning("schedule_travel.measure_failed", exc_info=True)
        return estimated.edges

    return measured.edges


__all__ = [
    "NON_WALKING_SPEED_MPS",
    "WALKING_SPEED_MPS",
    "consecutive_pairs",
    "resolve_schedule_travel_edges",
    "travel_minutes_from_edges",
]
