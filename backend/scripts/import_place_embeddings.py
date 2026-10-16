"""place_embeddings.jsonl을 검증해 Pinecone 취향 근거 인덱스에 적재한다.

원래는 Supabase `place_embeddings`에 썼다. Supabase를 무료 플랜 용량 안에 넣으려고
근거 벡터를 Pinecone으로 옮겼고(2026-10, 팀 합의), 서비스도 Pinecone을 읽으므로
적재도 Pinecone으로 한다. 장소가 활성 상태인지는 여전히 Supabase `places`로 확인한다.

레코드 형식(ID = `chunk_id`, 메타데이터 열)은 이관 스크립트
`export_place_embeddings_to_pinecone.py`의 `to_record`를 그대로 쓴다. 두 경로가
다르면 같은 문장이 다른 ID로 들어가 중복이 쌓인다.

설정: `backend/.env`의 SUPABASE_URL·SUPABASE_SECRET_KEY(장소 확인),
PINECONE_API_KEY·PINECONE_INDEX_HOST·PINECONE_NAMESPACE(적재).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import Settings
from scripts.export_place_embeddings_to_pinecone import (
    PINECONE_API_VERSION,
    UPSERT_BATCH_SIZE,
    to_record,
    upsert_batch,
)

_REQUEST_TIMEOUT_SECONDS = 120.0
_EMBEDDING_DIM = 768
# 옛 버전 정리 때 한 번에 조건으로 묶는 장소 수. 장소당 문장이 최대 100여 개라
# 50곳이면 5,000개 안쪽이다 — 지우기 전에 개수를 세는 질의(topK 상한 10,000)가
# 한 번에 다 셀 수 있는 크기로 잡았다.
_REPLACE_PLACE_BATCH = 50
_PINECONE_TOP_K_LIMIT = 10_000
# tour_overview는 202609070001 마이그레이션으로 허용됐다(TripBranch 분산
# 임베딩, 2026-09-07). published_at이 항상 비어 있어(overview는 작성일 개념이
# 없음) 아래 _parse_published_at은 raw가 없으면 그냥 None을 반환하는 기존
# 분기를 그대로 탄다 — source_type별 특별 처리가 필요 없다.
_VALID_SOURCE_TYPES = {"naver_post", "google_review", "tour_overview"}
_DEFAULT_JSONL_PATH = (
    Path(__file__).resolve().parents[2] / "package_D" / "place_embeddings.jsonl"
)

# naver_post: "YYYY. M. D. H:MM" 한국어 절대 표기(KST). 상대 표기("6시간 전")·
# 연월만("2026.08")·빈 문자열은 이 정규식에 매치되지 않아 NULL로 남는다 —
# 스크랩 기준 시각이 기록에 없어 절대 시각으로 되돌릴 근거가 없다(2026-08-18 실측).
_KOREAN_ABSOLUTE_RE = re.compile(
    r"^(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{1,2}):(\d{2})$"
)
# TripBranch_RAG_Distributed_Embedding(2026-09-07)의 naver_post published_at은
# prepare_rag_documents_prechunk.py의 normalize_naver_datetime()이 이미
# "YYYY-MM-DDTHH:MM:SS+09:00" ISO 8601로 정규화해 내보낸다. 위 한국어 절대
# 표기 정규식은 이 형식을 매치하지 못해 그대로 두면 새로 적재하는 naver_post
# 전체의 published_at이 조용히 NULL이 된다 — 두 형식을 모두 인식하도록
# ISO 8601(+HH:MM 오프셋) 형식도 함께 받는다. 기존 한국어 표기 데이터의 동작은
# 그대로 유지된다(이 정규식에 안 걸리면 기존 분기로 폴백).
_ISO_KST_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{2}:\d{2}$"
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
    conflict_key: str
    skipped_existing: int = 0
    deleted_superseded: int = 0


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
        help="jsonl과 장소 참조만 검증하고 Pinecone에는 보내지 않음",
    )
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help=(
            "적재 전에 동일 모델의 기존 임베딩을 지정 범위에서 삭제. "
            "청킹 버전 변경 시 사라진 옛 청크가 남는 것을 방지한다."
        ),
    )
    parser.add_argument(
        "--scope-content-ids",
        type=Path,
        help=(
            "--replace-existing 범위 CSV. content_id 컬럼이 있는 해당 구 "
            "place_catalog.csv를 지정해야 한다."
        ),
    )
    return parser


def _load_scope_content_ids(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = csv.DictReader(stream)
        if not rows.fieldnames or "content_id" not in rows.fieldnames:
            raise ValueError(f"{path}: content_id 컬럼이 필요합니다.")
        ids = sorted({str(row.get("content_id") or "").strip() for row in rows})
    ids = [value for value in ids if value]
    if not ids:
        raise ValueError(f"{path}: 교체 범위 content_id가 없습니다.")
    return ids


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
    if _ISO_KST_RE.match(text):
        # 이미 완전한 ISO 8601이라 재조합 없이 그대로 timestamptz 리터럴로 쓴다.
        return text
    match = _KOREAN_ABSOLUTE_RE.match(text)
    if match is None:
        return None
    year, month, day, hour, minute = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}T{int(hour):02d}:{minute}:00+09:00"


def _optional_metadata_fields(
    row: dict[str, object], *, content_id: str, source_ref: str
) -> dict[str, object | None]:
    """rating/language/is_translated/chunk_* — 202609070002 마이그레이션으로 추가된
    컬럼. 전부 nullable이라 jsonl에 없으면 None으로 채운다(기존 jsonl 형식과도
    호환). 값이 있으면 타입을 검증해 잘못된 형식이 조용히 NULL로 들어가지
    않게 한다.
    """
    label = f"{content_id}/{source_ref}"
    fields: dict[str, object | None] = {}

    rating = row.get("rating")
    if rating in (None, ""):
        fields["rating"] = None
    elif isinstance(rating, (int, float)) and 1 <= rating <= 5:
        fields["rating"] = int(rating)
    else:
        raise ValueError(f"{label}: rating은 1~5 정수여야 합니다 ({rating!r})")

    language = row.get("language")
    fields["language"] = str(language).strip() or None if language else None

    is_translated = row.get("is_translated")
    if is_translated is None or is_translated == "":
        fields["is_translated"] = None
    elif isinstance(is_translated, bool):
        fields["is_translated"] = is_translated
    else:
        raise ValueError(f"{label}: is_translated는 boolean이어야 합니다 ({is_translated!r})")

    for key in ("chunk_index", "chunk_count", "token_count"):
        value = row.get(key)
        if value in (None, ""):
            fields[key] = None
        elif (
            isinstance(value, int)
            and not isinstance(value, bool)
            and (value >= 0 if key == "chunk_index" else value > 0)
        ):
            fields[key] = value
        else:
            condition = "0 이상" if key == "chunk_index" else "1 이상"
            raise ValueError(f"{label}: {key}는 {condition} 정수여야 합니다 ({value!r})")

    if fields.get("chunk_index") is not None and fields.get("chunk_count") is not None:
        if fields["chunk_index"] >= fields["chunk_count"]:
            raise ValueError(
                f"{label}: chunk_index({fields['chunk_index']})가 "
                f"chunk_count({fields['chunk_count']}) 범위를 벗어났습니다."
            )

    for key in (
        "document_id", "chunk_id", "content_hash", "preprocessing_version",
        "embedding_version",
    ):
        value = row.get(key)
        fields[key] = str(value).strip() or None if value else None

    return fields


def load_embedding_payloads(
    jsonl_path: Path,
) -> tuple[list[dict[str, object]], int, int, int]:
    """jsonl을 읽어 upsert 페이로드로 바꾼다. 형식 위반은 즉시 멈춘다.

    v2의 (content_id, chunk_id)가 같은 행이 또 나오면 나중 것을 버린다.
    같은 배치 안에서 동일 충돌 키가 반복되면 ON CONFLICT가 같은 행을 두 번
    갱신할 수 없기 때문이다. 202609070003 이후에는 chunk_id가 필수다.
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
            chunk_id = str(row.get("chunk_id") or "").strip()
            source_type = str(row.get("source_type") or "").strip()
            source_text = str(row.get("source_text") or "").strip()
            place_title = str(row.get("place_title") or "").strip()
            model_name = str(row.get("model_name") or "").strip()
            embedding = row.get("embedding")

            if not content_id:
                raise ValueError(f"{line_number}행: content_id가 없습니다.")
            if not source_ref:
                raise ValueError(f"{content_id}: source_ref가 없습니다.")
            if not chunk_id:
                raise ValueError(f"{content_id}/{source_ref}: chunk_id가 없습니다.")
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

            key = (content_id, chunk_id)
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
                    **_optional_metadata_fields(row, content_id=content_id, source_ref=source_ref),
                }
            )

    return payloads, row_count, duplicate_count, published_at_nulled


