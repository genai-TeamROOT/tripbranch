"""추천 Explainability Layer v1: Evidence를 Rule 기반 문장으로 변환한다 (D-06).

역할: `RecommendationEvidence.contributions`(Feature별 score/weight/contribution)로
어떤 Feature를 문장화할지 고르고, 같은 Evidence가 들고 있는 원본 계산값
(distance_km/remaining_minutes/weather_condition/environment_type)으로 실제
수치가 들어간 한국어 문장을 조립한다. LLM을 호출하지 않는 Rule 기반·결정적
구조라 동일 입력에는 항상 동일한 문장이 나온다.
입력: `RecommendationEvidence` (`backend/app/domain/evidence.py`).
출력: `tuple[str, ...]` (0~3개, Feature 점수가 임계값 이상인 것만 포함).
호출 시점: 추천 파이프라인이 응답을 조립할 때 Evidence 계산 직후 호출한다.
설계 근거: `package_D/[D-06]explainability_detail.txt`(구체화 요청),
`package_D/[D-06] Recommendation Explainability Layer.txt`(최초 요청).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from app.domain.evidence import FeatureContribution, RecommendationEvidence
from app.domain.models import WeatherCondition

# 이 점수 이상인 Feature만 "특별히 강조할 이유"로 문장화한다.
# 결측(None)이거나 애매한 점수(< 임계값)는 문장을 생략한다 — 결측은 이미
# warnings가 별도로 안내하므로 중복 설명하지 않는다.
_EXPLANATION_SCORE_THRESHOLD = 0.7

# 1km 미만은 m 단위(10m 반올림), 이상은 km 단위(소수 첫째자리)로 표시한다.
# "직선거리"를 명시해 실제 이동거리(도보/대중교통 소요)로 오해하지 않게 한다.
_METERS_PER_KM = 1000
_DISTANCE_ROUNDING_STEP_M = 10


def _format_distance(distance_km: float) -> str:
    if distance_km < 1.0:
        meters = round(distance_km * _METERS_PER_KM / _DISTANCE_ROUNDING_STEP_M) * (
            _DISTANCE_ROUNDING_STEP_M
        )
        return f"직선거리 약 {meters}m"
    km = round(distance_km, 1)
    km_text = str(int(km)) if km == int(km) else str(km)
    return f"직선거리 약 {km_text}km"


def _distance_sentence(evidence: RecommendationEvidence) -> str:
    return f"현재 위치에서 {_format_distance(evidence.distance_km)}예요."


def _format_remaining_time(remaining_minutes: float) -> str:
    total_minutes = round(remaining_minutes)
    hours, minutes = divmod(total_minutes, 60)
    if hours > 0 and minutes > 0:
        return f"{hours}시간 {minutes}분"
    if hours > 0:
        return f"{hours}시간"
    return f"{minutes}분"


def _remaining_time_sentence(evidence: RecommendationEvidence) -> str:
    # remaining_operating_time Feature가 notable이면 remaining_minutes는
    # 항상 값이 있다(둘 다 None 여부가 함께 결정되므로).
    assert evidence.remaining_minutes is not None
    time_text = _format_remaining_time(evidence.remaining_minutes)
    return f"마감까지 약 {time_text} 남았어요."


# 문장은 "사실"만 전달하고 "여유롭다/방문하기 좋다" 같은 평가·어투는 붙이지
# 않는다 — 그 역할은 이 문장들을 자연어로 이어붙이는 Response Generator(LLM,
# A 담당)의 몫이다(package_D/[D-06]explainability_detail.txt 예시 참고).
# scoring.py의 _WEATHER_FIT_TABLE과 같은 축을 쓰되, 문턱값(0.7) 미만 조합
# (예: 비+야외)은 애초에 notable이 되지 않아 실제로는 호출되지 않는다.
_WEATHER_LABELS: Mapping[WeatherCondition, str] = {
    WeatherCondition.GOOD: "맑은 날씨",
    WeatherCondition.NEUTRAL: "무난한 날씨",
    WeatherCondition.BAD: "비 예보",
}
_WEATHER_LABEL_DEFAULT = "지금 날씨"

_ENVIRONMENT_LABELS: Mapping[str, str] = {
    "indoor": "실내 ",
    "outdoor": "야외 ",
}
_ENVIRONMENT_LABEL_DEFAULT = ""


def _weather_sentence(evidence: RecommendationEvidence) -> str:
    # weather Feature가 notable이면 weather_condition은 항상 값이 있다.
    assert evidence.weather_condition is not None
    weather_label = _WEATHER_LABELS.get(evidence.weather_condition, _WEATHER_LABEL_DEFAULT)
    environment_label = _ENVIRONMENT_LABELS.get(
        evidence.environment_type, _ENVIRONMENT_LABEL_DEFAULT
    )
    return f"{weather_label}에 적합한 {environment_label}장소예요."


_SENTENCE_BUILDERS: Mapping[str, Callable[[RecommendationEvidence], str]] = {
    "weather": _weather_sentence,
    "remaining_operating_time": _remaining_time_sentence,
    "distance": _distance_sentence,
}


def _is_notable(contribution: FeatureContribution) -> bool:
    return (
        contribution.score is not None
        and contribution.score >= _EXPLANATION_SCORE_THRESHOLD
    )


def build_explanations(evidence: RecommendationEvidence) -> tuple[str, ...]:
    """기여도(score × weight)가 큰 순서로, 임계값 이상인 Feature만 문장화한다.

    기여도가 같으면 `contributions`에 이미 고정된 Feature 순서(weather →
    remaining_operating_time → distance)를 그대로 tie-break로 사용해
    결정적 순서를 보장한다.
    """
    notable = [
        (index, contribution)
        for index, contribution in enumerate(evidence.contributions)
        if _is_notable(contribution)
    ]
    notable.sort(key=lambda pair: (-(pair[1].contribution or 0.0), pair[0]))
    return tuple(
        _SENTENCE_BUILDERS[contribution.feature](evidence) for _, contribution in notable
    )
