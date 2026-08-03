"""집중률 응답 정규화에 사용하는 공통 정책."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeGuard

# 집중률이 20% 미만이면 한적한 상태로 본다.
CONCENTRATION_QUIET_MAX_EXCLUSIVE = 20.0

# 집중률이 50% 미만이면 보통 상태로 본다.
CONCENTRATION_NORMAL_MAX_EXCLUSIVE = 50.0

# 집중률이 70% 미만이면 다소 혼잡한 상태로 본다.
CONCENTRATION_SLIGHTLY_CROWDED_MAX_EXCLUSIVE = 70.0

# INFO 단일 장소 질의에서만 쓰는 대체 관광지 탐색 반경이다. 추천 후보 수집의
# 기본 반경과 구분하며, 실측 결과에 따라 조정할 수 있도록 정책 상수로 둔다.
INFO_CONCENTRATION_FALLBACK_RADIUS_KM = 0.5


class ConcentrationLevel(StrEnum):
    """A–C 계약에서 사용하는 집중률 단계 코드."""

    QUIET = "quiet"
    NORMAL = "normal"
    SLIGHTLY_CROWDED = "slightly_crowded"
    CROWDED = "crowded"


class ConcentrationLabel(StrEnum):
    """사용자 응답에 표시할 집중률 단계명."""

    QUIET = "한적함"
    NORMAL = "보통"
    SLIGHTLY_CROWDED = "다소 혼잡"
    CROWDED = "혼잡"


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
    if rate < CONCENTRATION_QUIET_MAX_EXCLUSIVE:
        return NormalizedConcentration(
            ConcentrationLevel.QUIET,
            ConcentrationLabel.QUIET,
        )
    if rate < CONCENTRATION_NORMAL_MAX_EXCLUSIVE:
        return NormalizedConcentration(
            ConcentrationLevel.NORMAL,
            ConcentrationLabel.NORMAL,
        )
    if rate < CONCENTRATION_SLIGHTLY_CROWDED_MAX_EXCLUSIVE:
        return NormalizedConcentration(
            ConcentrationLevel.SLIGHTLY_CROWDED,
            ConcentrationLabel.SLIGHTLY_CROWDED,
        )
    return NormalizedConcentration(
        ConcentrationLevel.CROWDED,
        ConcentrationLabel.CROWDED,
    )


__all__ = [
    "CONCENTRATION_NORMAL_MAX_EXCLUSIVE",
    "CONCENTRATION_QUIET_MAX_EXCLUSIVE",
    "CONCENTRATION_SLIGHTLY_CROWDED_MAX_EXCLUSIVE",
    "INFO_CONCENTRATION_FALLBACK_RADIUS_KM",
    "ConcentrationLabel",
    "ConcentrationLevel",
    "NormalizedConcentration",
    "is_valid_concentration_rate",
    "normalize_concentration",
]
