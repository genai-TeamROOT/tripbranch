# Agent State Contract v1 (Package B)

- 작성자: 이태화
- 작성일: 2026-07-23
- 상태: Draft (Package A 1차 회신 반영)
- 협의 대상: Package A 
- 적용 범위: Phase 1

## 이 문서의 목적

패키지 B(Agent State · Memory · LLMOps)가 다중 턴 대화에서
사용자 조건과 추천 이력을 어떻게 저장하고 갱신하는지에 대한 계약을 정의한다.

패키지 A가 해석한 결과를 B가 어떤 형식으로 전달받고,
B가 어떤 형식으로 되돌려주는지를 확정하는 것이 목적이다.

## 전제 (Phase 1)

- 저장소는 인메모리를 기준으로 한다. (서버 재시작 시 상태 소멸)
- 로그인이 없으며 모든 세션은 익명이다.
- 사용자 원문 발화와 LLM 원문 응답은 저장하지 않는다.
- B는 자연어의 의미를 해석하지 않는다. A가 해석한 결과를 적용만 한다.
- 조건 데이터는 출처에 따라 `user_conditions`와 `api_context`로 분리 저장한다.

---

## 1. 조건 저장 구조 (Agent State Schema v1)

### 1.1 조건 데이터의 3층 구조

조건 데이터는 출처에 따라 세 층으로 나눈다.

| 층 | 내용 | B 저장 | 생성 주체 |
| --- | --- | --- | --- |
| `user_conditions` | 사용자 발화에서 추출한 조건 14개 | O | A (Structured Output) |
| `api_context` | GPS·날씨 API로 확보한 외부 데이터 | O | A 또는 Runtime |
| `answer_conditions` | 위 둘을 병합한 최종 조건 | **X** | A |

**분리하는 이유**

`weather`와 `current_location`은 사용자가 직접 말할 수도 있고,
외부 API로 확보할 수도 있다. 한 필드에 섞으면 다음 문제가 발생한다.

- 사용자가 "비 와"라고 말한 값을 API 갱신이 덮어쓴다.
- 어느 쪽 출처인지 구분할 수 없어 우선순위를 정할 수 없다.

**병합은 B가 하지 않는다.**
`user_conditions`와 `api_context`를 합쳐 `answer_conditions`를 만드는 것은
값의 우선순위를 판단하는 행위이므로 패키지 A의 책임이다.
B는 두 층을 분리해 저장하고 그대로 반환한다.

### 1.2 user_conditions (14개 필드)

`intent-definition.md` v0.2 및 `conditions-schema.md` 2절의 `Conditions`를 채택한다.

| # | 필드명 | 타입 | 값 성격 | 설명 |
| --- | --- | --- | --- | --- |
| 1 | `current_location` | string \| null | 단일 | 사용자가 직접 말한 현재 위치 |
| 2 | `search_center` | string \| null | 단일 | 검색 기준점 |
| 3 | `place_types` | list[string] | 복수 | 장소 대분류 |
| 4 | `place_tags` | list[string] | 복수 | 장소 세부 태그 |
| 5 | `weather` | string \| null | 단일 | 사용자가 직접 말한 날씨 |
| 6 | `weather_intent` | string \| null | 단일 | 날씨 대응 방향 |
| 7 | `transport` | string \| null | 단일 | 이동 수단 |
| 8 | `max_travel_time` | int \| null | 단일 | 최대 이동 시간(**분**) |
| 9 | `time_available` | int \| null | 단일 | 가용 시간(**분**) |
| 10 | `environment` | string \| null | 단일 | 실내/야외 |
| 11 | `companion` | string \| null | 단일 | 동행 유형 |
| 12 | `budget` | string \| null | 단일 | 예산 |
| 13 | `exclude_tags` | list[string] | 복수 | 제외 태그 |
| 14 | `special_requirements` | list[string] | 복수 | 특수 요구사항 |

- 복수 필드는 `place_types`, `place_tags`, `exclude_tags`, `special_requirements` 4개다.
- **이 14개 필드는 사용자가 말한 값만 담는다.** API로 확보한 값은 `api_context`에 저장한다.
- **B는 각 필드의 허용값을 검증하지 않는다.** 허용값 목록은 패키지 A가 정의한다.

**단위 주의**

거리 기반 필드가 없고 시간 기반 필드만 존재한다.

```
max_travel_time : 분 단위 (미터 아님)
time_available  : 분 단위
```

기본 검색 반경 1km는 조건이 아니라 소비 측의 기본 정책이다.

### 1.3 미설정 값의 표현

- 단일값 필드의 미설정은 `null`로 표현한다.
- 복수 필드의 미설정은 빈 배열 `[]`로 표현한다.
- 빈 문자열이나 `0`은 미설정 표현으로 사용하지 않는다.
- `place_types: []`는 "전체 유형 검색"을 뜻하며 미설정과 동일하게 취급한다.

**B는 조건의 기본값을 채우지 않는다.**
기본값 적용(반경 1km, 기본 이동수단 도보, `search_center` 미설정 시 대체 등)은
`answer_conditions` 생성 단계 또는 추천 실행 단계의 책임이다.

`null`을 그대로 전달함으로써
"사용자가 지정한 값"과 "시스템이 채운 값"을 구분할 수 있게 한다.

### 1.4 api_context (4개 필드)

외부에서 확보한 데이터를 `user_conditions`와 분리해 저장한다.

| 필드 | 타입 | 출처 | 유효 기간 |
| --- | --- | --- | --- |
| `gps_location` | string \| null | GPS API | 1시간 |
| `api_weather` | string \| null | 날씨 API | 1시간 |
| `gps_location_updated_at` | string \| null | 시스템 | — |
| `api_weather_updated_at` | string \| null | 시스템 | — |

**유효 기간 규칙**

```
1시간 이내 : 기존 값 유지, 재확보하지 않는다
1시간 초과 : 만료로 판정하고 응답에 만료 플래그를 포함한다
```

- **B는 만료 여부만 판정하고 갱신을 실행하지 않는다.**
  외부 API 호출은 A 또는 Runtime의 책임이다.
- `api_context` 변경은 `condition_version`을 증가시키지 않는다.
  사용자가 조건을 바꾼 것이 아니기 때문이다.
- `api_context`는 `operations` 대상이 아니며 별도 경로로 갱신한다. (6.5절)
- 날씨 API 실패 시 `api_weather`는 `null`로 두며 만료된 이전 값을 재사용하지 않는다.

### 1.5 answer_conditions (B 미저장)

`user_conditions`와 `api_context`를 병합한 최종 조건이다.
추천 엔진과 LLM 응답 생성에 전달된다.

