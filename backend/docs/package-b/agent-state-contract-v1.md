# Agent State Contract v1 (Package B)

- 작성자: 이태화
- 작성일: 2026-07-23
- 상태: Draft
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

---

## 1. 조건 저장 구조 (Agent State Schema v1)

### 1.1 조건 스키마의 출처

조건 필드는 **패키지 A의 `intent-definition.md` v0.2 6절 `Conditions`** 를
그대로 채택한다.

B는 조건의 의미를 해석하지 않으므로 자체 필드 체계를 정의하지 않는다.
A의 스키마가 변경되면 B는 이를 따라간다.

### 1.2 조건 필드 목록 (14개)

| # | 필드명 | 타입 | 값 성격 | 설명 |
| --- | --- | --- | --- | --- |
| 1 | `current_location` | string \| null | 단일 | 현재 위치 |
| 2 | `search_center` | string \| null | 단일 | 검색 기준 위치 |
| 3 | `place_types` | list[string] | 복수 | 장소 대분류 |
| 4 | `place_tags` | list[string] | 복수 | 장소 세부 태그 |
| 5 | `weather` | string \| null | 단일 | 날씨 상태 |
| 6 | `weather_intent` | string \| null | 단일 | 날씨 대응 방향 |
| 7 | `transport` | string \| null | 단일 | 이동 수단 |
| 8 | `max_travel_time` | int \| null | 단일 | 최대 이동 시간(**분**) |
| 9 | `time_available` | int \| null | 단일 | 가용 시간(**분**) |
| 10 | `environment` | string \| null | 단일 | 실내/실외 |
| 11 | `companion` | string \| null | 단일 | 동행 유형 |
| 12 | `budget` | string \| null | 단일 | 예산 |
| 13 | `exclude_tags` | list[string] | 복수 | 제외 태그 |
| 14 | `special_requirements` | list[string] | 복수 | 특수 요구사항 |

복수 필드는 `place_types`, `place_tags`, `exclude_tags`, `special_requirements`
4개다.

**B는 각 필드의 허용값을 검증하지 않는다.**
허용값 목록(`PlaceType`, `PlaceTag`, `weather` 등)은 A가 정의하며,
B는 전달받은 값을 그대로 저장한다.

### 1.3 단위 주의 사항

거리 기반 필드가 없고 **시간 기반 필드만 존재**한다.

```
max_travel_time : 분 단위 (미터 아님)
time_available  : 분 단위
```

거리 반경(예: 1km)은 조건이 아니라
A 문서 7절의 기본 정책으로 후보 처리 단계에서 적용된다.

### 1.4 미설정 값의 표현

- 단일값 필드의 미설정은 `null`로 표현한다.
- 복수 필드의 미설정은 빈 배열 `[]`로 표현한다.
- 빈 문자열, `0`, 필드 생략은 미설정 표현으로 사용하지 않는다.

**B는 조건의 기본값을 채우지 않는다.**
A 문서 7절의 기본 정책(반경 1km, 기본 이동수단 도보,
`search_center` 미설정 시 `current_location` 사용 등)은
B가 적용하지 않으며, 소비 측 패키지(AF-09 / AF-10)의 책임이다.

`null`을 그대로 전달함으로써
"사용자가 지정한 값"과 "시스템이 채운 값"을 구분할 수 있게 한다.

### 1.5 외부 갱신 필드 (협의 중)

`current_location`과 `weather`는 사용자 발화가 아니라
GPS·외부 API에서 매 턴 갱신되는 값이다.

B가 이전 턴의 값을 보관했다가 현재 값처럼 사용되면
"과거 외부 정보를 현재 정보로 오인"하는 문제가 발생한다.

**잠정 규칙 (A 확인 대기)**

- 두 필드는 State에 저장하되 `volatile` 필드로 분류한다.
- 매 실행 시 전달된 최신값으로 덮어쓴다.
- 값이 전달되지 않은 경우 이전 값을 재사용하지 않고 `null`로 취급한다.
- `condition_version` 증가 판정에서 제외한다.

