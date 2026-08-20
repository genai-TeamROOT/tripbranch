# RECOMMEND Prompt History

## 현재 활성 슬롯

| 슬롯 | 관리 버전 | 템플릿 | 공유 규칙 |
| --- | --- | --- | --- |
| recommend.extract | v2 | extract.md, location_rules.md, place_tag_rules.md | budget, weather, concentration, environment |
| recommend.summary | v1 | summary_instruction.md | persona, factuality |

## 승인 이력

| 기준선 | 날짜 | 커밋 | 슬롯·의존성 | 변경 내용 | 변경 이유 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| legacy-1.0.3 | 2026-08-06 | `0bfdcfc` | `recommend.extract` | RECOMMEND 추출에 실내외 환경 규칙 보강 | 위치 변경 뒤 environment 조건 소실 방지 | 승인됨 |
| legacy-1.0.5 | 2026-08-07 | `bfad75f` | `recommend.summary` | 추천 카드 요약 생성 슬롯 신설 | 카드 목록을 짧은 자연어 말풍선으로 소개 | 승인됨 |
| legacy-1.0.9 | 2026-08-10 | `86a9cd1` | `recommend.extract` | 위치 되묻기와 검색 중심점 유지 규칙 보강 | TP-67 후속 | 승인됨 |
| legacy-1.0.13 | 2026-08-18 | `585a045` | 공유 weather/concentration/environment | 비·혼잡·야외 허용 표현을 조건 완화로 분류 | 후보를 불필요하게 좁히거나 재정렬하는 문제 방지 | 승인됨 |
| 1.0.17 | 2026-08-19 | `3b991bf` | `recommend.extract` (v1 → v2) | 취향 발화를 `taste_query`로 분리 추출 | 취향 근거 벡터 검색 질의로 쓴다. `special_requirements`는 일정·교통 조건이 섞여 그대로 임베딩하면 오탐이 난다 — 비취향 발화 6건이 취향 근거를 찾아냈고(최대 "3시간 안에 다녀올 수 있는 곳" 0.523 · 150곳 중 19곳 통과), 이는 진짜 취향 발화 "친구들이랑 시끌벅적"(0.498)보다 높다. **분리 후 같은 6건이 전부 `null`이 됐다(6 → 0)** | 실 LLM 검증 14/14 통과(`scripts/verify_taste_query_extraction.py`), PR 검토 대기 |

> 슬롯 버전(`meta.yaml`)과 전역 `PROMPT_VERSION`(`app/providers/gemini_prompts.py`)은
> 함께 올린다. 전역 버전은 6개 인텐트가 공유하므로 어느 슬롯이 바뀌었는지는 이 표가
> 기록한다.

## 결정 근거

### 1.0.17 — `taste_query` 분리 (2026-08-19)

**측정 조건**: 종로 4개 중심점(경복궁·종각·혜화·부암동) x 발화 20개, 후보 150곳,
컷값 0.43. 원자료 `backend/test_results/taste_score_distribution.csv`,
스크립트 `backend/scripts/measure_taste_score_distribution.py`.

**문제**: 비취향 발화가 취향 근거 검색을 통과한다(경복궁, 150곳 기준).

| 발화 | 유사도 | 컷 통과 |
| --- | --- | --- |
| 3시간 안에 다녀올 수 있는 곳 | 0.523 | 19곳 |
| 지하철역에서 가까운 곳 | 0.530 | 11곳 |
| 반나절 코스로 짜줘 | 0.481 | 8곳 |
| (참고) 친구들이랑 시끌벅적 — **진짜 취향 발화** | 0.498 | 3곳 |

**바꾸지 않은 대안**

| 안 | 기각 이유 |
| --- | --- |
| 컷값을 0.52로 올려 오탐을 줄인다 | 실측이 반증한다 — 일정 발화 3건은 걸러지지만 진짜 취향 발화("친구들이랑 시끌벅적" 0.498, "빈티지 레트로" 0.521)가 **먼저 죽는다** |
| D가 정규식으로 일정 키워드를 제외한다 | 새 표현에 취약하다. LLM이 이미 문장을 읽고 있는데 뒤에서 다시 거를 이유가 없다 |
| `special_requirements`를 그대로 쓴다 | 그 필드가 "기타 전부"를 받는다 — 실측값이 전부 일정 관련이었다(반나절 코스 9건 등) |
| `taste_query`를 리스트로 둔다 | 여러 문장을 합치면 임베딩이 뭉개진다. 한 문장 = 한 질의다 |

**개선 수치**: 비취향 발화 6건의 `taste_query`가 **6건 → 0건**. 혼합 발화에서는
취향만 남는다 — "3시간 안에 갈 수 있는 조용한 카페" → `조용한`,
"지하철역 가까우면서 분위기 좋은 곳" → `분위기 좋은`.
실 LLM 검증 14/14 통과(`gemini-3.5-flash-lite`).

**한계**: 모델 1종·발화 14개뿐이고, LLM은 비결정적이라 한 번 통과가 항상
통과를 뜻하지 않는다. MODIFY로 취향을 수정하는 경로는 아직 보지 않았다.

공유 규칙의 원문 이력은 [`_shared/HISTORY.md`](../_shared/HISTORY.md)에서 관리합니다.