**B는 이 값을 저장하지 않는다.**
매 실행 시 A가 생성하는 휘발성 결과이며,
저장하면 그 자체가 오래된 정보로 남아 현재 값으로 오인될 수 있다.

병합 우선순위는 패키지 A가 정의한다. (사용자 값 우선, 없으면 API 값)

### 1.6 AgentState 구조

```json
{
  "session_id": "sess_01J8XKQ2M7N4P9",
  "user_conditions": {
    "current_location": null,
    "search_center": null,
    "place_types": [],
    "place_tags": [],
    "weather": null,
    "weather_intent": null,
    "transport": null,
    "max_travel_time": null,
    "time_available": null,
    "environment": null,
    "companion": null,
    "budget": null,
    "exclude_tags": [],
    "special_requirements": []
  },
  "api_context": {
    "gps_location": null,
    "api_weather": null,
    "gps_location_updated_at": null,
    "api_weather_updated_at": null
  },
  "condition_version": 0,
  "last_run_id": null,
  "last_intent": null,
  "status": "active",
  "created_at": "2026-07-23T09:00:00+09:00",
  "updated_at": "2026-07-23T09:00:00+09:00",
  "last_active_at": "2026-07-23T09:00:00+09:00"
}
```

| 필드 | 설명 |
| --- | --- |
| `session_id` | 대화 단위 식별자 (4절) |
| `user_conditions` | 사용자 발화에서 추출된 현재 조건 14개 |
| `api_context` | 외부 확보 데이터 4개 |
| `condition_version` | `user_conditions` 변경 횟수. 동시 갱신 감지용 |
| `last_run_id` | 이 상태를 마지막으로 갱신한 실행 식별자 |
| `last_intent` | 직전 턴의 인텐트. A의 맥락 판정용으로 반환 |
| `status` | `active` / `expired` |
| `created_at` | 세션 생성 시각 |
| `updated_at` | 조건이 마지막으로 변경된 시각 |
| `last_active_at` | 마지막 요청 수신 시각. 세션 TTL 판정 기준 (5절) |

### 1.7 규칙

- `user_conditions`는 **사용자 확인이 끝난 조건만** 담는다.
  되묻기 단계의 미확정 조건은 저장하지 않는다. (`confirmed` 플래그, 6.1절)
- `condition_version`은 세션 생성 시 0에서 시작하며,
  `user_conditions`가 실제로 변경된 경우에만 1 증가한다.
- `api_context` 변경은 `condition_version`을 증가시키지 않는다.
- 변경 요청이 있었으나 결과가 이전과 동일하면 증가시키지 않는다.
- 조건 유지만 요청된 경우에도 기존 `user_conditions`를 그대로 반환하며
  `condition_version`은 증가시키지 않는다.
- `updated_at`은 조건이 실제로 변경된 경우에만 갱신하고,
  `last_active_at`은 조건 변경 여부와 무관하게 요청 수신 시마다 갱신한다.
- 모든 시각은 ISO 8601 문자열로 저장하며 타임존을 포함한다.

## 2. 조건 변경 적용 규칙

### 2.1 변경 연산 Payload

```json
{ "op": "Update", "field": "max_travel_time", "value": 15 }
```

| 키 | 타입 | 설명 |
| --- | --- | --- |
| `op` | string | `Add` / `Update` / `Remove` |
| `field` | string | 1.2절 `user_conditions` 14개 필드 중 하나 |
| `value` | any \| null | 적용할 값. `Remove`는 생략 가능 |

- 연산은 **3종**이다. `Keep`은 payload에 포함되지 않는다.
- `operations` 배열에 포함되지 않은 필드는 자동으로 유지된다. (= Keep)
- 복수 필드의 `value`는 원소가 하나여도 리스트로 전달한다.
- `api_context`는 `operations` 대상이 아니다. (6.5절 별도 경로)

**`Keep` 수신 시**
A는 `Keep`을 전송하지 않으나, 수신할 경우 오류로 처리하지 않는다.
State를 변경하지 않고 `condition_version`도 증가시키지 않으며,
변경 기록에만 남긴다.

### 2.2 필드별 허용 연산

`conditions-schema.md` 4절 「필드별 적용 방식」을 기준으로 한다.
**허용되지 않은 연산은 적용하지 않고 `ignored_operations`로 반환한다.**

| 필드 | 값 성격 | 허용 연산 | `Remove` 결과 |
| --- | --- | --- | --- |
| `current_location` | 단일 | `Update` | — (해제 불가) |
| `search_center` | 단일 | `Update` / `Remove` | `null` |
| `place_types` | 복수 | `Update` / `Remove` | `[]` |
| `place_tags` | 복수 | `Add` / `Update` / `Remove` | 해당 원소 제거 |
| `weather` | 단일 | `Update` / `Remove` | `null` |
| `weather_intent` | 단일 | `Update` / `Remove` | `null` |
| `transport` | 단일 | `Update` / `Remove` | `null` |
| `max_travel_time` | 단일 | `Update` / `Remove` | `null` |
| `time_available` | 단일 | `Update` / `Remove` | `null` |
| `environment` | 단일 | `Update` / `Remove` | `null` |
| `companion` | 단일 | `Update` / `Remove` | `null` |
| `budget` | 단일 | `Update` / `Remove` | `null` |
| `exclude_tags` | 복수 | `Add` / `Remove` | 해당 원소 제거 |
| `special_requirements` | 복수 | `Add` / `Remove` | 해당 원소 제거 |

**`current_location`만 `Remove`를 허용하지 않는다.**
`conditions-schema.md` 4절에 필수 필드로 명시되어 있다.

**허용 범위를 넓게 잡은 이유**
허용해 두었으나 전달되지 않으면 해당 분기가 사용되지 않을 뿐이지만,
차단해 두었는데 전달되면 사용자 조건이 반영되지 않은 채 사라진다.
실제 사용 범위가 확정되면 표를 좁힌다. (7절 P0-1)

**`place_types` 교체 시 `place_tags` 정리**
B는 자동 정리를 수행하지 않는다.
패키지 A가 `place_tags`에 대한 `Remove` 연산을 함께 전달한다.

```json
"operations": [
  { "op": "Update", "field": "place_types", "value": ["cultural_facility", "shopping"] },
  { "op": "Remove", "field": "place_tags",  "value": ["카페"] }
]
```

태그와 유형의 소속 관계는 패키지 A의 도메인 정의이므로
B가 매핑 정보를 보유하지 않는다.

### 2.3 연산별 동작

| 연산 | 단일 필드 | 복수 필드 |
| --- | --- | --- |
| `Update` | 값 전체 교체 | 리스트 전체 교체 |
| `Add` | (허용 필드 없음) | 리스트에 추가. 중복 원소는 무시 |
| `Remove` | `null`로 되돌림 | `value` 있으면 해당 원소 제거, 없으면 전체 비움 |

