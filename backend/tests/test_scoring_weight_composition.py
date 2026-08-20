"""가중치 조립(build_weights) 회귀 검증.

조합별 가중치 상수를 열거하던 방식을 "켜진 선택 Feature로 조립"으로 바꾼 뒤,
**기존 세 세트가 숫자 하나까지 그대로인지**를 고정한다. 여기가 깨지면 과거
버전의 점수를 재현할 수 없다.

조립 규칙 자체(선택 Feature 1개당 기본 3축이 0.05씩 양보)도 여기서 고정한다.
"""

from __future__ import annotations

import pytest

from app.domain.scoring import (
    CONCENTRATION_WEIGHTS,
    DEFAULT_WEIGHTS,
    OPTIONAL_FEATURES,
    TASTE_WEIGHTS,
    build_weights,
)

# 조립 방식으로 바꾸기 전에 코드에 하드코딩돼 있던 값 그대로. 상수를 import해서
# 비교하면 "자기 자신과 같다"가 되므로 여기 숫자를 직접 적는다.
_LEGACY_DEFAULT = {"weather": 0.4, "remaining_operating_time": 0.4, "distance": 0.2}
_LEGACY_CONCENTRATION = {
    "weather": 0.35,
    "remaining_operating_time": 0.35,
    "distance": 0.15,
    "concentration": 0.15,
}
_LEGACY_TASTE = {
    "weather": 0.35,
    "remaining_operating_time": 0.35,
    "distance": 0.15,
    "taste": 0.15,
}


@pytest.mark.parametrize(
    ("active", "expected"),
    [
        ((), _LEGACY_DEFAULT),
        (("concentration",), _LEGACY_CONCENTRATION),
        (("taste",), _LEGACY_TASTE),
    ],
)
def test_build_weights_reproduces_legacy_sets(
    active: tuple[str, ...], expected: dict[str, float]
) -> None:
    assert build_weights(active) == expected


def test_exported_constants_match_legacy_sets() -> None:
    """import해서 쓰는 쪽(테스트 픽스처 포함)이 보는 값도 그대로여야 한다."""
    assert dict(DEFAULT_WEIGHTS) == _LEGACY_DEFAULT
    assert dict(CONCENTRATION_WEIGHTS) == _LEGACY_CONCENTRATION
    assert dict(TASTE_WEIGHTS) == _LEGACY_TASTE


def test_taste_and_concentration_together_sums_to_one() -> None:
    """조립 이전에는 존재하지 않던 조합. 기본 3축이 0.05씩 더 양보한다."""
    weights = build_weights(("taste", "concentration"))
    assert weights == {
        "weather": 0.3,
        "remaining_operating_time": 0.3,
        "distance": 0.1,
        "taste": 0.15,
        "concentration": 0.15,
    }


@pytest.mark.parametrize("count", range(len(OPTIONAL_FEATURES) + 1))
def test_every_combination_sums_to_one(count: int) -> None:
    weights = build_weights(OPTIONAL_FEATURES[:count])
    assert sum(weights.values()) == pytest.approx(1.0)
    assert all(weight > 0 for weight in weights.values())


def test_unknown_optional_feature_raises() -> None:
    """오타를 조용히 무시하면 그 Feature가 점수에서 빠진 채 정상처럼 돈다."""
    with pytest.raises(ValueError, match="알 수 없는 선택 Feature"):
        build_weights(("tast",))


def test_optional_feature_order_does_not_change_weights() -> None:
    assert build_weights(("concentration", "taste")) == build_weights(("taste", "concentration"))
