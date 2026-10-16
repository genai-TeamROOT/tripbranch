"""Pinecone 취향 근거 저장소의 요청 구성·묶기 규칙·재조회 테스트.

묶기 규칙은 Supabase `search_place_evidence` RPC와 같아야 한다 — 채점과 근거 문장이
그 결과를 전제로 짜여 있다. 그래서 RPC 규칙(컷 → 글당 1문장 → 장소당 상위 N개
평균) 하나하나를 각각 못 박는다.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

import httpx
import pytest

from app.config import settings
from app.domain.models import PlaceEvidenceMatch
from app.providers import factory
from app.repositories.pinecone_evidence import (
    PineconeEvidenceRepository,
    PineconeRepositoryError,
)

_API_KEY = "pinecone-secret-key"
_HOST = "place-evidence-test.svc.pinecone.io"


def _hit(
    content_id: str,
    score: float,
    *,
    document_id: str | None = None,
    source_url: str | None = None,
    source_ref: str | None = None,
    text: str = "창가 자리에서 조용히 책 읽기 좋았어요",
    **extra: object,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "content_id": content_id,
        "place_title": f"장소 {content_id}",
        "source_text": text,
        "source_type": "naver_post",
    }
    for name, value in (
        ("document_id", document_id),
        ("source_url", source_url),
        ("source_ref", source_ref),
    ):
        if value is not None:
            metadata[name] = value
    metadata.update(extra)
    return {"id": f"{content_id}-{score}", "score": score, "metadata": metadata}


def _repository(handler) -> tuple[PineconeEvidenceRepository, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return PineconeEvidenceRepository(_API_KEY, _HOST, client, namespace="ns"), client


async def _search(
    hits: list[dict[str, object]],
    *,
    match_count: int = 3,
    min_similarity: float = 0.43,
) -> tuple[PlaceEvidenceMatch, ...]:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"matches": hits})

    repository, client = _repository(handler)
    async with client:
        return await repository.search_place_evidence(
            [0.1] * 768, ["a", "b"], match_count=match_count, min_similarity=min_similarity
        )


@pytest.mark.asyncio
async def test_query_request_shape() -> None:
    """후보 필터·메타데이터·네임스페이스가 빠지면 오류 없이 엉뚱한 결과가 온다."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"matches": []})

    repository, client = _repository(handler)
    async with client:
        await repository.search_place_evidence(
            [0.1] * 768, ["a", "b", "a"], match_count=3, min_similarity=0.43
        )

    assert len(seen) == 1
    request = seen[0]
    assert str(request.url) == f"https://{_HOST}/query"
    assert request.headers["Api-Key"] == _API_KEY
    assert request.headers["X-Pinecone-Api-Version"]
    body = json.loads(request.content)
    assert len(body["vector"]) == 768
    assert body["topK"] == 600
    # 중복 후보는 한 번만 보낸다.
    assert body["filter"] == {"content_id": {"$in": ["a", "b"]}}
    assert body["includeMetadata"] is True
    assert body["includeValues"] is False
    assert body["namespace"] == "ns"


@pytest.mark.asyncio
async def test_similarity_below_cut_is_dropped() -> None:
    matches = await _search(
        [
            _hit("a", 0.60, document_id="d1"),
            _hit("a", 0.4299, document_id="d2"),
            _hit("b", 0.42, document_id="d3"),
        ]
    )

    assert [m.content_id for m in matches] == ["a"]
    assert [s.similarity for s in matches[0].snippets] == [0.60]


@pytest.mark.asyncio
async def test_one_sentence_per_document_keeps_the_best() -> None:
    """같은 글의 문장이 여러 칸을 차지하면 근거가 한 글의 의견으로 쏠린다."""
    matches = await _search(
        [
            _hit("a", 0.70, document_id="d1", text="첫 번째 글의 가장 비슷한 문장입니다"),
            _hit("a", 0.65, document_id="d1", text="첫 번째 글의 두 번째 문장입니다만"),
            _hit("a", 0.50, document_id="d2", text="두 번째 글에서 나온 문장입니다만"),
        ]
    )

    snippets = matches[0].snippets
    assert [s.document_id for s in snippets] == ["d1", "d2"]
    assert snippets[0].source_text == "첫 번째 글의 가장 비슷한 문장입니다"


