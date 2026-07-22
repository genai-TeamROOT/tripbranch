"""TripBranch fake provider 구현체 모음.

역할: 외부 API 호출 없이 고정/임시 데이터로 각 provider 계약을 만족시킨다.
입력: 각 provider protocol이 요구하는 파라미터.
출력: 각 provider protocol이 요구하는 응답 모델.
호출 시점: PLACE_PROVIDER=fake 등 설정이 fake일 때 provider 팩토리가 주입한다.
TODO: 실제 provider(RealPlaceProvider 등)가 준비되면 팩토리에서 설정값으로 분기한다.
"""

from __future__ import annotations

from app.schemas import (
    InterpretedConditions,
    PlaceCandidate,
    RecommendationResponse,
)
from app.services.interpret import interpret_user_input
from app.services.recommendations import get_stub_recommendations


class FakeInterpretProvider:
    """자연어 입력 해석을 고정 조건으로 대체하는 fake provider."""

    def interpret(self, user_input: str) -> InterpretedConditions:
        return interpret_user_input(user_input)


class FakeRecommendationProvider:
    """추천 결과를 고정 목록으로 대체하는 fake provider."""

    def recommendations(self, shown_place_ids: list[str]) -> RecommendationResponse:
        return get_stub_recommendations(shown_place_ids)


class FakeGeocodingProvider:
    """장소 이름을 고정 좌표로 대체하는 fake provider."""

    def geocode(self, location_query: str) -> tuple[float, float]:
        # 경복궁 좌표를 기본값으로 고정 (fake 모드 재현성 확보용)
        return (37.5796, 126.9770)


class FakePlaceProvider:
    """장소 검색 결과를 고정 후보 목록으로 대체하는 fake provider."""

    def search_places(
        self,
        latitude: float,
        longitude: float,
        preferred_categories: list[str],
        search_radius_km: float,
    ) -> list[PlaceCandidate]:
        return [
            PlaceCandidate(
                place_id="fake-museum-1",
                name="테스트 박물관",
                category="museum",
                latitude=latitude,
                longitude=longitude,
                address="서울 종로구 어딘가",
                operating_hours="09:00-18:00",
                raw_source="fake_place",
            ),
            PlaceCandidate(
                place_id="fake-cafe-1",
                name="테스트 카페",
                category="cafe",
                latitude=latitude + 0.001,
                longitude=longitude + 0.001,
                address="서울 종로구 어딘가",
                operating_hours="08:00-22:00",
                raw_source="fake_place",
            ),
        ]