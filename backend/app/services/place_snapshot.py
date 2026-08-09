"""장소 목록 스냅샷 저장과 이전 스냅샷 대조.

역할: TourAPI 목록을 CSV 스냅샷으로 남기고, 이전 스냅샷과 비교해 added/removed/
      updated를 만든다. 그 결과가 다음 동기화의 상세조회 대상을 정한다.
입력: TourAPI 목록 레코드 또는 저장된 스냅샷 CSV.
출력: 스냅샷 CSV, 대조 CSV, 대조 결과 행.
호출 시점: scripts/snapshot_places.py CLI와 개발자 Ops 패널의 대조 단계.

DB는 건드리지 않는다 — 반영은 PlaceSyncService가 한다. 대조와 반영을 나눈 이유는
"이번에 무엇이 바뀌는가"를 먼저 눈으로 보고 반영 여부를 정하기 위해서다.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from app.domain.models import TourPlaceRecord
from app.providers.real_place import RealPlaceProvider

KST = ZoneInfo("Asia/Seoul")

# TourAPI 목록 조회는 numOfRows 1000까지 그대로 받는다. 종로구 전량(약 845건)이
# 한 번에 들어오므로 호출이 9회에서 1회로 준다 — areaBasedList2는 오퍼레이션 단위로
# 일일 한도가 걸려 있어(2026-08-07 소진 사례) 호출 수 자체를 줄이는 게 중요하다.
# 페이지가 하나면 중간에 끊겨 받아둔 페이지를 통째로 버리는 일도 없다.
LIST_PAGE_SIZE = 1000

# 1000건 응답은 100건일 때보다 훨씬 크고 느리다. 요청 경로용 공통 타임아웃
# (external_api_timeout_seconds)은 챗봇 응답 지연을 막으려고 짧게 잡혀 있어 여기서는
# 부족하다. 수동 실행이라 오래 기다려도 되므로 따로 넉넉히 준다.
LIST_FETCH_TIMEOUT_SECONDS = 120.0

# 저장소의 스냅샷 보관 위치. 팀이 공유하는 git 추적 대상이라 여기 쓴 파일은
# 그대로 커밋 대상이 된다.
DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "supabase" / "data"

SNAPSHOT_PREFIX = "places_api_snapshot_"
RECONCILIATION_PREFIX = "places_reconciliation_"

# 스냅샷 CSV 열. 기존 places_api_snapshot_*.csv와 같은 순서를 유지해 과거 파일과
# 그대로 비교할 수 있게 한다.
SNAPSHOT_COLUMNS = (
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
    "first_image_url",
    "thumbnail_url",
    "list_fetched_at",
)

# 변경 판정에 쓰는 열. list_fetched_at은 조회 시각이라 항상 달라져 제외한다.
COMPARED_COLUMNS = tuple(
    column for column in SNAPSHOT_COLUMNS if column != "list_fetched_at"
)

# 상세조회를 다시 할지 가르는 열. TourAPI가 상세 내용을 고치면 이 값이 함께
# 갱신된다. 나머지 열(좌표·이미지 등)만 바뀐 경우는 목록 upsert로 충분하다.
DETAIL_TRIGGER_COLUMN = "source_modified_at"


def normalize(value: object) -> str:
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
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(KST).isoformat()
    except ValueError:
        return text


def comparable_columns(baseline_columns: Sequence[str]) -> tuple[str, ...]:
    """기준 스냅샷에 실제로 있는 열만 비교 대상으로 남긴다.

    열을 새로 추가하면(D-056의 이미지 2열처럼) 과거 스냅샷에는 그 열이 없다. 없는 열을
    빈 값으로 보고 비교하면 값이 하나도 안 변한 장소까지 전부 updated로 잡혀 대조
    결과가 무의미해진다.

    건너뛴 열은 호출자가 반드시 출력한다 — 조용히 빼면 "안 바뀌었다"와 "안 봤다"가
    결과 파일에서 구분되지 않는다.
    """
    return tuple(column for column in COMPARED_COLUMNS if column in baseline_columns)


def changed_columns(
    before: Mapping[str, str],
    after: Mapping[str, str],
    compared: Sequence[str] = COMPARED_COLUMNS,
) -> list[str]:
    return [
        column
        for column in compared
        if normalize(before.get(column)) != normalize(after.get(column))
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


def snapshot_rows(
    records: Iterable[TourPlaceRecord], fetched_at: datetime
) -> dict[str, dict[str, str]]:
    """TourAPI 목록 레코드를 스냅샷 행으로 옮긴다."""
    rows: dict[str, dict[str, str]] = {}
    for record in records:
        row = {
            key: ("" if value is None else str(value))
            for key, value in asdict(record).items()
        }
        row["list_fetched_at"] = fetched_at.isoformat()
        rows[row["content_id"]] = row
    return rows


def _optional(value: str) -> str | None:
    stripped = value.strip()
    return stripped or None


def records_from_snapshot(path: Path) -> list[TourPlaceRecord]:
    """스냅샷 CSV를 다시 TourAPI 목록 레코드로 읽는다.

    대조에 쓴 목록과 DB에 반영하는 목록이 같은 데이터임을 보장한다 — 두 번 조회하면
    그 사이 원본이 바뀌어 대조 결과와 실제 반영분이 어긋날 수 있다.
    """
    with path.open(encoding="utf-8-sig") as fp:
        rows = list(csv.DictReader(fp))
    records: list[TourPlaceRecord] = []
    for row in rows:
        modified_at = _optional(row.get("source_modified_at", ""))
        records.append(
            TourPlaceRecord(
                content_id=row["content_id"].strip(),
                content_type_id=row["content_type_id"].strip(),
                title=row["title"].strip(),
                address=_optional(row.get("address", "")),
                latitude=float(row["latitude"]) if _optional(row.get("latitude", "")) else None,
                longitude=float(row["longitude"]) if _optional(row.get("longitude", "")) else None,
                area_code=row["area_code"].strip(),
                district_code=row["district_code"].strip(),
                lcls_systm1=_optional(row.get("lcls_systm1", "")),
                lcls_systm2=_optional(row.get("lcls_systm2", "")),
                lcls_systm3=_optional(row.get("lcls_systm3", "")),
                source_modified_at=(
                    datetime.fromisoformat(modified_at.replace("Z", "+00:00"))
                    if modified_at
                    else None
                ),
                # 이미지 2열은 D-056에서 추가됐다. 그 이전 스냅샷에는 열 자체가 없으므로
                # get의 기본값으로 None이 되어 옛 파일도 그대로 읽힌다.
                first_image_url=_optional(row.get("first_image_url", "")),
                thumbnail_url=_optional(row.get("thumbnail_url", "")),
            )
        )
    # 스냅샷 정렬과 무관하게 페이지 경계가 안정적이도록 고정 순서를 준다.
    records.sort(key=lambda record: record.content_id)
    return records


def write_snapshot(places: Mapping[str, Mapping[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.writer(fp)
        writer.writerow(SNAPSHOT_COLUMNS)
        for content_id in sorted(places):
            row = places[content_id]
            writer.writerow([row.get(column, "") for column in SNAPSHOT_COLUMNS])


def build_reconciliation_rows(
    baseline: Mapping[str, Mapping[str, str]],
    current: Mapping[str, Mapping[str, str]],
    compared: Sequence[str] = COMPARED_COLUMNS,
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
        columns = changed_columns(baseline[content_id], current[content_id], compared)
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
    rows: Sequence[Mapping[str, object]],
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
                    "|".join(row["changed_columns"]),  # type: ignore[arg-type]
                    json.dumps(row["previous"], ensure_ascii=False) if row["previous"] else "",
                    json.dumps(row["current"], ensure_ascii=False) if row["current"] else "",
                    baseline_name,
                    compared_at.isoformat(),
                ]
            )


async def fetch_place_rows(
    client: httpx.AsyncClient,
    api_key: str,
    area_code: str,
    district_code: str,
    fetched_at: datetime,
) -> dict[str, dict[str, str]]:
    """지역 전체 목록을 페이지 끝까지 받아 스냅샷 행으로 만든다."""
    provider = RealPlaceProvider(
        api_key=api_key,
        client=client,
        timeout_seconds=LIST_FETCH_TIMEOUT_SECONDS,
    )
    places: dict[str, dict[str, str]] = {}
    page_no = 1
    while True:
        page = await provider.list_places_by_area(
            area_code=area_code,
            district_code=district_code,
            page_no=page_no,
            num_of_rows=LIST_PAGE_SIZE,
        )
        places.update(snapshot_rows(page.places, fetched_at))
        if page_no * page.num_of_rows >= page.total_count:
            break
        page_no += 1
    return places


def list_snapshots(directory: Path | None = None) -> list[Path]:
    """저장된 스냅샷을 최신순으로. 파일명에 날짜가 있어 이름 정렬이 곧 시간 정렬이다.

    기본값을 `DATA_DIR`로 박지 않는 이유: 기본 인자는 임포트 시점에 값이 고정돼
    나중에 DATA_DIR을 바꿔도 반영되지 않는다.
    """
    target = directory if directory is not None else DATA_DIR
    if not target.exists():
        return []
    return sorted(
        target.glob(f"{SNAPSHOT_PREFIX}*.csv"),
        key=lambda path: path.name,
        reverse=True,
    )


def find_baseline(
    directory: Path | None = None, *, exclude: Path | None = None
) -> Path | None:
    """대조 기준으로 쓸 직전 스냅샷. 이번에 쓴 파일은 제외한다."""
    for path in list_snapshots(directory):
        if exclude is not None and path.name == exclude.name:
            continue
        return path
    return None


def select_detail_targets(
    rows: Sequence[Mapping[str, object]],
) -> tuple[frozenset[str], tuple[str, ...]]:
    """대조 결과에서 상세조회 대상과 '제외된 updated'를 가른다.

    상세조회 대상은 added 전부와, updated 중 source_modified_at이 바뀐 것이다.
    TourAPI가 상세를 고치면 modifiedtime이 함께 갱신되므로, 좌표·이미지만 바뀐
    행까지 detailIntro2를 부르면 호출만 낭비된다.

    다만 실측(2026-08-08 대조)에서 updated 16건이 **전부** source_modified_at을
    포함했다. modifiedtime 없이 다른 열만 바뀌는 경로는 관측된 적이 없다는 뜻이라,
    조용히 버리면 규칙이 깨져도 아무도 모른다. 두 번째 반환값으로 그런 행을
    돌려주어 화면이 "상세조회 제외 N건"으로 드러내게 한다.
    """
    targets: set[str] = set()
    excluded: list[str] = []
    for row in rows:
        content_id = str(row["content_id"])
        change_type = row["change_type"]
        if change_type == "added":
            targets.add(content_id)
        elif change_type == "updated":
            columns = row["changed_columns"]
            assert isinstance(columns, list)
            if DETAIL_TRIGGER_COLUMN in columns:
                targets.add(content_id)
            else:
                excluded.append(content_id)
    return frozenset(targets), tuple(excluded)


__all__ = [
    "COMPARED_COLUMNS",
    "DATA_DIR",
    "DETAIL_TRIGGER_COLUMN",
    "KST",
    "LIST_FETCH_TIMEOUT_SECONDS",
    "LIST_PAGE_SIZE",
    "RECONCILIATION_PREFIX",
    "SNAPSHOT_COLUMNS",
    "SNAPSHOT_PREFIX",
    "build_reconciliation_rows",
    "changed_columns",
    "comparable_columns",
    "fetch_place_rows",
    "find_baseline",
    "list_snapshots",
    "load_snapshot",
    "normalize",
    "records_from_snapshot",
    "select_detail_targets",
    "snapshot_rows",
    "write_reconciliation",
    "write_snapshot",
]