확정 시 본 절을 갱신한다. (7절 P0-4)

### 1.6 AgentState 구조

```json
{
  "session_id": "sess_01J8XKQ2M7N4P9",
  "final_conditions": {
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
  "condition_version": 0,
  "last_run_id": null,
  "status": "active",
  "created_at": "2026-07-23T09:00:00+09:00",
  "updated_at": "2026-07-23T09:00:00+09:00",
  "last_active_at": "2026-07-23T09:00:00+09:00"
}
```

| 필드 | 설명 |
| --- | --- |
| `session_id` | 대화 단위 식별자 (4절) |
| `final_conditions` | 사용자 확인이 완료된 현재 조건 14개 |
| `condition_version` | 조건 변경 횟수. 동시 갱신 감지용 |
| `last_run_id` | 이 상태를 마지막으로 갱신한 실행 식별자 |
| `status` | `active` / `expired` |
| `created_at` | 세션 생성 시각 |
| `updated_at` | 조건이 마지막으로 변경된 시각 |
| `last_active_at` | 마지막 요청 수신 시각. TTL 판정 기준 (5절) |

### 1.7 규칙

- `final_conditions`는 **사용자 확인이 끝난 조건만** 담는다.
  A 문서 7절의 되묻기 단계(위치 질문, 실내/야외 추가 질문 등)에서
  확정되지 않은 조건은 저장하지 않는다.
- `condition_version`은 세션 생성 시 0에서 시작하며,
  조건이 실제로 변경된 경우에만 1 증가한다.
- 변경 요청이 있었으나 결과가 이전과 동일하면 증가시키지 않는다.
- 조건 유지만 요청된 경우에도 기존 `final_conditions`를 그대로 반환하며
  `condition_version`은 증가시키지 않는다.
- `updated_at`은 조건이 실제로 변경된 경우에만 갱신하고,
  `last_active_at`은 조건 변경 여부와 무관하게 요청 수신 시마다 갱신한다.
- 모든 시각은 ISO 8601 문자열로 저장하며 타임존을 포함한다.

## 2. 조건 변경 적용 규칙

### 2.1 변경 연산 Payload

```json
{ "op": "Update", "field": "max_travel_time", "value": 30 }
```

| 키 | 타입 | 설명 |
| --- | --- | --- |
| `op` | string | `Add` / `Update` / `Remove` / `Keep` |
| `field` | string | 1.2절 14개 필드명 중 하나 |
| `value` | any \| null | 적용할 값. `Remove`·`Keep`은 생략 가능 |

- `value`의 타입은 `field`에 따라 결정된다.
- 복수 필드의 `value`는 원소가 하나여도 리스트로 전달한다.
  (`"박물관"` 이 아니라 `["박물관"]`)

### 2.2 필드별 허용 연산

A 문서 6절 「필드별 변경 규칙」을 그대로 따른다.
**허용되지 않은 연산은 적용하지 않고 `ignored_operations`로 반환한다.**

| 필드 | 값 성격 | 허용 연산 |
| --- | --- | --- |
| `current_location` | 단일 | `Update` |
| `search_center` | 단일 | `Update` |
| `place_types` | 복수 | `Update` (전체 교체) |
| `place_tags` | 복수 | `Add` / `Remove` |
| `weather` | 단일 | `Update` |
| `weather_intent` | 단일 | `Update` |
| `transport` | 단일 | `Update` |
| `max_travel_time` | 단일 | `Update` |
| `time_available` | 단일 | `Update` |
| `environment` | 단일 | `Update` |
| `companion` | 단일 | `Update` |
| `budget` | 단일 | `Update` / `Remove` |
| `exclude_tags` | 복수 | `Add` / `Remove` |
| `special_requirements` | 복수 | `Add` / `Remove` |

