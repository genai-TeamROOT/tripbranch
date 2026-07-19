"""TripBranch provider 계층의 최소 인터페이스 정의.

역할: 해석 provider와 추천 provider가 구현해야 할 메서드 계약을 표현한다.
입력: 사용자 자연어 입력 또는 이미 노출된 place_id 목록.
출력: 해석 조건 모델 또는 추천 응답 모델.
호출 시점: 실제 provider 주입 구조를 만들 때 타입 계약으로 사용된다.
TODO: provider가 늘어나면 오류 타입, 비동기 계약, 메타데이터 계약을 분리한다.
"""

from __future__ import annotations

from typing import Protocol

from app.schemas import InterpretedConditions, RecommendationResponse


class InterpretProvider(Protocol):
    def interpret(self, user_input: str) -> InterpretedConditions:
        """Return structured trip conditions from free-form input."""
        ...


class RecommendationProvider(Protocol):
    def recommendations(self, shown_place_ids: list[str]) -> RecommendationResponse:
        """Return place recommendations, excluding already shown IDs."""
        ...
