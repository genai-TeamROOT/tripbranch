# 지역구 임베딩 대량 적재 가이드

## 1. 목적

Colab에서 생성한 지역구별 `place_embeddings_*.jsonl.gz` 파일을 팀 Pinecone 인덱스
`place-evidence`에 안전하게 적재하는 방법을 설명한다.

> 2026-10 변경: 취향 근거 벡터를 Supabase `public.place_embeddings`에서 Pinecone으로
> 옮겼다(#453·#454·#455). Supabase 무료 플랜(500MB) 안에 들어가기 위해서다. 테이블은
> 삭제했고, 서비스와 적재 모두 Pinecone을 쓴다. 장소가 활성 상태인지 확인할 때만
> Supabase `places`를 읽는다.

이번 적재 방식은 다음 조건을 기준으로 한다.

- 임베딩 모델: `jhgan/ko-sroberta-multitask`
- 벡터 차원: 768 (인덱스는 cosine)
- 운영 파일 예시:
  `place_embeddings_170_yongsan_jhgan_evidence_120t_v8.jsonl.gz`
- Pinecone 레코드 ID: `chunk_id`
- 전송 방식: Pinecone upsert
- 요청당 배치 크기: 100개 (요청 상한 2MB, 레코드 하나가 약 10KB)
- 요청 타임아웃: 120초

## 2. 관련 코드

### `backend/scripts/import_place_embeddings.py`

- JSONL 형식, 벡터 차원, `content_id`, `chunk_id`, 활성 장소 여부 검증
- 같은 `chunk_id`가 서로 다른 장소에 나오면 적재 전에 중단
  (Pinecone 레코드 ID가 `chunk_id` 하나라, 겹치면 한 장소의 문장이 덮어써진다)
- 100개 단위 Pinecone upsert, 429·5xx·타임아웃은 재시도
- `--replace-existing`: 새 버전 적재가 끝난 뒤 옛 버전을 세고 나서 삭제

### `backend/scripts/pinecone_records.py`

- 레코드 ID 규칙과 메타데이터 열을 정한다. Supabase에서 옮겨 온 22만 개와 같은
  형식이라, 다시 적재하면 같은 문장이 덮어써지고 중복이 생기지 않는다.

### `backend/scripts/import_district_embedding_archive.py`

- `.jsonl.gz` 압축 해제
- 실제 적재 전에 자동 dry-run 수행
- 지역구와 파일 형식 검증
- 사용자가 `IMPORT <지역구 폴더명>`을 정확히 입력해야 실제 적재
- 다음 두 파일명 유형 지원
  - `jhgan_structural_120t_v*`
  - `jhgan_evidence_120t_v*`

## 3. 준비

`backend/.env`에 다음 값이 있어야 한다.

- `SUPABASE_URL`, `SUPABASE_SECRET_KEY`: 활성 장소 확인용
- `PINECONE_API_KEY`, `PINECONE_INDEX_HOST`: 적재용
- `PINECONE_NAMESPACE`: 비우면 기본 네임스페이스. 서비스가 읽는 곳과 같아야 한다.

## 4. 전체 작업 순서

```text
1. 팀원별로 Colab에서 담당 지역구 임베딩 생성
2. 지역구별 .jsonl.gz 파일 다운로드 및 보관
3. 지역구별 파일을 dry-run으로 검증
4. 확인 문구를 입력해 Pinecone에 적재
5. 지역구별 적재 건수 확인
6. 대표 취향 질의로 서비스 동작 확인
```

Supabase 시절에 필요했던 HNSW 인덱스 제거·재생성은 하지 않는다. Pinecone이 색인을
알아서 관리한다.

## 5. 지역구 파일 적재

평소 사용하는 `tripbranch/backend` 폴더에서 실행한다.

```bash
cd /각자경로/tripbranch/backend

.venv/bin/python -u scripts/import_district_embedding_archive.py \
  "/Users/본인계정/Downloads/place_embeddings_170_yongsan_jhgan_evidence_120t_v8.jsonl.gz"
```

`uv`를 사용한다면 다음과 같이 실행할 수도 있다.

```bash
uv run python -u scripts/import_district_embedding_archive.py \
  "/Users/본인계정/Downloads/place_embeddings_170_yongsan_jhgan_evidence_120t_v8.jsonl.gz"
```

스크립트는 다음 순서로 동작한다.

1. 파일명에서 지역구를 확인한다.
2. 임시 폴더에 JSONL을 압축 해제한다.
3. JSONL 형식, 벡터 차원, `content_id`, `chunk_id`, 활성 장소 여부를 검증한다.
4. dry-run 결과를 출력한다.
5. 사용자에게 `IMPORT 170_yongsan` 같은 확인 문구를 요구한다.
6. 확인 문구가 일치하면 100개씩 Pinecone에 upsert한다.
7. 임시 압축 해제 파일을 자동으로 삭제한다.

다운로드한 `.jsonl.gz` 원본은 재검증과 장애 복구를 위해 보관한다.

## 6. 검증만 실행하기

Pinecone을 변경하지 않고 파일과 참조 관계만 확인하려면 다음 옵션을 사용한다.
이때는 Pinecone 설정이 없어도 된다.

```bash
.venv/bin/python -u scripts/import_district_embedding_archive.py \
  "/다운로드/경로/place_embeddings_<구>_jhgan_evidence_120t_v8.jsonl.gz" \
  --dry-run-only
```

## 7. 기존 버전 교체

같은 지역구를 새 청킹 또는 새 임베딩 버전으로 다시 적재하면 새 파일에 존재하지
않는 옛 청크가 남을 수 있다. 이때만 `--replace-existing`을 사용한다.

```bash
.venv/bin/python -u scripts/import_district_embedding_archive.py \
  "/다운로드/경로/place_embeddings_<구>_jhgan_evidence_120t_v8.jsonl.gz" \
  --replace-existing
```

이 옵션은 새 버전 적재가 전부 성공한 뒤, 해당 지역구 장소 가운데
`embedding_version`이 새 버전이 아니거나 비어 있는 레코드를 먼저 세어 출력하고
지운다. 자동으로 지역구의 `place_catalog.csv`를 찾지 못하면 다음처럼 직접 지정한다.

```bash
.venv/bin/python -u scripts/import_district_embedding_archive.py \
  "/다운로드/경로/place_embeddings_<구>_jhgan_evidence_120t_v8.jsonl.gz" \
  --replace-existing \
  --scope-content-ids "/경로/place_catalog.csv"
```

처음 적재하는 지역구에는 `--replace-existing`이 필요 없다.

삭제 조건 실측(2026-10-16, 삭제 없이 개수만 셈):

| 조건 | 결과 |
| --- | ---: |
| 종로구 + 새 버전 `v8` (종로구는 `embedding_version` 없음) | 40,389개 전부 |
| 용산구 + 새 버전 `v8` (이미 v8) | 0개 |
| 용산구 + 가상 버전 `v9` | 13,123개 |

## 8. 적재 결과 확인

적재가 끝나면 스크립트가 `imported_count`(적재 수)와 `deleted_superseded`(지운 옛
버전 수)를 출력한다. 파일 manifest의 `output_chunks`와 `imported_count`가 같은지
확인한다.

인덱스 전체 레코드 수는 Pinecone 콘솔의 인덱스 화면이나 `describe_index_stats`로 본다.
2026-10-16 기준 220,670개다.

`published_at_nulled`는 작성 시각을 절대 날짜로 복원할 수 없는 문서 수다.
본문, URL, 임베딩 적재 실패 건수를 뜻하지 않는다.

## 9. 운영 주의사항

- Pinecone Starter 플랜은 쓰기 한도가 월 200만 WU다. 문장 하나가 약 4 WU라(2026-09
  측정 기준 추정) 구 하나(평균 약 9천 개)는 한도의 2% 안팎이지만, 전 구를 다시 넣으면
  40%를 넘는다. 여러 구를 다시 넣을 때는 한 달 안에 몰지 않는다.
- 파일을 다시 실행해도 `chunk_id`가 같은 레코드는 덮어써지므로 중복이 생기지 않는다.
- 청킹 방식이 바뀌어 `chunk_id` 자체가 달라진 경우에는 반드시
  `--replace-existing`으로 옛 버전을 정리한다.
- `.env`와 비밀값을 공유 파일, 로그 또는 Git에 포함하지 않는다.
