"""일정 예산 산수 — 개수와 체류시간이 같은 활동 가능 시간을 보게 만드는 곳. (TP-238)

**왜 이 모듈이 따로 있는가.** 같은 예산을 나눠 쓰는 규칙이 셋인데 서로를 몰랐다.
`target_item_range()`가 곳 수를 버킷 상수로 정하고, LLM이 장소별 체류시간을 제안하고,
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

from app.place_search_policy import WALKING_SPEED_KM_PER_MINUTE
from app.schedule.duration import VisitDurationPolicy, policy_for
from app.schedule.schemas import SchedulePlanningRequest
from app.schedule.timeline import (
    FALLBACK_TRAVEL_MINUTES,
    estimated_travel_minutes,
    travel_speed_km_per_minute,
)
from app.schemas import ScheduleBudgetStatus

# 요청한 활동 가능 시간과 실제 편성 결과 사이에 허용하는 오차(분).
#
# 예전에는 이 값이 response_composer에 `_DURATION_MATCH_TOLERANCE_MIN`이라는
# 이름으로 있었고 **표시에만** 쓰였다 — 라벨을 요청값으로 쓸지, 초과 안내를
# 붙일지. 편성 쪽에는 목표가 없어서 판정만 있고 지킬 방법이 없었다. 이제 편성이
# 이 값을 목표로 삼고 표시가 그 판정을 읽는다. **상수를 두 벌 두지 않는다.**
SCHEDULE_TIME_TOLERANCE_MIN = 30

# 한 일정에 넣을 수 있는 항목 수의 하드 캡. `ScheduleLLMPlan.items`의 `max_length`와
# 같은 수여야 한다 — 유도한 상한이 이 값을 넘으면 LLM 응답이 검증에서 거부된다.
MAX_SCHEDULE_ITEMS = 5

# 예산이 주어지지 않았을 때 쓰는 목표 개수 범위. 유도할 근거가 없으므로 기존 정책을
# 그대로 쓴다(프롬프트도 "3~4시간 내외"로 안내한다).
_ITEM_RANGE_WITHOUT_BUDGET = (3, MAX_SCHEDULE_ITEMS)


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


def travel_estimate_minutes(sorted_travel_min: Sequence[int], hops: int) -> int:
    """구간 `hops`개를 이동하는 데 걸릴 시간 추정(분).

    **후보들 사이 이동시간 중 짧은 것부터 `hops`개를 더한다.** 좋은 동선은 가까운
    구간을 쓰므로 실제 이동시간의 하한에 가깝다. `FALLBACK_TRAVEL_MINUTES`를 그대로
    곱하면 상한이 지나치게 보수적이 되는데, 그 값은 좌표를 못 구했을 때의 폴백이지
    실측이 아니다.

    하한을 쓰면 곳 수가 살짝 많게 나올 수 있다. **그쪽이 낫다고 봤다** — 남는 초과는
    `fit_durations_to_budget()`이 체류시간으로 흡수하고, 그래도 남으면
    `classify_budget()`이 알린다. 반대로 상한을 보수적으로 잡아 곳 수를 깎으면
    되돌릴 곳이 없다.

    거리 정보가 없으면(과거 세션 재생·단위 테스트) 폴백을 `hops`배 한다.
    """

    if hops <= 0:
        return 0
    if not sorted_travel_min:
        return FALLBACK_TRAVEL_MINUTES * hops
    picked = list(sorted_travel_min[:hops])
    # 후보가 적어 쌍이 hops개보다 적으면 남는 구간은 가장 짧은 값으로 메운다.
    picked += [sorted_travel_min[0]] * (hops - len(picked))
    return sum(picked)


def pairwise_travel_minutes(request: SchedulePlanningRequest) -> list[int]:
    """이번 요청의 후보 쌍 이동시간(분)을 오름차순으로.

    **시간표와 같은 환산 규칙을 쓴다**(`estimated_travel_minutes`). 여기서 따로
    나눗셈을 적으면 상한을 정한 가정과 시간표가 실제로 쓴 값이 갈린다.

    단 시간표는 실측 경로를 쓸 수도 있어서(TP-216) 이 추정과 어긋날 수 있다.
    상한은 LLM을 부르기 전에 정해야 하고 그때는 실측이 아직 없다 — 그 차이는
    체류시간 조절이 흡수하고, 남으면 판정이 알린다.
    """

    resolve = estimated_travel_minutes(
        request.pairwise_distances_km,
        speed_km_per_minute=travel_speed_km_per_minute(request.conditions),
    )
    minutes = [
        resolved
        for from_id, to_id in request.pairwise_distances_km
        if (resolved := resolve(from_id, to_id)) is not None
    ]
    return sorted(minutes)


def walkable_cluster_size(request: SchedulePlanningRequest, *, within_min: int) -> int:
    """도보 `within_min`분 안에 함께 묶을 수 있는 후보 수의 **근사 최대치**. (TP-242)

    근접 묶기(TP-243)가 대부분의 요청에 영향이 있는 기능인지 미리 재기 위한 값이다.
    이 수가 3 미만인 요청이 대부분이면 그 카드는 범위를 줄일 근거가 생긴다.

    **정확한 최대 묶음이 아니다.** 서로 모두 가까운 최대 집합을 구하는 것은 최대
    클리크 문제라 후보 수가 늘면 비싸진다. 여기서는 **한 후보를 중심으로 놓고 그
    반경 안에 들어오는 후보 수 + 1**의 최댓값을 쓴다 — 중심에서는 가깝지만 서로는
    먼 조합을 과대 계산할 수 있다. 지표는 추세를 보는 값이고, 실제 묶음 규칙은
    TP-243이 자기 기준으로 다시 정한다. **근사라는 사실을 이름이 아니라 이 주석이
    말한다** — 지표를 읽는 사람이 정확값으로 오해하면 잘못된 결론을 낸다.

    거리 정보가 없으면 0을 돌려준다 — "묶을 수 없다"가 아니라 "알 수 없다"이지만,
    그 구분은 이 지표의 목적(빈도 추세)에 필요하지 않다.
    """

    distances = request.pairwise_distances_km
    if not distances:
        return 0
    resolve = estimated_travel_minutes(
        distances, speed_km_per_minute=WALKING_SPEED_KM_PER_MINUTE
    )
    place_ids = sorted({place_id for pair in distances for place_id in pair})
    best = 0
    for center in place_ids:
        near = sum(
            1
            for other in place_ids
            if other != center
            and (minutes := resolve(center, other)) is not None
            and minutes <= within_min
        )
        best = max(best, near + 1)
    return best


def derive_item_range(
    request: SchedulePlanningRequest, *, hard_cap: int = MAX_SCHEDULE_ITEMS
) -> tuple[int, int]:
    """이번 요청에 맞는 일정 항목 개수의 (최소, 최대)를 예산 산수로 구한다.

    예전에는 버킷 상수였다 — 120분 미만이면 1~2곳, 210분 미만이면 2~4곳, 그
    이상이면 3~5곳. **그 상한이 예산과 안 맞았다.** 관광지 최소 체류 60분·이동
    15분 기준으로 2시간에 4곳은 최소 285분이다. 그런데 프롬프트는 그 상한까지
    채우라고 시켰다.

    지금은 이 부등식을 만족하는 최대 n이다.

        n곳의 체류 최소 합 + (n-1)구간 이동 추정 <= 활동 가능 시간 + 허용 오차

    **체류 최소는 이번 후보들의 분류에서 온다.** 60분을 상수로 박으면 박물관
    (최소 90분)과 쇼핑(최소 30분)이 같은 취급을 받는다. 작은 것부터 n개를 쓰는
    것은 이동 추정과 같은 방향(하한)이다 — 위 `travel_estimate_minutes()` 주석에
    이유가 있다.

    **허용 오차가 곳 수를 가른다.** 30분이면 3시간에 3곳까지 통과하고(60*3 +
    15*2 - 180 = 30) 4시간에 4곳은 45분이 필요해 자동으로 막힌다. 오차를 키우면
    "짧게 머물며 많이 넣기"로 새어나간다.

    최솟값은 후보 부족 가드에만 쓰인다("LLM을 부를 가치가 있는가"). 상한이 2곳
    이상이면 2, 아니면 1이다. 예전에는 예산이 길수록 최솟값도 3까지 올라가서
    4시간 요청에 후보가 2곳이면 편성을 아예 포기했는데, 그건 2곳을 보여주는
    것보다 나쁘다 — 이제 부족은 판정이 알리므로 조용히 나쁜 답이 나가지 않는다.
    """

    if request.conditions.time_available is None:
        return _ITEM_RANGE_WITHOUT_BUDGET

    stay_minimums = sorted(
        policy_for(candidate.category).minimum_min for candidate in request.candidates
    )
    travel_min = pairwise_travel_minutes(request)
    allowance = request.conditions.time_available + SCHEDULE_TIME_TOLERANCE_MIN

    max_items = 1
    for count in range(1, hard_cap + 1):
        if count > len(stay_minimums):
            break
        needed = sum(stay_minimums[:count]) + travel_estimate_minutes(travel_min, count - 1)
        if needed > allowance:
            # 체류·이동 모두 n에 대해 단조 증가라 더 큰 n도 넘는다.
            break
        max_items = count

    return min(2, max_items), max_items


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
    "MAX_SCHEDULE_ITEMS",
    "SCHEDULE_TIME_TOLERANCE_MIN",
    "DurationSlot",
    "classify_budget",
    "derive_item_range",
    "fit_durations_to_budget",
    "pairwise_travel_minutes",
    "travel_estimate_minutes",
    "walkable_cluster_size",
]