_VALIDATE_PAGE_SIZE = 1000


async def _validate_active_places(
    client: httpx.AsyncClient,
    payloads: Sequence[dict[str, object]],
) -> None:
    # limit만 걸고 페이지네이션이 없으면 활성 장소가 1000건을 넘는 순간(다른 구
    # 확장 등으로) 뒤쪽 행이 조용히 잘려나가 실제로 활성인 content_id를
    # "없다"고 오판한다(2026-08-20, 중구 확장 중 실측). order를 명시해야
    # offset 페이지네이션이 페이지 사이에서 행을 건너뛰거나 중복하지 않는다.
    active_ids: set[str] = set()
    offset = 0
    while True:
        response = await client.get(
            "/rest/v1/places",
            params={
                "select": "content_id",
                "is_active": "eq.true",
                "order": "content_id.asc",
                "limit": str(_VALIDATE_PAGE_SIZE),
                "offset": str(offset),
            },
        )
        response.raise_for_status()
        rows = response.json()
        active_ids.update(
            str(row["content_id"])
            for row in rows
            if isinstance(row, dict) and row.get("content_id")
        )
        if len(rows) < _VALIDATE_PAGE_SIZE:
            break
        offset += _VALIDATE_PAGE_SIZE
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


def _check_chunk_ids_unique_across_places(payloads: Sequence[dict[str, object]]) -> None:
    """같은 chunk_id가 서로 다른 장소에 나오면 멈춘다.

    Supabase는 (content_id, chunk_id) 쌍이 고유했지만 Pinecone 레코드 ID는 chunk_id
    하나다. 겹치면 나중에 보낸 장소의 문장이 앞 장소의 문장을 오류 없이 덮어쓴다.
    (2026-10-16 확인: 이관한 220,670행에는 겹침이 없었다.)
    """
    owner: dict[str, str] = {}
    conflicts: list[str] = []
    for payload in payloads:
        chunk_id = str(payload["chunk_id"])
        content_id = str(payload["content_id"])
        previous = owner.setdefault(chunk_id, content_id)
        if previous != content_id:
            conflicts.append(f"{chunk_id}({previous}, {content_id})")
    if conflicts:
        raise ValueError(
            "서로 다른 장소에 같은 chunk_id가 있습니다: " + ", ".join(conflicts[:20])
            + (f" 외 {len(conflicts) - 20}건" if len(conflicts) > 20 else "")
        )