**복수 필드라고 해서 `Add`를 허용하지 않는다.**
`place_types`는 복수 필드이지만 전체 교체만 사용한다.
"카페 말고 맛집"은 `place_types` 전체 교체이고,
"박물관도 추가"는 `place_tags`에 `Add`이다.

`Keep`은 모든 필드에서 무동작이므로 위 표의 제약을 받지 않는다.

### 2.3 연산별 동작

| 연산 | 단일 필드 | 복수 필드 |
| --- | --- | --- |
| `Update` | 값 전체 교체 | 리스트 전체 교체 |
| `Add` | (허용 필드 없음) | 리스트에 추가. 중복 원소는 무시 |
| `Remove` | `null`로 되돌림 (`budget`만 해당) | `value` 있으면 해당 원소 제거<br>`value` 없으면 리스트 전체 비움 |
| `Keep` | 변경 없음 | 변경 없음 |

**존재하지 않는 원소에 대한 `Remove`**
오류로 처리하지 않고 무시하며, 결과가 변하지 않으므로
`condition_version`도 증가시키지 않는다.

**`Keep`** *(A 확인 대기 — 7절 P0-3)*
State를 변경하지 않으며 `condition_version`도 증가시키지 않는다.
A가 명시적으로 유지를 판단했다는 신호이므로 변경 기록에는 남긴다.
A 문서 6절에는 `Keep`이 없으므로 확정 시 본 항목을 갱신한다.

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

```json
"ignored_operations": [
  { "operation": { "op": "Add", "field": "place_types", "value": ["cafe"] },
    "reason": "unsupported_operation" }
]
```

**B는 값을 변환하거나 추측하지 않는다.**
문자열 `"30분"`을 `30`으로 변환하지 않으며,
`value: null`인 `Update`를 `Remove`로 해석하지 않는다.
허용값 목록에 없는 값이라도 검증하지 않고 저장한다.

### 2.6 요청 단위 예외 처리

| 상황 | 처리 |
| --- | --- |
| `operations`가 빈 배열 | State 변경 없음, 기존 조건 그대로 반환 |
| `operations` 키 없음 | 빈 배열과 동일 |
| `session_id` 없음 | 새 세션 생성 후 빈 State에 적용 |
| `session_id` 만료 | 새 세션 생성 후 빈 State에 적용 (5절) |
| `confirmed: false` | State에 반영하지 않고 현재 State를 반환 |

조건 변경 없이 재추천만 요청하는 경우에도
기존 `final_conditions`는 그대로 유지된다.

### 2.7 condition_version 증가 기준

적용 전후의 `final_conditions`를 전체 비교하여 판정한다.

- 결과가 달라진 경우에만 1 증가시킨다.
- 빈 연산, `Keep`만 있는 경우, 전부 무효 처리된 경우,
  적용 결과가 이전과 동일한 경우에는 증가시키지 않는다.
- `volatile` 필드(`current_location`, `weather`)의 변경은
  판정에서 제외한다. (1.5절)
- `updated_at`도 동일한 기준으로 갱신한다.

### 2.8 변경 기록

```json
{
  "session_id": "sess_01J8XKQ2M7N4P9",
  "run_id": "run_01J8XKQ5A1B2C3",
  "seq": 1,
  "op": "Update",
  "field": "max_travel_time",
  "before_value": null,
  "after_value": 30,
  "applied_at": "2026-07-23T09:05:12+09:00"
}
```

- 유효한 연산은 결과 변화가 없어도 기록한다.
- 무효한 연산은 기록하지 않고 `ignored_operations`로만 반환한다.
- 사용자 원문 발화와 LLM 원문 응답은 기록하지 않는다.

### 2.9 적용 예시