@pytest.mark.asyncio
async def test_document_key_falls_back_like_the_rpc() -> None:
    """RPC의 coalesce(document_id, source_url, source_ref)와 같은 순서로 글을 가른다.

    Google 리뷰는 서로 다른 리뷰가 같은 지도 URL을 공유한다 — document_id가 있으면
    URL이 같아도 다른 글이어야 한다. 종로구 구버전 행은 document_id가 없어 URL로 가른다.
    """
    matches = await _search(
        [
            # document_id가 다르면 URL이 같아도 각각 남는다.
            _hit("a", 0.70, document_id="r1", source_url="https://maps.test/place"),
            _hit("a", 0.69, document_id="r2", source_url="https://maps.test/place"),
            # document_id가 없으면 URL로 묶인다.
            _hit("b", 0.68, source_url="https://blog.test/1"),
            _hit("b", 0.67, source_url="https://blog.test/1"),
            # 둘 다 없으면 source_ref로 묶인다.
            _hit("b", 0.66, source_ref="ref-1"),
            _hit("b", 0.65, source_ref="ref-1"),
        ]
    )

    by_place = {m.content_id: m for m in matches}
    assert [s.similarity for s in by_place["a"].snippets] == [0.70, 0.69]
    assert [s.similarity for s in by_place["b"].snippets] == [0.68, 0.66]


@pytest.mark.asyncio
async def test_top_n_per_place_is_averaged_and_places_are_sorted() -> None:
    matches = await _search(
        [
            _hit("a", 0.50, document_id="a1"),
            _hit("b", 0.90, document_id="b1"),
            _hit("a", 0.60, document_id="a2"),
            _hit("a", 0.70, document_id="a3"),
            _hit("a", 0.80, document_id="a4"),
        ],
        match_count=3,
    )

    assert [m.content_id for m in matches] == ["b", "a"]
    place_a = matches[1]
    assert [s.similarity for s in place_a.snippets] == [0.80, 0.70, 0.60]
    assert place_a.avg_similarity == pytest.approx(0.70)
    assert place_a.place_title == "장소 a"


@pytest.mark.asyncio
async def test_snippet_fields_are_mapped() -> None:
    matches = await _search(
        [
            _hit(
                "a",
                0.6,
                document_id="d1",
                source_url="https://blog.test/1",
                published_at="2026-05-01T00:00:00+00:00",
            ),
            _hit("b", 0.5, document_id="d2", published_at="날짜 아님"),
        ]
    )

    first = matches[0].snippets[0]
    assert first.source_url == "https://blog.test/1"
    assert first.source_type == "naver_post"
    assert first.document_id == "d1"
    assert first.published_at == datetime.fromisoformat("2026-05-01T00:00:00+00:00")
    # 날짜를 못 읽어도 근거는 버리지 않는다.
    assert matches[1].snippets[0].published_at is None


@pytest.mark.asyncio
async def test_full_page_above_cut_is_queried_again_with_the_limit() -> None:
    """600칸이 꽉 찼고 마지막까지 컷을 넘으면 뒤에 더 있을 수 있다."""
    seen_top_k: list[int] = []
    full_page = [_hit("a", 0.9 - i * 0.0001, document_id=f"d{i}") for i in range(600)]

    def handler(request: httpx.Request) -> httpx.Response:
        top_k = json.loads(request.content)["topK"]
        seen_top_k.append(top_k)
        hits = full_page if top_k == 600 else [*full_page, _hit("b", 0.5, document_id="late")]
        return httpx.Response(200, json={"matches": hits})

    repository, client = _repository(handler)
    async with client:
        matches = await repository.search_place_evidence(
            [0.1] * 768, ["a", "b"], match_count=3, min_similarity=0.43
        )

    assert seen_top_k == [600, 10_000]
    # 두 번째 조회에서만 보이는 장소가 결과에 들어와야 한다.
    assert {m.content_id for m in matches} == {"a", "b"}


@pytest.mark.asyncio
async def test_no_requery_when_page_ends_below_cut() -> None:
    seen: list[int] = []
    page = [_hit("a", 0.9 - i * 0.001, document_id=f"d{i}") for i in range(600)]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["topK"])
        return httpx.Response(200, json={"matches": page})

    repository, client = _repository(handler)
    async with client:
        await repository.search_place_evidence(
            [0.1] * 768, ["a"], match_count=3, min_similarity=0.43
        )

    # 마지막 문장 유사도가 0.301로 컷 아래라 더 받을 것이 없다.
    assert seen == [600]