def _superseded_filter(content_ids: Sequence[str], embedding_version: str) -> dict[str, object]:
    """이 장소들 가운데 새 버전이 아닌 문장을 고르는 조건.

    `embedding_version`이 없는 문장(종로구 구버전 40,389행)도 옛 버전이다. Pinecone
    문서는 `$ne`가 필드 없는 레코드에 걸리는지 밝히지 않아서 `$exists: false`를
    따로 건다. Supabase 시절 조건 `embedding_version.is.null or neq`와 같은 뜻이다.
    """
    return {
        "$and": [
            {"content_id": {"$in": list(content_ids)}},
            {
                "$or": [
                    {"embedding_version": {"$exists": False}},
                    {"embedding_version": {"$ne": embedding_version}},
                ]
            },
        ]
    }


def _pinecone_headers(api_key: str) -> dict[str, str]:
    return {
        "Api-Key": api_key,
        "Content-Type": "application/json",
        "X-Pinecone-Api-Version": PINECONE_API_VERSION,
    }


async def _delete_superseded_versions(
    client: httpx.AsyncClient,
    *,
    host: str,
    api_key: str,
    namespace: str,
    content_ids: Sequence[str],
    embedding_version: str,
) -> int:
    """새 적재 성공 뒤 해당 구의 과거 버전만 지운다. 지운 문장 수를 돌려준다.

    지우기 전에 같은 조건으로 질의해 개수를 센다. 조건이 생각과 다르게 걸리면(예:
    새 버전까지 걸리면) 숫자로 바로 드러나게 하려는 것이다.
    """
    # 질의에는 벡터가 꼭 필요하다. 개수만 세므로 어느 방향이든 상관없고, 코사인은
    # 영벡터를 받지 않으므로 단위 벡터를 쓴다.
    probe = [1 / _EMBEDDING_DIM**0.5] * _EMBEDDING_DIM
    deleted = 0
    for start in range(0, len(content_ids), _REPLACE_PLACE_BATCH):
        chunk = content_ids[start : start + _REPLACE_PLACE_BATCH]
        flt = _superseded_filter(chunk, embedding_version)
        response = await client.post(
            f"https://{host}/query",
            json={
                "vector": probe,
                "topK": _PINECONE_TOP_K_LIMIT,
                "filter": flt,
                "includeMetadata": False,
                "includeValues": False,
                "namespace": namespace,
            },
            headers=_pinecone_headers(api_key),
        )
        response.raise_for_status()
        matched = len(response.json().get("matches") or [])
        if matched == 0:
            continue
        response = await client.post(
            f"https://{host}/vectors/delete",
            json={"filter": flt, "namespace": namespace},
            headers=_pinecone_headers(api_key),
        )
        response.raise_for_status()
        deleted += matched
    return deleted


