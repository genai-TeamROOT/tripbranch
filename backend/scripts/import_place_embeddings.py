"""package_D의 place_embeddings.jsonl을 Supabase place_embeddings에 적재한다."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import Settings

_UPSERT_CHUNK_SIZE = 100
_UPSERT_TIMEOUT_SECONDS = 60.0
_EMBEDDING_DIM = 768
_VALID_SOURCE_TYPES = {"naver_post", "google_review"}
_DEFAULT_JSONL_PATH = (
    Path(__file__).resolve().parents[2] / "package_D" / "place_embeddings.jsonl"
)

# naver_post: "YYYY. M. D. H:MM" 한국어 절대 표기(KST). 상대 표기("6시간 전")·
# 연월만("2026.08")·빈 문자열은 이 정규식에 매치되지 않아 NULL로 남는다 —
# 스크랩 기준 시각이 기록에 없어 절대 시각으로 되돌릴 근거가 없다(2026-08-18 실측).
_KOREAN_ABSOLUTE_RE = re.compile(
    r"^(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{1,2}):(\d{2})$"
)
# google_review: ISO 8601이되 끝맺음이 "Z"거나 "+00:00"이고, 나노초(9자리) 소수부가
# 있을 수도 없을 수도 있다(2026-08-18 실측, 두 형식이 3,988/1,667건). timestamptz는
# 마이크로초(6자리)까지만 받으므로 소수부가 있으면 뒤를 잘라낸다.
_ISO_UTC_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(?:Z|\+00:00)$"
)


@dataclass(frozen=True)
class PlaceEmbeddingImportResult:
    jsonl_row_count: int
    payload_count: int
    duplicate_keys: int
    published_at_nulled: int
    imported_count: int
    dry_run: bool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="place_embeddings.jsonl 적재")
    parser.add_argument(
        "--jsonl",
        type=Path,
        default=_DEFAULT_JSONL_PATH,
        help="place_embeddings.jsonl 경로(기본값: package_D/place_embeddings.jsonl)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="jsonl과 장소 참조만 검증하고 테이블은 수정하지 않음",
    )
    return parser


def _parse_published_at(raw: object, *, source_type: str, content_id: str) -> str | None:
    if not raw:
        return None
    text = str(raw)
    if source_type == "google_review":
        match = _ISO_UTC_RE.match(text)
        if match is None:
            raise ValueError(
                f"{content_id}: 알 수 없는 google_review published_at 형식 {text!r}"
            )
        base, frac = match.groups()
        return f"{base}.{frac[:6]}Z" if frac else f"{base}Z"
    match = _KOREAN_ABSOLUTE_RE.match(text)
    if match is None:
        return None
    year, month, day, hour, minute = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}T{int(hour):02d}:{minute}:00+09:00"


def load_embedding_payloads(
    jsonl_path: Path,
) -> tuple[list[dict[str, object]], int, int, int]:
    """jsonl을 읽어 upsert 페이로드로 바꾼다. 형식 위반은 즉시 멈춘다.

    (content_id, source_ref)가 같은 행이 또 나오면 나중 것을 버린다 — 이
    쌍이 테이블의 unique 제약이라, 같은 배치 안에 중복이 있으면
    ON CONFLICT가 "같은 행을 두 번 건드릴 수 없다" 오류를 낸다.
    """
    payloads: list[dict[str, object]] = []
    seen_keys: set[tuple[str, str]] = set()
    duplicate_count = 0
    published_at_nulled = 0
    row_count = 0

    with jsonl_path.open(encoding="utf-8") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            line = raw_line.strip()
            if not line:
                continue
            row_count += 1
            row = json.loads(line)

            content_id = str(row.get("content_id") or "").strip()
            source_ref = str(row.get("source_ref") or "").strip()
            source_type = str(row.get("source_type") or "").strip()
            source_text = str(row.get("source_text") or "").strip()
            place_title = str(row.get("place_title") or "").strip()
            model_name = str(row.get("model_name") or "").strip()
            embedding = row.get("embedding")

            if not content_id:
                raise ValueError(f"{line_number}행: content_id가 없습니다.")
            if not source_ref:
                raise ValueError(f"{content_id}: source_ref가 없습니다.")
            if source_type not in _VALID_SOURCE_TYPES:
                raise ValueError(f"{content_id}: 알 수 없는 source_type {source_type!r}")
            if not source_text:
                raise ValueError(f"{content_id}/{source_ref}: source_text가 비어 있습니다.")
            if not place_title:
                raise ValueError(f"{content_id}/{source_ref}: place_title이 비어 있습니다.")
            if not model_name:
                raise ValueError(f"{content_id}/{source_ref}: model_name이 없습니다.")
            if not isinstance(embedding, list) or len(embedding) != _EMBEDDING_DIM:
                raise ValueError(
                    f"{content_id}/{source_ref}: embedding이 {_EMBEDDING_DIM}차원이 아닙니다."
                )

            key = (content_id, source_ref)
            if key in seen_keys:
                duplicate_count += 1
                continue
            seen_keys.add(key)

            raw_published_at = row.get("published_at")
            published_at = _parse_published_at(
                raw_published_at, source_type=source_type, content_id=content_id
            )
            if raw_published_at and published_at is None:
                published_at_nulled += 1

            source_url = str(row["source_url"]).strip() if row.get("source_url") else ""
            payloads.append(
                {
                    "content_id": content_id,
                    "place_title": place_title,
                    "source_type": source_type,
                    "source_text": source_text,
                    "source_url": source_url or None,
                    "source_ref": source_ref,
                    "published_at": published_at,
                    "embedding": embedding,
                    "model_name": model_name,
                }
            )

    return payloads, row_count, duplicate_count, published_at_nulled


async def _validate_active_places(
    client: httpx.AsyncClient,
    payloads: Sequence[dict[str, object]],
) -> None:
    response = await client.get(
        "/rest/v1/places",
        params={"select": "content_id", "is_active": "eq.true", "limit": "1000"},
    )
    response.raise_for_status()
    active_ids = {
        str(row["content_id"])
        for row in response.json()
        if isinstance(row, dict) and row.get("content_id")
    }
    missing_ids = sorted(
        {
            str(payload["content_id"])
            for payload in payloads
            if str(payload["content_id"]) not in active_ids
        }
    )
    if missing_ids:
        raise ValueError(
            "활성 places에 없는 content_id: " + ", ".join(missing_ids[:20])
            + (f" 외 {len(missing_ids) - 20}건" if len(missing_ids) > 20 else "")
        )


async def run(
    args: argparse.Namespace,
    settings: Settings,
) -> PlaceEmbeddingImportResult:
    if not settings.supabase_url:
        raise ValueError("SUPABASE_URL이 필요합니다.")
    if not settings.supabase_secret_key:
        raise ValueError("SUPABASE_SECRET_KEY가 필요합니다.")

    payloads, row_count, duplicate_count, published_at_nulled = load_embedding_payloads(
        args.jsonl
    )
    headers = {
        "apikey": settings.supabase_secret_key,
        "Authorization": f"Bearer {settings.supabase_secret_key}",
    }
    async with httpx.AsyncClient(
        base_url=settings.supabase_url.rstrip("/"),
        headers=headers,
        timeout=_UPSERT_TIMEOUT_SECONDS,
    ) as client:
        await _validate_active_places(client, payloads)
        if not args.dry_run:
            total_chunks = (len(payloads) + _UPSERT_CHUNK_SIZE - 1) // _UPSERT_CHUNK_SIZE
            for chunk_index, start in enumerate(
                range(0, len(payloads), _UPSERT_CHUNK_SIZE), start=1
            ):
                chunk = payloads[start : start + _UPSERT_CHUNK_SIZE]
                response = await client.post(
                    "/rest/v1/place_embeddings",
                    params={"on_conflict": "content_id,source_ref"},
                    headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                    json=chunk,
                )
                response.raise_for_status()
                if chunk_index % 20 == 0 or chunk_index == total_chunks:
                    print(f"  적재 {chunk_index}/{total_chunks} 배치 완료")

    return PlaceEmbeddingImportResult(
        jsonl_row_count=row_count,
        payload_count=len(payloads),
        duplicate_keys=duplicate_count,
        published_at_nulled=published_at_nulled,
        imported_count=0 if args.dry_run else len(payloads),
        dry_run=args.dry_run,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = asyncio.run(run(args, Settings()))
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
