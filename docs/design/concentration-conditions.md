
# 혼잡도(Concentration) 조건 설계

## 문서 정보

| 항목 | 값 |
|------|-----|
| 버전 | v0.4 |
| 상태 | 초안 (Draft) |
| 최종 수정 | 2026-07-29 |
| 소유 | A (Agent Runtime) |
| 관련 코드 | `backend/app/concentration_policy.py`, `backend/app/domain/scoring.py`, `backend/app/agent_context/enrichment_service.py`, `backend/app/state/field_spec.py` |

---

## 1. 목적과 배경

관광지 혼잡도를 사용자에게 노출하는 요청은 형태가 다른 두 가지로 들어온다.

1. **여러 후보 중에서** 혼잡도 방향을 반영해 추천해달라는 요청 — "핫한 관광지 어디야", "조용한 공원 추천해줘"
2. **특정 장소 하나**의 혼잡도를 묻는 요청 — "이번 주말 창덕궁 사람 많을까?"

전자는 여러 후보를 비교·정렬하는 문제이므로 RECOMMEND의 조건(Condition) 확장으로,
후자는 단일 장소에 대한 질의응답이므로 INFO의 질문 유형(`question_type`) 확장으로
각각 처리한다. 판별 복잡도와 응답 속도를 이유로 별도의 Intent는 만들지 않는다
([intent-definition.md](./intent-definition.md) 판별 규칙 재사용).