**존재하지 않는 원소에 대한 `Remove`**
오류로 처리하지 않고 무시하며, 결과가 변하지 않으므로
`condition_version`도 증가시키지 않는다.

### 2.4 적용 순서

1. `reset_scope`가 있으면 먼저 적용한다. (5절)
2. `operations` 배열을 받은 순서대로 순차 적용한다.
3. 같은 필드에 여러 연산이 오면 마지막 연산 결과가 최종 상태가 된다.
4. 중간 연산도 변경 기록에는 전부 남긴다.
5. B는 연산 순서를 재정렬하지 않는다.

`condition_version`은 연산 개수와 무관하게 요청 단위로 최대 1 증가한다.

### 2.5 유효성 검증

적용 전에 `operations` 전체를 검증하고, 유효한 연산만 적용한다.

| 상황 | reason |
| --- | --- |
| 1.2절에 없는 `field` | `unknown_field` |
| 정의되지 않은 `op` | `unknown_op` |
| 해당 필드가 허용하지 않는 연산 (2.2절 위반) | `unsupported_operation` |
| 값 타입 불일치 | `type_mismatch` |
| 복수 필드의 `value`가 리스트가 아님 | `type_mismatch` |
| `Add`/`Update`에 `value` 없음 | `missing_value` |
| `Add`/`Update`의 `value`가 `null` | `null_value` |
| `api_context` 필드를 `field`로 지정 | `unsupported_operation` |

```json
"ignored_operations": [
  { "operation": { "op": "Add", "field": "place_types", "value": ["shopping"] },
    "reason": "unsupported_operation" }
]
```

**B는 값을 변환하거나 추측하지 않는다.**
문자열 `"30분"`을 `30`으로 변환하지 않으며,
`value: null`인 `Update`를 `Remove`로 해석하지 않는다.
해제 의도는 `Remove` 연산으로만 표현한다.
허용값 목록에 없는 값이라도 검증하지 않고 저장한다.

### 2.6 요청 단위 예외 처리

| 상황 | 처리 |
| --- | --- |
| `operations`가 빈 배열 | State 변경 없음, 기존 조건 그대로 반환 |
| `operations` 키 없음 | 빈 배열과 동일 |
| `session_id` 없음 | 새 세션 생성 후 빈 State에 적용 |
| `session_id` 만료 | 새 세션 생성 후 빈 State에 적용 (5절) |
| `confirmed: false` | State에 반영하지 않고 현재 State를 반환 |

`INFO` / `COMPARE` / `GENERAL` / `OUT_OF_SCOPE` 인텐트는
`operations`를 생성하지 않으므로 빈 배열로 전달된다.
이 경우에도 기존 `user_conditions`는 그대로 유지된다.

### 2.7 condition_version 증가 기준

적용 전후의 `user_conditions`를 전체 비교하여 판정한다.

- 결과가 달라진 경우에만 1 증가시킨다.
- 빈 연산, 전부 무효 처리된 경우, 적용 결과가 이전과 동일한 경우에는 증가시키지 않는다.
- `api_context` 변경은 판정에서 제외한다.
- `updated_at`도 동일한 기준으로 갱신한다.

### 2.8 변경 기록

```json
{
  "session_id": "sess_01J8XKQ2M7N4P9",
  "run_id": "run_01J8XKQ5A1B2C3",
  "seq": 1,
  "op": "Update",
  "field": "max_travel_time",
  "before_value": 30,
  "after_value": 15,
  "applied_at": "2026-07-23T09:05:12+09:00"
}
```

- 유효한 연산은 결과 변화가 없어도 기록한다.
- 무효한 연산은 기록하지 않고 `ignored_operations`로만 반환한다.
- `api_context` 갱신은 별도 경로이므로 이 기록에 남기지 않는다.
- 사용자 원문 발화와 LLM 원문 응답은 기록하지 않는다.

### 2.9 적용 예시

```
[예시 1] 조건 추가
before:  { place_types: ["restaurant"], special_requirements: [] }
ops:     [{ op: "Add", field: "special_requirements", value: ["주차"] }]
after:   { place_types: ["restaurant"], special_requirements: ["주차"] }
version: 3 → 4

[예시 2] 대분류 교체 + 태그 정리 (A가 두 연산을 함께 전송)
before:  { place_types: ["cultural_facility", "restaurant"],
           place_tags: ["박물관", "카페"] }
ops:     [{ op: "Update", field: "place_types", value: ["cultural_facility", "shopping"] },
          { op: "Remove", field: "place_tags",  value: ["카페"] }]
after:   { place_types: ["cultural_facility", "shopping"],
           place_tags: ["박물관"] }
version: 4 → 5

[예시 3] 조건 해제
before:  { budget: "free", environment: "indoor" }
ops:     [{ op: "Remove", field: "budget" },
          { op: "Update", field: "environment", value: "any" }]
after:   { budget: null, environment: "any" }
version: 5 → 6

[예시 4] 변경 없는 재추천 (REJECT_ALL)
before:  { place_types: ["restaurant"], max_travel_time: 15 }
ops:     []
after:   { place_types: ["restaurant"], max_travel_time: 15 }
version: 6 → 6 (유지)

[예시 5] 허용되지 않은 연산
before:  { place_types: ["restaurant"] }
ops:     [{ op: "Add", field: "place_types", value: ["shopping"] }]
after:   { place_types: ["restaurant"] }   ← 변경 없음
version: 6 → 6
ignored: place_types + Add → unsupported_operation
```

## 3. 추천·거절 이력 구조

### 3.1 recommended와 rejected의 구분

| 구분 | 의미 | 목적 |
| --- | --- | --- |
| `recommended` | 사용자에게 노출된 적 있는 장소 | 중복 노출 방지 |
| `rejected` | 사용자가 명시적으로 거부한 장소 | 재노출 방지 |

두 이력은 초기화 범위가 다르므로 별도 구조로 관리한다. (5절)
Phase 1에서는 제외 목적으로 동일하게 사용하지만,
구조를 분리해 두어 이후 스코어링 정책에서 다르게 취급할 수 있도록 한다.

### 3.2 이력 구조

```json
{
  "session_id": "sess_01J8XKQ2M7N4P9",
  "recommended": [
    { "place_id": "126511", "run_id": "run_01J8XKQ5A1B2C3", "rank": 1,
      "shown_at": "2026-07-23T09:05:12+09:00" },
    { "place_id": "126512", "run_id": "run_01J8XKQ5A1B2C3", "rank": 2,
      "shown_at": "2026-07-23T09:05:12+09:00" }
  ],
  "rejected": [
    { "place_id": "126508", "run_id": "run_01J8XKQ9Z8Y7X6",
      "reason_code": "too_far",
      "rejected_at": "2026-07-23T09:07:30+09:00" }
  ],
  "updated_at": "2026-07-23T09:07:30+09:00"
}
```

