"""Pinecone에 옮긴 취향 근거 벡터를 검색하는 저장소.

역할: `PlaceEvidenceRepository` 계약을 Pinecone으로 구현한다. Supabase를 무료 플랜
      용량(500MB) 안에 넣으려고 `place_embeddings`(1,117MB)를 옮겼다(2026-10, 팀 합의).
입력: 질의 임베딩, 후보 content_id 목록, 장소당 근거 수, 유사도 컷.
출력: 장소별 근거(`PlaceEvidenceMatch`). 평균 유사도 내림차순.

**결과는 Supabase `search_place_evidence` RPC와 같아야 한다.** 채점·근거 문장이 그
결과를 전제로 짜여 있어서다. 규칙은 RPC 그대로다.

1. 유사도가 컷 미만인 문장을 버린다
2. 같은 글(`document_id` → `source_url` → `source_ref` 순으로 첫 값)에서는 유사도가
   가장 높은 문장 하나만 남긴다
3. 장소마다 유사도 상위 `match_count`개를 남기고 그 평균을 장소 점수로 쓴다

Pinecone은 유사도 순으로 문장을 돌려주는 것까지만 하고 2·3번(묶기)을 못 한다. 그래서
컷을 넘는 문장을 전부 받아 와서 여기서 묶는다.

**받는 개수를 단계로 늘린다.** 묶으려면 문장마다 글 ID가 필요한데, Pinecone은 메타
데이터를 필드별로 고를 수 없어 본문까지 통째로 온다(문장당 약 1KB). 후보 30곳의
문장은 1,700개 안팎이지만 컷을 넘는 것은 중앙값 302개, 최대 902개였다(2026-10-16,
평가셋 48회). 그래서 600개를 먼저 받고, 600번째까지 전부 컷을 넘었을 때만 상한으로
다시 받는다 — 그 뒤에 컷을 넘는 문장이 더 있을 수 있어서다. 같은 측정에서 이 방식은
중앙값 257ms, 1,000개를 한 번에 받으면 463~879ms였다(실행마다 흔들림).

**Pinecone 유사도는 전수 계산보다 0.001 안팎 높게 나온다.** 그래서 컷 바로 아래
문장이 가끔 컷을 넘는다. 상위 3개 근거는 48회 모두 RPC와 같았다.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime

import httpx

from app.domain.models import PlaceEvidenceMatch, PlaceEvidenceSnippet
from app.errors import AppError

logger = logging.getLogger(__name__)

# Pinecone 데이터 API 버전. 헤더가 없으면 가장 오래된 계약으로 응답하므로 명시한다.
# 적재 스크립트(export_place_embeddings_to_pinecone)와 같은 값이다.
_PINECONE_API_VERSION = "2026-07"

# Supabase RPC와 같은 후보 상한. 호출부가 같은 계약을 기대하므로 맞춘다.
_MAX_EVIDENCE_CANDIDATES = 500

# 처음 받는 문장 수와 다시 받을 때의 상한. 상한은 Pinecone topK의 최댓값이다.
_INITIAL_TOP_K = 600
_MAX_TOP_K = 10_000


class PineconeRepositoryError(AppError):
    """Pinecone 요청이나 응답이 저장소 계약을 만족하지 못한 경우."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            code="pinecone_repository_error",
            message="취향 근거를 찾는 중 문제가 발생했어요.",
            status_code=502,
            retryable=True,
            provider="pinecone",
            details={"upstream_detail": detail},
        )