```
[예시 1] 조건 추가
before:  { place_types: ["restaurant"], max_travel_time: null }
ops:     [{ op: "Update", field: "max_travel_time", value: 30 }]
after:   { place_types: ["restaurant"], max_travel_time: 30 }
version: 3 → 4

[예시 2] 대분류 교체 ("카페 말고 맛집")
before:  { place_types: ["cultural_facility"], place_tags: ["박물관"] }
ops:     [{ op: "Update", field: "place_types", value: ["restaurant"] }]
after:   { place_types: ["restaurant"], place_tags: ["박물관"] }
version: 4 → 5
※ place_tags는 별도 연산이 없으면 유지된다.

[예시 3] 세부 태그 추가 ("박물관도 추가")
before:  { place_tags: ["미술관"] }
ops:     [{ op: "Add", field: "place_tags", value: ["박물관"] }]
after:   { place_tags: ["미술관", "박물관"] }
version: 5 → 6

[예시 4] 변경 없는 재추천 ("다른 곳 추천해줘")
before:  { place_types: ["restaurant"], max_travel_time: 30 }
ops:     []
after:   { place_types: ["restaurant"], max_travel_time: 30 }
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

두 이력은 초기화 범위가 다르므로 별도 구조로 관리한다. (5절 참조)
Phase 1에서는 제외 목적으로 동일하게 사용하지만,
구조를 분리해 두어 이후 스코어링 정책에서 다르게 취급할 수 있도록 한다.

### 3.2 이력 구조

```json
{
  "session_id": "sess_01J8XKQ2M7N4P9",
  "recommended": [
    { "place_id": "p_001", "run_id": "run_A", "rank": 1,
      "shown_at": "2026-07-23T09:05:12+09:00" }
  ],
  "rejected": [
    { "place_id": "p_001", "run_id": "run_B", "reason_code": "too_far",
      "rejected_at": "2026-07-23T09:07:30+09:00" }
  ],
  "updated_at": "2026-07-23T09:07:30+09:00"
}
```

**recommended 항목**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `place_id` | string | 장소 식별자 |
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

`recommended`와 `rejected`는 append-only 리스트이며 기존 항목을 수정하지 않는다.

### 3.3 제외 ID 목록

```
exclusion_place_ids = recommended의 place_id ∪ rejected의 place_id
```

- 중복은 제거하여 반환한다.
- 순서는 보장하지 않는다.
- 추천 이력이 없는 `place_id`가 `rejected`로 전달되어도 검증하지 않고 저장한다.

### 3.4 중복 처리

- 동일한 `place_id`가 다시 전달되어도 오류로 처리하지 않고 리스트에 추가한다.
- 중복 제거는 `exclusion_place_ids` 생성 시점에만 수행한다.

### 3.5 이력 누적 범위

- 이력은 세션 단위로 누적한다.
- **B는 조건 변화를 감지하여 이력을 자동으로 초기화하지 않는다.**
  초기화가 필요한 경우 패키지 A가 `reset_scope`를 명시적으로 전달한다. (5절)
- Phase 1에서는 이력 건수 상한을 두지 않는다.

### 3.6 책임 범위 밖

B는 다음을 수행하지 않는다.

| 항목 | 담당 |
| --- | --- |
| 거절 사유의 해석 | 패키지 A |
| 추천 순위 계산 | 패키지 D (AF-10) |
| 장소 상세 정보(이름·주소·좌표) 저장 | 패키지 C |
| 조건 변화 기반 이력 자동 초기화 | 패키지 A의 `reset_scope` 지시 |

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
- 빈 `AgentState` 생성 (모든 조건 `null` / `[]`, `condition_version = 0`)
- 빈 이력 생성 (`recommended: []`, `rejected: []`)
- 응답에 `session_created: true` 포함

**어떤 경우에도 오류를 반환하지 않는다.**
익명 세션에서 만료는 오류가 아니라 정상적인 생애주기이므로,
신규 세션을 발급하고 정상 응답을 반환한다.

### 5.3 세션 유지

- 서버는 `session_id`를 키로 State와 이력을 보관한다.
- 클라이언트는 `session_id` 문자열을 보관하고 매 요청에 포함한다.
- 보관 위치는 `sessionStorage`를 기준으로 한다. (프론트 협의 항목)

**시각 필드의 구분**

| 필드 | 갱신 기준 | 용도 |
| --- | --- | --- |
| `updated_at` | 조건이 실제로 변경된 경우에만 | 마지막 조건 변경 시점 |
| `last_active_at` | 요청 수신 시마다 | TTL 판정 |

조건 변경 없는 재추천 요청이 반복되어도 세션이 만료되지 않도록
두 필드를 분리한다.

### 5.4 세션 만료 (TTL)

```
TTL = last_active_at 기준 30분
판정 시점 = 요청 수신 시 (주기적 스캔을 수행하지 않는다)
```

- 만료된 세션은 `status`를 `expired`로 표시한다.
- 만료된 State는 복구하지 않으며, 신규 세션으로 시작한다.
- Phase 1에서는 만료된 세션 데이터를 즉시 삭제하지 않는다.
- TTL 값은 실사용 후 조정 가능하다.

**Phase 1 제약:** 인메모리 저장이므로 서버 재시작 시 모든 세션이 소멸한다.
이는 의도된 제약이며 저장소 교체 시 해소된다.

### 5.5 초기화 범위

| 종류 | `reset_scope` | 조건 | 추천 이력 | 거절 이력 | session_id |
| --- | --- | --- | --- | --- | --- |
| Soft Reset | `soft` | 초기화 | 유지 | 유지 | 유지 |
| History Reset | `history` | 유지 | 초기화 | **유지** | 유지 |
| Full Reset | `full` | 초기화 | 초기화 | 초기화 | **신규 발급** |

**Soft Reset**
조건만 초기화하고 이력은 유지한다.
조건이 바뀌더라도 이미 노출된 장소를 다시 보여주지 않기 위함이다.

**History Reset**
추천 이력만 비우고 거절 이력은 유지한다.
사용자가 명시적으로 거부한 장소를 재노출하지 않기 위함이다.

**Full Reset**
기존 세션을 만료 처리하고 신규 세션을 발급한다.
TTL 만료도 결과적으로 동일하게 동작한다.

**판정 주체**
어떤 발화가 어느 초기화에 해당하는지 판정하는 것은 패키지 A의 책임이다.
B는 전달받은 `reset_scope` 값에 따라 실행만 하며 발화를 해석하지 않는다.

**적용 순서**
`reset_scope`와 `operations`가 함께 전달된 경우
`reset_scope`를 먼저 적용한 뒤 `operations`를 적용한다.

**초기화 기록**

```json
{
  "session_id": "sess_01J8XKQ2M7N4P9",
  "run_id": "run_01J8XKQ5A1B2C3",
  "seq": 0,
  "op": "Reset",
  "field": null,
  "reset_scope": "soft",
  "applied_at": "2026-07-23T09:10:00+09:00"
}
```

### 5.6 저장 범위

**저장한다**
- 구조화된 조건값 (`final_conditions`)
- `place_id`
- 식별자 (`session_id`, `run_id`, `trace_id`)
- 조건 변경 기록의 `before_value` / `after_value`
- 실행 메타데이터 (지연 시간, 토큰 사용량, 오류 유형)
- 버전 정보 (`prompt_version`, `scoring_version`, `variant_id`)

**저장하지 않는다**
- 사용자 원문 발화
- LLM 원문 응답 텍스트
- Chain-of-Thought 등 내부 추론 과정
- 장소 상세 정보 (이름·주소·좌표·영업시간)

원문을 저장하지 않아도 `ChangeLog`의 구조화된 값과 `run_id`로
조건 변경 경위를 재구성할 수 있다.

## 6. A → B 전달 계약 초안

### 6.0 계약의 형태

본 계약은 패키지 간 데이터 형식을 정의한다.
Phase 1에서는 동일 프로세스 내 함수 호출로 구현하며,
HTTP 엔드포인트 노출은 AF-05 Agent Runtime의 책임 범위다.
패키지 B는 엔드포인트를 직접 정의하지 않는다.

본 절은 세 개의 계약으로 구성된다.

| 계약 | 방향 | 성격 |
| --- | --- | --- |
| 6.1 / 6.2 조건 적용 | A → B | 상태 변경 |
| 6.3 세션 컨텍스트 조회 | A → B | 읽기 전용 |
| 6.4 추천 결과 기록 | Runtime → B | 이력 기록 |

### 6.1 조건 적용 요청 (A → B)

```json
{
  "session_id": "sess_01J8XKQ2M7N4P9",
  "intent": "MODIFY",
  "confirmed": true,
  "reset_scope": null,
  "operations": [
    { "op": "Update", "field": "max_travel_time", "value": 30 }
  ],
  "rejected_places": [
    { "place_id": "p_001", "reason_code": "too_far" }
  ],
  "prompt_version": "intent_v1.2"
}
```

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `session_id` | string \| null | O | 없거나 `null`이면 B가 신규 발급 |
| `intent` | string | O | A가 분류한 6종 중 하나. B는 기록 용도로만 저장 |
| `confirmed` | bool | O | 사용자 확인 완료 여부 |
| `reset_scope` | string \| null | O | `soft` / `history` / `full` / `null` |
| `operations` | list | O | 변경 연산 목록. 없으면 `[]` |
| `rejected_places` | list | O | 이번 턴 거절 장소. 없으면 `[]` |
| `prompt_version` | string \| null | X | LLMOps 기록용 |

- "필수"는 키의 존재를 의미하며, 값이 `null` 또는 `[]`인 것은 허용한다.
- `intent`는 저장 용도로만 사용하며 B의 동작 분기에 사용하지 않는다.
- `confirmed`가 `false`인 경우 `operations`를 State에 반영하지 않고
  현재 State를 그대로 반환한다.
- 거절 장소는 `operations`가 아닌 `rejected_places`로 전달한다.
  조건 변경과 이력 기록은 성격이 다르기 때문이다.

### 6.2 조건 적용 응답 (B → A)

```json
{
  "session_id": "sess_01J8XKQ2M7N4P9",
  "run_id": "run_01J8XKQ5A1B2C3",
  "session_created": false,
  "final_conditions": {
    "current_location": "강남역",
    "search_center": null,
    "place_types": ["restaurant"],
    "place_tags": ["카페"],
    "weather": "rain",
    "weather_intent": "AVOID",
    "transport": "walk",
    "max_travel_time": 30,
    "time_available": null,
    "environment": "indoor",
    "companion": null,
    "budget": null,
    "exclude_tags": [],
    "special_requirements": []
  },
  "condition_version": 5,
  "condition_changed": true,
  "applied_operations": [
    { "op": "Update", "field": "max_travel_time",
      "before_value": null, "after_value": 30 }
  ],
  "ignored_operations": [],
  "exclusion_place_ids": ["p_001", "p_002", "p_003"],
  "reset_applied": null
}
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `session_id` | string | 신규·기존 무관하게 항상 포함 |
| `run_id` | string | 이번 실행 식별자 |
| `session_created` | bool | 세션 신규 발급 여부 |
| `final_conditions` | object | 병합 완료된 현재 조건 14개 전체 |
| `condition_version` | int | 병합 후 조건 버전 |
| `condition_changed` | bool | 이번 요청으로 조건이 실제 변경됐는지 |
| `applied_operations` | list | 적용된 연산과 전후 값 |
| `ignored_operations` | list | 무시된 연산과 사유 |
| `exclusion_place_ids` | list[string] | 추천 제외 대상 ID |
| `reset_applied` | string \| null | 적용된 초기화 종류 |