**recommended 항목**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `place_id` | string | 장소 식별자. TourAPI `contentid` |
| `run_id` | string | 이 추천이 발생한 실행 식별자 |
| `rank` | int | 해당 실행에서의 노출 순위(1부터). 패키지 D가 결정한 값을 그대로 저장 |
| `shown_at` | string | 노출 시각 (ISO 8601) |

**rejected 항목**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `place_id` | string | 거절된 장소 식별자 |
| `run_id` | string | 거절이 발생한 실행 식별자 |
| `reason_code` | string \| null | 거절 사유 코드. 패키지 A가 해석한 값을 그대로 저장 |
| `rejected_at` | string | 거절 시각 (ISO 8601) |

`reason_code` 후보값 (패키지 A 정의, 미확정):

```
too_far / not_interested / already_visited / closed / other
```

B는 값을 검증하지 않고 그대로 저장한다. 값이 없으면 `null`로 둔다.

`recommended`와 `rejected`는 append-only 리스트이며 기존 항목을 수정하지 않는다.

### 3.3 제외 ID 목록

```
exclusion_place_ids = recommended의 place_id ∪ rejected의 place_id
```

- 중복은 제거하여 반환한다.
- 순서는 보장하지 않는다.
- 추천 이력이 없는 `place_id`가 `rejected`로 전달되어도 검증하지 않고 저장한다.

세션이 유지되는 동안 계속 누적된다.

### 3.4 마지막 노출 목록

누적 목록과 별개로, **마지막 실행에서 노출된 목록**을 구분해 반환한다.

```
shown_place_ids = recommended 중 last_recommended_run_id 와 일치하는 항목의
                  place_id 를 rank 순으로 정렬한 목록
```

| 항목 | 값 |
| --- | --- |
| 범위 | 마지막 실행 1건 |
| 정렬 | `rank` 오름차순 |
| 용도 | 패키지 A의 `COMPARE` 지시 표현 해석 |

**누적이 아닌 마지막 실행 기준인 이유**

`COMPARE`에서 "첫 번째", "두 번째"는 **방금 본 추천**을 가리킨다.

```
1차 추천: [126508, 126509, 126510]
2차 추천: [126511, 126512, 126513]
사용자: "첫 번째가 좋아"

누적 기준     → 126508 (세 턴 전 항목)
마지막 실행 기준 → 126511 (방금 본 항목)  ← 올바른 해석
```

누적 목록이 필요한 경우 `excluded_place_ids`를 사용한다.

### 3.5 중복 처리

- 동일한 `place_id`가 다시 전달되어도 오류로 처리하지 않고 리스트에 추가한다.
- 중복 제거는 `exclusion_place_ids` 생성 시점에만 수행한다.

이력을 append-only로 유지하면 저장 로직에 조회·비교 단계가 필요 없고,
같은 장소가 두 번 노출된 사실 자체도 기록으로 남는다.

### 3.6 이력 누적 범위

- 이력은 세션 단위로 누적한다.
- **B는 조건 변화를 감지하여 이력을 자동으로 초기화하지 않는다.**
  초기화가 필요한 경우 패키지 A가 `reset_scope`를 명시적으로 전달한다. (5절)
- Phase 1에서는 이력 건수 상한을 두지 않는다.

`int-03-modify.md` 8절은 `search_center` 변경 시 제외 목록 초기화를 규정하나,
해당 판정은 패키지 A가 수행하고 `reset_scope: history`를 함께 전달한다.

### 3.7 책임 범위 밖

B는 다음을 수행하지 않는다.

| 항목 | 담당 |
| --- | --- |
| 거절 사유의 해석 | 패키지 A |
| 추천 순위 계산 | 패키지 D (AF-10) |
| 장소 상세 정보(이름·주소·좌표) 저장 | 패키지 C |
| 조건 변화 기반 이력 자동 초기화 | 패키지 A의 `reset_scope` 지시 |
| 노출 여부 판단 | AF-05 Agent Runtime |

**B는 `place_id`만 저장하며 장소 상세 정보를 보관하지 않는다.**
외부 장소 정보는 시점에 따라 변경될 수 있으므로,
B가 보관한 과거 정보가 현재 정보로 오인되는 상황을 방지한다.

## 4. 세션·실행 식별자 정의

### 4.1 계층 구조

```
session_id                대화 단위 (여러 턴)
└── run_id                사용자 요청 1건 = Agent 1회 실행
    └── trace_id          run 내부의 개별 실행 단계
```

| 식별자 | 범위 | 대응하는 질문 |
| --- | --- | --- |
| `session_id` | 대화 전체 | 어느 대화의 상태·이력인가 |
| `run_id` | 요청 1건 | 어느 요청에서 조건이 변경되고 추천이 발생했는가 |
| `trace_id` | 실행 내부 단계 | 요청 내부에서 어느 단계가 수행·지연됐는가 |

### 4.2 생성 주체

세 식별자는 모두 **패키지 B가 발급**한다.
다른 패키지는 발급하지 않으며 전달받은 값을 사용한다.

### 4.3 생성 시점

| 식별자 | 생성 조건 | 시점 |
| --- | --- | --- |
| `session_id` | 요청에 없거나, 저장소에 존재하지 않거나, 만료된 경우 | 요청 처리 시작 시점 |
| `run_id` | 모든 요청마다 1개 | 세션 확보 직후, **조건 병합 이전** |
| `trace_id` | 실행 내부 외부 호출마다 1개 | 각 단계 시작 시점 |

**처리 순서**

```
1. session_id 확보 (없으면 발급)
2. run_id 발급
3. 조건 병합 및 변경 기록
4. 추천 실행
5. 추천 이력 저장
```

`run_id`를 조건 병합 이전에 발급하는 이유는,
2.7절의 변경 기록과 3.2절의 추천 이력이 모두 `run_id`를 필수로 포함하기 때문이다.

### 4.4 형식

```
접두어 + "_" + 정렬 가능한 고유 문자열(ULID 기준)

sess_01J8XKQ2M7N4P9QRSTVWXYZ0
run_01J8XKQ5A1B2C3D4E5F6G7H8
trace_01J8XKQ5D4E5F6G7H8I9J0K
```

| 접두어 | 대상 |
| --- | --- |
| `sess_` | session_id |
| `run_` | run_id |
| `trace_` | trace_id |

- 접두어는 로그 판독성과 오사용 탐지를 위해 사용한다.
- 생성 순서대로 정렬 가능한 값을 사용한다. (append-only 데이터의 시간순 조회 목적)
- 구체적 생성 방식(ULID / UUID)은 구현 시점에 확정한다. (7절)