@pytest.mark.asyncio
async def test_limit_still_above_cut_warns_and_uses_what_it_got(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        top_k = json.loads(request.content)["topK"]
        return httpx.Response(
            200, json={"matches": [_hit("a", 0.9, document_id=f"d{i}") for i in range(top_k)]}
        )

    repository, client = _repository(handler)
    with caplog.at_level(logging.WARNING, logger="app.repositories.pinecone_evidence"):
        async with client:
            matches = await repository.search_place_evidence(
                [0.1] * 768, ["a"], match_count=3, min_similarity=0.43
            )

    assert [m.content_id for m in matches] == ["a"]
    assert "모두 컷" in caplog.text


@pytest.mark.asyncio
async def test_empty_candidates_skip_the_request() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("요청하면 안 된다")

    repository, client = _repository(handler)
    async with client:
        assert await repository.search_place_evidence(
            [0.1] * 768, [], match_count=3, min_similarity=0.43
        ) == ()


@pytest.mark.asyncio
async def test_candidate_limit_is_blocked_before_the_request() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("요청하면 안 된다")

    repository, client = _repository(handler)
    async with client:
        with pytest.raises(PineconeRepositoryError):
            await repository.search_place_evidence(
                [0.1] * 768, [str(i) for i in range(501)], match_count=3, min_similarity=0.43
            )


@pytest.mark.asyncio
async def test_http_error_hides_the_key_and_body() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": f"bad key {_API_KEY}"})

    repository, client = _repository(handler)
    async with client:
        with pytest.raises(PineconeRepositoryError) as caught:
            await repository.search_place_evidence(
                [0.1] * 768, ["a"], match_count=3, min_similarity=0.43
            )

    assert caught.value.details == {"upstream_detail": "HTTP 401"}
    assert _API_KEY not in repr(caught.value.details)


@pytest.mark.asyncio
async def test_timeout_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    repository, client = _repository(handler)
    async with client:
        with pytest.raises(PineconeRepositoryError):
            await repository.search_place_evidence(
                [0.1] * 768, ["a"], match_count=3, min_similarity=0.43
            )


@pytest.mark.asyncio
async def test_response_without_matches_list_is_rejected() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"matches": "없음"})

    repository, client = _repository(handler)
    async with client:
        with pytest.raises(PineconeRepositoryError):
            await repository.search_place_evidence(
                [0.1] * 768, ["a"], match_count=3, min_similarity=0.43
            )


def test_host_accepts_scheme_and_trailing_slash() -> None:
    client = httpx.AsyncClient()
    repository = PineconeEvidenceRepository(_API_KEY, f"https://{_HOST}/", client)
    assert repository._query_url == f"https://{_HOST}/query"


@pytest.mark.asyncio
async def test_factory_builds_the_pinecone_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "taste_evidence_enabled", True)
    monkeypatch.setattr(settings, "pinecone_api_key", _API_KEY)
    monkeypatch.setattr(settings, "pinecone_index_host", _HOST)
    # 인코더는 첫 encode 때 모델을 올리므로 만들기만 해서는 무겁지 않지만, 여기서는
    # 저장소 조립만 보면 되므로 가벼운 대역으로 바꾼다.
    monkeypatch.setattr(factory, "get_shared_encoder", lambda: object())

    async with httpx.AsyncClient() as client:
        provider = factory.get_place_evidence_provider(client)

    assert provider is not None
    assert isinstance(provider._repository, PineconeEvidenceRepository)


@pytest.mark.asyncio
async def test_factory_turns_taste_off_without_pinecone_settings(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Supabase로 되돌아가지 않는다(D-042). 꺼지되 이유는 로그로 남긴다."""
    monkeypatch.setattr(settings, "taste_evidence_enabled", True)
    monkeypatch.setattr(settings, "pinecone_api_key", "")
    monkeypatch.setattr(settings, "pinecone_index_host", _HOST)
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_secret_key", "supabase-key")

    with caplog.at_level(logging.WARNING, logger="app.providers.factory"):
        async with httpx.AsyncClient() as client:
            assert factory.get_place_evidence_provider(client) is None

    assert "PINECONE_API_KEY" in caplog.text
