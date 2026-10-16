"""새 임베딩 적재 스크립트가 Pinecone에 올바르게 쓰는지 확인한다.

서비스(`PineconeEvidenceRepository`)가 읽는 메타데이터가 실제로 실리는지, 그리고
옛 버전 삭제가 적재가 끝난 뒤에만 맞는 조건으로 나가는지를 못 박는다. 적재가
조용히 빈 필드로 들어가면 검색은 성공하는데 근거가 0건이 된다.
"""

from __future__ import annotations

import argparse
import functools
import json
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from scripts import import_place_embeddings as importer

_HOST = "place-evidence-test.svc.pinecone.io"


def _row(content_id: str, chunk_id: str, *, version: str = "v9") -> dict[str, object]:
    return {
        "content_id": content_id,
        "source_ref": f"ref-{chunk_id}",
        "chunk_id": chunk_id,
        "document_id": f"doc-{chunk_id}",
        "source_type": "naver_post",
        "source_text": "창가 자리에서 조용히 책 읽기 좋았어요",
        "source_url": "https://blog.test/1",
        "place_title": f"장소 {content_id}",
        "model_name": "jhgan/ko-sroberta-multitask",
        "embedding_version": version,
        "published_at": "2026-05-01T12:00:00+09:00",
        "embedding": [0.01] * 768,
    }


def _write_jsonl(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / "place_embeddings.jsonl"
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), "utf-8")
    return path


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "supabase_url": "https://example.supabase.co",
        "supabase_secret_key": "supabase-key",
        "pinecone_api_key": "pinecone-key",
        "pinecone_index_host": _HOST,
        "pinecone_namespace": "ns",
    }
    values.update(overrides)
    # 개발자 .env를 읽지 않게 한다 — 실제 키로 테스트가 돌면 안 된다.
    return Settings(_env_file=None, **values)


def _args(jsonl: Path, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "jsonl": jsonl,
        "dry_run": False,
        "replace_existing": False,
        "scope_content_ids": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class _FakeServices:
    """Supabase places 조회와 Pinecone 호출을 흉내 내고 요청을 순서대로 남긴다."""

    def __init__(self, active_ids: list[str], superseded_matches: int = 0) -> None:
        self.active_ids = active_ids
        self.superseded_matches = superseded_matches
        self.requests: list[tuple[str, dict[str, object] | None]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.url.path, body))
        if request.url.path == "/rest/v1/places":
            return httpx.Response(200, json=[{"content_id": cid} for cid in self.active_ids])
        if request.url.path == "/vectors/upsert":
            return httpx.Response(200, json={"upsertedCount": len(body["vectors"])})
        if request.url.path == "/query":
            matches = [{"id": f"old-{i}", "score": 0.1} for i in range(self.superseded_matches)]
            return httpx.Response(200, json={"matches": matches})
        if request.url.path == "/vectors/delete":
            return httpx.Response(200, json={})
        raise AssertionError(f"예상하지 못한 요청: {request.url}")

    def paths(self) -> list[str]:
        return [path for path, _ in self.requests]

    def bodies(self, path: str) -> list[dict[str, object]]:
        return [body for p, body in self.requests if p == path and body is not None]


@pytest.fixture
def services(monkeypatch: pytest.MonkeyPatch) -> _FakeServices:
    fake = _FakeServices(active_ids=["a", "b"])
    transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(
        importer.httpx,
        "AsyncClient",
        functools.partial(httpx.AsyncClient, transport=transport),
    )
    return fake


@pytest.mark.asyncio
async def test_records_carry_the_fields_the_service_reads(
    tmp_path: Path, services: _FakeServices
) -> None:
    jsonl = _write_jsonl(tmp_path, [_row("a", "chunk_1"), _row("b", "chunk_2")])

    result = await importer.run(_args(jsonl), _settings())

    assert result.imported_count == 2
    upserts = services.bodies("/vectors/upsert")
    assert len(upserts) == 1
    assert upserts[0]["namespace"] == "ns"
    record = upserts[0]["vectors"][0]
    # 레코드 ID는 이관 스크립트와 같은 chunk_id다 — 다르면 다시 넣을 때 중복이 쌓인다.
    assert record["id"] == "chunk_1"
    assert len(record["values"]) == 768
    metadata = record["metadata"]
    # PineconeEvidenceRepository가 후보 필터·글 판별·근거 문장에 쓰는 값이다.
    assert metadata["content_id"] == "a"
    assert metadata["document_id"] == "doc-chunk_1"
    assert metadata["source_text"] == "창가 자리에서 조용히 책 읽기 좋았어요"
    assert metadata["embedding_version"] == "v9"
    assert metadata["published_at"] == "2026-05-01T12:00:00+09:00"