데이터 소스는 **한국관광공사 관광지 집중률 예측 API**(`get_concentration` Tool,
[tool-intelligence-contract-v1.md §6.5](./tool-intelligence-contract-v1.md#65-get_concentration))만
우선 사용한다. 서울시 실시간 혼잡도 API(카페·음식점 등 업종별 실시간 데이터)는
이번 범위 밖이며 §8에 TODO로 남긴다.

이 문서가 다루지 않는 것: `place_types`/`place_tags` 등 기존 Conditions 필드의
전체 정의(→ [conditions-schema.md](./conditions-schema.md) 소유), Scoring 가중치
공식의 최종 확정(→ [recommendation-scoring.md](./recommendation-scoring.md), D 확인 필요).

---

## 2. RECOMMEND 확장 — `concentration_intent`

### 2.1 필드 정의

`UserConditions`에 15번째 필드로 추가한다. `weather_intent`와 완전히 동일한 패턴이다.

```typescript
concentration_intent: "AVOID" | "SEEK" | "IGNORE" | null;
```

| 값 | 의미 | 예시 입력 | 추천 정책 |
|----|------|-----------|-----------|
| `AVOID` | 혼잡한 곳을 피하고 싶음 | "조용한 공원 추천해줘", "한적한 곳 가고싶어", "사람 없는 데" | `concentration` Feature: 집중률 낮을수록 고득점 |
| `SEEK` | 혼잡한(인기 있는) 곳을 원함 | "핫한 관광지 어디야", "인기 많은 곳 추천해줘", "사람 많고 북적이는 데" | `concentration` Feature: 집중률 높을수록 고득점 |
| `IGNORE` | 혼잡도 무관 | 혼잡도 관련 언급 없음 | `concentration` 가중치 제외 (재분배) |
| `null` | 판별 불가 | 혼잡도 관련 단어는 있으나 방향이 모호함 (드묾) | `IGNORE`와 동일하게 처리 |

**`weather_intent`와의 차이점**: `weather_intent`의 `null`은 `environment`(indoor/outdoor)
하드 필터를 결정하지 못해 사용자에게 추가 질문을 한다
([int-01-recommend.md §8](./int-01-recommend.md#8-weather_intent-판별)). `concentration_intent`는
하드 필터에 관여하지 않고 Scoring 가중치에만 영향을 주므로, `null`도 `IGNORE`와 동일하게
가중치만 제외하고 **추가 질문 없이 진행**한다 — concentration은 순위 조정용 Feature일
뿐 후보군 자체를 바꾸지 않기 때문이다.

### 2.2 데이터 확보 시점 — 초기 Context 요청으로 이동

**(초안 수정 — v0.3까지의 §2.2는 아래 내용으로 대체한다.)** concentration이
Scoring 가중치에 반영되어 **순위 자체를 바꾸는** 이상(§2.3), 기존에 설계돼 있던
"D가 1차 점수 계산 후 상위 후보만 C에 별도로 보강 요청"하는 방식
([a-c-context-contract-draft.md §5.2](./a-c-context-contract-draft.md), 기존
`CandidateEnrichmentRequest`/`Response` 계약)은 이번 용도에 맞지 않는다는 걸
뒤늦게 확인했다 — 그 계약은 D가 순위를 이미 확정한 **뒤에** 상위 5개만 보강하도록
설계됐고, 원래 "표시용 정보만 덧붙이고 순위는 바꾸지 않는다"는 전제였다
([a-c-context-contract-draft.md §5.2.3](./a-c-context-contract-draft.md)). 순위
계산 **전에** 데이터가 있어야 하는 이번 요구에는 그 경로가 구조적으로 맞지 않는다.

대신 concentration은 weather/places/holidays와 마찬가지로 **초기 Context 요청**
단계에서 확보한다. 별도 플래그도 새로 필요 없다 — `conditions.concentration_intent`
자체가 이미 초기 `AgentContextRequest.conditions`
([a-c-context-contract-draft.md §4.1](./a-c-context-contract-draft.md#41-스키마))에
실려 가므로, C는 이 값만 보고 concentration 포함 여부를 판단할 수 있다.

```
concentration_intent가 AVOID/SEEK (초기 요청의 conditions에 이미 포함됨)
  → C가 초기 Context 응답(location/weather/places/holidays)에
    concentration을 추가로 담아 반환 (§4.1 — 지역 단위 1회 조회로 후보
    전체를 커버, 후보별 재조회 불필요)
  → A는 이 concentration 데이터를 그대로 D의 Scoring 호출에 전달
  → D는 여전히 1회만 호출된다 (기존 run_agent_flow() 구조 유지, §1.1/§4.3)
```

**D는 여전히 1회만 호출된다는 결론은 같지만, 근거가 바뀌었다.** "D 호출 → 상위
후보만 C 재조회"가 아니라 **"C 조회(1회, 확장된 초기 응답) → D 호출(1회)"로 순서
자체가 바뀐다**는 점이 기존 [agent-runtime-contract.md §6](./agent-runtime-contract.md)
2단계 호출 설계와의 핵심 차이다 (갱신 내용은 §6 참고).

**기존 `CandidateEnrichmentRequest`/`Response`(post-ranking, 상위 5개 한정, 표시
전용)는 폐기하지 않는다.** "순위에는 반영하지 않고 설명에만 쓰는" 다른 보강
Feature가 생기면 그대로 유효한 경로다. 이번 `concentration_intent` 경로는 그
계약을 재사용하지 않고 초기 Context 응답 확장이라는 별도 경로를 쓴다는 뜻이다.

### 2.3 Scoring 반영 개요

D의 Scoring(`backend/app/domain/scoring.py`)에 `concentration` Feature를 추가한다.
가중치 값과 점수 변환 공식의 상세 설계는
[recommendation-scoring.md](./recommendation-scoring.md)에 "A 제안 초안"으로 반영하고
D 확인을 받는다(D 소유 문서). 이 절에서는 코드 조사로 확인한 재사용 지점만 남긴다.

- 조사 결과 `DEFAULT_WEIGHTS`(`scoring.py:24`)와 `ScoringCandidate` 모델 어디에도
  concentration 관련 키/필드가 없다 — 완전히 새로 추가하는 Feature다
  (`scoring.py:13` docstring에도 "TODO: 혼잡도 Feature ... v2 이후"로 명시돼 있었음).
- `concentration_intent`가 `null`/`IGNORE`면 계산하지 않는다 → `missing_features`에
  `"concentration"`을 추가 → 기존 `redistribute_weights()`(`scoring.py:111`)가 그대로
  나머지 가중치를 재분배한다. 이 함수는 Feature 이름에 무관하게 동작하는 범용
  구현이라 weather/remaining_operating_time 결측과 동일한 경로를 재사용할 수 있다.
- `concentration_intent`가 `AVOID`/`SEEK`면 C가 **초기 Context 응답**(§2.2)에
  담아 돌려주는 `concentration_rate`(0~100대 상대 비율)를 0~1 점수로 변환한다.
  방향은 AVOID면 낮을수록, SEEK면 높을수록 고득점. 점수 변환을
  `concentration_policy.py`의 4단계(`quiet`/`normal`/`slightly_crowded`/`crowded`,
  임계값 20/50/70%) 구간 기준으로 할지, `concentration_rate` 원본을 선형 정규화할지는
  아직 미정 — recommendation-scoring.md에서 D와 함께 확정한다.
- 후보별로 concentration 값이 없으면(해당 후보가 집중률 데이터셋에 없음)
  weather/remaining_operating_time과 동일하게 **후보별 개별 결측**으로 처리한다
  (해당 후보만 concentration 가중치 재분배, 전체 실행을 막지 않음).

---

## 3. INFO 확장 — `question_type: "concentration"`

### 3.1 정의

[int-02-info.md §6](./int-02-info.md#6-question_type-정의) enum에 추가한다.

| `question_type` | 정의 | 예시 입력 | 필요 API |
|---|---|---|---|
| `concentration` | 특정 장소/지역의 방문객 혼잡도 예측 | "사람 많아?", "붐빌까?", "혼잡해?" | `get_concentration` (집중률 API) |

### 3.2 `visit_time` 필드

`InfoQuery`에 선택 필드를 추가한다 (`question_type === "concentration"`일 때만 사용,
다른 유형에는 쓰지 않음):

```typescript
visit_time: string | null;  // YYYY-MM-DD, concentration 질의 전용
```

**파싱 규칙**: "오늘"/명시 없음 → 오늘 날짜, "내일" → 내일 날짜, "이번 주말" → 돌아오는
토/일 중 가까운 날, "8월 3일"처럼 특정 날짜 언급 → 해당 날짜로 정규화.

**데이터 범위 (정정)**: TourAPI 집중률 예측은 **오늘부터 향후 약 30일치**를 제공한다.
`FakeConcentrationProvider`(`backend/app/providers/concentration.py:91`)는 테스트
편의상 어제/오늘/내일 3일치만 반환하도록 단순화돼 있어 실제 API 범위를 대표하지
않는다 — `visit_time`이 오늘+2일 이상인 시나리오를 테스트하려면 Fake를 확장하거나
별도 Fixture가 필요하다(§8 TODO). "이번 주말"처럼 30일 이내의 요청은 정상 지원
범위이며, 30일을 넘는 날짜는 API가 예측치를 갖고 있지 않으므로 `no_data`로 처리하고
§7의 fallback 문구를 사용한다.

장소 식별 로직은 기존 `place_context`(`explicit`/`from_recommendation`/
`from_conversation`, [int-02-info.md §5](./int-02-info.md#5-place_context-정의))를
그대로 재사용한다.

### 3.3 목적지 인근 관광지 대체 조회 (근접치 Fallback)

"용리단길 카페 사람 많을까?", "명동 식당 웨이팅 있을까?"처럼 집중률 API가 다루는
"관광지" 콘텐츠에 없는 개별 상점(카페·음식점 등)을 물으면, 그 상점 자체의 집중률은
구할 수 없다. 이 경우 목적지 질문 자체를 포기하지 않고 **목적지 근처의 가장 가까운
관광지 집중률로 대체 조회**해 참고 정보로 제공한다. (`decision-log.md` 하단 상태표의
미결 항목 "혼잡도 fallback: 장소 근접치·구 단위·Feature 제외" 중 **장소 근접치**
안을 채택하는 결정이다 — `decision-log.md` D-036으로 반영했다.)

**흐름:**

```
1. place_context로 대상 장소(예: "OO카페") 식별, 좌표 확보 (기존 로직 재사용)
2. get_concentration(place_name="OO카페", ...) 호출
3. status == "success" → 그대로 응답
4. status == "no_data" →
   a. search_nearby_places(location=대상 좌표, place_types=["attraction"], radius_km=1.0, limit=1)
      로 가장 가까운 관광지 탐색 (기존 Tool 재사용 — `NearbyPlaceDetailsTool`,
      backend/app/tools/nearby_place_details.py, tool-intelligence-contract-v1.md §6.2)
   b. 결과 있음 → 그 관광지 이름으로 get_concentration 재호출
      → 성공 시 "대체 조회"임을 명시해 응답
      → 그마저 no_data면 c로
   c. 결과 없음(반경 내 관광지 없음) 또는 대체 조회도 no_data → 순수 "데이터 없음" 응답
5. status == "unavailable" (API 장애) → 대체 조회로 넘기지 않고 일반 오류로 처리한다
   (데이터 커버리지 문제가 아니라 API 장애이므로 fallback으로 가릴 문제가 아니다)
```

**응답 원칙**: 대체 조회로 얻은 값은 반드시 "정확한 [상점명] 데이터가 아니라 인근
관광지 기준 추정"이라는 것을 명시한다.

> "OO카페 자체의 혼잡도 데이터는 없지만, 가장 가까운 관광지인 [명소명] 기준으로는
> 오늘 다소 혼잡한 편이에요. 비슷한 수준일 가능성이 있어요."

절대 "OO카페가 혼잡해요"처럼 대상 장소 자체의 값인 것처럼 단정하지 않는다 — 항상
"근처 [관광지] 기준" 문구를 포함한다.

**탐색 반경(`radius_km`)**: 기본값 1.0km를 제안한다. `search_nearby_places`의
시스템 기본값(`place_search_policy.py`의 `DEFAULT_PLACE_SEARCH_RADIUS_KM`)은
2.0km이지만, "근처 관광지"로 참고할 수 있는 신뢰도를 위해 이 fallback 전용으로는
더 좁게 잡는 게 안전하다고 판단했다. 정확한 값과 "관광지가 너무 멀면 대체 조회
자체를 포기할지"는 C/D와 함께 확정 필요(§8 TODO).

**RECOMMEND 쪽 적용 여부는 별도 확정 필요**: 이 절은 INFO(단일 장소 질의) 기준으로
설계했다. RECOMMEND에서도 `concentration_intent`가 있고 후보가 `restaurant`(카페·
음식점) 유형이면 같은 문제가 생기지만, 후보가 최대 5개인 배치 보강 흐름에 근접치
조회를 얹으면 후보당 API 호출이 최대 2배로 늘어난다. 이번 범위에 포함할지는 별도
결정 필요(§8 TODO).

---

## 4. Concentration API 요청 필드 설계

### 4.1 현재 구현된 요청 필드 (코드 확인)

Tool 계층(`ConcentrationQuery`, `backend/app/tools/concentration.py`)과 실제
TourAPI 호출(`RealConcentrationProvider`, `backend/app/providers/concentration.py`)을
조사한 결과는 다음과 같다.

| 필드 | 계층 | 필수 여부 | 비고 |
|---|---|---|---|
| `area_code` | Tool 요청 (`areaCd`) | 필수 (`ConcentrationQuery.__post_init__`에서 공백 검증) | 시도 코드 |
| `district_code` | Tool 요청 (`signguCd`) | 필수 (동일 검증) | 시군구 코드 |
| `place_name` | Tool 요청 (`tAtsNm`) | 선택 | 응답 필터링용 |
| 날짜 | 없음 | — | **API 요청 자체엔 날짜 파라미터가 없다.** 지역 코드로만 조회하면 API가 다중 날짜 예측치(향후 약 30일, §3.2)를 한 번에 반환하고, 원하는 날짜는 응답을 받은 뒤 클라이언트(C)가 직접 선택한다. |

**중요 발견 — `area_code`/`district_code`는 이미 종로구로 고정돼 있다.**
`enrichment_service.py`의 `_JONGNO_AREA_CODE`("11")/`_JONGNO_DISTRICT_CODE`("11110")가
모든 후보에 그대로 쓰인다. 이건 버그가 아니라 **시스템 전체의 MVP 범위 결정과
일치**한다 — `resolve_location` 자체가 이미 서울특별시 종로구 밖은 `unsupported`로
거부한다(`resolve_location.py:15,147`, 결정 근거 `decision-log.md` D-025). 즉
concentration 요청에 새 지역 코드 해석 로직을 추가할 필요가 없다 — 종로구 하드코딩을
그대로 재사용하면 된다.

**단, 이 전제 때문에 종로구 밖 장소를 다루는 INFO 질의는 `resolve_location` 단계에서
먼저 `unsupported`로 막힌다.** 지난 초안(§6)에 썼던 "잠수교"(서초구 인근)·"용리단길"
(용산구) 예시가 실제로는 이 경계에 걸린다는 걸 뒤늦게 확인해서, 아래 §6에서
종로구 내 장소로 바꾸고 이 경계 자체를 사례로 추가했다.

**§2.2 수정에 따른 `place_name` 사용법 변경**: 기존 `_enrich_candidate`는 후보마다
`place_name`을 채워 API를 후보 수만큼 반복 호출했다. 초기 Context 단계(§2.2)에서는
아직 개별 후보가 정해지지 않았거나(장소 검색과 병렬), 후보가 여러 개이므로
`place_name`을 **비워서 종로구 전체 관광지의 예측치를 한 번에 받아온 뒤**, C가
`places` Context의 각 후보 이름과 매칭하는 방식이 맞다. 지역 코드만으로 호출하면
`tAtsNm` 없이도 응답 자체는 이미 다건으로 온다(§4.1 표) — 코드 변경은 필요 없고
필터링 로직만 후보 매칭으로 바뀐다.

### 4.2 조회 기준일 — RECOMMEND는 불필요, INFO만 명시적 필드가 필요

**(초안 수정)** v0.2/v0.3에서는 `CandidateEnrichmentRequest`에 `reference_date`
필드를 추가하자고 제안했으나, §2.2 수정으로 그 계약 자체를 이번 경로에서 쓰지
않게 되면서 이 제안은 대상이 없어졌다. 날짜 확보 방식을 인텐트별로 다시 정리하면:

| 호출 경로 | 날짜 확보 방식 | 비고 |
|---|---|---|
| RECOMMEND (`concentration_intent`) | 명시적 필드 불필요 | 초기 Context 요청은 사용자 메시지를 처리하는 그 시점에 동기로 실행되므로, weather와 동일하게 C가 자신의 clock으로 "오늘"을 판단해도 된다 — weather도 `visit_at`을 명시적으로 안 받고 동일하게 동작한다([tool-intelligence-contract-v1.md §6.4](./tool-intelligence-contract-v1.md)) |
| INFO (`question_type=concentration`) | `visit_time`(§3.2)을 명시적으로 전달 | 오늘이 아닌 날짜를 조회하는 유일한 경우라 명시적 필드가 꼭 필요하다 |

INFO는 이 A↔C Context 계약(v0, RECOMMEND 전용 —
[a-c-context-contract-draft.md §3](./a-c-context-contract-draft.md#3-범위와-확장-원칙))의
대상이 아니다. INFO의 concentration 조회는 별도의 직접 Tool 호출 경로를 쓴다:
`GetConcentrationTool`을 직접 호출하고, 그 결과에서 원하는 날짜를 선택하는 로직에
`visit_time`을 파라미터로 넘긴다. 서버(C) 쪽에서 재사용할 수 있는 부분 — 날짜로
예측치 하나를 선택하는 로직은 이미
`_select_current_forecast(concentration, candidate_name, reference_date)`
(`enrichment_service.py:175`)로 구현돼 있고 `reference_date`를 파라미터로 받는
범용 함수다. 이 함수(또는 동등한 로직)를 INFO 경로에서도 재사용할 수 있도록 C가
공개 인터페이스로 노출하면 된다 — RECOMMEND 전용 서비스 내부에 갇혀 있을
필요는 없다.

### 4.3 그 외 필수 필드 점검

조사 범위에서 위 두 가지(지역 코드, 조회 기준일) 외에 추가로 필요한 필수 필드는
발견하지 못했다. `place_name`은 이미 선택 필드로 존재하고, 페이지네이션/포맷
파라미터(`pageNo`/`numOfRows`/`_type`)는 고정값이라 설계 대상이 아니다.

---

## 5. B 저장 필드 추가

`backend/app/state/field_spec.py`(코드)와 그 계약 문서
`backend/docs/package-b/agent-state-contract-v1.md`(B 소유 — 이번 조사에서 새로
발견했고, 기존 6개 수정 대상 목록에는 없던 문서)를 함께 확인했다. B의 조건 저장
구조는 `user_conditions`(14개 필드, `FIELD_SPECS`)와 `api_context`(`gps_location`/
`api_weather` + 각각의 `_updated_at`, `ApiContext` 모델) 두 갈래로 나뉜다.

### 5.1 `user_conditions`에 추가 — `concentration_intent`

`weather_intent`와 동일하게 `FIELD_SPECS`에 항목을 추가한다.

```python
"concentration_intent": _single("concentration_intent", str, OP_UPDATE, OP_REMOVE),
```

- 대상 코드: `backend/app/state/field_spec.py`의 `FIELD_SPECS` dict
- 대상 문서: `backend/docs/package-b/agent-state-contract-v1.md` §1.2(14개 필드
  표 → 15개로), §2.2(허용 연산 표) — B 소유 문서이므로 "A 제안, B 확인 필요"로 표시
- [conditions-schema.md](./conditions-schema.md)(A 소유, §2 필드 정의)에도 동일하게
  반영 — 같은 14개 필드를 서로 다른 소유권 각도에서 중복 기술하는 두 문서이므로
  **둘 다** 갱신 대상이다.

### 5.2 `api_context` 추가는 보류 — §4.2 수정으로 근거가 사라짐

**(초안 수정)** v0.2/v0.3에서는 `gps_location`/`api_weather` 패턴을 따라
`api_context.concentration_reference_date`를 추가하자고 제안했다. 그런데 §4.2를
RECOMMEND는 명시적 날짜 필드가 필요 없는 쪽으로 고치면서, "조회에 실제 사용한
날짜를 기록"할 근거 자체가 약해졌다. 게다가 concentration은 `gps_location`/
`api_weather`처럼 세션 내내 재사용하는 단일 스칼라 값이 아니라, RECOMMEND
실행마다 여러 관광지의 예측치를 새로 받아오는 목록형 데이터라 — `places`
Context와 성격이 더 가깝다(`places`도 `api_context`에 캐싱하지 않는다). 그래서
이번 범위에서는 `api_context` 추가를 제안하지 않는다. `user_conditions`의
`concentration_intent`(§5.1)만으로 충분하다고 판단했다 — 세션 재사용 캐싱이
실제로 필요해지면 그때 B와 별도로 설계한다.

---

## 6. 경계 사례

| 입력 | 판정 | 이유 |
|---|---|---|
| "핫한 관광지 어디야" | RECOMMEND (`concentration_intent=SEEK`) | 복수 후보 비교·추천 요청 |
| "인기 많은 공원 추천해줘" | RECOMMEND (`concentration_intent=SEEK`) | 복수 후보 비교·추천 요청 |
| "조용한 공원 추천해줘" | RECOMMEND (`concentration_intent=AVOID`) | 복수 후보 비교·추천 요청 |
| "이번 주말 창덕궁 사람 많을까?" | INFO (`question_type=concentration`) | 특정 장소 단일 질의, `visit_time`=이번 주말 |
| "인사동 카페 사람 많아?" | INFO (`question_type=concentration`) | 특정 장소 단일 질의 — 단, 카페 개별이 아니라 지역/관광지 단위 데이터로만 답변 (§7 한계 참고) |
| "경복궁 오늘 열어?" | INFO (`question_type=operating_hours`) | 운영시간 질문, concentration 아님 (대조군) |
| "이번 주말 잠수교 사람 많을까?" | INFO 시도 → `resolve_location`에서 `unsupported` | 종로구 밖 장소 — concentration 로직에 도달하기 전에 위치 해석 단계에서 이미 거부됨(D-025, §4.1) |

---

## 7. 데이터 한계와 응답 원칙

- **예측치이지 실시간이 아님**: 응답 생성 시 "지금 혼잡해요" 같은 실시간 단정 표현을
  쓰지 않고, "이번 주말엔 방문객이 많을 것으로 예측돼요" 같은 예측 표현을 쓴다.
- **관광지 단위 데이터**: API는 "관광지" 단위로만 예측치를 제공한다. 카페·음식점처럼
  관광지 콘텐츠에 없는 `place_type`은 집중률 데이터 자체가 없을 수 있다 — INFO는
  이 경우 순수 "데이터 없음" 대신 §3.3의 **인근 관광지 대체 조회(장소 근접치
  fallback)**를 우선 시도하고, 그마저 실패하면 "이 장소 유형은 혼잡도 데이터가
  없어요"로 안내한다. (`decision-log.md` 하단 상태표의 기존 미결 항목 "혼잡도
  fallback"을 이 결정으로 해소한다 — 문서 갱신은 §8 TODO 참고.)

---

## 8. 미확정 / TODO

- 서울시 실시간 혼잡도 API 연동(카페·음식점 등 업종별 실시간 데이터) — 이번 범위
  밖, 추후 별도 설계
- `concentration` Feature의 정확한 점수 변환 함수(4단계 구간 기준 vs 원본 비율
  선형 정규화) — `recommendation-scoring.md`에서 D와 확정
- §3.3 인근 관광지 대체 조회의 탐색 반경(`radius_km`, 제안값 1.0km)과 "반경 내
  관광지가 없으면 포기" 기준 — C/D 확인 필요
- RECOMMEND의 `restaurant` 유형 후보에도 §3.3과 동일한 근접치 fallback을 적용할지
  — 배치 보강 흐름의 API 호출 비용 문제로 별도 결정 필요
- 초기 Context 응답(`RecommendationContext`)에 `concentration`을 새 필드로 추가하는
  정확한 스키마(지역 단위 목록 vs 후보별 매칭 결과) — C 확인 필요 (§2.2,
  a-c-context-contract-draft.md §5.2)
- `_select_current_forecast`(또는 동등 로직)를 RECOMMEND 전용 서비스 내부에 갇히지
  않도록 C가 공개 인터페이스로 노출해 INFO 경로에서도 재사용 — C 확인 필요 (§4.2)
- `FakeConcentrationProvider`가 어제/오늘/내일 3일치만 반환해 실제 ~30일 범위를
  대표하지 못함 — `visit_time`이 오늘+2일 이상인 시나리오 테스트를 위해 Fake 확장
  또는 별도 Fixture 필요

---

## 9. 관련 문서

- [conditions-schema.md](./conditions-schema.md) — `concentration_intent` 필드 전체 정의 소유
- [int-01-recommend.md](./int-01-recommend.md) §8 — `weather_intent` 판별 패턴 참고
- [int-02-info.md](./int-02-info.md) §6 — `question_type` enum 소유
- [recommendation-scoring.md](./recommendation-scoring.md) — `concentration` Scoring Feature 상세 설계 (D 확인 필요)
- [agent-runtime-contract.md](./agent-runtime-contract.md) §6 — 혼잡도 보강 흐름 (2단계 호출 방식 폐기, 조건부 1회 조회로 대체)
- [a-c-context-contract-draft.md](./a-c-context-contract-draft.md) §4/§5.1/§5.2 — 초기 Context 응답에 `concentration` 필드 추가 (제안, C 확인 필요). 기존 §5.2의 `CandidateEnrichmentRequest`/`Response`(후보 보강 계약)는 이번 경로에서 쓰지 않고 원래 용도로 유지
- `backend/docs/package-b/agent-state-contract-v1.md` §1.2/§2.2 — B 소유, `concentration_intent`/`api_context` 필드 추가 (제안, B 확인 필요)
- [tool-intelligence-contract-v1.md §6.2](./tool-intelligence-contract-v1.md#62-search_nearby_places) — §3.3 대체 조회가 재사용하는 `search_nearby_places`/`NearbyPlaceDetailsTool` 계약
- [`docs/decision-log.md`](../decision-log.md) D-036 — §3.3의 "혼잡도 fallback: 장소 근접치" 채택 결정 (A 제안, C·D 확인 필요)

---

## 10. 변경 이력

| 버전 | 날짜 | 변경 내용 |
|---|---|---|
| v0.1 | 2026-07-29 | 초안 작성 |
| v0.2 | 2026-07-29 | §4 API 요청 필드 설계(지역 코드 종로구 고정 확인, `reference_date` 신규 필드 제안), §5 B 저장 필드 추가(`concentration_intent`, `api_context.concentration_reference_date`) 신설. §3.2 데이터 범위를 3일→약 30일로 정정. §6 경계 사례의 종로구 밖 예시(잠수교·용리단길)를 종로구 내 장소로 교체하고 범위 밖 사례를 별도 행으로 추가 |
| v0.3 | 2026-07-29 | §3.3 "목적지 인근 관광지 대체 조회(장소 근접치 fallback)" 신설 — 카페·음식점 등 관광지 콘텐츠 밖 장소 질의 시 `search_nearby_places`로 가장 가까운 관광지를 찾아 대체 조회하는 흐름과 응답 원칙 추가. `decision-log.md`의 기존 "혼잡도 fallback" 미결 항목을 이 결정으로 해소 |
| v0.4 | 2026-07-29 | **아키텍처 정정**: agent-runtime-contract.md §6을 쓰다가, concentration이 순위에 반영되는 이상(§2.3) 기존 post-ranking 후보 보강 계약(`CandidateEnrichmentRequest`/`Response`)으로는 데이터가 순위 계산 시점보다 늦게 도착해 구조적으로 맞지 않는다는 걸 뒤늦게 발견. §2.2를 "초기 Context 요청 단계에서 확보"로 다시 씀, §2.3 문구 정합, §4.2에서 `reference_date` 신규 필드 제안을 철회(RECOMMEND는 불필요, INFO만 `visit_time`으로 별도 경로), §5.2 `api_context` 추가 제안 철회. 기존 후보 보강 계약 자체는 폐기하지 않고 원래 용도(표시 전용)로 유지 |
