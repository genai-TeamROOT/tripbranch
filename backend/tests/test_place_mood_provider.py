"""장소 분위기 Provider의 호출 생략 조건과 인코더 부재 처리 테스트."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.domain.models import PlaceMoodMatch, PlaceMoodProfile
from app.providers.contracts import ProviderSource, ProviderStatus
from app.providers.place_mood import (
    DEFAULT_MATCH_COUNT,
    DEFAULT_MIN_SIMILARITY,
    PlaceMoodProvider,
)


class _RecordingEncoder:
    """torch 없이 도는 가짜 인코더 — 호출 여부만 센다."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def encode_image(self, image_bytes: bytes) -> Sequence[float]:
        self.calls.append(len(image_bytes))
        return [0.1] * 768


class _RecordingRepository:
    def __init__(
        self,
        profiles: dict[str, PlaceMoodProfile] | None = None,
        matches: tuple[PlaceMoodMatch, ...] = (),
    ) -> None:
        self.profile_calls: list[list[str]] = []
        self.search_calls: list[dict[str, object]] = []
        self._profiles = profiles or {}
        self._matches = matches

    async def find_mood_profiles(
        self,
        content_ids: Sequence[str],
    ) -> dict[str, PlaceMoodProfile]:
        self.profile_calls.append(list(content_ids))
        return dict(self._profiles)

    async def search_place_mood(
        self,
        query_embedding: Sequence[float],
        candidate_content_ids: Sequence[str] | None,
        *,
        match_count: int,
        min_similarity: float,
        latitude: float | None = None,
        longitude: float | None = None,
        radius_km: float | None = None,
    ) -> tuple[PlaceMoodMatch, ...]:
        self.search_calls.append(
            {
                "embedding_len": len(query_embedding),
                "candidates": (
                    None
                    if candidate_content_ids is None
                    else list(candidate_content_ids)
                ),
                "match_count": match_count,
                "min_similarity": min_similarity,
                "latitude": latitude,
                "longitude": longitude,
                "radius_km": radius_km,
            }
        )
        return self._matches


def _profile(content_id: str, photo_count: int = 4) -> PlaceMoodProfile:
    return PlaceMoodProfile(
        content_id=content_id,
        axis_scores={"calm": 0.12, "traditional": -0.08},
        photo_count=photo_count,
    )


def _match(content_id: str, similarity: float) -> PlaceMoodMatch:
    return PlaceMoodMatch(
        content_id=content_id,
        similarity=similarity,
        profile=_profile(content_id),
    )


@pytest.mark.asyncio
async def test_describe_returns_profiles() -> None:
    repository = _RecordingRepository(profiles={"a": _profile("a")})
    provider = PlaceMoodProvider(repository)

    result = await provider.describe(["a", "b"])

    assert result.metadata.source is ProviderSource.SUPABASE_PLACE_MOOD
    assert result.metadata.status is ProviderStatus.SUCCESS
    assert set(result.data) == {"a"}
    assert repository.profile_calls == [["a", "b"]]


@pytest.mark.asyncio
async def test_describe_skips_query_when_no_candidates() -> None:
    """후보가 없으면 조회하지 않는다 — 빈 in 필터로 왕복만 낭비된다."""
    repository = _RecordingRepository()
    provider = PlaceMoodProvider(repository)

    result = await provider.describe([])

    assert result.metadata.status is ProviderStatus.NO_DATA
    assert repository.profile_calls == []


@pytest.mark.asyncio
async def test_describe_reports_no_data_when_nothing_loaded() -> None:
    """분위기 벡터가 없는 구의 후보만 들어오면 결측이 정상이다."""
    repository = _RecordingRepository(profiles={})
    provider = PlaceMoodProvider(repository)

    result = await provider.describe(["only-in-other-district"])

    assert result.metadata.status is ProviderStatus.NO_DATA
    assert result.data == {}


@pytest.mark.asyncio
async def test_photo_search_passes_defaults_to_repository() -> None:
    """컷값이나 개수를 빠뜨리면 RPC 기본값이 조용히 적용된다."""
    encoder = _RecordingEncoder()
    repository = _RecordingRepository(matches=(_match("a", 0.71),))
    provider = PlaceMoodProvider(repository, encoder)

    result = await provider.search_by_photo(b"fake-jpeg-bytes", ["a", "b"])

    assert result.metadata.status is ProviderStatus.SUCCESS
    assert encoder.calls == [len(b"fake-jpeg-bytes")]
    assert repository.search_calls == [
        {
            "embedding_len": 768,
            "candidates": ["a", "b"],
            "match_count": DEFAULT_MATCH_COUNT,
            "min_similarity": DEFAULT_MIN_SIMILARITY,
            "latitude": None,
            "longitude": None,
            "radius_km": None,
        }
    ]


@pytest.mark.asyncio
async def test_photo_search_without_candidates_passes_none() -> None:
    """후보를 안 넘기면 전체 검색이다 — 빈 배열로 바뀌면 결과가 0건이 된다."""
    repository = _RecordingRepository(matches=(_match("a", 0.71),))
    provider = PlaceMoodProvider(repository, _RecordingEncoder())

    await provider.search_by_photo(b"bytes")

    assert repository.search_calls[0]["candidates"] is None


@pytest.mark.asyncio
async def test_photo_search_without_encoder_does_not_query() -> None:
    """인코더가 없으면 조회하지 않는다.

    빈 벡터로 흉내내면 유사도가 전부 같아져 아무 장소나 순서대로 돌아오고,
    그게 추천으로 나가면 틀린 줄도 모른다(D-042).
    """
    repository = _RecordingRepository(matches=(_match("a", 0.71),))
    provider = PlaceMoodProvider(repository, encoder=None)

    result = await provider.search_by_photo(b"bytes")

    assert provider.photo_search_available is False
    assert result.metadata.status is ProviderStatus.NO_DATA
    assert result.data == ()
    assert repository.search_calls == []


@pytest.mark.asyncio
async def test_photo_search_skips_empty_image() -> None:
    encoder = _RecordingEncoder()
    repository = _RecordingRepository()
    provider = PlaceMoodProvider(repository, encoder)

    result = await provider.search_by_photo(b"")

    assert result.metadata.status is ProviderStatus.NO_DATA
    assert encoder.calls == []
    assert repository.search_calls == []


@pytest.mark.asyncio
async def test_describe_works_without_encoder() -> None:
    """SigLIP이 안 깔린 환경에서도 발화 경로는 돌아야 한다."""
    repository = _RecordingRepository(profiles={"a": _profile("a")})
    provider = PlaceMoodProvider(repository, encoder=None)

    result = await provider.describe(["a"])

    assert result.metadata.status is ProviderStatus.SUCCESS
    assert provider.photo_search_available is False


@pytest.mark.asyncio
async def test_radius_is_passed_through() -> None:
    """좌표와 반경으로 부르면 DB가 직접 좁힌다.

    후보 목록으로 부르면 그 목록을 만드는 데 TourAPI 상세 조회가 붙어 최대
    20곳이 된다 — 2,009곳을 적재해 두고 그 안에서만 고르는 셈이 된다.
    """
    repository = _RecordingRepository(matches=(_match("a", 0.9),))
    provider = PlaceMoodProvider(repository, _RecordingEncoder())

    await provider.search_by_photo(
        b"bytes", None, latitude=37.57, longitude=126.98, radius_km=2.0, match_count=40
    )

    call = repository.search_calls[0]
    assert call["candidates"] is None
    assert call["latitude"] == pytest.approx(37.57)
    assert call["radius_km"] == pytest.approx(2.0)
    assert call["match_count"] == 40
