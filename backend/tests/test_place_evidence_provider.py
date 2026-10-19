"""취향 근거 Provider의 호출 생략 조건과 컷값 전달 테스트."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.domain.models import PlaceEvidenceMatch, PlaceEvidenceSnippet
from app.providers.contracts import ProviderSource, ProviderStatus
from app.providers.place_evidence import (
    DEFAULT_MATCH_COUNT,
    DEFAULT_MIN_SIMILARITY,
    EVIDENCE_POOL_COUNT,
    MIN_EVIDENCE_TEXT_LENGTH,
    PlaceEvidenceProvider,
)


class _RecordingEncoder:
    """torch 없이 도는 가짜 인코더 — 호출 여부만 센다."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def encode(self, text: str) -> Sequence[float]:
        self.calls.append(text)
        return [0.1] * 768


class _RecordingRepository:
    def __init__(self, matches: tuple[PlaceEvidenceMatch, ...] = ()) -> None:
        self.calls: list[dict[str, object]] = []
        self._matches = matches

    async def search_place_evidence(
        self,
        query_embedding: Sequence[float],
        candidate_content_ids: Sequence[str],
        *,
        match_count: int,
        min_similarity: float,
    ) -> tuple[PlaceEvidenceMatch, ...]:
        self.calls.append(
            {
                "embedding_len": len(query_embedding),
                "candidates": list(candidate_content_ids),
                "match_count": match_count,
                "min_similarity": min_similarity,
            }
        )
        return self._matches


def _match(content_id: str) -> PlaceEvidenceMatch:
    return PlaceEvidenceMatch(
        content_id=content_id,
        place_title=f"장소 {content_id}",
        avg_similarity=0.55,
        snippets=(
            PlaceEvidenceSnippet(
                source_text="혼자 조용히 책 읽으며 오래 머물기 좋았다",
                source_url=None,
                similarity=0.55,
                published_at=None,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_cut_value_and_match_count_reach_the_repository() -> None:
    """컷값을 안 넘기면 RPC 기본값 0.0이 적용돼 필터가 조용히 사라진다."""
    encoder, repository = _RecordingEncoder(), _RecordingRepository((_match("a"),))
    provider = PlaceEvidenceProvider(encoder, repository)

    await provider.search("혼자 조용히 쉬고 싶어", ["a", "b"])

    assert repository.calls[0]["min_similarity"] == DEFAULT_MIN_SIMILARITY == 0.43
    # 짧은 문장을 거른 뒤에도 칸을 채우도록 넉넉히 받아 온다.
    assert repository.calls[0]["match_count"] == EVIDENCE_POOL_COUNT > DEFAULT_MATCH_COUNT
    assert repository.calls[0]["embedding_len"] == 768


@pytest.mark.asyncio
async def test_result_is_keyed_by_content_id() -> None:
    """채점 측이 후보별로 바로 꺼내 쓸 수 있어야 한다."""
    provider = PlaceEvidenceProvider(
        _RecordingEncoder(), _RecordingRepository((_match("a"), _match("b")))
    )

    result = await provider.search("조용한 곳", ["a", "b"])

    assert set(result.data) == {"a", "b"}
    assert result.metadata.source is ProviderSource.SUPABASE_PLACE_EVIDENCE
    assert result.metadata.status is ProviderStatus.SUCCESS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "candidates"),
    [("", ["a"]), ("   ", ["a"]), ("조용한 곳", [])],
)
async def test_empty_input_skips_encoding_and_query(
    query: str, candidates: list[str]
) -> None:
    """취향을 말하지 않은 요청이 대부분이라, 여기서 안 걸러내면 모델 호출이 낭비된다."""
    encoder, repository = _RecordingEncoder(), _RecordingRepository()
    provider = PlaceEvidenceProvider(encoder, repository)

    result = await provider.search(query, candidates)

    assert encoder.calls == []
    assert repository.calls == []
    assert result.data == {}
    assert result.metadata.status is ProviderStatus.NO_DATA


@pytest.mark.asyncio
async def test_no_match_is_reported_as_no_data() -> None:
    """컷값을 넘긴 근거가 하나도 없으면 성공이 아니라 데이터 없음이다."""
    provider = PlaceEvidenceProvider(_RecordingEncoder(), _RecordingRepository(()))

    result = await provider.search("조용한 곳", ["a"])

    assert result.data == {}
    assert result.metadata.status is ProviderStatus.NO_DATA


def _snippet(text: str, similarity: float) -> PlaceEvidenceSnippet:
    return PlaceEvidenceSnippet(
        source_text=text, source_url=None, similarity=similarity, published_at=None
    )


@pytest.mark.asyncio
async def test_short_praise_is_dropped_and_top_three_are_kept() -> None:
    """"아주 좋은 카페입니다." 같은 짧은 칭찬은 취향 단어 없이 유사도만 높다."""
    pool = PlaceEvidenceMatch(
        content_id="a",
        place_title="장소 a",
        avg_similarity=0.60,
        snippets=(
            _snippet("아주 좋은 카페입니다.", 0.67),
            _snippet("창가 자리에 콘센트가 있어 노트북 작업하기 좋았어요", 0.62),
            _snippet("넓은 테이블이 많아 오래 앉아 공부하기 편했습니다", 0.58),
            _snippet("조용해서 혼자 책 읽거나 작업하는 사람이 많았다", 0.55),
            _snippet("커피 맛은 무난하고 디저트 종류가 다양한 편이에요", 0.50),
        ),
    )
    provider = PlaceEvidenceProvider(_RecordingEncoder(), _RecordingRepository((pool,)))

    result = await provider.search("카공하기 좋은 카페", ["a"])

    match = result.data["a"]
    assert [snippet.similarity for snippet in match.snippets] == [0.62, 0.58, 0.55]
    assert all(len(s.source_text.strip()) >= MIN_EVIDENCE_TEXT_LENGTH for s in match.snippets)
    # 남은 문장끼리 평균을 다시 낸다 — RPC가 준 평균은 거른 문장까지 섞인 값이다.
    assert match.avg_similarity == pytest.approx((0.62 + 0.58 + 0.55) / 3)


@pytest.mark.asyncio
async def test_place_with_only_short_evidence_has_no_match() -> None:
    """짧은 문장뿐인 장소는 근거가 없는 곳이다 — 채점에서 0점이 된다."""
    pool = PlaceEvidenceMatch(
        content_id="a",
        place_title="장소 a",
        avg_similarity=0.648,
        snippets=(_snippet("전망 좋은 정말 멋진 카페!", 0.648),),
    )
    provider = PlaceEvidenceProvider(_RecordingEncoder(), _RecordingRepository((pool,)))

    result = await provider.search("카공하기 좋은 카페", ["a"])

    assert result.data == {}
    assert result.metadata.status is ProviderStatus.NO_DATA
