# FakeLlmProvider - 실제 LLM 없이 키워드 매칭만으로 자유 입력을 구조화하는 규칙 기반 구현.
# 정교한 자연어 이해가 아니라 "대표 입력 몇 개가 그럴듯하게 동작"하는 수준을 목표로 함.
# 사용법: 위치/카테고리/날씨 키워드 표를 늘리면 더 많은 예시 입력을 커버할 수 있다.
# TODO: RealLlmProvider(providers/real/llm.py)로 교체될 대상 - structured output/function
# calling으로 InterpretedInput과 동일한 스키마를 뽑아내도록 프롬프트를 설계할 것.

"""Rule-based fake LLM: keyword matching, not real NLU. Good enough to
exercise the interpret -> confirm -> recommend flow end to end without a
real LLM API key."""

from __future__ import annotations

from app.domain.models import InterpretedInput, WeatherCondition
from app.domain.weights import DEFAULT_SEARCH_RADIUS_KM

KNOWN_LOCATION_KEYWORDS = ["경복궁", "서울역", "광화문"]
DEFAULT_LOCATION_QUERY = "경복궁"

CATEGORY_KEYWORDS: dict[str, str] = {
    "박물관": "museum",
    "전시": "gallery",
    "갤러리": "gallery",
    "카페": "cafe",
    "커피": "cafe",
    "공원": "park",
    "식당": "restaurant",
    "밥": "restaurant",
    "시장": "market",
    "사찰": "temple",
    "절": "temple",
    "서점": "bookstore",
    "책방": "bookstore",
}

BAD_WEATHER_KEYWORDS = ["비", "눈", "폭우", "태풍", "우산"]
GOOD_WEATHER_KEYWORDS = ["맑음", "화창", "쾌청"]


class FakeLlmProvider:
    async def interpret(self, user_input: str) -> InterpretedInput:
        text = user_input.strip()

        location_query = next(
            (kw for kw in KNOWN_LOCATION_KEYWORDS if kw in text), DEFAULT_LOCATION_QUERY
        )

        preferred_categories: list[str] = []
        for keyword, category in CATEGORY_KEYWORDS.items():
            if keyword in text and category not in preferred_categories:
                preferred_categories.append(category)
        if not preferred_categories:
            preferred_categories = ["cafe"]

        if any(kw in text for kw in BAD_WEATHER_KEYWORDS):
            weather_condition = WeatherCondition.BAD
        elif any(kw in text for kw in GOOD_WEATHER_KEYWORDS):
            weather_condition = WeatherCondition.GOOD
        else:
            weather_condition = WeatherCondition.NEUTRAL

        return InterpretedInput(
            location_query=location_query,
            preferred_categories=preferred_categories,
            weather_condition=weather_condition,
            search_radius_km=DEFAULT_SEARCH_RADIUS_KM,
        )
