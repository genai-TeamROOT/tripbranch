"""추천 Explainability Layer v1: Evidence를 Rule 기반 문장으로 변환한다 (D-06).

역할: `RecommendationEvidence.contributions`(Feature별 score/weight/contribution)로
어떤 Feature를 문장화할지 고르고, 같은 Evidence가 들고 있는 원본 계산값
(distance_km/remaining_minutes/weather_condition/environment_type/
concentration_level)으로 실제 수치가 들어간 한국어 문장을 조립한다. LLM을
호출하지 않는 Rule 기반·결정적 구조라 동일 입력에는 항상 동일한 문장이 나온다.
concentration은 2차 Scoring(D-040, rerank_with_concentration())에서만 등장한다.
입력: `RecommendationEvidence` (`backend/app/domain/evidence.py`).
출력: `tuple[str, ...]` (0~3개, Feature 점수가 임계값 이상인 것만 포함).
호출 시점: 추천 파이프라인이 응답을 조립할 때 Evidence 계산 직후 호출한다.
설계 근거: `package_D/[D-06]explainability_detail.txt`(구체화 요청),
`package_D/[D-06] Recommendation Explainability Layer.txt`(최초 요청).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from app.concentration_policy import ConcentrationLevel
from app.domain.evidence import FeatureContribution, RecommendationEvidence
from app.domain.models import WeatherCondition
from app.domain.travel_route import TravelMode
from app.domain.weather_judgment import WeatherReason

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


def _format_travel_duration(duration_seconds: int) -> str:
    minutes = max(1, round(duration_seconds / 60))
    hours, remainder = divmod(minutes, 60)
    if hours > 0 and remainder > 0:
        return f"{hours}시간 {remainder}분"
    if hours > 0:
        return f"{hours}시간"
    return f"{minutes}분"


def _distance_sentence(evidence: RecommendationEvidence) -> str:
    """실측 이동시간이 있으면 그걸 말하고, 없으면 기존 직선거리 문구를 쓴다.

    거리 Feature 점수도 같은 기준으로 계산되므로(`scoring.py::_proximity_score()`),
    점수와 근거 문장이 서로 다른 거리를 말하는 일이 없다. 기준점 **이름**도
    마찬가지다 — 예전에는 기준점이 무엇이든 "현재 위치"라고 말해서, "경복궁 근처
    카페"를 물으면 경복궁 기준 거리를 사용자 위치 기준인 것처럼 말했다(TP-109).

    "걸어서"는 도보 실측일 때만 쓴다. 다른 이동수단의 문구는 그 이동수단을
    연결하는 카드가 여기에 추가한다 — 그때까지는 직선거리 문구로 돌아가므로,
    자동차 실측을 "걸어서"라고 말하는 일은 없다.
    """
    origin = evidence.origin_name or "현재 위치"
    if (
        evidence.travel_duration_seconds is not None
        and evidence.travel_mode is TravelMode.WALKING
    ):
        walk_text = _format_travel_duration(evidence.travel_duration_seconds)
        return f"{origin}에서 걸어서 약 {walk_text} 거리예요."
    return f"{origin}에서 {_format_distance(evidence.distance_km)}예요."


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
#
# weather_condition(GOOD/NEUTRAL/BAD)만으로 라벨을 고르면 "왜" BAD인지가
# 사라진다 — ENJOY 반전으로 비인데 GOOD이 되거나(2026-08-05 검수에서 발견),
# 폭염으로 BAD인데 "비 예보"라고 말하는 식의 사실-근거 불일치가 생긴다.
# weather_reason(비/눈/폭염/한파)이 있으면 그걸 우선하고, 없을 때만(맑음/흐림처럼
# 강수·기온이 원인이 아닌 경우, 또는 발화 GOOD) weather_condition 기반 라벨로
# 폴백한다.
_WEATHER_REASON_LABELS: Mapping[str, str] = {
    "rain": "비 예보",
    "snow": "눈 예보",
    "heat": "폭염 예보",
    "cold": "한파 예보",
}
_WEATHER_CONDITION_LABELS: Mapping[WeatherCondition, str] = {
    WeatherCondition.GOOD: "맑은 날씨",
    WeatherCondition.NEUTRAL: "무난한 날씨",
}
_WEATHER_LABEL_DEFAULT = "지금 날씨"

_ENVIRONMENT_LABELS: Mapping[str, str] = {
    "indoor": "실내 ",
    "outdoor": "야외 ",
}
_ENVIRONMENT_LABEL_DEFAULT = ""


def _weather_label(weather_condition: WeatherCondition, weather_reason: WeatherReason) -> str:
    if weather_reason is not None:
        return _WEATHER_REASON_LABELS[weather_reason]
    return _WEATHER_CONDITION_LABELS.get(weather_condition, _WEATHER_LABEL_DEFAULT)


def _weather_sentence(evidence: RecommendationEvidence) -> str:
    # weather Feature가 notable이면 weather_condition은 항상 값이 있다.
    assert evidence.weather_condition is not None
    weather_label = _weather_label(evidence.weather_condition, evidence.weather_reason)
    environment_label = _ENVIRONMENT_LABELS.get(
        evidence.environment_type, _ENVIRONMENT_LABEL_DEFAULT
    )
    return f"{weather_label}에 적합한 {environment_label}장소예요."


def _environment_sentence(evidence: RecommendationEvidence) -> str:
    """요청 환경으로 채점된 실행 전용 문장.

    이 실행에는 날씨가 점수에 들어가지 않았으므로 날씨를 근거로 말하지 않는다 —
    `_weather_sentence()`를 그대로 쓰면 맑은 날에 "궂은 날씨에 적합한 실내
    장소예요" 같은 사실과 다른 문장이 나간다.
    """
    environment_label = _ENVIRONMENT_LABELS.get(
        evidence.environment_type, _ENVIRONMENT_LABEL_DEFAULT
    )
    return f"요청하신 {environment_label}장소예요."


# concentration Feature(D-040, 2차 Scoring 전용)의 사실 문장. concentration_score
# (scoring.py::concentration_score())는 SEEK/AVOID 방향이 이미 반영된 값이라
# "notable하다"는 것만으로는 실제로 붐비는지 한적한지 알 수 없다 — 그래서
# 방향과 무관한 원본 4단계 구간(evidence.concentration_level)으로 문장을 고른다.
# 다른 Feature와 같은 원칙: 사실만 전달하고 "좋다/나쁘다" 평가는 붙이지 않는다
# (SEEK인 사용자에게도 "혼잡한 편"이라고만 말하지 "붐벼서 좋아요"라고 하지 않음).
_CONCENTRATION_SENTENCES: Mapping[ConcentrationLevel, str] = {
    ConcentrationLevel.QUIET: "지금 이 근처는 한적한 편이에요.",
    ConcentrationLevel.NORMAL: "지금 이 근처는 보통 수준으로 붐벼요.",
    ConcentrationLevel.SLIGHTLY_CROWDED: "지금 이 근처는 다소 혼잡한 편이에요.",
    ConcentrationLevel.CROWDED: "지금 이 근처는 혼잡한 편이에요.",
}


def _concentration_sentence(evidence: RecommendationEvidence) -> str:
    # concentration Feature가 notable이면 concentration_level은 항상 값이 있다.
    assert evidence.concentration_level is not None
    return _CONCENTRATION_SENTENCES[evidence.concentration_level]


_SENTENCE_BUILDERS: Mapping[str, Callable[[RecommendationEvidence], str]] = {
    "weather": _weather_sentence,
    "environment": _environment_sentence,
    "remaining_operating_time": _remaining_time_sentence,
    "distance": _distance_sentence,
    "concentration": _concentration_sentence,
}


def _is_notable(contribution: FeatureContribution) -> bool:
    return contribution.score is not None and contribution.score >= _EXPLANATION_SCORE_THRESHOLD


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
    return tuple(_SENTENCE_BUILDERS[contribution.feature](evidence) for _, contribution in notable)
