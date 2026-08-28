"""place_preference_cards.csv를 펼쳐 Supabase 취향 태그 테이블에 upsert한다."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from collections.abc import Sequence
from pathlib import Path

import httpx

from app.config import Settings

CHUNK_SIZE = 100


def load_payloads(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    payloads: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for row_number, row in enumerate(rows, start=2):
        content_id = str(row.get("content_id") or "").strip()
        version = str(row.get("extraction_version") or "").strip()
        if not content_id or not version:
            raise ValueError(f"{row_number}행: content_id 또는 extraction_version이 없습니다.")
        try:
            details = json.loads(str(row.get("preference_details_json") or "[]"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{row_number}행: 태그 JSON이 잘못됐습니다.") from exc
        if not isinstance(details, list):
            raise ValueError(f"{row_number}행: 태그 JSON은 배열이어야 합니다.")
        for rank, detail in enumerate(details, start=1):
            if not isinstance(detail, dict):
                raise ValueError(f"{row_number}행 {rank}번 태그가 객체가 아닙니다.")
            code = str(detail.get("code") or "").strip()
            label = str(detail.get("label") or "").strip()
            key = (content_id, code)
            if not code or not label or key in seen:
                raise ValueError(f"{row_number}행: 비어 있거나 중복된 태그 {key}")
            seen.add(key)
            positive = int(detail.get("positive_documents") or 0)
            negative = int(detail.get("negative_documents") or 0)
            payloads.append(
                {
                    "content_id": content_id,
                    "preference_code": code,
                    "preference_label": label,
                    "display_rank": rank,
                    "mention_count": positive + negative,
                    "positive_document_count": positive,
                    "negative_document_count": negative,
                    "source_count": int(detail.get("source_count") or 0),
                    "confidence": float(detail["confidence"])
                    if detail.get("confidence") is not None
                    else None,
                    "extraction_version": version,
                }
            )
    return payloads


async def validate_place_ids(
    client: httpx.AsyncClient, payloads: Sequence[dict[str, object]]
) -> None:
    expected = sorted({str(item["content_id"]) for item in payloads})
    found: set[str] = set()
    for start in range(0, len(expected), 200):
        batch = expected[start : start + 200]
        response = await client.get(
            "/rest/v1/places",
            params={
                "select": "content_id",
                "content_id": "in.(" + ",".join(batch) + ")",
                "limit": str(len(batch)),
            },
        )
        response.raise_for_status()
        found.update(str(row["content_id"]) for row in response.json())
    missing = sorted(set(expected) - found)
    if missing:
        raise ValueError("places에 없는 content_id: " + ", ".join(missing[:20]))


async def run(args: argparse.Namespace) -> None:
    settings = Settings()
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise ValueError("SUPABASE_URL / SUPABASE_SECRET_KEY가 필요합니다.")
    payloads = load_payloads(args.csv)
    headers = {
        "apikey": settings.supabase_secret_key,
        "Authorization": f"Bearer {settings.supabase_secret_key}",
    }
    async with httpx.AsyncClient(
        base_url=settings.supabase_url.rstrip("/"), headers=headers, timeout=60
    ) as client:
        await validate_place_ids(client, payloads)
        print(f"태그 {len(payloads):,}건 / places 참조 검증 완료")
        if args.dry_run:
            return
        for start in range(0, len(payloads), CHUNK_SIZE):
            chunk = payloads[start : start + CHUNK_SIZE]
            response = await client.post(
                "/rest/v1/place_preference_tags",
                params={"on_conflict": "content_id,preference_code"},
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                json=chunk,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"적재 실패 HTTP {response.status_code}: {response.text[:1000]}")
            print(f"적재 {min(start + CHUNK_SIZE, len(payloads)):,}/{len(payloads):,}")


def main() -> int:
    parser = argparse.ArgumentParser(description="장소별 취향 태그 Supabase 적재")
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(run(parser.parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
