"""일정 예산 산수 — 개수와 체류시간이 같은 활동 가능 시간을 보게 만드는 곳. (TP-238)

**왜 이 모듈이 따로 있는가.** 같은 예산을 나눠 쓰는 규칙이 셋인데 서로를 몰랐다.
`schemas.target_item_range()`가 곳 수를 정하고, LLM이 장소별 체류시간을 제안하고,
`duration.resolve_visit_duration()`이 그 제안을 분류별 범위로 자른다. 셋 중
**어느 것도 활동 가능 시간을 보지 않는다.** `timeline`이 마지막에 합산할 뿐이고
합이 예산을 넘어도 조정하는 곳이 없어서, "3시간 코스"가 4시간 26분으로 나갔다.

`duration.py`가 이 함정을 미리 적어뒀다 — "두 곳이 서로 다른 가정을 쓰면 개수는
맞는데 시간이 안 맞는 일정이 나온다." 고치려면 **예산을 아는 자리가 하나** 있어야
하고, 그게 이 모듈이다.

**허용 오차가 왜 필요한가.** 관광지 최소 체류가 60분이고 구간 이동이 15분이면
3시간에 3곳은 아무리 줄여도 210분이라 정확히는 못 맞춘다. 오차를 안 두면 그런
요청이 2곳으로 떨어진다 — 시간은 지켜지지만 좋은 답이 아니다. 30분은 임의값이
아니라 **"3시간에 3곳"이 통과하는 최소 문턱**이다(60*3 + 15*2 - 180 = 30). 같은
계산으로 4시간에 4곳은 45분이 필요해서 자동으로 막힌다 — 오차를 키우면 "짧게
많이" 쪽으로 새어나간다는 뜻이라, 이 값은 밀도 상한을 겸한다.

**무엇을 고르는지는 건드리지 않는다.** 이미 고른 장소의 체류시간만 분류별 정책
범위 안에서 조절한다. 후보 선정에 근접도를 섞으면 좋은 장소가 밀리고, 구 단위
요청에서 거리 축 영향을 줄인 SCORING_VERSION 1.9.0 방향과도 어긋난다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.schedule.duration import VisitDurationPolicy
from app.schemas import ScheduleBudgetStatus

# 요청한 활동 가능 시간과 실제 편성 결과 사이에 허용하는 오차(분).
#
# 예전에는 이 값이 response_composer에 `_DURATION_MATCH_TOLERANCE_MIN`이라는
# 이름으로 있었고 **표시에만** 쓰였다 — 라벨을 요청값으로 쓸지, 초과 안내를
# 붙일지. 편성 쪽에는 목표가 없어서 판정만 있고 지킬 방법이 없었다. 이제 편성이
# 이 값을 목표로 삼고 표시가 그 판정을 읽는다. **상수를 두 벌 두지 않는다.**
SCHEDULE_TIME_TOLERANCE_MIN = 30


@dataclass(frozen=True)
class DurationSlot:
    """체류시간 조절 대상 한 자리.

    `policy`가 None이면 **이 자리는 조절하지 않는다.** 부분 재편성에서 사용자가
    유지하기로 한 항목(pinned)이 그렇다 — `_draft_from_schedule_item()` 주석의
    "그대로 뒀다는 약속"과 같은 근거다. 후보 목록에 없는 place_id가 곧 pinned라는
    기존 불변식(`_compose_items()` 주석)을 그대로 쓴다.
    """

    current_min: int
    policy: VisitDurationPolicy | None = None


def classify_budget(
    total_duration_min: int, time_available_min: int | None
) -> ScheduleBudgetStatus | None:
    """편성 결과가 요청한 시간을 지켰는지 판정한다.

    사용자가 시간을 말하지 않았으면(None) 판정할 것이 없다 — "지켰다"도 "넘었다"도
    아니므로 None을 돌려준다. 0으로 뭉개면 화면이 지키지도 않은 약속을 말하게 된다.
    """

    if time_available_min is None:
        return None
    difference = total_duration_min - time_available_min
    if difference > SCHEDULE_TIME_TOLERANCE_MIN:
        return ScheduleBudgetStatus.OVER
    if difference < -SCHEDULE_TIME_TOLERANCE_MIN:
        return ScheduleBudgetStatus.UNDER
    return ScheduleBudgetStatus.WITHIN


def fit_durations_to_budget(
    slots: Sequence[DurationSlot], *, overhead_min: int, budget_min: int | None
) -> list[int]:
    """체류시간을 활동 가능 시간에 맞춰 조절한 값을 돌려준다.

    `overhead_min`은 체류가 아닌 시간(구간 이동 + 개장 전 대기)의 합이다. 총
    소요시간에서 체류 합계를 뺀 값이라 호출부가 시간표에서 그대로 구한다 — 여기서
    다시 계산하지 않는다. 다시 계산하면 시간표가 쓴 이동시간과 갈릴 수 있다.

    **정책 범위를 넘지 않는다.** 예산을 맞추려고 "관광지 10분"을 만들지 않는다.
    여유를 다 써도 남는 차이는 그대로 두고, 그 사실은 `classify_budget()`이
    판정으로 알린다 — 조용히 어기지 않는다.

    **비례 배분이고 재배정이 아니다.** 자리마다 남은 여유에 비례해 나누므로 LLM이
    매긴 항목 간 상대 크기가 유지된다. 균등하게 깎으면 "국립박물관은 더 오래"라는
    판단이 사라진다.

    **이미 허용 오차 안이면 아무것도 하지 않는다.** 판정이 곧 목표라서, 목표를
    만족한 편성을 굳이 예산에 딱 맞게 늘리거나 줄일 이유가 없다. 그리고 밴드 안에서
    체류를 늘리는 것은 "사용자가 말한 3시간은 꽉 채워 다니겠다는 뜻"이라고 가정하는
    것인데, 팀이 그렇게 합의한 기록이 없다 — 이 함수가 혼자 정할 문제가 아니다.
    """

    current = [slot.current_min for slot in slots]
    if budget_min is None or not slots:
        return current

    total_min = sum(current) + overhead_min
    if classify_budget(total_min, budget_min) is ScheduleBudgetStatus.WITHIN:
        return current

    delta = (budget_min - overhead_min) - sum(current)
    if delta == 0:
        return current

    if delta < 0:
        headroom = [
            max(0, slot.current_min - slot.policy.minimum_min) if slot.policy else 0
            for slot in slots
        ]
    else:
        headroom = [
            max(0, slot.policy.maximum_min - slot.current_min) if slot.policy else 0
            for slot in slots
        ]

    available = sum(headroom)
    if available == 0:
        return current

    move = min(abs(delta), available)
    shares = [room * move // available for room in headroom]
    # 정수 나눗셈에서 남는 분은 여유가 큰 자리부터 1분씩 준다. 여유가 같으면 앞
    # 자리부터 — 같은 입력에 같은 결과가 나와야 테스트가 성립한다.
    remainder = move - sum(shares)
    for index in sorted(range(len(slots)), key=lambda i: (-headroom[i], i)):
        if remainder == 0:
            break
        if shares[index] < headroom[index]:
            shares[index] += 1
            remainder -= 1

    sign = 1 if delta > 0 else -1
    return [value + sign * share for value, share in zip(current, shares, strict=True)]


__all__ = [
    "SCHEDULE_TIME_TOLERANCE_MIN",
    "DurationSlot",
    "classify_budget",
    "fit_durations_to_budget",
]
