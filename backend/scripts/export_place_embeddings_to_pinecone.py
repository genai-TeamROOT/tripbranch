"""Supabase `place_embeddings`를 Pinecone 인덱스로 옮긴다(수동 실행).

역할: 무료 플랜 전환을 위해 가장 큰 테이블(1,117MB, 220,670행)을 외부 벡터 DB로
내보낸다. Supabase는 읽기만 하고 아무것도 지우지 않는다 — 원본 삭제는 Pinecone
쪽 동작을 확인한 뒤 별도로 한다.

입력: `backend/.env`의 PINECONE_API_KEY·PINECONE_INDEX(+ 선택 PINECONE_NAMESPACE).
출력: Pinecone upsert 결과 요약. `--dry-run`이면 전송 없이 형식만 검사한다.
호출 시점: `python -m scripts.export_place_embeddings_to_pinecone --limit 2000 --dry-run`

**의존성을 늘리지 않는다.** `pinecone` 클라이언트 대신 httpx로 REST를 직접 부른다 —
저장소의 다른 Provider·스크립트가 모두 httpx를 쓰고, 이 한 번짜리 이관 때문에
`pyproject.toml`을 건드려 다른 사람 설치를 무겁게 만들 이유가 없다.

**설정을 app/config.py에 넣지 않는다.** 그 파일은 A 소유이고, 지금 필요한 값은 이
스크립트만 쓴다. 런타임이 Pinecone을 읽기 시작할 때 Settings에 정식으로 올리면서 A와
이야기한다. 그때까지는 같은 `backend/.env`를 이 스크립트가 따로 읽는다.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import Settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
_ENV_FILE = BACKEND_DIR / ".env"

# 데이터 평면 호출에 쓰는 API 버전. Pinecone은 이 헤더가 없으면 가장 오래된 계약으로
# 응답하므로 명시한다 — 나중에 계약이 바뀌어도 이 값을 올릴 때까지 동작이 고정된다.
PINECONE_API_VERSION = "2026-07"
_CONTROL_PLANE = "https://api.pinecone.io"

# Pinecone upsert 한 요청의 상한은 레코드 1,000개 또는 **2MB**다. 우리 레코드는
# 768개 float이 JSON 숫자로 풀리면서 9KB를 넘고 메타데이터가 1KB 가까이 붙어
# 레코드당 약 10KB다. 1,000개를 담으면 10MB로 상한을 훌쩍 넘으므로 개수가 아니라
# 크기가 실질 제약이다. 100개면 약 1MB로 절반쯤 여유가 남는다.
UPSERT_BATCH_SIZE = 100
_UPSERT_TIMEOUT_SECONDS = 120.0
_UPSERT_MAX_ATTEMPTS = 5

# Supabase에서 한 번에 읽어 오는 행 수. PostgREST 기본 상한이 1,000이라 그보다 크게
# 잡아도 소용없고, 행마다 3KB 벡터가 붙어 1,000행이면 응답이 3MB다.
_READ_PAGE_SIZE = 500
_READ_TIMEOUT_SECONDS = 120.0

_EMBEDDING_DIM = 768

# Pinecone 메타데이터로 옮기는 열. `embedding`은 벡터로 따로 가고 `id`는 쓰지 않는다.
#
# **`content_id`와 `source_text`는 빠지면 안 된다.** `content_id`는 후보 장소 필터에
# 쓰고(`$in`), `source_text`는 화면에 보여줄 근거 문장 본문이다. 둘 중 하나라도 비면
# 검색은 성공하는데 결과가 쓸모없어진다 — 이 저장소에서 반복된 "조용한 fake"와 같은
# 모양의 실패다.
#
# `district_code`는 `place_embeddings`에 없어서 `places`를 조인해 채운다. 지금은
# 네임스페이스를 나누지 않기로 했으므로 메타데이터로만 들어가지만, 나중에 구별로
# 나누고 싶어지면 이 값이 있어야 재적재 없이 판단할 수 있다.
_METADATA_COLUMNS = (
    "content_id",
    "place_title",
    "source_type",
    "source_text",
    "source_url",
    "source_ref",
    "published_at",
    "rating",
    "language",
    "chunk_index",
    "chunk_count",
    "document_id",
    "content_hash",
    "embedding_version",
)

# Supabase에서 읽어올 열. `chunk_id`는 Pinecone 레코드 ID로 쓴다 —
# place_embeddings_content_chunk_id_unique 인덱스가 고유성을 보장한다.
_SELECT_COLUMNS = ("id", "chunk_id", "embedding", *_METADATA_COLUMNS)


class PineconeSettings(BaseSettings):
    """이 스크립트만 쓰는 설정. app/config.py의 Settings와 같은 .env를 읽는다."""

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore", env_ignore_empty=True)

    pinecone_api_key: str = ""
    pinecone_index: str = ""
    # 비우면 기본 네임스페이스(빈 문자열)에 들어간다. 후보가 30곳으로 묶여 있어
    # 구별로 나눠도 이득이 작다고 판단해 당장은 나누지 않는다 — 나중에 나누려면
    # 전체를 지우고 다시 넣어야 한다(네임스페이스는 upsert 때 박히고 이동이 안 된다).
    pinecone_namespace: str = ""


@dataclass(frozen=True)
class PineconeIndex:
    """describe_index가 돌려준 인덱스 정보."""

    name: str
    host: str
    dimension: int
    metric: str


@dataclass
class ExportStats:
    read: int = 0
    skipped: int = 0
    sent: int = 0
    batches: int = 0
    # 마지막으로 읽은 행의 id. 중간에 끊겼을 때 `--start-after-id`로 이어 돌리게
    # 끝에 출력한다.
    last_id: int = 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Supabase place_embeddings를 Pinecone으로 내보낸다"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="내보낼 행 수 상한. 생략하면 전체. 소규모 시험에 쓴다",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pinecone에 전송하지 않고 레코드 형식과 건수만 확인한다",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=UPSERT_BATCH_SIZE,
        help=f"upsert 한 요청에 담는 레코드 수 (기본 {UPSERT_BATCH_SIZE}, 요청 상한 2MB)",
    )
    parser.add_argument(
        "--start-after-id",
        type=int,
        default=0,
        help=(
            "이 id보다 큰 행부터 내보낸다. 중단된 적재를 이어서 돌릴 때, "
            "또는 앞쪽(종로구 구버전) 말고 뒤쪽 행을 시험할 때 쓴다"
        ),
    )
    parser.add_argument(
        "--content-ids-file",
        type=Path,
        default=None,
        help=(
            "이 파일에 적힌 장소(content_id)의 행만 내보낸다. 한 줄에 하나, 또는 "
            "content_id 열이 있는 CSV. 근사 검색 정확도를 평가 대상 장소만으로 잴 때 쓴다"
        ),
    )
    return parser.parse_args(argv)


def load_content_ids(path: Path) -> list[str]:
    """`--content-ids-file`을 읽는다. CSV면 content_id 열을, 아니면 줄마다 하나씩 읽는다.

    평가 후보 목록(`candidate_places.csv`)을 그대로 넘길 수 있게 CSV를 받는다.
    """
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if not lines:
        raise SystemExit(f"{path}가 비어 있습니다.")
    if "content_id" in lines[0].split(","):
        with path.open(encoding="utf-8-sig", newline="") as file:
            ids = [row["content_id"].strip() for row in csv.DictReader(file)]
    else:
        ids = [line.strip() for line in lines]
    ids = list(dict.fromkeys(value for value in ids if value))
    if not ids:
        raise SystemExit(f"{path}에서 content_id를 하나도 읽지 못했습니다.")
    return ids


def _require(value: str, name: str) -> str:
    if not value:
        raise SystemExit(
            f"{name}이 비어 있습니다. backend/.env에 넣고 다시 실행하세요.\n"
            "  (키 값은 로그나 화면에 찍지 않습니다)"
        )
    return value


async def describe_index(client: httpx.AsyncClient, api_key: str, name: str) -> PineconeIndex:
    """인덱스 호스트를 조회한다.

    호스트를 .env에 직접 적게 하지 않는 이유는, 인덱스를 다시 만들면 호스트가
    바뀌는데 그걸 모른 채 옛 호스트로 쏘면 404가 아니라 **다른 인덱스에 들어갈 수**
    있기 때문이다. 이름만 받아 매번 조회한다.
    """
    response = await client.get(
        f"{_CONTROL_PLANE}/indexes/{name}",
        headers={"Api-Key": api_key, "X-Pinecone-Api-Version": PINECONE_API_VERSION},
        timeout=30.0,
    )
    if response.status_code == 404:
        raise SystemExit(f"Pinecone에 '{name}' 인덱스가 없습니다. 콘솔에서 먼저 만드세요.")
    if response.status_code == 401:
        raise SystemExit("Pinecone 인증이 거부됐습니다(401). PINECONE_API_KEY를 확인하세요.")
    response.raise_for_status()
    payload = response.json()

    host = payload.get("host")
    if not host:
        raise SystemExit(f"describe_index 응답에 host가 없습니다: {sorted(payload)}")

    # **응답 형식이 두 가지다.** 문서의 예시는 `dimension`·`metric`을 최상위에 두는데,
    # 2026-10-03에 실제로 받아 보니 `schema.fields._values` 안에 들어 있었다(관리형
    # serverless 인덱스). 어느 쪽이 올지 버전으로 가려내지 말고 둘 다 읽는다 —
    # 최상위가 없다고 0으로 두면 "차원이 0입니다"라며 정상 인덱스를 거부한다.
    dense = payload.get("schema", {}).get("fields", {}).get("_values", {})
    dimension = payload.get("dimension") or dense.get("dimension") or 0
    metric = payload.get("metric") or dense.get("metric") or ""

    index = PineconeIndex(
        name=payload.get("name", name),
        host=str(host),
        dimension=int(dimension),
        metric=str(metric),
    )

    # **여기서 막는 게 중요하다.** 차원이나 거리 척도가 다른 인덱스에 넣어도 Pinecone은
    # 차원이 맞으면 조용히 받아들인다. 거리 척도가 cosine이 아니면 오류 없이 순위만
    # 엉뚱해진다 — 적재가 끝난 뒤에야 드러나고, 되돌리려면 쓰기 예산을 또 쓴다.
    if index.dimension != _EMBEDDING_DIM:
        raise SystemExit(
            f"인덱스 차원이 {index.dimension}입니다. {_EMBEDDING_DIM}이어야 합니다 "
            f"(모델 jhgan/ko-sroberta-multitask)."
        )
    if index.metric != "cosine":
        raise SystemExit(
            f"인덱스 거리 척도가 '{index.metric}'입니다. 'cosine'이어야 합니다 — "
            "벡터를 길이 1로 정규화해 넣었으므로 다른 척도면 순위가 달라집니다."
        )
    return index


async def _fetch_page(
    client: httpx.AsyncClient,
    settings: Settings,
    *,
    after_id: int,
    page_size: int,
    content_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """id가 `after_id`보다 큰 행을 page_size개 읽는다.

    **OFFSET을 쓰지 않는다.** OFFSET은 건너뛸 행을 실제로 다 읽으므로 22만 행을 끝까지
    훑는 동안 페이지마다 느려지고, 뒤쪽에서는 Postgres의 statement_timeout(57014)에
    걸린다. `id > n` 조건은 기본키 인덱스를 타서 어느 위치에서나 같은 속도다.

    (2026-10-02 확인: `places`를 조인해 구로 거르는 방식도 같은 타임아웃이 났다 —
    조인 결과를 id로 정렬하느라 전수 스캔이 된다. 그래서 구 필터는 넣지 않는다.)

    `content_ids`를 주면 그 장소의 행만 읽는다. 구 조인과 달리
    `place_embeddings_content_id_idx`를 타므로 빠르다(55곳 4,242행 기준).
    """
    params: dict[str, str] = {
        "select": ",".join(_SELECT_COLUMNS),
        "order": "id.asc",
        "id": f"gt.{after_id}",
        "limit": str(page_size),
    }
    if content_ids:
        params["content_id"] = f"in.({','.join(content_ids)})"

    response = await client.get(
        f"{settings.supabase_url}/rest/v1/place_embeddings",
        params=params,
        headers={
            "apikey": settings.supabase_secret_key,
            "Accept": "application/json",
        },
        timeout=_READ_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise SystemExit(f"place_embeddings 응답이 배열이 아닙니다: {type(payload).__name__}")
    return payload


def _record_id(row: dict[str, Any]) -> str | None:
    """Pinecone 레코드 ID를 만든다.

    `chunk_id`를 먼저 쓴다 — `place_embeddings_content_chunk_id_unique`가 고유성을
    보장하고, 다시 적재해도 같은 행이 같은 ID로 덮이므로 중복이 쌓이지 않는다.

    **종로구 40,389행은 `chunk_id`가 없다**(2026-10-02 확인: v8 180,281행은 전부 있고
    구버전은 0건). 그래서 `id`(bigint 기본키)로 대체한다. 두 체계가 섞이지만 ID는
    고유하기만 하면 되고, `chunk_id`는 문자열 해시라 숫자와 겹치지 않는다.

    `id`를 전부에 쓰지 않는 이유는 재적재 안정성이다. `id`는 행을 지우고 다시 넣으면
    바뀌는 값이라, 적재 스크립트를 다시 돌릴 때 같은 청크가 다른 ID로 들어가 중복이
    생긴다. `chunk_id`는 내용에서 나온 값이라 그 문제가 없다.
    """
    chunk_id = row.get("chunk_id")
    if chunk_id:
        return str(chunk_id)
    row_id = row.get("id")
    if row_id is not None:
        return f"row-{row_id}"
    return None


def to_record(row: dict[str, Any]) -> dict[str, Any] | None:
    """Supabase 행 하나를 Pinecone 레코드로 바꾼다. 못 쓰는 행은 None.

    새 임베딩 적재(import_place_embeddings)도 이 함수로 레코드를 만든다. 두 경로가
    같은 ID·같은 메타데이터를 써야 다시 넣었을 때 같은 문장이 덮어써진다.
    """
    record_id = _record_id(row)
    if record_id is None:
        # ID를 만들 수 없는 행. 건너뛰고 수만 센다 — 여기서 죽이면 22만 행 중 한 행
        # 때문에 전체 적재가 멈춘다.
        return None

    embedding = row.get("embedding")
    # PostgREST는 vector 타입을 문자열 "[0.1,0.2,...]"로 돌려준다. 리스트로 오는
    # 경우도 있어 둘 다 받는다.
    if isinstance(embedding, str):
        try:
            embedding = json.loads(embedding)
        except json.JSONDecodeError:
            return None
    if not isinstance(embedding, list) or len(embedding) != _EMBEDDING_DIM:
        return None

    metadata: dict[str, Any] = {}
    for column in _METADATA_COLUMNS:
        value = row.get(column)
        # **None은 넣지 않는다.** Pinecone 메타데이터는 null을 받지 않아 400이 난다.
        # 종로구 40,389행은 document_id·chunk_index·embedding_version이 비어 있어
        # 이 분기를 실제로 탄다.
        if value is None or value == "":
            continue
        metadata[column] = value

    if not metadata.get("content_id"):
        # content_id가 없으면 후보 필터에 걸리지 않아 검색에서 영원히 안 나온다.
        # 넣어도 쓸 수 없는 레코드이므로 건너뛴다.
        return None

    return {"id": record_id, "values": embedding, "metadata": metadata}


async def upsert_batch(
    client: httpx.AsyncClient,
    host: str,
    api_key: str,
    namespace: str,
    records: list[dict[str, Any]],
) -> None:
    """레코드 묶음을 upsert한다. 적재 스크립트(import_place_embeddings)도 같이 쓴다."""
    body = {"vectors": records, "namespace": namespace}
    last_error: Exception | None = None

    for attempt in range(1, _UPSERT_MAX_ATTEMPTS + 1):
        try:
            response = await client.post(
                f"https://{host}/vectors/upsert",
                json=body,
                headers={
                    "Api-Key": api_key,
                    "Content-Type": "application/json",
                    "X-Pinecone-Api-Version": PINECONE_API_VERSION,
                },
                timeout=_UPSERT_TIMEOUT_SECONDS,
            )
        except httpx.TimeoutException as error:
            last_error = error
        else:
            if response.status_code < 400:
                return
            # 429(한도 초과)와 5xx는 다시 시도할 가치가 있다. 4xx 나머지는 요청 자체가
            # 잘못된 것이라 재시도해도 같은 답이 온다 — 본문을 보여주고 멈춘다.
            if response.status_code != 429 and response.status_code < 500:
                raise SystemExit(
                    f"Pinecone upsert가 {response.status_code}로 거부했습니다.\n"
                    f"  응답: {response.text[:500]}"
                )
            last_error = httpx.HTTPStatusError(
                f"status {response.status_code}", request=response.request, response=response
            )

        if attempt < _UPSERT_MAX_ATTEMPTS:
            await asyncio.sleep(min(2**attempt, 30))

    raise SystemExit(f"Pinecone upsert가 {_UPSERT_MAX_ATTEMPTS}번 모두 실패했습니다: {last_error}")


async def run(args: argparse.Namespace) -> ExportStats:
    settings = Settings()
    _require(settings.supabase_url, "SUPABASE_URL")
    _require(settings.supabase_secret_key, "SUPABASE_SECRET_KEY")

    pinecone = PineconeSettings()
    namespace = pinecone.pinecone_namespace

    # **dry-run은 Pinecone 설정을 요구하지 않는다.** 전송을 하지 않으므로 키가 필요
    # 없고, 키를 넣기 전에 읽기 경로와 레코드 형식을 먼저 확인할 수 있어야 한다.
    api_key = ""
    index_name = ""
    if not args.dry_run:
        api_key = _require(pinecone.pinecone_api_key, "PINECONE_API_KEY")
        index_name = _require(pinecone.pinecone_index, "PINECONE_INDEX")

    content_ids = None
    if args.content_ids_file is not None:
        content_ids = load_content_ids(args.content_ids_file)
        print(f"장소 {len(content_ids)}곳의 행만 내보냅니다.")

    stats = ExportStats()
    pending: list[dict[str, Any]] = []

    async with httpx.AsyncClient() as client:
        index: PineconeIndex | None = None
        if args.dry_run:
            print("dry-run — Supabase만 읽고 Pinecone에는 전송하지 않습니다.")
        else:
            index = await describe_index(client, api_key, index_name)
            print(
                f"인덱스 '{index.name}' 확인 — {index.dimension}차원 {index.metric}, "
                f"네임스페이스 {namespace or '(기본)'}"
            )

        after_id = args.start_after_id
        while True:
            remaining = None if args.limit is None else args.limit - stats.read
            if remaining is not None and remaining <= 0:
                break
            page_size = _READ_PAGE_SIZE if remaining is None else min(_READ_PAGE_SIZE, remaining)

            rows = await _fetch_page(
                client,
                settings,
                after_id=after_id,
                page_size=page_size,
                content_ids=content_ids,
            )
            if not rows:
                break
            # 다음 페이지 기준점. 정렬이 id.asc이므로 마지막 행이 가장 큰 id다.
            after_id = int(rows[-1]["id"])
            stats.read += len(rows)
            stats.last_id = after_id

            for row in rows:
                record = to_record(row)
                if record is None:
                    stats.skipped += 1
                    continue
                pending.append(record)

                if len(pending) >= args.batch_size:
                    if index is not None:
                        await upsert_batch(client, index.host, api_key, namespace, pending)
                    stats.sent += len(pending)
                    stats.batches += 1
                    pending.clear()
                    print(f"  {stats.sent}건 전송 ({stats.batches}번째 묶음)", flush=True)

            if len(rows) < page_size:
                break

        if pending:
            if index is not None:
                await upsert_batch(client, index.host, api_key, namespace, pending)
            stats.sent += len(pending)
            stats.batches += 1
            pending.clear()

    return stats


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.batch_size < 1:
        raise SystemExit("--batch-size는 1 이상이어야 합니다.")

    stats = asyncio.run(run(args))

    print()
    print(f"읽은 행      {stats.read:,}")
    print(f"건너뛴 행    {stats.skipped:,}")
    print(f"보낸 레코드  {stats.sent:,} ({stats.batches:,}번 요청)")
    if stats.last_id:
        print(f"마지막 id    {stats.last_id:,}  (이어 돌리려면 --start-after-id {stats.last_id})")
    if stats.skipped:
        print()
        print(
            "건너뛴 행이 있습니다. chunk_id·content_id가 비었거나 벡터가 768개가 아닌 "
            "행입니다 — 수가 많으면 적재를 멈추고 원인을 보세요."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