async def run(
    args: argparse.Namespace,
    settings: Settings,
) -> PlaceEmbeddingImportResult:
    if not settings.supabase_url:
        raise ValueError("SUPABASE_URL이 필요합니다.")
    if not settings.supabase_secret_key:
        raise ValueError("SUPABASE_SECRET_KEY가 필요합니다.")
    # dry-run은 Pinecone에 보내지 않으므로 키 없이도 검증할 수 있어야 한다.
    if not args.dry_run:
        if not settings.pinecone_api_key:
            raise ValueError("PINECONE_API_KEY가 필요합니다.")
        if not settings.pinecone_index_host:
            raise ValueError("PINECONE_INDEX_HOST가 필요합니다.")

    payloads, row_count, duplicate_count, published_at_nulled = load_embedding_payloads(
        args.jsonl
    )
    _check_chunk_ids_unique_across_places(payloads)
    records = []
    for payload in payloads:
        record = to_record(payload)
        if record is None:
            # load_embedding_payloads가 chunk_id·content_id·768차원을 이미 검사했으므로
            # 여기 오면 두 스크립트의 레코드 규칙이 어긋난 것이다.
            label = f"{payload['content_id']}/{payload['chunk_id']}"
            raise ValueError(f"{label}: Pinecone 레코드로 바꿀 수 없습니다.")
        records.append(record)

    headers = {
        "apikey": settings.supabase_secret_key,
        "Authorization": f"Bearer {settings.supabase_secret_key}",
    }
    async with httpx.AsyncClient(
        base_url=settings.supabase_url.rstrip("/"),
        headers=headers,
        timeout=_REQUEST_TIMEOUT_SECONDS,
    ) as client:
        await _validate_active_places(client, payloads)

    replace_scope_ids: list[str] | None = None
    replace_embedding_version: str | None = None
    if not args.dry_run and args.replace_existing:
        if args.scope_content_ids is None:
            raise ValueError(
                "--replace-existing에는 --scope-content-ids place_catalog.csv가 필요합니다."
            )
        model_names = {str(payload["model_name"]) for payload in payloads}
        if len(model_names) != 1:
            raise ValueError("교체 적재 파일에는 model_name이 하나만 있어야 합니다.")
        embedding_versions = {str(payload.get("embedding_version") or "") for payload in payloads}
        if len(embedding_versions) != 1 or not next(iter(embedding_versions)):
            raise ValueError(
                "교체 적재 파일에는 비어 있지 않은 embedding_version 하나가 필요합니다."
            )
        replace_scope_ids = _load_scope_content_ids(args.scope_content_ids)
        replace_embedding_version = next(iter(embedding_versions))

    deleted_count = 0
    if not args.dry_run:
        host = settings.pinecone_index_host.strip().removeprefix("https://").rstrip("/")
        api_key = settings.pinecone_api_key
        namespace = settings.pinecone_namespace
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            total_batches = (len(records) + UPSERT_BATCH_SIZE - 1) // UPSERT_BATCH_SIZE
            for batch_index, start in enumerate(
                range(0, len(records), UPSERT_BATCH_SIZE), start=1
            ):
                # upsert_batch가 429·5xx를 재시도하고, 그 밖의 오류는 응답 본문과 함께 멈춘다.
                await upsert_batch(
                    client, host, api_key, namespace, records[start : start + UPSERT_BATCH_SIZE]
                )
                if batch_index % 20 == 0 or batch_index == total_batches:
                    print(f"  적재 {batch_index}/{total_batches} 배치 완료")
            # 새 버전 전체가 정상 적재된 뒤에만 과거 버전을 제거한다. 선삭제 후
            # 적재 실패로 검색 데이터가 비는 상황을 피한다.
            if replace_scope_ids is not None:
                deleted_count = await _delete_superseded_versions(
                    client,
                    host=host,
                    api_key=api_key,
                    namespace=namespace,
                    content_ids=replace_scope_ids,
                    embedding_version=replace_embedding_version or "",
                )
                print(
                    f"  과거 임베딩 버전 정리 완료: {len(replace_scope_ids)}개 장소, "
                    f"{deleted_count}개 문장 삭제"
                )

    return PlaceEmbeddingImportResult(
        jsonl_row_count=row_count,
        payload_count=len(payloads),
        duplicate_keys=duplicate_count,
        published_at_nulled=published_at_nulled,
        imported_count=0 if args.dry_run else len(records),
        dry_run=args.dry_run,
        conflict_key="pinecone:chunk_id",
        deleted_superseded=deleted_count,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = asyncio.run(run(args, Settings()))
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
