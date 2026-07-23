# 조건 스키마 v0.1

## 문서 정보

| 항목 | 값 |
|------|-----|
| 버전 | v0.1 |
| 상태 | 초안 (Draft) |
| 최종 수정 | 2026-07-22 |
| 경로 | `docs/design/conditions-schema.md` |

---

## 1. Intent와 Conditions 관계

```
사용자 입력
    ↓
Intent (목적 1개)
    ↓
Conditions (조건 N개, Intent가 RECOMMEND/MODIFY일 때 추출)
```

- Intent: 사용자가 **무엇을** 하고 싶은가
- Conditions: **어떤 조건으로** 하고 싶은가
- RECOMMEND, MODIFY에서 Conditions를 사용한다
- INFO, COMPARE, GENERAL, OUT_OF_SCOPE는 별도 스키마를 사용한다

---

## 2. Conditions 필드 정의

```typescript
interface Conditions {
  // 위치
  current_location: string | null;
  search_center: string | null;

  // 장소 유형 (복수 가능)
  place_types: PlaceType[];
  place_tags: PlaceTag[];

  // 날씨
  weather: "rain" | "snow" | "hot" | "cold" | "good" | null;
  weather_intent: "AVOID" | "ENJOY" | "IGNORE" | null;

  // 이동
  transport: "walk" | "public" | "car" | null;
  max_travel_time: number | null;

  // 시간
  time_available: number | null;

  // 환경
  environment: "indoor" | "outdoor" | "any" | null;

  // 동행
  companion: "solo" | "couple" | "friend" | "parent" | "child" | "pet" | null;

  // 예산
  budget: "free" | string | null;

  // 태그 (복수 가능)
  exclude_tags: string[];
  special_requirements: string[];


type PlaceType =
  | "attraction"         // 관광지 (contentTypeId: 12)
  | "cultural_facility"  // 문화시설 (contentTypeId: 14)
  | "festival"           // 축제/공연/행사 (contentTypeId: 15)
  | "leisure"            // 레포츠 (contentTypeId: 28)
  | "shopping"           // 쇼핑 (contentTypeId: 38)
  | "restaurant";        // 음식점/카페 (contentTypeId: 39)

type PlaceTag =
  // attraction 하위
  | "공원" | "궁궐" | "산" | "해변" | "호수" | "계곡"
  | "전망대" | "테마파크" | "동물원" | "수목원"
  | "사찰" | "성곽" | "마을" | "둘레길"
  | "전통체험" | "공예체험" | "웰니스"
  // cultural_facility 하위
  | "박물관" | "미술관" | "도서관" | "공연장" | "과학관" | "전시관"
  // festival 하위
  | "축제" | "전시회" | "공연" | "콘서트"
  // shopping 하위
  | "시장" | "쇼핑몰" | "면세점" | "백화점"
  // restaurant 하위
  | "한식" | "일식" | "중식" | "양식" | "카페" | "찻집" | "주점" | "분식";
}
```

---

## 3. 상태 구조

### initial_conditions

첫 RECOMMEND 요청 시 LLM이 추출한 최초 조건.

```json
{
  "current_location": "37.5665,126.9780",
  "search_center": "경복궁",
  "place_types": ["restaurant"],
  "place_tags": ["카페"],
  "weather": "rain",
  "weather_intent": "AVOID",
  "transport": "walk",
  "max_travel_time": null,
  "time_available": null,
  "environment": "indoor",
  "companion": null,
  "budget": null,
  "exclude_tags": [],
  "special_requirements": []
}
```

### current_conditions

MODIFY를 거치며 갱신된 현재 유효 조건. 추천 엔진은 항상 이 값을 사용한다.

```json
{
  "current_location": "37.5665,126.9780",
  "search_center": "경복궁",
  "place_types": ["restaurant"],
  "place_tags": ["카페"],
  "weather": "rain",
  "weather_intent": "AVOID",
  "transport": "walk",
  "max_travel_time": 15,
  "time_available": null,
  "environment": "indoor",
  "companion": null,
  "budget": "free",
  "exclude_tags": [],
  "special_requirements": []
}
```

### missing_conditions

추천 실행에 필수이지만 아직 확보되지 않은 조건.

| 필드 | 필수 여부 | 미확보 시 처리 |
|------|-----------|---------------|
| `current_location` | 필수 | 사용자에게 질문 |
| `search_center` | 선택 | null이면 current_location 사용 |
| `place_types` | 선택 | 빈 배열이면 전체 유형 검색 |
| `weather` | 선택 | API 호출 → 실패 시 가중치 제외 |

```
missing_conditions 처리 흐름:
  ① 필수 조건 미확보 → 사용자에게 질문 (추천 진행하지 않음)
  ② 선택 조건 미확보 → 기본값 적용 또는 해당 가중치 제외
```

---

## 4. 조건 변경 연산

### 4가지 처리 방식

| 처리 방식 | 설명 | 예시 |
|-----------|------|------|
| **Add** | 기존 조건은 유지하고 새로운 항목을 추가 | "주차 가능한 곳" → special_requirements에 "주차" 추가 |
| **Update** | 같은 필드의 값을 새로운 값으로 교체 | "카페 말고 맛집" → place_tags 교체 |
| **Remove** | 특정 조건을 명시적으로 해제 | "가격 상관없어" → budget을 null로 |
| **Keep** | 언급되지 않은 조건은 그대로 유지 | "더 가까운 곳" → 나머지 조건 전부 유지 |

