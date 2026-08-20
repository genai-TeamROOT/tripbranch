"""취향 근거 Provider 조립과 D 진입점 배선 테스트."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.domain.models import PlaceEvidenceMatch
from app.providers.contracts import ProviderSource, ProviderStatus, provider_result
from app.schemas import UserConditions
from app.services.runtime.real_recommendation_provider import (
    RealRecommendationProvider,
)


class _RecordingEvidenceProvider:
    def __init__(self, matches: dict[str, PlaceEvidenceMatch] | None = None) -> None:
        self.calls: list[tuple[str, list[str]]] = []
        self._matches = matches or {}

    async def search(self, query: str, candidate_content_ids: Sequence[str]):
        self.calls.append((query, list(candidate_content_ids)))
        return provider_result(
            self._matches,
            source=ProviderSource.SUPABASE_PLACE_EVIDENCE,
            status=ProviderStatus.SUCCESS if self._matches else ProviderStatus.NO_DATA,
        )


class _FailingEvidenceProvider:
    async def search(self, query: str, candidate_content_ids: Sequence[str]):
        raise RuntimeError("RPC 장애")


class _Prepared:
    """preparation.eligible_candidates만 보는 최소 대역."""

    def __init__(self, place_ids: Sequence[str]) -> None:
        self.preparation = type(
            "P",
            (),
            {
                "eligible_candidates": tuple(
                    type("C", (), {"candidate": type("X", (), {"place_id": pid})()})()
                    for pid in place_ids
                )
            },
        )()


def _match(place_id: str) -> PlaceEvidenceMatch:
    return PlaceEvidenceMatch(place_id, f"장소 {place_id}", 0.6, ())


@pytest.mark.asyncio
async def test_search_is_scoped_to_hard_filter_survivors() -> None:
    """후보를 안 좁히면 RPC가 전체를 훑어 6~9초가 걸린다(2026-08-18 실측)."""
    evidence = _RecordingEvidenceProvider({"a": _match("a")})
    provider = RealRecommendationProvider(evidence)

    matches = await provider._taste_matches_for(
        UserConditions(taste_query="조용한 곳"), _Prepared(["a", "b"])
    )

    assert evidence.calls == [("조용한 곳", ["a", "b"])]
    assert matches is not None and set(matches) == {"a"}


@pytest.mark.asyncio
async def test_no_taste_query_skips_the_search_and_the_feature() -> None:
    """취향 미언급 요청의 가중치가 바뀌면 안 된다 — None이어야 Feature가 꺼진다."""
    evidence = _RecordingEvidenceProvider()
    provider = RealRecommendationProvider(evidence)

    matches = await provider._taste_matches_for(
        UserConditions(), _Prepared(["a"])
    )

    assert matches is None
    assert evidence.calls == []


@pytest.mark.asyncio
async def test_provider_absent_disables_the_feature() -> None:
    """모델을 올릴 수 없는 배포에서도 추천은 그대로 동작해야 한다."""
    provider = RealRecommendationProvider(None)

    assert await provider._taste_matches_for(
        UserConditions(taste_query="조용한 곳"), _Prepared(["a"])
    ) is None


@pytest.mark.asyncio
async def test_search_failure_falls_back_to_scoring_without_taste() -> None:
    """취향은 순위를 다듬는 축이지 후보를 만드는 축이 아니다 — 실패가 추천을 막으면 안 된다."""
    provider = RealRecommendationProvider(_FailingEvidenceProvider())

    assert await provider._taste_matches_for(
        UserConditions(taste_query="조용한 곳"), _Prepared(["a"])
    ) is None


@pytest.mark.asyncio
async def test_empty_candidates_skip_the_search() -> None:
    """하드 필터가 후보를 다 걸러낸 요청에서 빈 RPC를 부르지 않는다."""
    evidence = _RecordingEvidenceProvider()
    provider = RealRecommendationProvider(evidence)

    assert await provider._taste_matches_for(
        UserConditions(taste_query="조용한 곳"), _Prepared([])
    ) is None
    assert evidence.calls == []


def test_subclass_without_init_still_works() -> None:
    """A의 테스트 대역이 __init__을 부르지 않고 상속한다 — 클래스 기본값이 필요하다."""

    class _Sub(RealRecommendationProvider):
        def __init__(self) -> None:  # noqa: D107 - 의도적으로 super()를 부르지 않는다
            pass

    assert _Sub()._place_evidence is None
