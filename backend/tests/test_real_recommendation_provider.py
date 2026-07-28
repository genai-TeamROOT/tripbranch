"""RealRecommendationProvider 단위 테스트.

D의 실제 recommendation_pipeline을 호출하되, Tool을 직접 호출하지 않는
run_recommendation_pipeline_from_context() 경로만 쓰므로 외부 API 없이 순수하게
테스트 가능하다.
"""

from __future__ import annotations

import pytest

from app.errors import AppError
from app.schemas import UserConditions
from app.services.runtime import real_recommendation_provider as module
from app.services.runtime.context_schemas import (
    ContextValue,
    Coordinates,
    PlaceCandidate,
    RecommendationContext,
    ResolvedLocation,
)
from app.services.runtime.real_recommendation_provider import RealRecommendationProvider


def _context(*, place_ids: list[str]) -> RecommendationContext:
    return RecommendationContext(
        location=ContextValue(
            status="success",
            data=ResolvedLocation(
                requested_query="경복궁",
                resolved_name="경복궁",
                location=Coordinates(latitude=37.5796, longitude=126.9770),
            ),
        ),
        places=ContextValue(
            status="success",
            data=[
                PlaceCandidate(
                    place_id=place_id,
                    name=f"장소-{place_id}",
                    category="cafe",
                    location=Coordinates(latitude=37.58, longitude=126.978),
                    operating_hours_raw="09:00~22:00",
                )
                for place_id in place_ids
            ],
        ),
    )


@pytest.mark.asyncio
async def test_recommend_returns_response_for_valid_context() -> None:
    provider = RealRecommendationProvider()
    conditions = UserConditions(max_travel_time=30)
    context = _context(place_ids=["a", "b"])

    result = await provider.recommend(conditions, context, excluded_place_ids=[])

    all_items = [*result.recommendations, *result.unverified_recommendations]
    assert {item.place_id for item in all_items} == {"a", "b"}


@pytest.mark.asyncio
async def test_recommend_excludes_given_place_ids() -> None:
    provider = RealRecommendationProvider()
    conditions = UserConditions()
    context = _context(place_ids=["a", "b", "c"])

    result = await provider.recommend(conditions, context, excluded_place_ids=["a", "b"])

    all_items = [*result.recommendations, *result.unverified_recommendations]
    assert {item.place_id for item in all_items} == {"c"}


@pytest.mark.asyncio
async def test_recommend_raises_app_error_when_context_is_none() -> None:
    provider = RealRecommendationProvider()
    conditions = UserConditions()

    with pytest.raises(AppError):
        await provider.recommend(conditions, None, excluded_place_ids=[])  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_search_radius_km_passed_to_pipeline_matches_to_search_radius_km(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D 호출에 실제로 넘어가는 search_radius_km이 to_search_radius_km() 값과 같은지 확인."""
    captured: dict[str, object] = {}
    original = module.run_recommendation_pipeline_from_context

    async def _capture(context, **kwargs):
        captured.update(kwargs)
        return await original(context, **kwargs)

    monkeypatch.setattr(module, "run_recommendation_pipeline_from_context", _capture)

    provider = RealRecommendationProvider()
    conditions = UserConditions(max_travel_time=30)
    context = _context(place_ids=["a"])

    await provider.recommend(conditions, context, excluded_place_ids=[])

    assert captured["search_radius_km"] == pytest.approx(module.to_search_radius_km(conditions))
    assert captured["visit_at"].tzinfo is not None
