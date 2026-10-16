# 취향 RAG 검색 품질 골드셋

임베딩 모델·청킹·Dense/Hybrid 검색·리랭커 조합을 동일한 폐쇄형 후보 풀에서 비교한다.
Agent Intent/조건 추출 평가는 형제 폴더인 `agent_quality/`가 담당하며, 이 폴더는 **취향
검색 순위만** 평가한다.

## 평가 범위

- 지역: 용산구(`170`)·성동구(`200`)
- 후보 장소: 55곳
- 문서: 네이버 블로그 근거문장 v3와 Google 리뷰 1,500건
- 취향: 사진 명소, 힐링하기 좋은, 색다른 경험, 조용한 곳, 넓고 쾌적한, 데이트 코스,
  아이와 함께, 부모님과 함께
- 정답: 55곳 × 8개 취향 = 440개 관련도 등급
- 관련도 `2`: 복수의 직접 근거 또는 매우 명확한 방문 근거
- 관련도 `1`: 단일 후기, 조건부 상황 또는 약한 직접 근거
- 관련도 `0`: 근거 없음, 키워드만 등장, 다른 장소·의미 또는 부정 근거

이 평가는 55개 후보 안에서 조합을 비교하는 **폐쇄형 실험**이다. 서울 전체 검색의 절대
성능으로 해석하지 않는다.

## Dev와 Final

`evaluation_dev.csv`는 현재 **16개 질의(8개 취향 × 표현 2개)**다. 이미 모델과 청킹 방식
선택에 사용했으므로 개발셋으로 분류한다. 모델·청킹·검색 로직을 고치는 동안 반복 실행한다.

`evaluation_final.csv`는 헤더만 있는 봉인용 파일이다. 기존 결과를 보지 않고 새 표현으로
최소 8개, 가능하면 16개 질의를 만든 뒤 최종 변경 직전에만 실행한다. Final 결과를 본 뒤
방식을 다시 조정하면 평가 과적합이므로 다시 Dev로 돌아가야 한다.

`qrels.csv`는 문장 표현이 아니라 `취향 × 장소` 점수이므로 Dev와 Final이 함께 사용한다.

## 파일

| 파일 | 역할 |
| --- | --- |
| `evaluation_dev.csv` | 개발 중 반복 실행하는 16개 평가 질의 |
| `evaluation_final.csv` | 아직 작성하지 않은 최종 봉인 질의 |
| `candidate_places.csv` | 공통 검색 후보 55곳 |
| `qrels.csv` | 장소 55 × 취향 8의 최종 관련도 440행 |
| `label_evidence.csv` | 정답 판정 근거·URL 감사 자료 |
| `review/qrels_human_review.csv` | 사람이 정답을 검토할 때 보는 한국어 표 |
| `fixtures/evaluation_corpus.csv` | 청킹·임베딩 대상 네이버/Google 문서 1,500건 |
| `history.csv` | 실행별 최고 nDCG 조합의 요약 이력 |
| `runs/` | 실행별 보고서·지표·검색 결과 |

`fixtures/evaluation_corpus.csv`의 `embedding_text` 문단은 실제 개행 대신 `\\n` 문자열로
보존되어 있다. 로딩 후 `str.replace('\\\\n', '\\n')` 방식으로 복원한다.

## 지표

- **Precision@5**: 상위 5곳 중 관련도 1점 이상 장소의 비율
- **Strict Precision@5**: 상위 5곳 중 강한 근거인 2점 장소의 비율
- **nDCG@5**: 2점 장소가 1점 장소보다 상단에 나오는지 평가

Recall은 취향별 전체 정답 수가 다르고 후보 풀 자체가 표본이므로 핵심 지표에서 제외한다.

## 실행 흐름

### 1. 골드셋 계약만 검사

```bash
cd backend
.venv/bin/python -m scripts.evaluate_preference_retrieval --split dev --dry-run
```

질의 수, 후보 수, qrels 완전성, 0/1/2 점수, 코퍼스의 후보 장소 커버리지를 검사한다.

### 2. Colab에서 네 조합 실행

참조 노트북:

```text
docs/reference/tripbranch_rag_preference_retrieval_evaluation_v1.ipynb
```

현재 비교 조합은 다음과 같다.

1. `A`: jhgan · 구조적 120토큰 · Dense
2. `B`: jhgan · 시멘틱 120토큰 · Dense
3. `C`: jhgan · 구조적 120토큰 · Hybrid + Reranker
4. `D`: Qwen3 · 구조적 120토큰 · Dense

노트북 마지막 셀에서 `tripbranch_preference_eval_v1.zip`을 다운로드한다.

### 3. 결과를 프로젝트 이력으로 등록

```bash
cd backend
.venv/bin/python -m scripts.evaluate_preference_retrieval \
  --split dev \
  --label jhgan-qwen-chunk-search-v1 \
  --results "/Users/본인계정/Downloads/tripbranch_preference_eval_v1.zip"
```

ZIP 대신 압축을 푼 폴더나 `rankings_top5.csv`를 직접 넘겨도 된다. ZIP 안에
`build_timing.csv`와 `search_timing.csv`가 있으면 구축 시간과 평균·P95 검색 시간도 함께
기록한다.

점검용으로 일부 질의만 평가하려면 다음처럼 실행한다.

```bash
.venv/bin/python -m scripts.evaluate_preference_retrieval \
  --split dev --limit 2 --results "/다운로드/결과.zip"
```

## 실행 결과 읽는 법

실행 폴더 이름에는 시각·split·실험명·질의 수·골드셋 해시가 들어간다.

```text
runs/2026-09-17_1430_dev_jhgan-qwen-chunk-search-v1_16queries_a83f1c2d91ef/
```

| 파일 | 읽는 방법 |
| --- | --- |
| `report.md` | 가장 먼저 열어 조합별 평균과 해석 기준을 확인 |
| `summary.json` | 장표·자동화가 읽는 실행 설정과 지표 |
| `metrics_summary.csv` | 조합별 평균 품질·시간 |
| `metrics_by_query.csv` | 어떤 취향·표현에서 성능이 갈리는지 확인 |
| `rankings.csv` | 상위 장소와 실제 근거 청크를 눈으로 검토 |
| `config.json` | 사용한 split·해시·원본 결과 경로 확인 |

`history.csv` 비교는 **같은 split과 같은 dataset_digest**끼리만 한다. 골드셋이 바뀌면
점수 변화가 검색 방식 때문인지 정답 변경 때문인지 구분할 수 없기 때문이다.

## 운영 DB 평가와의 구분

이 스크립트는 Colab에서 생성한 고정 코퍼스 결과를 재채점하고 이력화한다. 실제 Supabase
`place_embeddings`와 `search_place_evidence` RPC의 배포 상태·임베딩 누락·운영 임계값은
별도 통합 테스트 대상이다. 품질 비교에서는 임계값으로 결과를 잘라내지 말고 전체 후보의
상대 순위를 평가해야 하므로 `min_similarity=0.0`에 해당하는 결과를 사용한다.
