from __future__ import annotations

from app.schemas import RecommendationItem, RecommendationResponse

STUB_RECOMMENDATIONS = [
    RecommendationItem(
        place_id="stub-museum-1",
        name="테스트 박물관",
        category="museum",
        distance_km=0.4,
        remaining_minutes=150,
        environment_type="indoor",
        recommendation_reason="비 오는 날 방문하기 좋은 실내 장소예요.",
        warnings=[],
    ),
    RecommendationItem(
        place_id="stub-cafe-1",
        name="테스트 카페",
        category="cafe",
        distance_km=0.7,
        remaining_minutes=80,
        environment_type="indoor",
        recommendation_reason="현재 위치에서 가까운 장소예요.",
        warnings=[],
    ),
    RecommendationItem(
        place_id="stub-park-1",
        name="테스트 공원",
        category="park",
        distance_km=0.9,
        remaining_minutes=200,
        environment_type="outdoor",
        recommendation_reason="가까운 야외 장소예요.",
        warnings=["현재 날씨를 확인해주세요."],
    ),
]

STUB_UNVERIFIED_RECOMMENDATIONS = [
    RecommendationItem(
        place_id="stub-gallery-1",
        name="운영시간 미확인 갤러리",
        category="gallery",
        distance_km=0.8,
        remaining_minutes=None,
        environment_type="indoor",
        recommendation_reason="선호한 문화 장소와 비슷한 장소예요.",
        warnings=["방문 전에 운영 여부를 확인해주세요."],
    )
]


def get_stub_recommendations(shown_place_ids: list[str]) -> RecommendationResponse:
    shown = set(shown_place_ids)
    return RecommendationResponse(
        recommendations=[item for item in STUB_RECOMMENDATIONS if item.place_id not in shown],
        unverified_recommendations=[
            item for item in STUB_UNVERIFIED_RECOMMENDATIONS if item.place_id not in shown
        ],
    )
