"""체류시간 정책 (TP-215)."""

from __future__ import annotations

import pytest

from app.schedule.duration import policy_for, resolve_visit_duration
from app.schemas import PlaceType


def test_known_category_uses_its_preferred_value() -> None:
    """제안값이 없으면 분류 권장값으로 채운다."""

    assert resolve_visit_duration(category=PlaceType.ATTRACTION.value) == 90
    assert resolve_visit_duration(category=PlaceType.SHOPPING.value) == 60
    assert resolve_visit_duration(category=PlaceType.CULTURAL_FACILITY.value) == 120


def test_proposal_inside_the_range_is_kept() -> None:
    """범위 안의 LLM 제안은 그대로 살린다 — 엔진이 불필요하게 덮어쓰지 않는다."""

    assert resolve_visit_duration(category=PlaceType.ATTRACTION.value, proposed_min=75) == 75


def test_proposal_below_minimum_is_raised() -> None:
    """"개수를 맞추겠다고 카페 20분"이 이 경로로 막힌다(SCHEDULE-10에서 관측된 사례)."""

    assert resolve_visit_duration(category=PlaceType.RESTAURANT.value, proposed_min=20) == 60


def test_proposal_above_maximum_is_capped() -> None:
    assert resolve_visit_duration(category=PlaceType.SHOPPING.value, proposed_min=600) == 90


def test_unknown_category_falls_back_to_a_wide_range() -> None:
    """분류를 모르는 후보에는 엔진이 강한 주장을 하지 않는다."""

    assert resolve_visit_duration(category="unknown") == 60
    assert resolve_visit_duration(category=None, proposed_min=140) == 140
    assert resolve_visit_duration(category="처음 보는 분류", proposed_min=5) == 40


@pytest.mark.parametrize("proposed", [0, -30, None])
def test_missing_or_nonpositive_proposal_uses_preferred(proposed: int | None) -> None:
    """LLM이 0을 주는 것은 "머물지 않는다"가 아니라 값을 못 만들었다는 뜻이다."""

    assert resolve_visit_duration(category=PlaceType.ATTRACTION.value, proposed_min=proposed) == 90


def test_priority_is_user_then_stored_then_proposed() -> None:
    resolved = resolve_visit_duration(
        category=PlaceType.ATTRACTION.value,
        proposed_min=70,
        stored_min=80,
        user_specified_min=110,
    )
    assert resolved == 110

    without_user = resolve_visit_duration(
        category=PlaceType.ATTRACTION.value,
        proposed_min=70,
        stored_min=80,
    )
    assert without_user == 80


def test_user_specified_value_is_still_clamped() -> None:
    """사용자 지정값도 범위로 자른다 — 여기서 통과시키면 걸러줄 곳이 뒤에 없다."""

    assert (
        resolve_visit_duration(category=PlaceType.ATTRACTION.value, user_specified_min=10) == 60
    )


def test_restaurant_minimum_admits_the_cafe_guidance() -> None:
    """카페와 식당은 같은 분류라 가를 수 없다(RecommendationItem.category = PlaceType).

    프롬프트가 안내하는 "카페 60분"이 restaurant 범위 안에 들어오는지 잠근다 —
    최소값을 올리면 카페 제안이 조용히 90분으로 부풀려진다.
    """

    assert policy_for(PlaceType.RESTAURANT.value).minimum_min <= 60
    assert resolve_visit_duration(category=PlaceType.RESTAURANT.value, proposed_min=60) == 60