**B는 전달받은 `session_id`의 형식을 검증하지 않는다.**
저장소에 존재하지 않으면 신규 세션으로 처리하며 오류로 반환하지 않는다.

### 4.5 요청·응답에서의 전달

**요청 (A → B)**
- `session_id`만 전달한다. 없으면 생략하거나 `null`로 보낸다.
- `run_id`, `trace_id`는 요청에 포함하지 않는다.

**응답 (B → A)**
- `session_id`는 신규·기존 여부와 무관하게 항상 포함한다.
- `run_id`는 항상 포함한다. 장애 추적 시 기준값으로 사용한다.
- `session_created`(boolean)로 세션 신규 발급 여부를 알린다.
- `trace_id`는 응답에 포함하지 않는다. (내부 관측 용도)

**클라이언트 보관**
- `session_id`는 `sessionStorage`에 보관한다.
- 탭 종료 시 소멸되며, 이후 요청은 신규 세션으로 시작한다.

### 4.6 trace_id 명칭에 관한 주석

업계 관측 표준(OpenTelemetry)에서는 `trace_id`가 요청 전체를,
`span_id`가 내부 단계를 의미하며 본 문서의 정의와 반대다.

v1에서는 업무 정의서 표기를 따라 `trace_id`를 run 내부 단계 식별자로 사용한다.
외부 관측 도구를 도입할 경우 다음과 같이 명칭을 변경한다.

```
run_id   → trace_id
trace_id → span_id
```

### 4.7 Phase 1 구현 범위

| 식별자 | Phase 1 | 비고 |
| --- | --- | --- |
| `session_id` | 구현 | State 조회·저장의 기준 키 |
| `run_id` | 구현 | 변경 기록·추천 이력에 필수 |
| `trace_id` | 정의만 | 발급은 Agent Runtime(AF-05) 연결 이후 |

## 5. 익명 세션 정책

### 5.1 전제

로그인이 없으므로 조건과 이력은 사용자 계정이 아닌 세션에 귀속된다.
`session_id`가 소멸하면 해당 대화의 상태와 이력을 복구할 수 없다.

### 5.2 세션 생성

다음 세 경우에 새 세션을 발급한다.

1. 요청에 `session_id`가 없는 경우
2. 요청의 `session_id`가 저장소에 존재하지 않는 경우
3. 요청의 `session_id`가 `expired` 상태인 경우

세 경우 모두 동일하게 처리한다.

- 새 `session_id` 발급
- 빈 `AgentState` 생성
  (`user_conditions` 전 필드 `null` / `[]`, `api_context` 전 필드 `null`,
  `condition_version = 0`)
- 빈 이력 생성 (`recommended: []`, `rejected: []`)
- 응답에 `session_created: true` 포함

**어떤 경우에도 오류를 반환하지 않는다.**
익명 세션에서 만료는 오류가 아니라 정상적인 생애주기이므로,
신규 세션을 발급하고 정상 응답을 반환한다.

**GPS 미확보 상태에서의 세션 생성**

`api_context.gps_location`이 없어도 세션을 생성하고 `null`로 유지한다.
사용자가 위치를 직접 말한 경우 `user_conditions.current_location`에 저장되며,
두 값의 병합은 패키지 A가 수행한다. (1.5절)

B는 GPS 확보 여부로 세션 생성을 거부하지 않는다.
진행 가능 여부 판단은 패키지 A 또는 UI의 책임이다. (7절 P0-3)

### 5.3 세션 유지

- 서버는 `session_id`를 키로 State와 이력을 보관한다.
- 클라이언트는 `session_id` 문자열을 보관하고 매 요청에 포함한다.
- 보관 위치는 `sessionStorage`를 기준으로 한다. (프론트 협의 항목)

**시각 필드의 구분**

| 필드 | 갱신 기준 | 용도 |
| --- | --- | --- |
| `updated_at` | `user_conditions`가 실제로 변경된 경우에만 | 마지막 조건 변경 시점 |
| `last_active_at` | 요청 수신 시마다 | 세션 TTL 판정 |

조건 변경 없는 재추천 요청이 반복되어도 세션이 만료되지 않도록
두 필드를 분리한다.

`api_context` 갱신(6.5절)은 `updated_at`을 갱신하지 않으며,
`last_active_at`만 갱신한다.

### 5.4 만료 판정

B가 관리하는 만료는 세 종류이며, 모두 시각 비교로 판정한다.

| 대상 | 기준 필드 | 기간 | 만료 시 동작 |
| --- | --- | --- | --- |
| 세션 | `last_active_at` | 30분 | `status: expired`, 신규 세션 발급 |
| GPS | `gps_location_updated_at` | 1시간 | 응답에 `gps_expired: true` |
| 날씨 | `api_weather_updated_at` | 1시간 | 응답에 `weather_expired: true` |

**판정 시점**

```
요청이 수신된 시점에 해당 세션만 확인한다. (lazy 방식)
주기적 스캔을 수행하지 않는다.
```

**세션 만료 처리**

- `status`를 `expired`로 표시한다.
- 만료된 State는 복구하지 않으며 신규 세션으로 시작한다.
- Phase 1에서는 만료된 세션 데이터를 즉시 삭제하지 않는다.

**api_context 만료 처리**

- **B는 만료를 알릴 뿐 갱신을 실행하지 않는다.**
  GPS·날씨 재확보는 패키지 A 또는 Agent Runtime의 책임이다.
- 만료된 값을 응답에서 제거하지 않는다. 플래그만 함께 반환한다.
- 갱신된 값은 6.5절 경로로 전달받는다.
- 날씨 API 실패 시 `api_weather`는 `null`로 저장하며,
  만료된 이전 값을 재사용하지 않는다.

세션 TTL(30분)이 `api_context` 유효 기간(1시간)보다 짧으므로,
연속 대화가 1시간을 넘는 경우에만 `api_context` 만료 판정이 발생한다.

**Phase 1 제약:** 인메모리 저장이므로 서버 재시작 시 모든 세션이 소멸한다.
이는 의도된 제약이며 저장소 교체 시 해소된다.

TTL 값은 실사용 후 조정 가능하다.

### 5.5 초기화 범위

| 종류 | `reset_scope` | 조건 | 추천 이력 | 거절 이력 | session_id |
| --- | --- | --- | --- | --- | --- |
| Soft Reset | `soft` | 초기화 | 유지 | 유지 | 유지 |
| History Reset | `history` | 유지 | 초기화 | **유지** | 유지 |
| Full Reset | `full` | 초기화 | 초기화 | 초기화 | **신규 발급** |

