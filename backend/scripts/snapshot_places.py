"""TourAPI 종로구 장소 목록을 스냅샷으로 저장하고 이전 스냅샷과 대조한다.

역할: DB 동기화 전에 "이번에 무엇이 바뀌는가"를 파일로 남긴다. 목록 조회는 여기서
한 번만 수행하고, 저장한 스냅샷을 sync_places.py --from-snapshot이 재사용해 같은
날 목록 API를 두 번 호출하지 않는다.
입력: --baseline(이전 스냅샷 CSV). 생략하면 비교 없이 스냅샷만 남긴다.
출력:
  - supabase/data/places_api_snapshot_<오늘>.csv        (이번 조회 원본)
  - supabase/data/places_reconciliation_<오늘>.csv      (added/removed/updated)
호출 시점: `python -m scripts.snapshot_places --baseline <이전 스냅샷>`으로 수동 실행.

DB는 건드리지 않는다 — 반영은 sync_places.py가 담당한다.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings
from app.providers.real_place import RealPlaceProvider

_KST = ZoneInfo("Asia/Seoul")
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "supabase" / "data"
_PAGE_SIZE = 100

# 스냅샷 CSV 열. 기존 places_api_snapshot_*.csv와 같은 순서를 유지해 과거 파일과
# 그대로 비교할 수 있게 한다.
_SNAPSHOT_COLUMNS = (
    "content_id",
    "content_type_id",
    "title",
    "address",
    "latitude",
    "longitude",
    "area_code",
    "district_code",
    "lcls_systm1",
    "lcls_systm2",
    "lcls_systm3",
    "source_modified_at",
    "list_fetched_at",
)

# 변경 판정에 쓰는 열. list_fetched_at은 조회 시각이라 항상 달라져 제외한다.
_COMPARED_COLUMNS = tuple(
    column for column in _SNAPSHOT_COLUMNS if column != "list_fetched_at"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TourAPI 장소 목록 스냅샷·대조")
    parser.add_argument("--area-code", help="TourAPI 광역 행정구역 코드")
    parser.add_argument("--district-code", help="TourAPI 시·군·구 코드")
    parser.add_argument(
        "--baseline",
        type=Path,
        help="비교 기준 스냅샷 CSV. 생략하면 스냅샷만 저장한다.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_DATA_DIR,
        help="스냅샷과 대조 결과를 저장할 디렉터리",
    )
    return parser


def _normalize(value: object) -> str:
    """비교용 정규화.

    좌표는 소수 자릿수 표기가 흔들리고(37.5727080048934 vs 37.5727080049), 시각은
    같은 시점이라도 문자열이 다를 수 있어(2026-02-06 05:25:01+00 vs ISO) 값 자체로
    맞춘다. 그러지 않으면 실제로는 바뀌지 않은 행이 updated로 잡힌다.
    """
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    try:
        return f"{float(text):.7f}"
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(_KST).isoformat()
    except ValueError:
        return text


def _changed_columns(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return [
        column
        for column in _COMPARED_COLUMNS
        if _normalize(before.get(column)) != _normalize(after.get(column))
    ]


def load_snapshot(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig") as fp:
        rows = list(csv.DictReader(fp))
    snapshot: dict[str, dict[str, str]] = {}
    for row in rows:
        content_id = (row.get("content_id") or "").strip()
        if not content_id:
            raise ValueError(f"{path}: content_id가 없는 행이 있습니다.")
        snapshot[content_id] = row
    return snapshot


async def fetch_places(
    settings: Settings, area_code: str, district_code: str, fetched_at: datetime
) -> dict[str, dict[str, str]]:
    """종로구 전체 목록을 페이지 끝까지 받아 스냅샷 행으로 만든다."""
    async with httpx.AsyncClient() as client:
        provider = RealPlaceProvider(
            api_key=settings.tour_api_service_key,
            client=client,
            timeout_seconds=settings.external_api_timeout_seconds,
        )
        places: dict[str, dict[str, str]] = {}
        page_no = 1
        while True:
            page = await provider.list_places_by_area(
                area_code=area_code,
                district_code=district_code,
                page_no=page_no,
                num_of_rows=_PAGE_SIZE,
            )
            for record in page.places:
                row = {
                    key: ("" if value is None else str(value))
                    for key, value in asdict(record).items()
                }
                row["list_fetched_at"] = fetched_at.isoformat()
                places[row["content_id"]] = row
            if page_no * page.num_of_rows >= page.total_count:
                break
            page_no += 1
        return places


def write_snapshot(places: dict[str, dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.writer(fp)
        writer.writerow(_SNAPSHOT_COLUMNS)
        for content_id in sorted(places):
            row = places[content_id]
            writer.writerow([row.get(column, "") for column in _SNAPSHOT_COLUMNS])


def build_reconciliation_rows(
    baseline: dict[str, dict[str, str]],
    current: dict[str, dict[str, str]],
) -> list[dict[str, object]]:
    """added / removed / updated 세 종류로 변경분을 만든다."""
    rows: list[dict[str, object]] = []
    for content_id in sorted(set(current) - set(baseline)):
        rows.append(
            {
                "content_id": content_id,
                "title": current[content_id].get("title", ""),
                "content_type_id": current[content_id].get("content_type_id", ""),
                "change_type": "added",
                "changed_columns": [],
                "previous": {},
                "current": current[content_id],
            }
        )
    for content_id in sorted(set(baseline) - set(current)):
        rows.append(
            {
                "content_id": content_id,
                "title": baseline[content_id].get("title", ""),
                "content_type_id": baseline[content_id].get("content_type_id", ""),
                # 이번 목록에 없으므로 sync_places가 is_active=false로 비활성화한다.
                "change_type": "removed",
                "changed_columns": [],
                "previous": baseline[content_id],
                "current": {},
            }
        )
    for content_id in sorted(set(baseline) & set(current)):
        columns = _changed_columns(baseline[content_id], current[content_id])
        if not columns:
            continue
        rows.append(
            {
                "content_id": content_id,
                "title": current[content_id].get("title", ""),
                "content_type_id": current[content_id].get("content_type_id", ""),
                "change_type": "updated",
                "changed_columns": columns,
                "previous": {c: baseline[content_id].get(c, "") for c in columns},
                "current": {c: current[content_id].get(c, "") for c in columns},
            }
        )
    return rows


def write_reconciliation(
    rows: Sequence[dict[str, object]],
    path: Path,
    *,
    baseline_name: str,
    compared_at: datetime,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.writer(fp)
        writer.writerow(
            [
                "content_id",
                "title",
                "content_type_id",
                "change_type",
                "changed_columns",
                "previous_values_json",
                "current_values_json",
                "baseline_snapshot",
                "compared_at",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["content_id"],
                    row["title"],
                    row["content_type_id"],
                    row["change_type"],
                    "|".join(row["changed_columns"]),
                    json.dumps(row["previous"], ensure_ascii=False) if row["previous"] else "",
                    json.dumps(row["current"], ensure_ascii=False) if row["current"] else "",
                    baseline_name,
                    compared_at.isoformat(),
                ]
            )


async def run(args: argparse.Namespace, settings: Settings) -> int:
    area_code = args.area_code or settings.place_sync_area_code
    district_code = args.district_code or settings.place_sync_district_code
    if not settings.tour_api_service_key:
        raise ValueError("TOUR_API_SERVICE_KEY가 필요합니다.")

    now = datetime.now(_KST)
    current = await fetch_places(settings, area_code, district_code, now)
    snapshot_path = args.output_dir / f"places_api_snapshot_{now:%Y%m%d}.csv"
    write_snapshot(current, snapshot_path)
    print(f"스냅샷 {len(current)}건 저장: {snapshot_path}")

    if args.baseline is None:
        print("기준 스냅샷이 없어 대조는 건너뜁니다.")
        return 0

    baseline = load_snapshot(args.baseline)
    rows = build_reconciliation_rows(baseline, current)
    reconciliation_path = args.output_dir / f"places_reconciliation_{now:%Y%m%d}.csv"
    write_reconciliation(
        rows,
        reconciliation_path,
        baseline_name=args.baseline.name,
        compared_at=now,
    )

    counts = {"added": 0, "removed": 0, "updated": 0}
    for row in rows:
        counts[str(row["change_type"])] += 1
    print(f"기준 {args.baseline.name}: {len(baseline)}건")
    print(
        f"변경: 신규 {counts['added']} / 삭제 {counts['removed']} / 수정 {counts['updated']}"
    )
    for change_type in ("added", "removed"):
        titles = [str(row["title"]) for row in rows if row["change_type"] == change_type]
        if titles:
            preview = ", ".join(titles[:8])
            suffix = " …" if len(titles) > 8 else ""
            print(f"  {change_type}: {preview}{suffix}")
    print(f"대조 결과 저장: {reconciliation_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(run(args, Settings()))


if __name__ == "__main__":
    raise SystemExit(main())