@pytest.mark.asyncio
async def test_dry_run_sends_nothing_to_pinecone_and_needs_no_key(
    tmp_path: Path, services: _FakeServices
) -> None:
    jsonl = _write_jsonl(tmp_path, [_row("a", "chunk_1")])

    result = await importer.run(
        _args(jsonl, dry_run=True), _settings(pinecone_api_key="", pinecone_index_host="")
    )

    assert result.imported_count == 0
    assert services.paths() == ["/rest/v1/places"]


@pytest.mark.asyncio
async def test_shared_chunk_id_across_places_stops_before_any_request(
    tmp_path: Path, services: _FakeServices
) -> None:
    jsonl = _write_jsonl(tmp_path, [_row("a", "chunk_1"), _row("b", "chunk_1")])

    with pytest.raises(ValueError, match="같은 chunk_id"):
        await importer.run(_args(jsonl), _settings())

    assert services.paths() == []


@pytest.mark.asyncio
async def test_inactive_place_stops_before_writing(
    tmp_path: Path, services: _FakeServices
) -> None:
    jsonl = _write_jsonl(tmp_path, [_row("zzz", "chunk_1")])

    with pytest.raises(ValueError, match="활성 places"):
        await importer.run(_args(jsonl), _settings())

    assert "/vectors/upsert" not in services.paths()


@pytest.mark.asyncio
async def test_missing_pinecone_key_is_rejected(tmp_path: Path, services: _FakeServices) -> None:
    jsonl = _write_jsonl(tmp_path, [_row("a", "chunk_1")])

    with pytest.raises(ValueError, match="PINECONE_API_KEY"):
        await importer.run(_args(jsonl), _settings(pinecone_api_key=""))


@pytest.mark.asyncio
async def test_replace_deletes_old_versions_only_after_all_upserts(
    tmp_path: Path, services: _FakeServices
) -> None:
    services.superseded_matches = 7
    jsonl = _write_jsonl(tmp_path, [_row("a", f"chunk_{i}") for i in range(150)])
    scope = tmp_path / "place_catalog.csv"
    scope.write_text("content_id,title\na,장소 a\nb,장소 b\n", "utf-8")

    result = await importer.run(
        _args(jsonl, replace_existing=True, scope_content_ids=scope), _settings()
    )

    paths = [p for p in services.paths() if p != "/rest/v1/places"]
    # 150개는 100개씩 두 번 보낸 뒤에야 세고 지운다.
    assert paths == ["/vectors/upsert", "/vectors/upsert", "/query", "/vectors/delete"]
    expected_filter = {
        "$and": [
            {"content_id": {"$in": ["a", "b"]}},
            {
                "$or": [
                    {"embedding_version": {"$exists": False}},
                    {"embedding_version": {"$ne": "v9"}},
                ]
            },
        ]
    }
    assert services.bodies("/query")[0]["filter"] == expected_filter
    assert services.bodies("/vectors/delete")[0] == {"filter": expected_filter, "namespace": "ns"}
    assert result.deleted_superseded == 7


@pytest.mark.asyncio
async def test_replace_skips_delete_when_nothing_matches(
    tmp_path: Path, services: _FakeServices
) -> None:
    jsonl = _write_jsonl(tmp_path, [_row("a", "chunk_1")])
    scope = tmp_path / "place_catalog.csv"
    scope.write_text("content_id\na\n", "utf-8")

    await importer.run(_args(jsonl, replace_existing=True, scope_content_ids=scope), _settings())

    assert "/vectors/delete" not in services.paths()