**조건의 단일 기준은 B다.**
A는 부분 변경분을 자체 조립하지 않고
`final_conditions`를 그대로 사용한다.

`condition_changed`는 A가 버전을 직접 비교하지 않아도 되도록
B가 판정 결과를 함께 제공하는 값이다.

`applied_operations`의 전후 값은
A가 사용자에게 변경 내용을 안내할 때 사용한다.

### 6.3 세션 컨텍스트 조회 (A → B, 읽기 전용)

A 문서 5절 판별 규칙에서 `MODIFY`와 `COMPARE`는
"이전 추천 이력 존재"를 전제 조건으로 한다.
해당 이력은 B가 보관하므로, A가 인텐트를 분류하기 전에 조회가 필요하다.

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
  "recommended_count": 3,
  "last_recommended_run_id": "run_01J8XKQ5A1B2C3",
  "final_conditions": { "...14개 필드..." },
  "condition_version": 5
}
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `session_exists` | bool | 세션이 존재하고 유효한지 |
| `has_recommendation` | bool | 추천 이력이 1건 이상 존재하는지 |
| `recommended_count` | int | 지금까지 노출된 장소 수 |
| `last_recommended_run_id` | string \| null | 마지막 추천이 발생한 실행 |
| `final_conditions` | object | 현재 조건 전체 |
| `condition_version` | int | 현재 조건 버전 |

