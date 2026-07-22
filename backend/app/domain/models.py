"""Weather/Geocoding provider가 공유하는 내부 도메인 모델.

역할: 외부 API(Naver Geocoding, KMA 단기예보) 응답을 라우터/서비스가 직접 다루지
않도록, provider 구현체가 반드시 이 타입으로 변환해서 반환하게 한다.
이 모듈은 FastAPI/Pydantic/HTTP 라이브러리를 import하지 않는다.
"""

from __future__ import annotations

from enum import StrEnum


class WeatherCondition(StrEnum):
    GOOD = "good"
    NEUTRAL = "neutral"
    BAD = "bad"
