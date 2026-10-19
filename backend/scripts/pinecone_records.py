"""취향 근거 문장을 Pinecone 레코드로 만들고 보내는 공통 함수.

역할: 새 임베딩 적재(`import_place_embeddings.py`)가 쓴다. 레코드 ID 규칙과 메타데이터
      열을 이 한 곳에서 정한다.

원래 Supabase `place_embeddings`를 Pinecone으로 옮긴 이관 스크립트
(`export_place_embeddings_to_pinecone.py`, PR #453)에 있던 함수다. 이관이 끝나고 테이블을
지우면서 그 스크립트는 삭제했고, 적재가 같이 쓰던 부분만 여기로 옮겼다. **이관 때와 같은
ID·같은 메타데이터를 써야** 다시 넣었을 때 같은 문장이 덮어써지고 중복이 쌓이지 않는다.

서비스가 읽는 쪽은 `app/repositories/pinecone_evidence.py`다.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

# 데이터 평면 호출에 쓰는 API 버전. Pinecone은 이 헤더가 없으면 가장 오래된 계약으로
# 응답하므로 명시한다 — 나중에 계약이 바뀌어도 이 값을 올릴 때까지 동작이 고정된다.
PINECONE_API_VERSION = "2026-07"

# Pinecone upsert 한 요청의 상한은 레코드 1,000개 또는 **2MB**다. 우리 레코드는
# 768개 float이 JSON 숫자로 풀리면서 9KB를 넘고 메타데이터가 1KB 가까이 붙어
# 레코드당 약 10KB다. 1,000개를 담으면 10MB로 상한을 훌쩍 넘으므로 개수가 아니라
# 크기가 실질 제약이다. 100개면 약 1MB로 절반쯤 여유가 남는다.
UPSERT_BATCH_SIZE = 100
_UPSERT_TIMEOUT_SECONDS = 120.0
_UPSERT_MAX_ATTEMPTS = 5

_EMBEDDING_DIM = 768

# Pinecone 메타데이터로 싣는 열. `embedding`은 벡터로 따로 간다.
#
# **`content_id`와 `source_text`는 빠지면 안 된다.** `content_id`는 후보 장소 필터에
# 쓰고(`$in`), `source_text`는 화면에 보여줄 근거 문장 본문이다. 둘 중 하나라도 비면
# 검색은 성공하는데 결과가 쓸모없어진다 — 이 저장소에서 반복된 "조용한 fake"와 같은
# 모양의 실패다. `document_id`·`source_url`·`source_ref`는 같은 글을 가르는 키다.
METADATA_COLUMNS = (
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


def _record_id(row: dict[str, Any]) -> str | None:
    """Pinecone 레코드 ID를 만든다.

    `chunk_id`를 먼저 쓴다 — 내용에서 나온 값이라 다시 적재해도 같은 문장이 같은 ID로
    덮이므로 중복이 쌓이지 않는다.

    **종로구 40,389행은 `chunk_id`가 없었다**(2026-10-02 확인). 이관 때 Supabase 행
    번호로 `row-{id}`를 대신 썼다. 지금 적재 스크립트는 `chunk_id`가 없는 행을 받지
    않으므로 새로 들어오는 레코드는 모두 `chunk_id`를 ID로 쓴다. 이 분기는 이관 때의
    규칙을 기록으로 남겨 둔 것이다(백업 `~/Backups/tripbranch/README.md`도 이 규칙으로
    짝을 맞춘다).
    """
    chunk_id = row.get("chunk_id")
    if chunk_id:
        return str(chunk_id)
    row_id = row.get("id")
    if row_id is not None:
        return f"row-{row_id}"
    return None


def to_record(row: dict[str, Any]) -> dict[str, Any] | None:
    """문장 한 줄을 Pinecone 레코드로 바꾼다. 못 쓰는 줄은 None."""
    record_id = _record_id(row)
    if record_id is None:
        return None

    embedding = row.get("embedding")
    # PostgREST는 vector 타입을 문자열 "[0.1,0.2,...]"로 돌려줬다. 리스트로 오는
    # 경우도 있어 둘 다 받는다.
    if isinstance(embedding, str):
        try:
            embedding = json.loads(embedding)
        except json.JSONDecodeError:
            return None
    if not isinstance(embedding, list) or len(embedding) != _EMBEDDING_DIM:
        return None

    metadata: dict[str, Any] = {}
    for column in METADATA_COLUMNS:
        value = row.get(column)
        # **None은 넣지 않는다.** Pinecone 메타데이터는 null을 받지 않아 400이 난다.
        if value is None or value == "":
            continue
        metadata[column] = value

    if not metadata.get("content_id"):
        # content_id가 없으면 후보 필터에 걸리지 않아 검색에서 영원히 안 나온다.
        return None

    return {"id": record_id, "values": embedding, "metadata": metadata}


async def upsert_batch(
    client: httpx.AsyncClient,
    host: str,
    api_key: str,
    namespace: str,
    records: list[dict[str, Any]],
) -> None:
    """레코드 묶음을 upsert한다. 429·5xx·타임아웃은 다시 시도한다."""
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
