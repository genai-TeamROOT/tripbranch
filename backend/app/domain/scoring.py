"""Scoring v1: Candidate 목록에 하드 필터와 가중치 점수를 적용해 정렬한다.

역할: `ScoringCandidate` 목록을 받아 이전 노출/거절 후보와 폐점 후보(운영 유무
최종 판정)를 제외하고, 날씨·거리·남은 운영시간 Feature로 가중치 점수를 계산해
정렬한다. 카테고리(place_type/place_tag) 하드 필터는 Scoring 이전 단계에서
이미 처리됐다고 전제한다.
입력: `ScoringCandidate` 목록과 실행 조건(기준 시각, 날씨, 검색 반경, 이전
노출·거절 ID).
출력: `ScoringResult` (정렬된 `RankedCandidate` 목록, 후보별 사용 가중치,
제외 ID).
호출 시점: 추천 파이프라인이 카테고리 필터를 마친 뒤 순위를 매길 때 호출한다.
설계 근거: `docs/design/recommendation-scoring.md` 참고.
TODO: 혼잡도 Feature, 실제 이동시간 기반 거리, 예산/동행 하드 필터는 v2 이후.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.concentration_policy import ConcentrationLevel
from app.domain.models import OperatingHours, ScoringCandidate, WeatherCondition
from app.domain.travel_route import RouteStatus, WalkingRoute
from app.domain.weather_judgment import WeatherReason
from app.place_search_policy import WALKING_SPEED_KM_PER_MINUTE

# B의 LLMOps Trace(record_trace(scoring_version=...))에 넘길 값 —
# backend/docs/package-b/llmops-trace-contract-v1.md §7 Q2. B는 이 값의 의미를
# 해석하지 않고 문자열로만 저장한다(B-01 경계 원칙). operating_hours.py의
# OPERATING_PARSER_VERSION과 동일한 semver 패턴. 점수 산출에 영향을 주는 변경
# (가중치, Feature 추가/제거, environment_type 판정표 등) 시 버전을 올린다 —
# 사소한 리팩터링·주석 변경은 올리지 않는다.
SCORING_VERSION = "recommendation-scoring-1.2.0"

DEFAULT_WEIGHTS: Mapping[str, float] = {
    "weather": 0.4,
    "remaining_operating_time": 0.4,
    "distance": 0.2,
}

# D-040: concentration_intent가 AVOID/SEEK일 때만 쓰는 2차 Scoring 기본 가중치.
# 1차 Scoring(DEFAULT_WEIGHTS)은 이 이름 자체를 모른다 — concentration은 1차에
# "결측"이 아니라 "존재하지 않는 Feature"다(concentration-conditions.md §2.3).
CONCENTRATION_WEIGHTS: Mapping[str, float] = {
    "weather": 0.35,
    "remaining_operating_time": 0.35,
    "distance": 0.15,
    "concentration": 0.15,
}

# 남은 운영시간이 이 값(분) 이상이면 만점(1.0)으로 취급한다.
_REMAINING_TIME_FULL_SCORE_MINUTES = 120.0

_WEATHER_FIT_TABLE: Mapping[tuple[WeatherCondition, str], float] = {
    (WeatherCondition.GOOD, "indoor"): 0.70,
    (WeatherCondition.GOOD, "outdoor"): 1.00,
    (WeatherCondition.GOOD, "unknown"): 0.85,
    (WeatherCondition.NEUTRAL, "indoor"): 0.80,
    (WeatherCondition.NEUTRAL, "outdoor"): 0.80,
    (WeatherCondition.NEUTRAL, "unknown"): 0.80,
    (WeatherCondition.BAD, "indoor"): 1.00,
    (WeatherCondition.BAD, "outdoor"): 0.30,
    (WeatherCondition.BAD, "unknown"): 0.60,
}
_WEATHER_FIT_DEFAULT = 0.80

# 사용자가 실내/실외를 명시했는데 날씨 언급이 없으면, 날씨 사실 대신 이 표로
# 같은 자리의 Feature 점수를 매긴다(D-051 문제 5의 후속). 값은
# _WEATHER_FIT_TABLE의 BAD 행과 같은 폭이다 — "명시적으로 피해야 할 환경"에
# 이미 쓰던 간격이라 근거 없는 숫자를 새로 만들지 않았다.
_ENVIRONMENT_FIT_TABLE: Mapping[tuple[str, str], float] = {
    ("indoor", "indoor"): 1.00,
    ("indoor", "outdoor"): 0.30,
    ("indoor", "unknown"): 0.60,
    ("outdoor", "outdoor"): 1.00,
    ("outdoor", "indoor"): 0.30,
    ("outdoor", "unknown"): 0.60,
}
_ENVIRONMENT_FIT_DEFAULT = 0.60

WEATHER_FEATURE = "weather"
ENVIRONMENT_FEATURE = "environment"

# 이 두 값일 때만 환경으로 채점한다. `any`는 "실내외 무관"이라 제외한다 —
# 되묻기 기본값이 ANY라(D-053) 여기 넣으면 되묻기 답변 경로 전체가 환경
# 판정으로 넘어간다.
_ENVIRONMENT_PREFERENCES = frozenset({"indoor", "outdoor"})

_UNVERIFIED_WARNING = "방문 전에 운영 여부를 확인해주세요."
_CLOSED_NOW_WARNING = "지금은 운영시간이 아니에요. 방문 전에 다시 확인해주세요."


class ExclusionReason(StrEnum):
    """하드 필터에서 후보를 제외한 이유."""

    CLOSED = "closed"
    ALREADY_SHOWN = "already_shown"
    REJECTED = "rejected"


@dataclass(frozen=True)
class PreparedCandidate:
    """하드 필터를 통과해 점수 계산을 기다리는 후보."""

    candidate: ScoringCandidate
    remaining_minutes: float | None
    is_unverified: bool
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExcludedCandidate:
    """하드 필터에서 제외된 후보와 그 사유."""

    candidate: ScoringCandidate
    reason: ExclusionReason

    @property
    def place_id(self) -> str:
        return self.candidate.place_id


@dataclass(frozen=True)
class PrepareResult:
    """하드 필터가 입력 후보 전체를 통과/제외로 분류한 결과."""

    eligible_candidates: tuple[PreparedCandidate, ...]
    excluded_candidates: tuple[ExcludedCandidate, ...]
    input_count: int

    @property
    def eligible_count(self) -> int:
        return len(self.eligible_candidates)

    @property
    def excluded_place_ids(self) -> tuple[str, ...]:
        return tuple(candidate.place_id for candidate in self.excluded_candidates)


@dataclass(frozen=True)
class RankedCandidate:
    """점수 계산 후 정렬된 후보 1건."""

    place_id: str
    name: str
    category: str
    rank: int
    score: float
    feature_scores: Mapping[str, float | None]
    weights_used: Mapping[str, float]
    is_unverified: bool
    warnings: tuple[str, ...]
    # 정규화 점수(feature_scores)만으로는 "직선거리 약 400m" 같은 구체적인
    # 문장을 만들 수 없어, Explainability Layer(D-06)가 쓸 원본 값을 보존한다.
    distance_km: float
    remaining_minutes: float | None
    weather_condition: WeatherCondition | None
    environment_type: str
    # 실측 도보 경로가 있을 때만 채워진다. 거리 Feature 점수를 이 값으로
    # 계산했다는 표시이자, 근거 문장·응답 표기의 원본이다(`_proximity_score()`).
    walking_distance_m: int | None = None
    walking_duration_seconds: int | None = None
    # D-040: 2차 Scoring(rerank_with_concentration())에서만 채워진다. 1차 Scoring
    # 결과는 concentration 자체를 모르므로 항상 None이다 — explanation.py가 문장을
    # "한적함/보통/다소 혼잡/혼잡" 중 무엇으로 쓸지 고르는 데 필요하다(direction이
    # 이미 반영된 concentration_score만으로는 실제 붐빔 정도를 알 수 없다).
    concentration_level: ConcentrationLevel | None = None
    # WeatherCondition만으로는 "왜"(비/눈/폭염/한파 중 무엇 때문)를 알 수 없어서
    # 근거 문장(explanation.py) 조립에 따로 필요하다 — 점수 계산에는 안 쓰인다.
    weather_reason: WeatherReason = None


@dataclass(frozen=True)
class ScoringResult:
    """Scoring v1의 최종 출력."""

    ranked: tuple[RankedCandidate, ...]
    excluded_place_ids: tuple[str, ...]
    # 폐점이라 제외된 후보만 별도로 센다(이전 노출/거절 제외와 구분) — 호출부가
    # "결과가 0건인 이유가 전부 폐점인가"를 판단하는 데 쓴다.
    excluded_closed_place_ids: tuple[str, ...] = ()


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _remaining_minutes(now: datetime, hours: OperatingHours) -> float | None:
    """`now`가 영업시간 안이면 마감까지 남은 분을, 밖이면 `None`(폐점)을 반환한다.

    정기 휴무일은 구간 안이어도 `None`이다 — `hours`가 그날 실제로 여는 시간이
    아니라 평소 구간이기 때문이다. 이 한 곳에서 걸러 두면 폐점 판정·잔여시간
    Feature·"운영시간 무시" 경고가 모두 같은 기준을 따른다.
    """
    if hours.is_regular_closure:
        return None
    current_time = now.time()
    if not (hours.open_time <= current_time < hours.close_time):
        return None
    close_at = datetime.combine(
        now.date(),
        hours.close_time,
        tzinfo=now.tzinfo,
    )
    return (close_at - now).total_seconds() / 60.0


def _remaining_time_score(remaining_minutes: float) -> float:
    return _clamp(remaining_minutes / _REMAINING_TIME_FULL_SCORE_MINUTES, 0.0, 1.0)


def _weather_fit_score(candidate: ScoringCandidate, weather_condition: WeatherCondition) -> float:
    return _WEATHER_FIT_TABLE.get(
        (weather_condition, candidate.environment_type), _WEATHER_FIT_DEFAULT
    )


def _environment_fit_score(candidate: ScoringCandidate, requested_environment: str) -> float:
    return _ENVIRONMENT_FIT_TABLE.get(
        (requested_environment, candidate.environment_type), _ENVIRONMENT_FIT_DEFAULT
    )


def uses_environment_feature(requested_environment: str | None) -> bool:
    """요청 환경이 실내/실외로 명시됐으면 True — 날씨 대신 환경으로 채점한다."""
    return requested_environment in _ENVIRONMENT_PREFERENCES


def _rename_weather_weight(weights: Mapping[str, float]) -> dict[str, float]:
    """날씨 자리의 가중치를 값 그대로 환경 Feature로 옮긴다.

    숫자는 바꾸지 않는다 — 두 Feature는 한 실행에서 동시에 쓰이지 않아 합이
    그대로 1.0이고, 결측 재분배도 기존과 같은 조건에서만 일어난다.
    """
    return {
        (ENVIRONMENT_FEATURE if feature == WEATHER_FEATURE else feature): weight
        for feature, weight in weights.items()
    }


def weights_for_environment(
    weights: Mapping[str, float], requested_environment: str | None
) -> dict[str, float]:
    """요청 환경으로 채점하는 실행이면 날씨 가중치 키를 환경으로 바꿔 돌려준다."""
    if not uses_environment_feature(requested_environment):
        return dict(weights)
    return _rename_weather_weight(weights)


def weights_for_feature_scores(
    weights: Mapping[str, float], feature_scores: Mapping[str, float | None]
) -> dict[str, float]:
    """이미 채점된 feature_scores에 가중치 키를 맞춘다.

    2차 Scoring(`rerank_with_concentration()`)은 조건을 다시 받지 않고 1차
    결과만 재사용하므로, 어느 Feature로 채점됐는지를 키 존재로 판단한다.
    """
    if ENVIRONMENT_FEATURE not in feature_scores:
        return dict(weights)
    return _rename_weather_weight(weights)


def _distance_score(distance_km: float, max_distance_km: float) -> float:
    if max_distance_km <= 0:
        return 1.0 if distance_km <= 0 else 0.0
    return _clamp(1.0 - distance_km / max_distance_km, 0.0, 1.0)


def _walking_minutes_budget(max_distance_km: float) -> float:
    """검색 반경을 도보 소요시간 예산(분)으로 되돌린다.

    호출부(`to_search_radius_km()`)가 `max_travel_time × 도보 속도`로 반경을
    만들었으므로, 같은 속도로 나누면 사용자가 말한 이동시간이 그대로 나온다.
    이동시간을 말하지 않은 요청은 기본 반경(2.0km)에서 약 28.6분이 된다.

    분모를 이렇게 유도하면 직선거리 → 실거리 우회 계수를 추정할 필요가 없다.
    거리 기준으로 하면 분모(반경)가 직선거리 전제라 반경 경계 후보가 전부
    0점으로 몰리는데, 시간 기준은 분자·분모가 같은 단위라 그 왜곡이 없다.
    """
    return max_distance_km / WALKING_SPEED_KM_PER_MINUTE


def _walking_time_score(duration_seconds: int, max_distance_km: float) -> float:
    budget_minutes = _walking_minutes_budget(max_distance_km)
    if budget_minutes <= 0:
        return 0.0
    return _clamp(1.0 - (duration_seconds / 60.0) / budget_minutes, 0.0, 1.0)


def _applied_walking_route(route: WalkingRoute | None) -> WalkingRoute | None:
    """실제로 채점에 쓸 수 있는 도보 경로만 남긴다.

    조회 실패(`NO_DATA`/`UNAVAILABLE`)나 직선거리 추정 폴백은 소요시간이 없거나
    실측이 아니므로 여기서 걸러진다. 반환값이 `None`이면 거리 Feature는 직선거리로
    계산되고, 응답에도 도보 값이 실리지 않는다.
    """
    if (
        route is not None
        and route.status is RouteStatus.SUCCESS
        and route.duration_seconds is not None
    ):
        return route
    return None


def _walking_field(route: WalkingRoute | None, field: str) -> int | None:
    """채점에 실제로 쓴 경로에서만 값을 꺼낸다 — 폴백 후보는 `None`이다."""
    applied = _applied_walking_route(route)
    return None if applied is None else getattr(applied, field)


def _proximity_score(
    candidate: ScoringCandidate,
    route: WalkingRoute | None,
    max_distance_km: float,
) -> float:
    """거리 Feature 점수. 실측 도보 시간이 있으면 쓰고, 없으면 직선거리로 돌아간다.

    폴백을 결측(`missing_features`)으로 처리하지 않는 이유: 거리는 이미 알고
    있어서 결측이 아니고, 재분배를 태우면 도보 조회에 실패한 후보만 거리
    Feature가 빠져 오히려 유리해진다.
    """
    applied = _applied_walking_route(route)
    if applied is not None:
        assert applied.duration_seconds is not None
        return _walking_time_score(applied.duration_seconds, max_distance_km)
    return _distance_score(candidate.distance_km, max_distance_km)


def concentration_score(concentration_rate: float, *, seek: bool) -> float:
    """혼잡률(평시 대비 0~100대 상대 비율)을 0~1 점수로 선형 정규화한다.

    `seek`(concentration_intent=SEEK, 붐비는 곳 선호)이면 혼잡률이 높을수록
    점수가 높고, `seek=False`(AVOID, 한적한 곳 선호)면 그 반대다. distance/
    remaining_operating_time과 같은 연속값 스타일을 따른다 — 4단계 구간
    (quiet/normal/slightly_crowded/crowded) 매핑 대신 선형 정규화를 택해
    정보 손실을 피한다.
    """
    normalized = _clamp(concentration_rate / 100.0, 0.0, 1.0)
    return normalized if seek else 1.0 - normalized


def redistribute_weights(
    weights: Mapping[str, float], missing_features: Iterable[str]
) -> dict[str, float]:
    """결측 Feature들을 제외하고 나머지 가중치를 기존 비중에 비례해 재분배한다."""
    missing = set(missing_features)
    remaining = {feature: weight for feature, weight in weights.items() if feature not in missing}
    total_remaining = sum(remaining.values())
    if total_remaining <= 0:
        return remaining
    return {feature: weight / total_remaining for feature, weight in remaining.items()}


def _is_closed(candidate: ScoringCandidate, now: datetime) -> bool:
    if candidate.operating_hours is None:
        return False  # 운영시간 미확인은 폐점이 아니다.
    return _remaining_minutes(now, candidate.operating_hours) is None


def prepare_candidates(
    candidates: Sequence[ScoringCandidate],
    *,
    now: datetime,
    shown_place_ids: Iterable[str] = (),
    rejected_place_ids: Iterable[str] = (),
    ignore_operating_hours: bool = False,
) -> PrepareResult:
    """하드 필터를 적용하고 통과 후보의 운영시간 Feature를 준비한다.

    제외 사유는 사용자 이력을 폐점보다 우선한다. 이미 노출되거나 거절된 후보가
    현재 폐점이기도 하더라도 폐점 때문에 제외된 것으로 집계하지 않는 기존
    ``score_candidates()`` 동작을 보존하기 위해서다.
    """
    shown = frozenset(shown_place_ids)
    rejected = frozenset(rejected_place_ids)
    eligible: list[PreparedCandidate] = []
    excluded: list[ExcludedCandidate] = []

    for candidate in candidates:
        if candidate.place_id in shown:
            excluded.append(
                ExcludedCandidate(candidate, ExclusionReason.ALREADY_SHOWN)
            )
            continue
        if candidate.place_id in rejected:
            excluded.append(ExcludedCandidate(candidate, ExclusionReason.REJECTED))
            continue

        remaining_minutes = (
            _remaining_minutes(now, candidate.operating_hours)
            if candidate.operating_hours is not None
            else None
        )
        is_closed = candidate.operating_hours is not None and remaining_minutes is None
        if is_closed and not ignore_operating_hours:
            excluded.append(ExcludedCandidate(candidate, ExclusionReason.CLOSED))
            continue

        is_unverified = candidate.operating_hours is None or is_closed
        warnings = (
            (_CLOSED_NOW_WARNING,) if is_closed else (_UNVERIFIED_WARNING,)
        ) if is_unverified else ()
        eligible.append(
            PreparedCandidate(
                candidate=candidate,
                remaining_minutes=remaining_minutes,
                is_unverified=is_unverified,
                warnings=warnings,
            )
        )

    return PrepareResult(
        eligible_candidates=tuple(eligible),
        excluded_candidates=tuple(excluded),
        input_count=len(candidates),
    )


def score_prepared_candidates(
    candidates: Sequence[PreparedCandidate],
    *,
    weather_condition: WeatherCondition | None,
    max_distance_km: float,
    weights: Mapping[str, float] | None = None,
    weather_reason: WeatherReason = None,
    requested_environment: str | None = None,
    # A가 조회해 넘긴 실측 도보 경로. 해당 후보가 없거나 조회에 실패했으면
    # 직선거리로 돌아간다(`_proximity_score()`).
    walking_routes: Sequence[WalkingRoute] = (),
) -> ScoringResult:
    """하드 필터를 통과한 후보에 가중치 점수를 적용해 정렬한다.

    1. 후보별로 날씨·남은 운영시간 결측 여부를 확인해 기본 가중치 또는
       재분배 가중치를 적용 (두 Feature 모두 결측일 수도 있음)
    2. Feature별 점수 계산 후 가중합 (날씨 또는 요청 환경, 남은 운영시간, 거리)
    3. score 내림차순 → distance_km 오름차순 → place_id 오름차순으로 정렬

    `requested_environment`가 indoor/outdoor면 날씨 Feature 자리를 환경 적합도가
    대신한다 — 사용자가 실내/실외를 직접 말했는데 날씨 사실이 순위를 뒤집는
    문제(맑은 날 GOOD/indoor=0.70)를 막기 위해서다. 가중치 숫자는 그대로고 키만
    바뀐다. 날씨를 함께 언급한 경우(weather_intent=AVOID/ENJOY)는 호출부가 이
    값을 넘기지 않아 기존 날씨 판정을 그대로 쓴다.
    """
    environment_driven = uses_environment_feature(requested_environment)
    routes_by_place_id = {route.place_id: route for route in walking_routes}
    base_weights = weights_for_environment(
        dict(weights) if weights is not None else dict(DEFAULT_WEIGHTS),
        requested_environment,
    )
    scored: list[
        tuple[
            ScoringCandidate,
            float,
            dict[str, float | None],
            dict[str, float],
            bool,
            float | None,
            tuple[str, ...],
        ]
    ] = []

    for prepared in candidates:
        candidate = prepared.candidate
        missing_features: list[str] = []

        # 날씨와 요청 환경은 한 실행에서 같은 자리를 나눠 쓴다. 요청 환경은
        # 후보마다 항상 판정할 수 있어 결측이 없다(unknown도 표에 값이 있다).
        primary_feature = ENVIRONMENT_FEATURE if environment_driven else WEATHER_FEATURE
        primary_score: float | None
        if environment_driven:
            assert requested_environment is not None
            primary_score = _environment_fit_score(candidate, requested_environment)
        elif weather_condition is None:
            primary_score = None
            missing_features.append(primary_feature)
        else:
            primary_score = _weather_fit_score(candidate, weather_condition)

        remaining_minutes = prepared.remaining_minutes
        remaining_time_score: float | None
        if remaining_minutes is None:
            remaining_time_score = None
            missing_features.append("remaining_operating_time")
        else:
            remaining_time_score = _remaining_time_score(remaining_minutes)

        weights_used = (
            redistribute_weights(base_weights, missing_features)
            if missing_features
            else dict(base_weights)
        )

        feature_scores: dict[str, float | None] = {
            primary_feature: primary_score,
            "remaining_operating_time": remaining_time_score,
            "distance": _proximity_score(
                candidate, routes_by_place_id.get(candidate.place_id), max_distance_km
            ),  # 실측 도보 시간 우선, 없으면 직선거리
        }

        score = sum(
            feature_scores[feature] * weight  # type: ignore[operator]
            for feature, weight in weights_used.items()
        )

        scored.append(
            (
                candidate,
                score,
                feature_scores,
                weights_used,
                prepared.is_unverified,
                remaining_minutes,
                prepared.warnings,
            )
        )

    scored.sort(key=lambda entry: (-entry[1], entry[0].distance_km, entry[0].place_id))

    ranked = tuple(
        RankedCandidate(
            place_id=candidate.place_id,
            name=candidate.name,
            category=candidate.category,
            rank=index + 1,
            score=round(score, 4),
            feature_scores=feature_scores,
            weights_used=weights_used,
            is_unverified=is_unverified,
            warnings=warnings,
            distance_km=candidate.distance_km,
            remaining_minutes=remaining_minutes,
            weather_condition=weather_condition,
            weather_reason=weather_reason,
            environment_type=candidate.environment_type,
            walking_distance_m=_walking_field(
                routes_by_place_id.get(candidate.place_id), "distance_m"
            ),
            walking_duration_seconds=_walking_field(
                routes_by_place_id.get(candidate.place_id), "duration_seconds"
            ),
        )
        for index, (
            candidate,
            score,
            feature_scores,
            weights_used,
            is_unverified,
            remaining_minutes,
            warnings,
        ) in enumerate(scored)
    )

    return ScoringResult(
        ranked=ranked,
        excluded_place_ids=(),
        excluded_closed_place_ids=(),
    )


def score_candidates(
    candidates: Sequence[ScoringCandidate],
    *,
    now: datetime,
    weather_condition: WeatherCondition | None,
    max_distance_km: float,
    shown_place_ids: Iterable[str] = (),
    rejected_place_ids: Iterable[str] = (),
    weights: Mapping[str, float] | None = None,
    weather_reason: WeatherReason = None,
    # True면 폐점 후보를 제외하지 않고 그대로 채점한다 — "운영중이 아닌 곳도
    # 볼래요"(no_data_closed 되묻기) 해소 시에만 호출부가 켠다. 기본은 False로,
    # 기존 하드 필터 동작을 그대로 유지한다.
    ignore_operating_hours: bool = False,
    # 사용자가 명시한 실내/실외. indoor/outdoor면 날씨 대신 이 조건으로 같은
    # 자리의 Feature를 채점한다(호출부가 날씨 언급이 없을 때만 넘긴다).
    requested_environment: str | None = None,
) -> ScoringResult:
    """기존 하드 필터와 점수 계산을 연속 실행하는 호환 진입점."""
    prepared_result = prepare_candidates(
        candidates,
        now=now,
        shown_place_ids=shown_place_ids,
        rejected_place_ids=rejected_place_ids,
        ignore_operating_hours=ignore_operating_hours,
    )
    scoring_result = score_prepared_candidates(
        prepared_result.eligible_candidates,
        weather_condition=weather_condition,
        max_distance_km=max_distance_km,
        weights=weights,
        weather_reason=weather_reason,
        requested_environment=requested_environment,
    )
    return ScoringResult(
        ranked=scoring_result.ranked,
        excluded_place_ids=prepared_result.excluded_place_ids,
        excluded_closed_place_ids=tuple(
            candidate.place_id
            for candidate in prepared_result.excluded_candidates
            if candidate.reason is ExclusionReason.CLOSED
        ),
    )
