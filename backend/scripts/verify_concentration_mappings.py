"""매핑된 집중률 장소명으로 실제 조회가 되는지 확인한다.

역할: 매핑 테이블에 이름이 있어도 집중률 API 조회가 실패할 수 있어(표기 차이·API
데이터 변경) 재매핑 효과를 숫자로 확인한다. 실측(2026-08-03)에서는 100건 중 30건이
실패했고, 그중 6건은 접두·부기를 뗀 이름으로는 조회됐다.
입력: 없음(Supabase 매핑 테이블을 읽는다). .env에 실 자격증명 필요.
출력: 표준 출력 요약 + backend/test_results/concentration_mapping_failures.csv
호출 시점: 매핑 적재(import_concentration_mappings.py) 이후 `python -m
scripts.verify_concentration_mappings`로 수동 실행한다.

집중률 API를 매핑 건수만큼 호출한다. 동시 요청을 올리면 서비스 요청제한에 걸려
전건이 unavailable로 나오므로(2026-08-03 실측) 기본값을 낮게 두고 재시도한다.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import Settings
from app.providers.concentration import RealConcentrationProvider
from app.tools.concentration import ConcentrationQuery, GetConcentrationTool

_RESULTS_DIR = Path(__file__).resolve().parent.parent / "test_results"
_BRACKET_PATTERN = re.compile(r"\s*\[[^\]]*\]")
_PAREN_PATTERN = re.compile(r"\s*\([^)]*\)")
_SEOUL_PREFIX = "서울 "


@dataclass(frozen=True)
class MappingRecord:
    content_id: str
    place_title: str
    concentration_name: str
    match_method: str


@dataclass
class VerifyResult:
    record: MappingRecord
    status: str
    working_alternative: str = ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="집중률 매핑 조회 검증")
    parser.add_argument("--area-code", default="11")
    parser.add_argument("--district-code", default="11110")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="동시 요청 수. 올리면 요청제한(returnReasonCode 22)에 걸리기 쉽다.",
    )
    parser.add_argument(
        "--retries", type=int, default=3, help="unavailable 응답 재시도 횟수"
    )
    parser.add_argument(
        "--skip-alternatives",
        action="store_true",
        help="실패 건의 정정 후보를 추가 조회하지 않는다(호출량 절약)",
    )
    return parser


def _alternatives(name: str) -> list[str]:
    """접두·부기를 뗀 이름 후보. 실패 원인이 표기 차이인지 가려내는 용도다."""
    candidates: list[str] = []
    stripped = _PAREN_PATTERN.sub("", _BRACKET_PATTERN.sub("", name)).strip()
    if stripped and stripped != name:
        candidates.append(stripped)
    for base in [stripped or name, name]:
        if base.startswith(_SEOUL_PREFIX):
            candidates.append(base[len(_SEOUL_PREFIX) :].strip())
    seen: set[str] = set()
    return [c for c in candidates if c and c != name and not (c in seen or seen.add(c))]


async def load_mappings(settings: Settings) -> list[MappingRecord]:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            settings.supabase_url.rstrip("/") + "/rest/v1/place_concentration_mappings",
            params={
                "select": "content_id,primary_concentration_name,match_method,places(title)",
                "limit": "2000",
            },
            headers={"apikey": settings.supabase_secret_key},
            timeout=settings.external_api_timeout_seconds,
        )
        response.raise_for_status()
        rows = response.json()
    records: list[MappingRecord] = []
    for row in rows:
        place = row.get("places")
        if isinstance(place, list):
            place = place[0] if place else None
        records.append(
            MappingRecord(
                content_id=str(row["content_id"]),
                place_title=str((place or {}).get("title", "")),
                concentration_name=str(row["primary_concentration_name"]),
                match_method=str(row.get("match_method", "")),
            )
        )
    return records


async def verify(args: argparse.Namespace, settings: Settings) -> list[VerifyResult]:
    semaphore = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient() as client:
        tool = GetConcentrationTool(
            RealConcentrationProvider(
                api_key=settings.tour_api_service_key,
                client=client,
                timeout_seconds=settings.external_api_timeout_seconds,
            )
        )

        async def probe(name: str) -> str:
            async with semaphore:
                for attempt in range(args.retries):
                    result = await tool.execute(
                        ConcentrationQuery(args.area_code, args.district_code, name)
                    )
                    if result.status.value != "unavailable":
                        return result.status.value
                    # 요청제한은 잠깐 쉬면 풀리는 경우가 있어 간격을 늘려 재시도한다.
                    await asyncio.sleep(1.5 * (attempt + 1))
                return "unavailable"

        records = await load_mappings(settings)
        statuses = await asyncio.gather(
            *(probe(record.concentration_name) for record in records)
        )
        results = [
            VerifyResult(record=record, status=status)
            for record, status in zip(records, statuses, strict=True)
        ]

        if not args.skip_alternatives:
            for result in results:
                if result.status == "success":
                    continue
                for alternative in _alternatives(result.record.concentration_name):
                    if await probe(alternative) == "success":
                        result.working_alternative = alternative
                        break
        return results


def write_failures_csv(results: Sequence[VerifyResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    failures = [item for item in results if item.status != "success"]
    with path.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.writer(fp)
        writer.writerow(
            [
                "content_id",
                "TourAPI_장소명",
                "저장된_집중률명",
                "조회결과",
                "match_method",
                "정상조회되는_후보명",
                "정정가능",
            ]
        )
        for item in failures:
            writer.writerow(
                [
                    item.record.content_id,
                    item.record.place_title,
                    item.record.concentration_name,
                    item.status,
                    item.record.match_method,
                    item.working_alternative,
                    "O" if item.working_alternative else "X",
                ]
            )


async def run(args: argparse.Namespace, settings: Settings) -> int:
    if not settings.tour_api_service_key:
        raise ValueError("TOUR_API_SERVICE_KEY가 필요합니다.")
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise ValueError("SUPABASE_URL / SUPABASE_SECRET_KEY가 필요합니다.")

    results = await verify(args, settings)
    counts: dict[str, int] = {}
    for item in results:
        counts[item.status] = counts.get(item.status, 0) + 1

    total = len(results)
    success = counts.get("success", 0)
    print(f"매핑 {total}건 중 조회 성공 {success} / 실패 {total - success}")
    print(f"  상태 분포: {counts}")
    # unavailable은 이름 문제가 아니라 요청제한일 수 있어 no_data와 구분해서 읽는다.
    if counts.get("unavailable"):
        print(
            f"  주의: unavailable {counts['unavailable']}건은 요청제한일 수 있습니다. "
            "잠시 후 다시 실행해 확인하세요."
        )
    fixable = [item for item in results if item.working_alternative]
    if fixable:
        print(f"\n표기 정정으로 해결 가능한 {len(fixable)}건:")
        for item in fixable:
            print(f"  '{item.record.concentration_name}' → '{item.working_alternative}'")

    output = _RESULTS_DIR / "concentration_mapping_failures.csv"
    write_failures_csv(results, output)
    print(f"\n실패 목록 저장: {output}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(run(args, Settings()))


if __name__ == "__main__":
    raise SystemExit(main())