class PineconeEvidenceRepository:
    def __init__(
        self,
        api_key: str,
        index_host: str,
        client: httpx.AsyncClient,
        *,
        namespace: str = "",
        timeout_seconds: float = 10.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key가 필요합니다.")
        host = index_host.strip().removeprefix("https://").rstrip("/")
        if not host:
            raise ValueError("index_host가 필요합니다.")
        self._query_url = f"https://{host}/query"
        self._api_key = api_key
        self._client = client
        self._namespace = namespace
        self._timeout_seconds = timeout_seconds

    async def search_place_evidence(
        self,
        query_embedding: Sequence[float],
        candidate_content_ids: Sequence[str],
        *,
        match_count: int,
        min_similarity: float,
    ) -> tuple[PlaceEvidenceMatch, ...]:
        unique_ids = list(dict.fromkeys(candidate_content_ids))
        if not unique_ids:
            return ()
        if len(unique_ids) > _MAX_EVIDENCE_CANDIDATES:
            raise PineconeRepositoryError(
                f"후보 content_id가 {len(unique_ids)}건입니다. "
                f"{_MAX_EVIDENCE_CANDIDATES}건 이하로 좁혀서 호출하세요."
            )

        vector = list(query_embedding)
        top_k = _INITIAL_TOP_K
        while True:
            hits = await self._query(vector, unique_ids, top_k)
            if not _may_have_more_above_cut(hits, top_k, min_similarity):
                break
            if top_k >= _MAX_TOP_K:
                # 상한까지 받았는데도 끝까지 컷을 넘는다. 후보 500곳 × 장소당 100개면
                # 생길 수 있다. 받은 만큼으로 묶는다 — 각 장소의 상위 문장은 이미
                # 들어와 있을 가능성이 높고, 여기서 실패시키면 취향 축 전체가 빠진다.
                logger.warning(
                    "취향 근거 %d개가 모두 컷(%.2f)을 넘어 일부를 받지 못했을 수 있습니다"
                    " (후보 %d곳).",
                    len(hits),
                    min_similarity,
                    len(unique_ids),
                )
                break
            top_k = _MAX_TOP_K

        return _group_by_place(hits, match_count=match_count, min_similarity=min_similarity)

    async def _query(
        self,
        vector: list[float],
        content_ids: list[str],
        top_k: int,
    ) -> list[Mapping[str, object]]:
        try:
            response = await self._client.post(
                self._query_url,
                json={
                    "vector": vector,
                    "topK": top_k,
                    "filter": {"content_id": {"$in": content_ids}},
                    "includeMetadata": True,
                    "includeValues": False,
                    "namespace": self._namespace,
                },
                headers={
                    "Api-Key": self._api_key,
                    "Content-Type": "application/json",
                    "X-Pinecone-Api-Version": _PINECONE_API_VERSION,
                },
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException:
            raise PineconeRepositoryError("request timeout") from None
        except httpx.HTTPStatusError as exc:
            # 응답 본문은 싣지 않는다 — 요청을 되풀이한 내용이 섞일 수 있다.
            raise PineconeRepositoryError(f"HTTP {exc.response.status_code}") from None
        except httpx.HTTPError:
            raise PineconeRepositoryError("request failed") from None

        try:
            payload = response.json()
        except ValueError:
            raise PineconeRepositoryError("non-JSON response") from None
        matches = payload.get("matches") if isinstance(payload, Mapping) else None
        if not isinstance(matches, list):
            raise PineconeRepositoryError("invalid query response")
        return [match for match in matches if isinstance(match, Mapping)]


def _may_have_more_above_cut(
    hits: Sequence[Mapping[str, object]],
    top_k: int,
    min_similarity: float,
) -> bool:
    """받은 칸이 꽉 찼고 마지막 문장까지 컷을 넘으면, 그 뒤에도 넘는 문장이 있을 수 있다."""
    if len(hits) < top_k or not hits:
        return False
    return _score(hits[-1]) >= min_similarity


def _group_by_place(
    hits: Sequence[Mapping[str, object]],
    *,
    match_count: int,
    min_similarity: float,
) -> tuple[PlaceEvidenceMatch, ...]:
    """RPC와 같은 규칙으로 장소별 근거를 만든다. 규칙은 모듈 설명 1~3번."""
    best_per_document: dict[tuple[str, str | None], PlaceEvidenceSnippet] = {}
    titles: dict[str, str] = {}
    for hit in hits:
        similarity = _score(hit)
        if similarity < min_similarity:
            continue
        metadata = hit.get("metadata")
        if not isinstance(metadata, Mapping):
            continue
        content_id = _text(metadata.get("content_id"))
        if content_id is None:
            continue
        snippet = _to_snippet(metadata, similarity)
        # RPC의 coalesce(document_id, source_url, source_ref)와 같은 키다. 셋 다 없으면
        # None 하나로 묶인다 — RPC도 같은 동작이다(2026-10-01 확인: 그런 행은 0건).
        document_key = (
            _text(metadata.get("document_id"))
            or _text(metadata.get("source_url"))
            or _text(metadata.get("source_ref"))
        )
        key = (content_id, document_key)
        kept = best_per_document.get(key)
        if kept is None or snippet.similarity > kept.similarity:
            best_per_document[key] = snippet
        title = _text(metadata.get("place_title"))
        if title is not None:
            titles.setdefault(content_id, title)

    snippets_by_place: dict[str, list[PlaceEvidenceSnippet]] = {}
    for (content_id, _), snippet in best_per_document.items():
        snippets_by_place.setdefault(content_id, []).append(snippet)

    matches: list[PlaceEvidenceMatch] = []
    for content_id, snippets in snippets_by_place.items():
        top = sorted(snippets, key=lambda item: item.similarity, reverse=True)[:match_count]
        if not top:
            continue
        matches.append(
            PlaceEvidenceMatch(
                content_id=content_id,
                place_title=titles.get(content_id, ""),
                avg_similarity=sum(item.similarity for item in top) / len(top),
                snippets=tuple(top),
            )
        )
    matches.sort(key=lambda match: match.avg_similarity, reverse=True)
    return tuple(matches)


def _to_snippet(metadata: Mapping[str, object], similarity: float) -> PlaceEvidenceSnippet:
    return PlaceEvidenceSnippet(
        source_text=_text(metadata.get("source_text")) or "",
        source_url=_text(metadata.get("source_url")),
        similarity=similarity,
        published_at=_datetime(metadata.get("published_at")),
        source_type=_text(metadata.get("source_type")),
        document_id=_text(metadata.get("document_id")),
    )


def _score(hit: Mapping[str, object]) -> float:
    score = hit.get("score")
    if isinstance(score, bool) or not isinstance(score, int | float):
        raise PineconeRepositoryError("match without score")
    return float(score)


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _datetime(value: object) -> datetime | None:
    """적재 때 Supabase가 준 ISO 문자열 그대로 들어 있다. 못 읽으면 날짜 없이 쓴다."""
    text = _text(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
