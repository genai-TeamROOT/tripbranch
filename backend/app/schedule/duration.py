"""장소별 체류시간 정책. (TP-215)

**왜 필요한가.** 지금까지 `estimated_duration_min`은 프롬프트 예시("카페 60분,
관광지 90분")를 보고 LLM이 추정한 값이었다. 예시일 뿐이라 범위를 벗어난 값이
와도 막을 곳이 없었고, "개수를 맞추겠다고 카페 20분"처럼 비현실적으로 줄어드는
사례가 SCHEDULE-10에서 실제로 관측됐다. 프롬프트로 부탁하는 대신 엔진이
범위로 확정한다(SCHEDULE-07의 "LLM 지시 준수보다 구조적 보장을 우선한다").

**분류 어휘.** `RecommendationItem.category`는 `PlaceType` 값이다
(`providers/mappers.py`의 contentTypeId → PlaceType 매핑). 그래서 카페와 식당을
가를 수 없다 — 둘 다 `restaurant`다. 세분화하려면 `lcls_systm2`를
`RecommendationItem`까지 올려야 하는데 그건 D 소유 스키마라 이번 범위 밖이다.
`restaurant`의 최소값을 60분으로 둬서 프롬프트가 안내하는 "카페 60분"이 범위
안에 들어오게 맞췄다.

**아직 쓰지 않는 것.** `place_enrichments.estimated_visit_minutes` 컬럼이 있지만
값이 채워져 있지 않아 이번에는 참조하지 않는다. 채워지면
`resolve_visit_duration()`의 `stored_min` 인자로 넣기만 하면 된다 — 우선순위는
이미 그 자리에 뚫어뒀다.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas import PlaceType


@dataclass(frozen=True)
class VisitDurationPolicy:
    """한 분류의 체류시간 범위(분)."""

    minimum_min: int
    preferred_min: int
    maximum_min: int

    def clamp(self, minutes: int) -> int:
        return max(self.minimum_min, min(minutes, self.maximum_min))


# 분류별 (최소, 권장, 최대). 근거는 프롬프트가 이미 안내하던 체류시간 예시다.
# **이 최소값이 개수 상한을 정하는 입력이다** — budget.derive_item_range()가
# 이 값을 읽어 몇 곳이 예산에 들어가는지 계산한다(TP-239). 예전에는 개수 쪽이
# 자기 가정(장소당 60~90분)을 따로 갖고 있어서 "개수는 맞는데 시간이 안 맞는"
# 일정이 나왔다. 이제 한 곳에서만 읽으므로 이 값을 바꾸면 상한도 함께 움직인다.
_POLICY_BY_CATEGORY: dict[str, VisitDurationPolicy] = {
    PlaceType.ATTRACTION.value: VisitDurationPolicy(60, 90, 120),
    PlaceType.CULTURAL_FACILITY.value: VisitDurationPolicy(90, 120, 180),
    PlaceType.FESTIVAL.value: VisitDurationPolicy(60, 90, 150),
    PlaceType.LEISURE.value: VisitDurationPolicy(60, 90, 150),
    PlaceType.SHOPPING.value: VisitDurationPolicy(30, 60, 90),
    PlaceType.RESTAURANT.value: VisitDurationPolicy(60, 90, 120),
}

# 분류를 모르는 후보("unknown" 또는 매핑에 없는 값)의 폴백. 범위를 넓게 두는 것은
# 모르는 장소에 엔진이 강한 주장을 하지 않기 위해서다 — LLM 제안을 그대로
# 살려주는 쪽에 가깝다.
_DEFAULT_POLICY = VisitDurationPolicy(40, 60, 150)


def policy_for(category: str | None) -> VisitDurationPolicy:
    """분류에 맞는 체류시간 정책. 모르는 분류는 폴백을 돌려준다."""

    if category is None:
        return _DEFAULT_POLICY
    return _POLICY_BY_CATEGORY.get(category.strip().lower(), _DEFAULT_POLICY)


def resolve_visit_duration(
    *,
    category: str | None,
    proposed_min: int | None = None,
    stored_min: int | None = None,
    user_specified_min: int | None = None,
) -> int:
    """이 장소에 실제로 배정할 체류시간(분)을 확정한다.

    우선순위는 사용자 지정 → 저장된 장소별 값 → LLM 제안 → 분류 권장값이고,
    **어느 경로로 왔든 마지막에 분류 범위로 자른다.** 사용자 지정값까지 자르는
    것이 맞는지는 한 번 갈렸는데, 자르는 쪽으로 정했다 — 여기서 통과시키면
    시간표 계산은 맞아도 "관광지 10분"처럼 사람이 못 지키는 일정이 나가고,
    그걸 걸러줄 곳이 뒤에 없다.

    0 이하와 None은 같게 취급한다. LLM이 0을 주는 것은 값을 만들지 못했다는
    뜻이지 "머물지 않는다"는 뜻이 아니다.
    """

    policy = policy_for(category)
    for proposal in (user_specified_min, stored_min, proposed_min):
        if proposal is not None and proposal > 0:
            return policy.clamp(proposal)
    return policy.preferred_min


__all__ = [
    "VisitDurationPolicy",
    "policy_for",
    "resolve_visit_duration",
]