### 핵심 원칙

```
1. 새로운 항목이면 추가 (Add)
2. 같은 필드이면 최신 값으로 교체 (Update)
3. 사용자가 명시적으로 해제하면 삭제 (Remove)
4. 언급하지 않은 조건은 그대로 유지 (Keep)
```

### 필드별 적용 방식

| 필드 | 단일/복수 | 변경 시 처리 | 해제 시 처리 |
|------|-----------|-------------|-------------|
| `current_location` | 단일 | Update | — (필수 필드) |
| `search_center` | 단일 | Update | Remove → null (current_location 사용) |
| `place_types` | 복수 | Update (전체 교체) | Remove → 빈 배열 (전체 검색) |
| `place_tags` | 복수 | Add / Update / Remove | Remove → 빈 배열 |
| `weather` | 단일 | Update | Remove → null |
| `weather_intent` | 단일 | Update | Remove → null |
| `transport` | 단일 | Update | Remove → null (기본값 walk 적용) |
| `max_travel_time` | 단일 | Update | Remove → null (기본 반경 적용) |
| `time_available` | 단일 | Update | Remove → null |
| `environment` | 단일 | Update | Remove → null |
| `companion` | 단일 | Update | Remove → null |
| `budget` | 단일 | Update | Remove → null (예산 필터 미적용) |
| `exclude_tags` | 복수 | Add | Remove (특정 항목 제거) |
| `special_requirements` | 복수 | Add | Remove (특정 항목 제거) |

### place_types와 place_tags의 차이

| 필드 | 변경 시 동작 | 이유 |
|------|-------------|------|
| `place_types` | **Update** (전체 교체) | "카페 말고 맛집"은 기존 유형을 대체하는 의도 |
| `place_tags` | **Add** (누적) 또는 **Remove** (제거) | "박물관도 보고 싶어"는 기존 태그에 추가하는 의도 |

단, place_types가 교체되면 소속되지 않는 place_tags는 자동 제거된다.

---

## 5. 연산 적용 예시

### 예시 1: 조건 추가 (Add)

```
current_conditions:
  place_types: ["restaurant"]
  place_tags: ["카페"]
  special_requirements: []

사용자: "주차 가능한 곳"

처리:
  special_requirements: Add "주차"

결과:
  place_types: ["restaurant"]         (Keep)
  place_tags: ["카페"]                (Keep)
  special_requirements: ["주차"]      (Add)
```

### 예시 2: 조건 교체 (Update)

```
current_conditions:
  place_types: ["restaurant"]
  place_tags: ["카페"]
  budget: null

사용자: "카페 말고 맛집, 무료인 곳"

처리:
  place_tags: Remove "카페"  (명시적 제거)
  budget: Update "free"

결과:
  place_types: ["restaurant"]   (Keep)
  place_tags: []                (Remove "카페")
  budget: "free"                (Update)
```

### 예시 3: 조건 해제 (Remove)

```
current_conditions:
  budget: "free"
  environment: "indoor"

사용자: "가격 상관없어, 야외도 괜찮아"

처리:
  budget: Remove → null
  environment: Update "any"

결과:
  budget: null         (Remove)
  environment: "any"   (Update)
```

### 예시 4: 유지 (Keep)

```
current_conditions:
  search_center: "경복궁"
  place_types: ["restaurant"]
  place_tags: ["카페"]
  companion: "parent"
  budget: "free"

사용자: "더 가까운 곳"

처리:
  max_travel_time: Update (감소)

결과:
  search_center: "경복궁"      (Keep)
  place_types: ["restaurant"]   (Keep)
  place_tags: ["카페"]          (Keep)
  companion: "parent"           (Keep)
  budget: "free"                (Keep)
  max_travel_time: 15           (Update)
```

### 예시 5: place_types 교체에 따른 place_tags 자동 정리

```
current_conditions:
  place_types: ["cultural_facility", "restaurant"]
  place_tags: ["박물관", "카페"]

사용자: "음식점 빼고 쇼핑으로"

처리:
  place_types: Update → ["cultural_facility", "shopping"]
  place_tags: "카페"는 restaurant 소속이므로 자동 Remove

결과:
  place_types: ["cultural_facility", "shopping"]   (Update)
  place_tags: ["박물관"]                            (자동 Remove "카페")
```

---

## 6. 상태 전이 다이어그램

```
[시작]
    ↓
RECOMMEND → initial_conditions 생성 → current_conditions = initial_conditions
    ↓
MODIFY → Add/Update/Remove 적용 → current_conditions 갱신 (나머지 Keep)
    ↓
MODIFY → Add/Update/Remove 적용 → current_conditions 갱신 (나머지 Keep)
    ↓
... (반복)
    ↓
새 RECOMMEND → initial_conditions 재생성 → current_conditions 초기화
```

---

## 7. MODIFY에서의 전체 처리 흐름

```
사용자 MODIFY 입력
    ↓
LLM이 condition_changes 추출 (변경된 필드만)
    ↓
각 필드별 연산 판별:
  - 새 값이 있으면 → Update 또는 Add
  - 명시적 해제면 → Remove
  - 언급 없으면 → Keep
    ↓
current_conditions에 반영
    ↓
place_types 변경 시 → 소속 안 되는 place_tags 자동 정리
    ↓
갱신된 current_conditions로 재추천
```