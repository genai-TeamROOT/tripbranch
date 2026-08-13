"""검증된 집중률 장소 매핑 CSV를 Supabase에 적재한다."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import Settings

_VALID_MATCH_METHODS = {"exact", "normalized", "manual", "exact_with_alias"}


def _parse_search_keys(value: object) -> list[str]:
    """CSV의 concentration_search_keys 열(JSON 배열)을 순서 그대로 읽는다.

    순서가 곧 조회 우선순위라 set으로 걷거나 정렬하지 않는다(D-057).
    """
    text = str(value or "").strip()
    if not text:
        return []
    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise ValueError("concentration_search_keys는 JSON 배열이어야 합니다.")
    keys: list[str] = []
    for item in parsed:
        key = str(item).strip()
        if key and key not in keys:
            keys.append(key)
    return keys
_UPSERT_CHUNK_SIZE = 100
_DATA_DIR = Path(__file__).resolve().parents[2] / "supabase" / "data"
_MAPPING_CSV_GLOB = "concentration_place_mapping_*.csv"


def latest_mapping_csv(data_dir: Path = _DATA_DIR) -> Path | None:
    """가장 최근 매핑 CSV. 파일명이 날짜라 이름 정렬로 최신을 고른다.

    build_concentration_mappings.py가 실행일로 파일을 남기므로 기본값을 고정
    파일명으로 두면 재생성할 때마다 어긋난다.
    """
    candidates = sorted(data_dir.glob(_MAPPING_CSV_GLOB))
    return candidates[-1] if candidates else None


_DEFAULT_CSV_PATH = latest_mapping_csv()


@dataclass(frozen=True)
class ConcentrationMappingImportResult:
    csv_row_count: int
    matched_count: int
    unmatched_count: int
    imported_count: int
    dry_run: bool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="집중률 장소 매핑 CSV 적재")
    parser.add_argument(
        "--csv",
        type=Path,
        default=_DEFAULT_CSV_PATH,
        required=_DEFAULT_CSV_PATH is None,
        help="집중률 장소 매핑 CSV 경로(기본값: supabase/data의 최신 매핑 CSV)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="CSV와 장소 참조만 검증하고 매핑 테이블은 수정하지 않음",
    )
    return parser


def _parse_aliases(raw: str, *, content_id: str) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"{content_id}: concentration_aliases가 JSON이 아닙니다.") from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{content_id}: concentration_aliases는 문자열 배열이어야 합니다.")
    aliases = [item.strip() for item in value]
    if any(not item for item in aliases):
        raise ValueError(f"{content_id}: 빈 concentration alias는 허용하지 않습니다.")
    if len(aliases) != len(set(aliases)):
        raise ValueError(f"{content_id}: concentration alias가 중복됐습니다.")
    return aliases


def load_mapping_payloads(
    csv_path: Path,
) -> tuple[list[dict[str, object]], int, int]:
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))

    payloads: list[dict[str, object]] = []
    unmatched_count = 0
    seen_content_ids: set[str] = set()
    for row in rows:
        status = (row.get("match_status") or "").strip()
        content_id = (row.get("content_id") or "").strip()
        if status == "unmatched":
            if content_id:
                raise ValueError(f"{content_id}: unmatched 행에는 content_id가 없어야 합니다.")
            unmatched_count += 1
            continue
        if status != "matched":
            raise ValueError(f"{content_id or '<empty>'}: 알 수 없는 match_status입니다.")
        if not content_id:
            raise ValueError("matched 행에는 content_id가 필요합니다.")
        if content_id in seen_content_ids:
            raise ValueError(f"{content_id}: matched content_id가 중복됐습니다.")
        seen_content_ids.add(content_id)

        primary_name = (row.get("concentration_title") or "").strip()
        if not primary_name:
            raise ValueError(f"{content_id}: concentration_title이 필요합니다.")
        aliases = _parse_aliases(
            row.get("concentration_aliases") or "[]",
            content_id=content_id,
        )
        if primary_name in aliases:
            raise ValueError(f"{content_id}: 대표명이 aliases에 중복됐습니다.")

        # tAtsNm은 공백이 든 값을 넘기면 0건이 오므로(2026-08-04 실측) 조회용 검색어를
        # 따로 싣는다. 앞에서부터 시도할 목록이며 1순위가 기존 단일 검색어다(D-057).
        search_keys = _parse_search_keys(row.get("concentration_search_keys"))
        for key in search_keys:
            if any(c.isspace() for c in key):
                raise ValueError(
                    f"{content_id}: concentration_search_keys에 공백이 있으면 조회가 0건이 됩니다."
                )
        if not search_keys:
            # 조회할 값이 없으면 매핑이 있어도 혼잡도를 못 받는다. 정식 명칭이 공백을
            # 포함하면 그것마저 0건이므로 CSV 생성 단계의 문제로 보고 끊는다.
            if any(c.isspace() for c in primary_name):
                raise ValueError(
                    f"{content_id}: 검색어가 없고 정식 명칭에 공백이 있어 조회할 수 없습니다."
                )
            search_keys = [primary_name]

        match_method = (row.get("match_method") or "").strip()
        if match_method not in _VALID_MATCH_METHODS:
            raise ValueError(f"{content_id}: 지원하지 않는 match_method입니다.")
        confidence_raw = (row.get("confidence_score") or "").strip()
        confidence = float(confidence_raw) if confidence_raw else None
        if confidence is not None and not 0 <= confidence <= 1:
            raise ValueError(f"{content_id}: confidence_score 범위가 잘못됐습니다.")

        payloads.append(
            {
                "content_id": content_id,
                "primary_concentration_name": primary_name,
                "concentration_search_keys": search_keys,
                "concentration_aliases": aliases,
                "match_method": match_method,
                "confidence_score": confidence,
                "verified_at": (row.get("verified_at") or "").strip() or None,
            }
        )
    return payloads, len(rows), unmatched_count


async def _validate_active_places(
    client: httpx.AsyncClient,
    payloads: Sequence[dict[str, object]],
) -> None:
    response = await client.get(
        "/rest/v1/places",
        params={
            "select": "content_id",
            "is_active": "eq.true",
            "limit": "1000",
        },
    )
    response.raise_for_status()
    active_ids = {
        str(row["content_id"])
        for row in response.json()
        if isinstance(row, dict) and row.get("content_id")
    }
    missing_ids = sorted(
        str(payload["content_id"])
        for payload in payloads
        if str(payload["content_id"]) not in active_ids
    )
    if missing_ids:
        raise ValueError(
            "활성 places에 없는 concentration mapping content_id: "
            + ", ".join(missing_ids)
        )


async def run(
    args: argparse.Namespace,
    settings: Settings,
) -> ConcentrationMappingImportResult:
    if not settings.supabase_url:
        raise ValueError("SUPABASE_URL이 필요합니다.")
    if not settings.supabase_secret_key:
        raise ValueError("SUPABASE_SECRET_KEY가 필요합니다.")

    payloads, csv_row_count, unmatched_count = load_mapping_payloads(args.csv)
    headers = {
        "apikey": settings.supabase_secret_key,
        "Authorization": f"Bearer {settings.supabase_secret_key}",
    }
    async with httpx.AsyncClient(
        base_url=settings.supabase_url.rstrip("/"),
        headers=headers,
        timeout=settings.external_api_timeout_seconds,
    ) as client:
        await _validate_active_places(client, payloads)
        if not args.dry_run:
            for start in range(0, len(payloads), _UPSERT_CHUNK_SIZE):
                response = await client.post(
                    "/rest/v1/place_concentration_mappings",
                    params={"on_conflict": "content_id"},
                    headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                    json=payloads[start : start + _UPSERT_CHUNK_SIZE],
                )
                response.raise_for_status()

    return ConcentrationMappingImportResult(
        csv_row_count=csv_row_count,
        matched_count=len(payloads),
        unmatched_count=unmatched_count,
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