**규칙**

- 이 호출은 State를 변경하지 않는다.
- `run_id`를 발급하지 않으며 `last_active_at`도 갱신하지 않는다.
- 세션이 없거나 만료된 경우에도 오류를 반환하지 않고
  `session_exists: false`, `has_recommendation: false`로 응답한다.
  이때 세션을 새로 생성하지 않는다.
- 호출 시점은 A의 인텐트 분류 직전이다.

**전체 호출 순서**

```
1. A: get_session_context(session_id)       ← 읽기 전용 (6.3)
2. A: 인텐트 분류 및 조건 해석
3. A: apply(StateApplyRequest)              ← 상태 변경 (6.1 / 6.2)
4. C·D: 추천 실행
5. Runtime: record_recommendation(...)      ← 이력 기록 (6.4)
```

### 6.4 추천 결과 기록 (Agent Runtime → B)

조건 적용 계약은 추천 실행 이전 단계이므로,
실제 노출된 추천 결과를 별도로 전달받아야 이력이 축적된다.

**요청**

```json
{
  "session_id": "sess_01J8XKQ2M7N4P9",
  "run_id": "run_01J8XKQ5A1B2C3",
  "recommended": [
    { "place_id": "p_011", "rank": 1 },
    { "place_id": "p_012", "rank": 2 }
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

`run_id`는 6.1 요청에서 발급된 값을 그대로 사용하며,
이를 통해 조건 변경 기록·추천 이력·실행 메타데이터가 하나의 실행으로 묶인다.

### 6.5 실패 처리 원칙

| 실패 지점 | 추천 응답 | 처리 |
| --- | --- | --- |
| 세션 컨텍스트 조회 실패 | 계속 | 빈 컨텍스트로 응답 (오류 아님) |
| State 조회·병합 실패 | 중단 | 예외를 상위로 전달 |
| 추천 이력 기록 실패 | 계속 | 로그 기록 후 통과 |
| 실행 메타데이터 기록 실패 | 계속 | 로그 기록 후 통과 |

기록성 작업의 실패는 사용자 응답 경로를 중단시키지 않는다.

### 6.6 계약 범위 밖

| 항목 | 담당 |
| --- | --- |
| 사용자 원문 발화 | 저장하지 않음 |
| 장소 상세 정보 | 패키지 C |
| 추천 이유·설명 문장 | 패키지 D, A |
| 외부 API 응답 원본 | 패키지 C |
| 조건 기본값 적용 (A 문서 7절 정책) | 패키지 C, D |
| 조건 허용값 검증 | 패키지 A |
| HTTP 엔드포인트 정의 | AF-05 Agent Runtime |

## 7. 미확정 항목 (협의 필요)

### 7.0 원칙

미확정 항목은 공란으로 두지 않고 **잠정 결정**을 함께 기재한다.
잠정 결정을 기준으로 구현을 진행하며, 확정 시 해당 부분만 수정한다.

우선순위 기준:

| 등급 | 기준 |
| --- | --- |
| P0 | 미확정 시 State Merge 구현을 시작할 수 없음 |
| P1 | 구현은 가능하나 통합 테스트 전 확정 필요 |
| P2 | Phase 1 진행에 영향 없음 |

### 7.1 P0 — 구현 착수 전 확정 필요

| # | 항목 | 잠정 결정 | 상태 |
| --- | --- | --- | --- |
| 1 | 조건 스키마 채택 | A 문서 6절 `Conditions` 14개 필드를 그대로 사용 | 미확정 |
| 2 | 필드별 허용 연산 | A 문서 6절 변경 규칙표를 그대로 고정. 위반 시 `unsupported_operation` | 미확정 |
| 3 | `Keep` 연산 포함 여부 | 4종(`Add`/`Update`/`Remove`/`Keep`)으로 가정. A 문서에는 3종 | 미확정 |
| 4 | `current_location`·`weather` 저장 여부 | `volatile` 필드로 분류, 매 실행 최신값 사용, version 판정 제외 | 미확정 |
| 5 | 세션 컨텍스트 조회 계약 | `get_session_context()` 읽기 전용 함수 추가 (6.3절) | 미확정 |
| 6 | `confirmed` 판정 주체 | 패키지 A | 미확정 |
| 7 | `reset_scope` 판정 주체·값 | 패키지 A / `soft`·`history`·`full`·`null` | 미확정 |
| 8 | 거절 장소 전달 경로 | `operations`가 아닌 `rejected_places` 필드 | 미확정 |
| 9 | 기본값 적용 주체 | A 문서 7절 정책은 B가 적용하지 않고 소비 측에서 적용 | 미확정 |

### 7.2 P1 — 통합 전 확정 필요

| # | 항목 | 잠정 결정 | 대상 |
| --- | --- | --- | --- |
| 10 | `operations`를 생성하는 인텐트 범위 | `RECOMMEND` / `MODIFY`로 가정. 나머지는 빈 배열 | A |
| 11 | `reason_code` 목록 | nullable, B는 검증하지 않음 | A |
| 12 | `place_id` 형식 | TourAPI `contentid` 기준 | A·C·D |
| 13 | 추천 결과 기록 호출 주체 | AF-05 Agent Runtime | Runtime |
| 14 | 식별자 생성 방식 | ULID 우선, 의존성 제약 시 `uuid4` | 팀 공통 |
| 15 | `get_session_context` 반환 항목 | 6.3절 6개 필드. A 요청 시 추가 | A |

### 7.3 P2 — Phase 1 진행에 영향 없음

| # | 항목 | 잠정 결정 |
| --- | --- | --- |
| 16 | `trace_id` 명칭 | v1 유지. 관측 도구 도입 시 `span_id`로 변경 |
| 17 | 세션 TTL | 30분. 실사용 후 조정 |
| 18 | `session_id` 클라이언트 보관 위치 | `sessionStorage` |
| 19 | `session_created` 사용자 안내 여부 | 패키지 A 판단 |
| 20 | 추천 결과에 `score` 포함 여부 | Phase 1은 `rank`만 사용 |
| 21 | `ignored_operations` 사용자 안내 여부 | 패키지 A 판단 |
| 22 | 이력 건수 상한 | Phase 1 무제한. 저장소 교체 시 재검토 |
| 23 | 심화 인텐트(`REPLAN`·`IMAGE`) 대응 | Phase 1 범위 밖. 조건 스키마 재사용 예정 |

### 7.4 확정 이력

| 일자 | 항목 | 결정 내용 |
| --- | --- | --- |
| 2026-07-23 | 조건 변경 연산 | `Add` / `Update` / `Remove` / `Keep` 4종 사용 (A 문서 미반영, 재확인 필요) |
| 2026-07-23 | 조건 스키마 출처 | B 자체 필드 정의를 폐기하고 A `intent-definition.md` v0.2 6절을 채택 |