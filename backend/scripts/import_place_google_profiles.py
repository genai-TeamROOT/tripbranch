"""Supabase place_google_profiles CSV를 검증하고 upsert한다."""

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
JSON_FIELDS = {
    "google_types",
    "google_price_range",
    "google_regular_opening_hours",
    "google_parking_options",
    "google_accessibility_options",
    "google_photos",
}
BOOL_FIELDS = {
    "google_outdoor_seating", "google_good_for_children", "google_good_for_groups",
    "google_allows_dogs", "google_reservable", "google_serves_breakfast",
    "google_serves_lunch", "google_serves_dinner", "google_serves_coffee",
    "google_serves_dessert", "google_serves_vegetarian_food", "google_dine_in",
    "google_takeout",
}
FLOAT_FIELDS = {"matched_distance_m", "google_rating"}
INT_FIELDS = {"google_review_total", "google_photo_count"}

DB_FIELDS = {
    "content_id", "google_place_id", "google_name", "google_maps_uri",
    "matched_distance_m", "google_primary_type", "google_price_level",
} | JSON_FIELDS | BOOL_FIELDS | FLOAT_FIELDS | INT_FIELDS
SOURCE_FIELD_MAP = {
    "place_uri": "google_maps_uri",
    "distance_m": "matched_distance_m",
    "place_review_total": "google_review_total",
    "google_types_json": "google_types",
    "google_price_range_json": "google_price_range",
    "google_regular_opening_hours_json": "google_regular_opening_hours",
    "google_parking_options_json": "google_parking_options",
    "google_accessibility_options_json": "google_accessibility_options",
    "google_photos_json": "google_photos",
}


def nullable(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def load_payloads(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    payloads: list[dict[str, object]] = []
    seen: set[str] = set()
    for number, source_row in enumerate(rows, start=2):
        row = {SOURCE_FIELD_MAP.get(key, key): value for key, value in source_row.items()}
        content_id = nullable(row.get("content_id"))
        if not content_id:
            raise ValueError(f"{number}행: content_id가 없습니다.")
        if content_id in seen:
            raise ValueError(f"{number}행: 중복 content_id {content_id}")
        seen.add(content_id)
        payload: dict[str, object] = {"content_id": content_id}
        for key, raw in row.items():
            if key == "content_id" or key not in DB_FIELDS:
                continue
            value = nullable(raw)
            if key in JSON_FIELDS:
                if value:
                    payload[key] = json.loads(value)
                else:
                    # 배열 컬럼은 빈 배열로, 객체 컬럼은 NULL로 둔다.
                    payload[key] = [] if key in {"google_types", "google_photos"} else None
            elif key in BOOL_FIELDS:
                if value not in {None, "true", "false"}:
                    raise ValueError(f"{number}행 {key}: 불리언 형식이 아닙니다.")
                payload[key] = None if value is None else value == "true"
            elif key in FLOAT_FIELDS:
                payload[key] = float(value) if value is not None else None
            elif key in INT_FIELDS:
                payload[key] = int(value) if value is not None else None
            else:
                payload[key] = value
        if not payload.get("google_place_id") or not payload.get("google_name"):
            raise ValueError(f"{number}행: Google 장소 식별 정보가 없습니다.")
        payloads.append(payload)
    return payloads


async def validate_place_ids(
    client: httpx.AsyncClient, payloads: Sequence[dict[str, object]]
) -> None:
    expected = {str(item["content_id"]) for item in payloads}
    found: set[str] = set()
    expected_ids = sorted(expected)
    for start in range(0, len(expected_ids), 200):
        batch = expected_ids[start : start + 200]
        response = await client.get(
            "/rest/v1/places",
            params={
                "select": "content_id",
                "content_id": "in.(" + ",".join(batch) + ")",
                "limit": str(len(batch)),
            },
        )
        response.raise_for_status()
        rows = response.json()
        found.update(str(row["content_id"]) for row in rows if row.get("content_id"))
    missing = sorted(expected - found)
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
        print(f"CSV {len(payloads):,}건 / places 참조 검증 완료")
        if args.dry_run:
            return
        for start in range(0, len(payloads), CHUNK_SIZE):
            chunk = payloads[start : start + CHUNK_SIZE]
            response = await client.post(
                "/rest/v1/place_google_profiles",
                params={"on_conflict": "content_id"},
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                json=chunk,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"적재 실패 HTTP {response.status_code}: {response.text[:1000]}")
            print(f"적재 {min(start + CHUNK_SIZE, len(payloads)):,}/{len(payloads):,}")


def main() -> int:
    parser = argparse.ArgumentParser(description="place_google_profiles CSV 적재")
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(run(parser.parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
