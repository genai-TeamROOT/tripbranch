"""집중률 응답 정규화에 사용하는 공통 정책."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeGuard

# 평시 대비 집중률이 50% 이하이면 사람이 적은 상태로 본다.
CONCENTRATION_RELAXED_MAX = 50.0

# 평시 대비 집중률이 75% 이하이면 평소와 비슷한 상태로 본다.
CONCENTRATION_NORMAL_MAX = 75.0

# 평시 대비 집중률이 100% 이하이면 평소보다 약간 붐비는 상태로 본다.
CONCENTRATION_SLIGHTLY_CROWDED_MAX = 100.0


class ConcentrationLevel(StrEnum):
    """A–C 계약에서 사용하는 집중률 단계 코드."""

    RELAXED = "relaxed"
    NORMAL = "normal"
    SLIGHTLY_CROWDED = "slightly_crowded"
    CROWDED = "crowded"


class ConcentrationLabel(StrEnum):
    """사용자 응답에 표시할 집중률 단계명."""

    RELAXED = "여유"
    NORMAL = "보통"
    SLIGHTLY_CROWDED = "약간 붐빔"
    CROWDED = "붐빔"


@dataclass(frozen=True)
class NormalizedConcentration:
    level: ConcentrationLevel
    label: ConcentrationLabel


def is_valid_concentration_rate(rate: float | None) -> TypeGuard[float]:
    """음수가 아닌 유한 숫자만 상대 집중률로 사용한다."""

    return rate is not None and math.isfinite(rate) and rate >= 0


def normalize_concentration(rate: float) -> NormalizedConcentration:
    """평시 대비 상대 집중률을 합의된 네 단계로 변환한다."""

    if not is_valid_concentration_rate(rate):
        raise ValueError("집중률은 음수가 아닌 유한 숫자여야 합니다.")
    if rate <= CONCENTRATION_RELAXED_MAX:
        return NormalizedConcentration(
            ConcentrationLevel.RELAXED,
            ConcentrationLabel.RELAXED,
        )
    if rate <= CONCENTRATION_NORMAL_MAX:
        return NormalizedConcentration(
            ConcentrationLevel.NORMAL,
            ConcentrationLabel.NORMAL,
        )
    if rate <= CONCENTRATION_SLIGHTLY_CROWDED_MAX:
        return NormalizedConcentration(
            ConcentrationLevel.SLIGHTLY_CROWDED,
            ConcentrationLabel.SLIGHTLY_CROWDED,
        )
    return NormalizedConcentration(
        ConcentrationLevel.CROWDED,
        ConcentrationLabel.CROWDED,
    )


__all__ = [
    "CONCENTRATION_NORMAL_MAX",
    "CONCENTRATION_RELAXED_MAX",
    "CONCENTRATION_SLIGHTLY_CROWDED_MAX",
    "ConcentrationLabel",
    "ConcentrationLevel",
    "NormalizedConcentration",
    "is_valid_concentration_rate",
    "normalize_concentration",
]