**Soft Reset**
`user_conditions`만 초기화하고 이력은 유지한다.
조건이 바뀌더라도 이미 노출된 장소를 다시 보여주지 않기 위함이다.

**History Reset**
추천 이력만 비우고 거절 이력은 유지한다.
사용자가 명시적으로 거부한 장소를 재노출하지 않기 위함이다.

**Full Reset**
기존 세션을 만료 처리하고 신규 세션을 발급한다.
TTL 만료도 결과적으로 동일하게 동작한다.

**`api_context`의 취급**

| 종류 | `api_context` |
| --- | --- |
| Soft Reset | 유지 |
| History Reset | 유지 |
| Full Reset | 초기화 (신규 세션이므로) |

`api_context`는 사용자 조건이 아니라 외부 확보 데이터이므로,
조건 초기화 요청으로 함께 비우지 않는다.
유효 기간 내라면 재확보 없이 계속 사용한다.

**판정 주체**

어떤 발화가 어느 초기화에 해당하는지 판정하는 것은 패키지 A의 책임이다.
B는 전달받은 `reset_scope` 값에 따라 실행만 하며 발화를 해석하지 않는다.

패키지 A의 판정 기준:

| 발화 예시 | `reset_scope` |
| --- | --- |
| "조건 다시 정할게" | `soft` |
| "처음부터 다시 추천해줘" | `history` |
| "새로 시작" / "리셋" | `full` |
| 일반 `MODIFY` / `RECOMMEND` | `null` |
| `search_center` 변경 시 | `history` (Update 연산과 함께 전송) |

**적용 순서**

`reset_scope`와 `operations`가 함께 전달된 경우
`reset_scope`를 먼저 적용한 뒤 `operations`를 적용한다.

```json
{
  "reset_scope": "history",
  "operations": [
    { "op": "Update", "field": "search_center", "value": "인사동" }
  ]
}
```

**초기화 기록**

```json
{
  "session_id": "sess_01J8XKQ2M7N4P9",
  "run_id": "run_01J8XKQ5A1B2C3",
  "seq": 0,
  "op": "Reset",
  "field": null,
  "reset_scope": "history",
  "applied_at": "2026-07-23T09:10:00+09:00"
}
```

`op`에 `Reset`을 사용하며 `field`는 `null`이다.
2절의 연산 3종과는 별개 경로이므로 구분된다.

### 5.6 저장 범위

**저장한다**

- `user_conditions` 14개 필드 (구조화된 조건값)
- `api_context` 4개 필드 (외부 확보 데이터 + 확보 시각)
- `place_id` (TourAPI `contentid`)
- 식별자 (`session_id`, `run_id`, `trace_id`)
- `last_intent`
- 조건 변경 기록의 `before_value` / `after_value`
- 실행 메타데이터 (지연 시간, 토큰 사용량, 오류 유형)
- 버전 정보 (`prompt_version`, `scoring_version`, `variant_id`)

**저장하지 않는다**

- 사용자 원문 발화
- LLM 원문 응답 텍스트
- Chain-of-Thought 등 내부 추론 과정
- 장소 상세 정보 (이름·주소·좌표·영업시간)
- `answer_conditions` (병합 결과)

**`answer_conditions`를 저장하지 않는 이유**

`user_conditions`와 `api_context`를 병합한 결과이므로,
저장하면 그 자체가 오래된 값으로 남아 현재 값으로 오인될 수 있다.
매 실행 시 패키지 A가 최신 값으로 재생성한다.

**원문을 저장하지 않아도 되는 이유**

`ChangeLog`의 구조화된 값과 `run_id`로 조건 변경 경위를 재구성할 수 있다.

```
"어떤 연산이 적용됐는가"   → ChangeLog
"조건이 어떻게 바뀌었는가"  → before_value / after_value
"어느 실행에서 바뀌었는가"  → run_id
```

"사용자가 어떤 표현을 썼는가"만 확인할 수 없으며,
이는 AF-11 평가 Fixture의 영역이다.

## 6. A → B 전달 계약 초안

### 6.0 계약의 형태

본 계약은 패키지 간 데이터 형식을 정의한다.
Phase 1에서는 동일 프로세스 내 함수 호출로 구현하며,
HTTP 엔드포인트 노출은 AF-05 Agent Runtime의 책임 범위다.

본 절은 네 개의 계약으로 구성된다.

| 계약 | 방향 | 성격 |
| --- | --- | --- |
| 6.1 / 6.2 조건 적용 | A → B | 상태 변경 |
| 6.3 세션 컨텍스트 조회 | A → B | 읽기 전용 |
| 6.4 추천 결과 기록 | Runtime → B | 이력 기록 |
| 6.5 api_context 갱신 | A 또는 Runtime → B | 외부 데이터 갱신 |

**전체 호출 순서**

```
1. get_session_context()        조회 (인텐트 분류 전)
2. [gps_expired 시] update_api_context()
3. A: 인텐트 분류 + 조건 해석
4. apply()                      조건 병합, run_id 발급
5. A: user_conditions + api_context 병합 → answer_conditions 생성
6. C · D: 추천 실행
7. record_recommendation()      이력 기록
```

### 6.1 조건 적용 요청 (A → B)

```json
{
  "session_id": "sess_01J8XKQ2M7N4P9",
  "intent": "MODIFY",
  "confirmed": true,
  "reset_scope": null,
  "operations": [
    { "op": "Update", "field": "max_travel_time", "value": 15 }
  ],
  "rejected_places": [
    { "place_id": "126508", "reason_code": "too_far" }
  ],
  "prompt_version": "intent_v1.2"
}
```

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `session_id` | string \| null | O | 없거나 `null`이면 B가 신규 발급 |
| `intent` | string | O | A가 분류한 6종 중 하나. `last_intent`로 저장 |
| `confirmed` | bool | O | 사용자 확인 완료 여부 |
| `reset_scope` | string \| null | O | `soft` / `history` / `full` / `null` |
| `operations` | list | O | 변경 연산 목록. 없으면 `[]` |
| `rejected_places` | list | O | 이번 턴 거절 장소. 없으면 `[]` |
| `prompt_version` | string \| null | X | LLMOps 기록용 |

- "필수"는 키의 존재를 의미하며, 값이 `null` 또는 `[]`인 것은 허용한다.
- `intent`는 저장 용도로만 사용하며 B의 동작 분기에 사용하지 않는다.
  `RECOMMEND`와 `MODIFY`에서만 `operations`가 생성된다.
- `confirmed`가 `false`인 경우 `operations`를 반영하지 않고 현재 State를 반환한다.
- `place_id`는 TourAPI `contentid` 문자열을 사용한다.

**`confirmed` 판정 기준 (패키지 A)**

