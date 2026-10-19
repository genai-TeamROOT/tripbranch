# place_embeddings 데이터 딕셔너리

## 개요

네이버 블로그, Google 리뷰, TourAPI 개요를 청킹·임베딩한 RAG 근거 저장소다. 후보
`content_id`를 먼저 좁힌 뒤 같은 원문에서는 가장 관련도 높은 청크 하나만 사용해 장소별
근거 점수를 계산한다.

> 2026-10 변경: Supabase `public.place_embeddings` 테이블(1,117MB, 220,670행)을 Pinecone
> 인덱스 `place-evidence`로 옮기고 테이블을 삭제했다. Supabase를 무료 플랜(500MB) 안에
> 넣기 위해서다(#453·#454·#455, 팀 전원 동의). 아래는 Pinecone 레코드 기준이다.
>
> - 서비스가 읽는 곳: `backend/app/repositories/pinecone_evidence.py`
> - 레코드를 만드는 곳: `backend/scripts/pinecone_records.py`
> - 적재 방법: [place_embeddings_bulk_import_guide.md](place_embeddings_bulk_import_guide.md)

## 인덱스

| 항목 | 값 |
| --- | --- |
| 이름 | `place-evidence` |
| 차원 | 768 |
| 거리 | cosine |
| 종류 | serverless, aws `us-east-1` |
| 네임스페이스 | 기본(빈 값) |
| 레코드 ID | `chunk_id`. 종로구 구버전 40,389개는 `chunk_id`가 없어 이관 때 `row-{Supabase id}`로 넣었다 |

## 메타데이터

값이 없는 열은 메타데이터에 넣지 않는다(Pinecone은 null을 받지 않는다).

| 필드 | 정의 | 값 예시 | 활용 |
| --- | --- | --- | --- |
| `content_id` | `places`와 연결되는 장소 ID | `2808041` | 후보 장소 필터(`$in`) |
| `place_title` | 장소 표시명 | `후암편백` | 검색 결과 표시 |
| `source_type` | 원문 출처 | `naver_post`, `google_review`, `tour_overview` | 출처별 근거 제한 |
| `source_text` | 임베딩한 청크 본문 | `부모님과 식사하기 좋았어요.` | LLM 추천 근거 제공 |
| `source_url` | 원문 확인 URL | `https://blog.naver.com/...` | 사용자 출처 링크, 같은 글 판별(2순위) |
| `source_ref` | 청크 번호 없는 원본 문서 식별자 | 블로그 URL, `a:작성자|2026-09-01` | 같은 글 판별(3순위) |
| `document_id` | 전처리 문서 고유 ID | `doc_eb76253e...` | 같은 글 판별(1순위) |
| `published_at` | 원문 게시 시각(ISO 문자열) | `2026-08-01T13:00:00+09:00` | 최신 근거 우선 처리 |
| `rating` | Google 리뷰 별점 | `5` | 고평점 근거 필터 |
| `language` | 원문 언어 | `ko`, `mixed` | 언어별 품질 확인 |
| `chunk_index` | 원문 내 0부터 시작하는 청크 순번 | `2` | 원문 순서 복원 |
| `chunk_count` | 원문의 전체 청크 수 | `6` | 청킹 상태 확인 |
| `content_hash` | 전처리 원문 전체 SHA-256 | `bb51ffd5...` | 본문 변경 감지 |
| `embedding_version` | 모델·청킹 운영 버전 | `jhgan-evidence-120t-v8` | 옛 버전 정리. 종로구 구버전은 비어 있다 |

## 옮기지 않은 열

Supabase 테이블에 있던 다음 열은 서비스가 읽지 않아 Pinecone에 넣지 않았다. 테이블을
지우기 전에 로컬에 따로 백업했다(2026-10-19, 220,670행, 레코드 ID 규칙으로 짝을 맞출 수
있다).

| 필드 | 정의 | 값 |
| --- | --- | --- |
| `model_name` | 임베딩 모델명 | 전부 `jhgan/ko-sroberta-multitask` |
| `preprocessing_version` | 원문 정제 규칙 버전 | `naver-evidence-v3`, `rag-prechunk-1.6.0`, 종로구는 없음 |
| `is_translated` | Google 자동번역 여부 | true 3,042 / false 177,239 / 종로구는 없음 |
| `token_count` | jhgan 토크나이저 기준 청크 길이 | 종로구 외 180,281행 |
| `created_at` | DB 최초 적재 시각 | |
| `id` | DB 내부 행 식별자 | 종로구 레코드 ID(`row-{id}`)에만 남아 있다 |

## 적재 원칙

- 신규 레코드는 `document_id`, `chunk_id`, `content_hash`, 임베딩 버전을 채운다.
- 같은 `chunk_id`가 서로 다른 장소에 나오면 적재하지 않는다.
- 청킹 조건이 바뀐 지역구를 다시 넣을 때는 적재 스크립트의
  `--replace-existing --scope-content-ids <place_catalog.csv>`를 사용해 옛 버전을
  정리한다.
