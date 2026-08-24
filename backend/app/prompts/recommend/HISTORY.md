# RECOMMEND Prompt History

## 현재 활성 슬롯

| 슬롯 | 관리 버전 | 템플릿 | 공유 규칙 |
| --- | --- | --- | --- |
| recommend.extract | 2.3.0 | extract.md, location_rules.md, place_tag_rules.md | budget, weather, concentration, environment, transport |
| recommend.summary | v1 | summary_instruction.md | persona, factuality |

## 승인 이력

| 기준선 | 날짜 | 커밋 | 슬롯·의존성 | 변경 내용 | 변경 이유 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| legacy-1.0.3 | 2026-08-06 | `0bfdcfc` | `recommend.extract` | RECOMMEND 추출에 실내외 환경 규칙 보강 | 위치 변경 뒤 environment 조건 소실 방지 | 승인됨 |
| legacy-1.0.5 | 2026-08-07 | `bfad75f` | `recommend.summary` | 추천 카드 요약 생성 슬롯 신설 | 카드 목록을 짧은 자연어 말풍선으로 소개 | 승인됨 |
| legacy-1.0.9 | 2026-08-10 | `86a9cd1` | `recommend.extract` | 위치 되묻기와 검색 중심점 유지 규칙 보강 | TP-67 후속 | 승인됨 |
| legacy-1.0.13 | 2026-08-18 | `585a045` | 공유 weather/concentration/environment | 비·혼잡·야외 허용 표현을 조건 완화로 분류 | 후보를 불필요하게 좁히거나 재정렬하는 문제 방지 | 승인됨 |
| 1.0.17 | 2026-08-19 | `3b991bf` | `recommend.extract` (v1 → v2) | 취향 발화를 `taste_query`로 분리 추출 | 취향 근거 벡터 검색 질의로 쓴다. `special_requirements`는 일정·교통 조건이 섞여 그대로 임베딩하면 오탐이 난다 — 비취향 발화 6건이 취향 근거를 찾아냈고(최대 "3시간 안에 다녀올 수 있는 곳" 0.523 · 150곳 중 19곳 통과), 이는 진짜 취향 발화 "친구들이랑 시끌벅적"(0.498)보다 높다. **분리 후 같은 6건이 전부 `null`이 됐다(6 → 0)** | 실 LLM 검증 14/14 통과, 실 서버 왕복 확인 완료, PR 검토 대기 |
| 2.1.0 | 2026-08-20 | `8ce0ad4` | `recommend.extract` (2.0.0 → 2.1.0), 공유 `_shared/rules/transport.md` 신설 | "차로"/"걸어서"/"대중교통으로" 등 표현을 transport=car/walk/public로 매핑하는 구체 규칙과 예시 추가. 기존엔 "명시적으로 언급된 것만 채우고 나머지는 null"이라는 최소 지시뿐이었다. MODIFY와 매핑 규칙을 공유해야 해서 `_shared/rules/`에 둔다(같은 규칙이 두 곳에 있으면 한쪽만 바뀌었을 때 조용히 어긋난다) | TP-105(자동차 경로 네이버 실측, PR #196)로 D의 `to_travel_mode()`가 `transport=CAR`일 때 실제 자동차 provider를 호출하도록 이미 짜여 있었지만, 추출 프롬프트에 구체 매핑 규칙이 없어 이 조건이 채워질 근거가 약했다 — 상태 병합 경로(`_SINGLE_FIELDS`, `test_state_transform_field_coverage.py`)는 이미 통과 상태라 프롬프트만 비어 있었다 | 승인됨 — pytest 2137건 통과. 실 Gemini 골드셋 재현 발화(DEV-006 도보/DEV-007 자동차/FINAL-012 자동차+주차) 전건 통과. 같은 골드셋을 변경 전 코드로 재실행(베이스라인)해 비교한 결과, 다른 케이스의 통과/실패가 매번 다르게 흔들려 LLM 비결정성으로 확인 — 이 변경이 다른 필드 추출에 부작용을 준다는 증거 없음 |
| 2.2.0 | 2026-08-21 | `82a6af0` | `recommend.extract` (2.1.0 → 2.2.0) | 혼잡도 표현(조용한·한적한·붐비는·북적이는·시끌벅적)을 `taste_query`에서 제외하고 `concentration_intent` 전용으로 둠. 대표 예시 "혼자 조용히 쉴 만한" 교체 | "조용한/한적한" 발화가 `taste_query`와 `concentration_intent=AVOID`를 동시에 채워, 한 선호가 두 축에서 가중치 0.30(0.15+0.15)을 가져가던 것을 막는다(단일축 선호는 0.15) | 실 LLM 2회 검증(혼잡도 단어 누출 0/6), PR #206으로 develop 머지 완료 |
| 2.3.0 | 2026-08-21 | `5d65b7c` | `recommend.extract` (2.2.0 → 2.3.0) | 2.2.0에서 뺐던 혼잡도 표현을 `taste_query`에 되돌림. `concentration_intent`와 co-fill 허용 | 2.2.0의 "이중 반영은 문제"라는 전제를 검증 없이 따랐던 것으로 판단 — concentration(실측/근접치 수치)과 taste(리뷰·블로그 근거)는 서로 다른 근거원이라 co-fill이 부당한 이중계산이 아니라 정당한 신호일 수 있다 | 실 LLM 2회 검증(co-fill 6/6, 일정·거리·예산·인원수 누출 0건), 다중 턴 회귀(dev 35건, 실패 4건 전부 기존 SCHEDULE 비결정성), 전체 테스트 통과·스냅샷 갱신, PR 대기 |
| 2.2.0 | 2026-08-21 | (커밋 대기) | `recommend.extract` (2.1.0 → 2.2.0) | 혼잡도 표현(조용한·한적한·붐비는·북적이는·시끌벅적)을 `taste_query`에서 제외하고 `concentration_intent` 전용으로 둠. 대표 예시 "혼자 조용히 쉴 만한" 교체 | "조용한/한적한" 발화가 `taste_query`와 `concentration_intent=AVOID`를 동시에 채워, 한 선호가 두 축에서 가중치 0.30(0.15+0.15)을 가져가던 것을 막는다(단일축 선호는 0.15) | 실 LLM 2회 검증(혼잡도 단어 누출 0/6), 전체 테스트 통과·스냅샷 갱신, 커밋·PR 대기 |
| 2.3.0 | 2026-08-22 | (커밋 대기) | `recommend.extract` (2.2.0 → 2.3.0) | `location_rules.md`에 `travel_origin` 규칙 신설. "~~에서/까지 N분"처럼 조사가 이동시간의 출발점을 확정하는 발화만 `travel_origin="search_center"`로 채우고, "~~ 근처/주변"이나 조사 없는 발화는 그대로 null로 둔다 | "안국역에서 10분"과 "안국역 근처에 10분"이 지금까지 `search_center`만 같게 추출돼 랭킹 기준점을 구분할 수 없었다(D-067은 구분이 없는 상태의 기본값만 정한 것이라 한쪽은 항상 틀렸다). 새 필드로 문법이 이미 확정하는 케이스만 자동 처리하고, 조사 없는 소수 케이스는 필드를 비워 기존 기본값(D-067)이 그대로 적용되게 둔다 | 승인됨 — pytest 2283건 통과, 스냅샷 갱신. 실 LLM 검증(`scripts/verify_travel_origin_extraction.py`, `gemini-3.5-flash-lite`) 2회 실행 16/16 통과 — "~에서/까지"류 3건 전부 `search_center`, "근처/주변/가려는데"·조사 없음·시간 미언급 5건 전부 `null`. 골드셋에 이 패턴이 없어 신규 발화로 검증함 |

> 슬롯 버전(`meta.yaml`)과 전역 `PROMPT_VERSION`(`app/providers/gemini_prompts.py`)은
> 함께 올린다. 전역 버전은 6개 인텐트가 공유하므로 어느 슬롯이 바뀌었는지는 이 표가
> 기록한다.

## 결정 근거

### 2.3.0 — 혼잡도 단어를 `taste_query`에 되돌린다 (2026-08-21)

**측정**: `scripts/verify_taste_query_extraction.py`(겹침 6 + 취향 14 + 대조군 3),
`gemini-3.5-flash-lite`, 2회 실행.

**변경**: 2.2.0에서 뺐던 혼잡도(조용한·한적한·붐비는·북적이는·시끌벅적) 표현을
`taste_query`에 다시 넣는다. `concentration_intent`와 동시에 채워지는 것도
허용한다.

**왜 되돌리나**: 2.2.0은 "한 선호가 두 축에서 가중치 0.30을 가져가는 게 문제"라고
전제했는데, 그 전제 자체를 검증한 적이 없었다. 다시 보니:
- concentration은 실측/근접치 혼잡 수치, taste는 리뷰·블로그 문장의 의미
  유사도로 **서로 다른 근거원**이다. 같은 결론("조용하다")에 수렴해도 이중
  계산 오류가 아니라 서로 다른 근거가 확인해 주는 관계에 가깝다.
- 사용자가 "조용한"이라고만 말한 발화라면 그 선호에 0.30이 실리는 건 오히려
  의도대로다.

| 지표 | 2.2.0(적용 전) | 2.3.0(적용 후) |
| --- | --- | --- |
| 겹침 발화의 혼잡도·취향 co-fill | 0/6 (금지됨) | **6/6** |
| 대조군(순수 혼잡도 발화)의 taste_query | null | 채움("붐비는", "사람 많고 활기찬") |
| 일정·거리·예산·인원수 조건 누출 | 0/17 | **0/17** (2회 재현) |

일정·거리 조건은 여전히 taste_query에 섞이지 않는다 — 바뀐 건 혼잡도 단어의
취급뿐이다.

**바꾸지 않은 것**: "조용한 카페 + 저렴한 곳"처럼 여러 조건이 같이 오는
복합 발화에서 조용함이 다른 조건 대비 부당하게 과대 반영되는지는 이번에
측정·수정하지 않는다. 실측 없이 판단하지 않는다는 원칙에 따라 열린 질문으로
남긴다.

**다중 턴 회귀**: `scripts.evaluate_agent_quality --split dev`(35건)을 변경 후
재실행 — Intent Accuracy 100%·Macro F1 1.000·조건 필드 정확도 93.2%. 실패 4건
(DEV-008·009·023·033)은 전부 `search_center`/`time_available`(SCHEDULE 전용)
불일치이고, 변경 전 베이스라인(2026-08-20 실행)에서도 DEV-008·009·023이 동일하게
실패했다 — `taste_query`/`concentration_intent`와 무관한 기존 LLM 비결정성이다.
케이스 통과율은 오히려 +2.86%p 올랐다(직전 대비 자동 비교, `history.csv`).

**한계**: 모델 1종·2회 실행. LLM은 비결정적이라 두 번 통과가 항상 통과를 뜻하지
않는다. MODIFY로 취향을 수정하는 경로는 아직 보지 않았다.
### 2.3.0 — 이동시간 출발점(`travel_origin`) 규칙 신설 (2026-08-22)

**문제**: `location_rules.md`가 "~~ 근처/주변/가려는데" 또는 지명 단독을 전부
`search_center`로 묶는데, "~~에서"/"~~까지"로 출발점을 확정하는 발화를 구분하는
규칙이 없었다. "안국역에서 10분"과 "안국역 근처에 10분"이 `search_center="안국역"`
으로 똑같이 추출돼, 이동시간의 채점 기준점(`domain/ranking_origin.py`)이 둘 중
하나를 전역으로 골라야 했다 — D-067(기준점=사용자 위치)이 후자를 맞추고 전자를
틀리게 만들었고, 그 전에는 반대였다. 구분 자체가 없어 둘 다 맞을 방법이 없었다.

**바뀐 것**: `UserConditions`에 `travel_origin`(`user_location` | `search_center`
| null) 필드를 추가하고, 조사가 출발점을 확정하는 발화만 `"search_center"`로
채우도록 `location_rules.md`에 규칙을 추가했다. `resolve_ranking_origin()`이
이 값을 사용자 위치 우선 규칙보다 먼저 확인하고, `_distance_denominator_offset_km()`
도 이때 0.0을 반환하도록 맞췄다(D-071).

**바꾸지 않은 것**: "근처/주변" 케이스의 기본값(D-067)은 그대로 둔다. 조사 없이
애매한 소수 발화("안국역 10분 거리")는 이 필드를 비워 기본값에 맡긴다 — 애매한
케이스까지 이 필드로 강제 판정하지 않는다.

**검증**: 골드셋(`test_results/intent_classification_results.csv`)에 "~~에서
N분" 패턴 사례가 없어 회귀 기준이 없었다 — `scripts/verify_travel_origin_extraction.py`
로 신규 발화 8건(조사 확정 3 + 근처/주변/가려는데 3 + 조사 없음 1 + 시간 미언급 1)을
만들어 `gemini-3.5-flash-lite` 2회 실행, 16/16 통과.

**한계**: 모델 1종·발화 8개뿐이고, LLM은 비결정적이라 두 번 통과가 항상 통과를
뜻하지 않는다. MODIFY로 travel_origin을 사용자가 직접 바꾸는 경로는 아직 보지
않았다.

### 2.2.0 — 혼잡도 단어를 `taste_query`에서 분리 (2026-08-21)

**측정**: `scripts/verify_taste_query_extraction.py`(겹침 6 + 취향 14 + 대조군 3),
`gemini-3.5-flash-lite`, 2회 실행.

**문제**: `concentration_intent`(`_shared` 공유 규칙)와 `taste_query`(RECOMMEND
전용)가 같은 단어를 공유해, "조용한/한적한" 발화가 두 필드를 동시에 채웠다.
2.1.0까지의 대표 예시 "혼자 조용히 쉴 만한 곳 → 혼자 조용히 쉴 만한"이 그 동작을
가르치고 있었다. 취향 대표 예시·대조군 SEEK("사람 많고 활기찬")까지 번졌다.

| 지표 | 2.1.0(적용 전) | 2.2.0(적용 후) |
| --- | --- | --- |
| 겹침 발화의 혼잡도 단어 누출 | 6/6 | **0/6** |
| co-fill(두 축 동시) | 6/6 | 2/6 |
| 순수 혼잡도 발화 → `taste_query` | 채움 | **전부 null** |

한 선호가 두 축에서 0.30(0.15+0.15)을 가져가던 것을, 혼잡도 단어를
`concentration_intent` 한 축(0.15)으로 되돌렸다. 진짜 취향이 함께 있으면
그것만 taste로 남는다 — "한적하고 감성적인" → `taste_query="감성적인"`.
그래서 co-fill 2/6은 왜곡이 아니라 정당한 2축 케이스다.

**바꾸지 않은 것**: `_shared/rules/concentration_intent.md`(MODIFY 공용)는
건드리지 않았다. "조용한"이 AVOID를 켜는 것은 옳은 동작이고, taste가 그 단어를
메아리치지 않게만 좁혔다.

**한계**: 모델 1종·2회 실행. LLM은 비결정적이라 한 번 통과가 항상 통과를 뜻하지
않는다. MODIFY로 취향을 수정하는 경로는 아직 보지 않았다.

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

**추출만으로는 끝이 아니었다 (2026-08-20)**: 실 서버에서 확인해보니 `llm_output`에는
`taste_query`가 들어오는데 `state.user_conditions`에서는 `null`이었다. 조건 필드를
스키마 3곳(A/B/C)과 `field_spec.py`에 넣었는데도
`services/interpret/state_transform._SINGLE_FIELDS`라는 **하드코딩 목록**을 놓쳐서,
Operation이 만들어지지 않아 상태 병합에서 값이 사라졌다.

프롬프트가 아무리 정확히 뽑아도 그 뒤 경로가 하나라도 비면 **조용히 사라진다.**
새 조건 필드를 추가할 때 손대야 하는 곳은 다음 다섯이다.

| 파일 | 역할 |
| --- | --- |
| `app/prompts/recommend/extract.md` | 추출 규칙 |
| `app/schemas.py` | A↔D 조건 |
| `app/agent_context/schemas.py` | A↔C Context |
| `app/state/schema.py` + `field_spec.py` | B 상태 저장 |
| `app/services/interpret/state_transform.py` | **조건 → 상태 Operation 변환** |

마지막이 목록 기반이라 잊기 쉽다. `tests/test_state_transform_field_coverage.py`가
스키마와 목록의 동기화를 검사하므로, 다음부터는 테스트가 먼저 잡는다.

공유 규칙의 원문 이력은 [`_shared/HISTORY.md`](../_shared/HISTORY.md)에서 관리합니다.