| 상황 | 값 |
| --- | --- |
| 조건 추출 완료, `missing_conditions` 없음 | `true` |
| 되묻기 상태 | `false` |
| 확인 화면에서 사용자 명시적 확인 | `true` |
| `weather_intent: null` (의도 모호) | `false` |

### 6.2 조건 적용 응답 (B → A)

```json
{
  "session_id": "sess_01J8XKQ2M7N4P9",
  "run_id": "run_01J8XKQ5A1B2C3",
  "session_created": false,
  "user_conditions": { "...14개 필드..." },
  "api_context": {
    "gps_location": "37.5565,126.9236",
    "api_weather": "rain",
    "gps_expired": false,
    "weather_expired": false
  },
  "condition_version": 5,
  "condition_changed": true,
  "applied_operations": [
    { "op": "Update", "field": "max_travel_time",
      "before_value": 30, "after_value": 15 }
  ],
  "ignored_operations": [],
  "exclusion_place_ids": ["126508", "126509"],
  "reset_applied": null
}
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `session_id` | string | 신규·기존 무관하게 항상 포함 |
| `run_id` | string | 이번 실행 식별자 |
| `session_created` | bool | 세션 신규 발급 여부 |
| `user_conditions` | object | 병합 완료된 현재 조건 14개 전체 |
| `api_context` | object | 외부 데이터 + 만료 플래그 |
| `condition_version` | int | 병합 후 조건 버전 |
| `condition_changed` | bool | 이번 요청으로 조건이 실제 변경됐는지 |
| `applied_operations` | list | 적용된 연산과 전후 값 |
| `ignored_operations` | list | 무시된 연산과 사유 |
| `exclusion_place_ids` | list[string] | 추천 제외 대상 ID |
| `reset_applied` | string \| null | 적용된 초기화 종류 |

**조건의 단일 기준은 B다.**
A는 부분 변경분을 자체 조립하지 않고 `user_conditions`를 그대로 사용한다.

`api_context`의 `gps_expired` / `weather_expired`가 `true`인 경우,
A 또는 Runtime이 재확보 후 6.5절로 갱신한다.

### 6.3 세션 컨텍스트 조회 (A → B, 읽기 전용)

A가 인텐트를 분류하기 전에 필요한 정보를 제공한다.

**요청**

```json
{ "session_id": "sess_01J8XKQ2M7N4P9" }
```

**응답**

```json
{
  "session_id": "sess_01J8XKQ2M7N4P9",
  "session_exists": true,
  "has_recommendation": true,
  "recommended_count": 6,
  "shown_place_ids": ["126511", "126512", "126513"],
  "excluded_place_ids": ["126508", "126509", "126510"],
  "last_recommended_run_id": "run_01J8XKQ5A1B2C3",
  "last_intent": "MODIFY",
  "user_conditions": { "...14개 필드..." },
  "api_context": { "...4개 필드 + 만료 플래그..." },
  "condition_version": 5
}
```

| 필드 | 타입 | 용도 |
| --- | --- | --- |
| `session_exists` | bool | 세션 존재·유효 여부 |
| `has_recommendation` | bool | `MODIFY` / `COMPARE` 전제 조건 판정 |
| `recommended_count` | int | 누적 노출 장소 수 |
| `shown_place_ids` | list[string] | **마지막 실행** 노출 목록(rank 순). `COMPARE` 지시어 해석용 |
| `excluded_place_ids` | list[string] | 누적 제외 목록 |
| `last_recommended_run_id` | string \| null | 마지막 추천 실행 |
| `last_intent` | string \| null | 직전 턴 인텐트. `INFO`의 장소 맥락 판정용 |
| `user_conditions` | object | 현재 조건. 상대 표현("더 가까운 곳") 계산용 |
| `api_context` | object | 만료 여부 확인용 |
| `condition_version` | int | 현재 조건 버전 |

**규칙**

- 이 호출은 State를 변경하지 않는다.
- `run_id`를 발급하지 않으며 `last_active_at`도 갱신하지 않는다.
- 세션이 없거나 만료된 경우에도 오류를 반환하지 않고
  `session_exists: false`, `has_recommendation: false`로 응답한다.
  이때 세션을 새로 생성하지 않는다.

**`user_conditions`를 반환하는 이유**
`int-03-modify.md` 9절의 상대 표현 처리는 현재값을 알아야 계산할 수 있다.

```
"더 가까운 곳" → 현재 max_travel_time 의 50% (30분 → 15분)
```

현재값은 B가 보유하므로, A가 조회 후 절대값을 계산해 `operations`로 전달한다.
**B는 상대 표현을 해석하거나 계산하지 않는다.**

### 6.4 추천 결과 기록 (Agent Runtime → B)

**요청**

```json
{
  "session_id": "sess_01J8XKQ2M7N4P9",
  "run_id": "run_01J8XKQ5A1B2C3",
  "recommended": [
    { "place_id": "126511", "rank": 1 },
    { "place_id": "126512", "rank": 2 }
  ]
}
```

**응답**

```json
{ "recorded": 2 }
```

**호출 주체**
AF-05 Agent Runtime이 추천 응답을 조립한 직후 호출한다.
패키지 D는 순위를 계산할 뿐 실제 노출 여부를 알지 못하므로,
노출이 확정된 결과만 이력에 기록한다.

`run_id`는 6.1 요청에서 발급된 값을 그대로 사용한다.

### 6.5 api_context 갱신 (A 또는 Runtime → B)

GPS·날씨 API로 확보한 데이터를 저장한다.
`operations`와 별도 경로이며 조건 변경으로 취급하지 않는다.

**요청**

```json
{
  "session_id": "sess_01J8XKQ2M7N4P9",
  "gps_location": "37.5570,126.9240",
  "gps_location_updated_at": "2026-07-23T10:05:00+09:00",
  "api_weather": "good",
  "api_weather_updated_at": "2026-07-23T10:05:00+09:00"
}
```

**응답**

```json
{
  "session_id": "sess_01J8XKQ2M7N4P9",
  "api_context": {
    "gps_location": "37.5570,126.9240",
    "api_weather": "good",
    "gps_expired": false,
    "weather_expired": false
  }
}
```

**규칙**

- 전달된 필드만 갱신한다. 생략된 필드는 기존 값을 유지한다.
- `condition_version`을 증가시키지 않는다.
- `updated_at`을 갱신하지 않는다. (`last_active_at`은 갱신)
- 날씨 API 실패로 `api_weather: null`이 전달되면 `null`로 저장한다.
  만료된 이전 값을 재사용하지 않는다.
- `updated_at` 값이 전달되지 않으면 B가 수신 시각을 사용한다.

**호출 주체는 미확정이다.** (7절 P0-2)

### 6.6 실패 처리 원칙

| 실패 지점 | 추천 응답 | 처리 |
| --- | --- | --- |
| 세션 컨텍스트 조회 실패 | 계속 | 빈 컨텍스트로 응답 (오류 아님) |
| State 조회·병합 실패 | 중단 | 예외를 상위로 전달 |
| api_context 갱신 실패 | 계속 | 로그 기록 후 통과 |
| 추천 이력 기록 실패 | 계속 | 로그 기록 후 통과 |
| 실행 메타데이터 기록 실패 | 계속 | 로그 기록 후 통과 |

기록성 작업의 실패는 사용자 응답 경로를 중단시키지 않는다.

### 6.7 계약 범위 밖

| 항목 | 담당 |
| --- | --- |
| 사용자 원문 발화 | 저장하지 않음 |
| `answer_conditions` 생성·병합 | 패키지 A |
| 상대 표현("더 가까운 곳") 계산 | 패키지 A |
| `place_tags` 자동 정리 | 패키지 A |
| GPS·날씨 API 호출 | A 또는 Runtime |
| 장소 상세 정보 | 패키지 C |
| 추천 이유·설명 문장 | 패키지 D, A |
| 조건 기본값 적용 | A 또는 C·D |
| 조건 허용값 검증 | 패키지 A |
| HTTP 엔드포인트 정의 | AF-05 Agent Runtime |

## 7. 미확정 항목 (협의 필요)

### 7.0 원칙

미확정 항목은 공란으로 두지 않고 **잠정 결정**을 함께 기재한다.
잠정 결정을 기준으로 구현을 진행하며, 확정 시 해당 부분만 수정한다.

| 등급 | 기준 |
| --- | --- |
| P0 | 미확정 시 State Merge 구현을 시작할 수 없음 |
| P1 | 구현은 가능하나 통합 테스트 전 확정 필요 |
| P2 | Phase 1 진행에 영향 없음 |

참조 문서:
- `intent-definition.md` v0.2
- `conditions-schema.md` v0.1
- `int-01-recommend.md` v0.1
- `int-03-modify.md` v0.1
- Package A 1차 회신 (2026-07-23)

### 7.1 P0 — 확인 필요

| # | 항목 | 잠정 결정 |
| --- | --- | --- |
| P0-1 | 필드별 `Remove` 허용 범위 | `conditions-schema.md` 4절 기준(넓게). A 회신 표는 `budget`만 허용하나, 이는 B가 제시한 표를 승인한 결과이므로 원본 문서를 기준으로 함 |
| P0-2 | `update_api_context()` 호출 주체 | A 또는 Runtime 중 미정. B는 수신·저장만 수행 |
| P0-3 | GPS 미확보 시 세션 처리 | 세션을 생성하고 `gps_location: null`로 유지. 진행 가능 여부 판단은 A/UI 책임 |
| P0-4 | `shown_place_ids` 범위 | 마지막 실행 기준 (누적 아님) |

### 7.2 P1 — 통합 전 확정 필요

| # | 항목 | 잠정 결정 |
| --- | --- | --- |
| P1-1 | 새 `RECOMMEND` 수신 시 조건 초기화 | B는 자동 초기화하지 않음. 필요 시 A가 `reset_scope: soft` 동반 전송 |
| P1-2 | 조건 필드 명칭 통일 | `user_conditions`로 통일. (`current_conditions` / `final_conditions` 혼재) |
| P1-3 | `reason_code` 목록 | `too_far` / `not_interested` / `already_visited` / `closed` / `other` (A 확정 대기) |
| P1-4 | 추천 결과 기록 호출 주체 | AF-05 Agent Runtime |
| P1-5 | 식별자 생성 방식 | ULID 우선, 의존성 제약 시 `uuid4` |
| P1-6 | `initial_conditions` 보관 여부 | Phase 1에서는 저장하지 않음 |

### 7.3 P2 — Phase 1 진행에 영향 없음

| # | 항목 | 잠정 결정 |
| --- | --- | --- |
| P2-1 | `trace_id` 명칭 | v1 유지. 관측 도구 도입 시 `span_id`로 변경 |
| P2-2 | 세션 TTL | 30분 |
| P2-3 | `api_context` 유효 기간 | 1시간 |
| P2-4 | `session_id` 클라이언트 보관 위치 | `sessionStorage` |
| P2-5 | 추천 결과에 `score` 포함 여부 | Phase 1은 `rank`만 사용 |
| P2-6 | `ignored_operations` 사용자 안내 | 패키지 A 판단 |
| P2-7 | 이력 건수 상한 | Phase 1 무제한 |
| P2-8 | 심화 인텐트(`REPLAN`·`IMAGE`) | Phase 1 범위 밖 |

### 7.4 확정 이력

| 일자 | 항목 | 결정 내용 | 출처 |
| --- | --- | --- | --- |
| 07-23 | 조건 스키마 출처 | B 자체 정의를 폐기하고 A 정의를 채택 | 경계 원칙 |
| 07-23 | 조건 데이터 구조 | `user_conditions` / `api_context` / `answer_conditions` 3층 분리 | A 회신 1 |
| 07-23 | `answer_conditions` 병합 주체 | 패키지 A. B는 저장하지 않음 | A 회신 1 |
| 07-23 | 조건 필드 수 | 14개 (`preference_tags` 제외) | A 회신 1 |
| 07-23 | `current_location` | nullable | A 회신 1 |
| 07-23 | 전달 형식 | `operations` 배열 `{op, field, value}` | A 회신 2 |
| 07-23 | 연산 종류 | **3종** (`Add`/`Update`/`Remove`). `Keep`은 미전송 | A 회신 3 |
| 07-23 | `place_tags` 자동 정리 | A가 `Remove` 연산을 함께 전송. B는 수행하지 않음 | A 회신 2 |
| 07-23 | `api_context` 유효 기간 | 1시간. B는 만료 판정만, 갱신은 A/Runtime | A 회신 4 |
| 07-23 | `api_context`와 version | `condition_version` 증가 판정에서 제외 | A 회신 4 |
| 07-23 | 세션 컨텍스트 조회 | 승인. `shown_place_ids` / `excluded_place_ids` / `last_intent` 추가 | A 회신 5 |
| 07-23 | `confirmed` 판정 | 패키지 A. 판정 기준 4종 확정 | A 회신 6 |
| 07-23 | `reset_scope` | 3종 + `null` 승인. `search_center` 변경 시 A가 `history` 동반 전송 | A 회신 7 |
| 07-23 | 이력 자동 초기화 | B는 조건 변화를 감지해 초기화하지 않음 | A 회신 7 |
| 07-23 | `operations` 생성 인텐트 | `RECOMMEND` / `MODIFY`만 | A 회신 |
| 07-23 | `place_id` 형식 | TourAPI `contentid` 문자열 | A 회신 |