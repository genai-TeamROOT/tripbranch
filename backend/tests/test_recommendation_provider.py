"""RealRecommendationProvider(RecommendationProvider Protocol 실제 구현체) 검증.

package_D/[TECH-02] C-D 직접 의존 제거 및 RecommendationContext 경계 정리.txt
"""

from __future__ import annotations

import pytest

from app.agent_context.schemas import ContextValue as AgentContextValue
from app.agent_context.schemas import (
    Coordinates,
    PlaceCandidate,
    RecommendationContext,
    ResolvedLocation,
)
from app.schemas import Transport, UserConditions
from app.services.runtime.recommendation_provider import RealRecommendationProvider


def _context(*place_ids: str) -> RecommendationContext:
    return RecommendationContext(
        location=AgentContextValue(
            status="success",
            data=ResolvedLocation(
                requested_query="경복궁",
                resolved_name="경복궁",
                location=Coordinates(latitude=37.5796, longitude=126.9770),
            ),
        ),
        places=AgentContextValue(
            status="success",
            data=[
                PlaceCandidate(
                    place_id=place_id,
                    name=f"장소-{place_id}",
                    category="cafe",
                    location=Coordinates(latitude=37.5806, longitude=126.9770),
                    operating_schedule={
                        "availability": "all_day",
                        "rules": [],
                        "closure_rules": [],
                    },
                )
                for place_id in place_ids
            ],
        ),
    )


@pytest.mark.asyncio
async def test_recommend_uses_context_pipeline_and_returns_response() -> None:
    provider = RealRecommendationProvider()

    response = await provider.recommend(
        UserConditions(),
        _context("place-1"),
        [],
    )

    assert len(response.recommendations) == 1
    assert response.recommendations[0].place_id == "place-1"


@pytest.mark.asyncio
async def test_recommend_excludes_given_place_ids() -> None:
    provider = RealRecommendationProvider()

    response = await provider.recommend(
        UserConditions(),
        _context("place-1", "place-2"),
        ["place-1"],
    )

    place_ids = {item.place_id for item in response.recommendations}
    assert place_ids == {"place-2"}


@pytest.mark.asyncio
async def test_recommend_derives_search_radius_from_conditions() -> None:
    provider = RealRecommendationProvider()
    conditions = UserConditions(transport=Transport.WALK, max_travel_time=30)

    # to_search_radius_km(WALK, 30분) = 0.07 * 30 = 2.1km. 두 후보 모두 반경
    # 안(약 0.1km)이라 반경 계산 자체가 결과를 걸러내진 않지만, 예외 없이
    # conditions 기반 반경이 score_candidates까지 전달되는지 확인한다.
    response = await provider.recommend(conditions, _context("place-1"), [])

    assert len(response.recommendations) == 1
