# TripBranch API 및 내부 계약

## 1. 계약 구분

- **현재 공개 API**: 저장소에서 실제로 실행되는 FastAPI 계약
- **목표 공개 API**: Phase 1-A에서 도입할 통합 Chat 계약이며 아직 미구현
- **내부 계약**: Backend 모듈 사이에서만 사용하며 Frontend에 노출하지 않음

필드가 확정되지 않은 목표 계약은 `TBD`로 표시합니다.

## 2. 현재 공개 API

### `GET /api/health`

```ts
type HealthResponse = { status: string };
```

### `POST /api/interpret`

```ts
type InterpretRequest = {
  user_input: string; // 최소 길이 1
};

type InterpretedConditions = {
  location_query: string;
  preferred_categories: string[];
  weather_condition: "good" | "neutral" | "bad" | null;
  search_radius_km: number;
};
```

현재 구현은 입력 내용과 관계없이 고정 조건을 반환하는 Stub입니다.

### `POST /api/recommendations`

현재 공개 요청 모델의 이름이 `RecommendationRequest`이지만, 목표 아키텍처에서
동일 이름은 Backend 내부 추천 입력으로 사용할 예정입니다. 통합 Chat API 도입 시
공개 모델 이름 변경 여부는 `TBD`입니다.

```ts
type CurrentRecommendationRequest = InterpretedConditions & {
  shown_place_ids: string[];
};

type RecommendationItem = {
  place_id: string;
  name: string;
  category: string;
  distance_km: number;
  remaining_minutes: number | null;
  environment_type: "indoor" | "outdoor" | "mixed" | "unknown";
  recommendation_reason: string;
  warnings: string[];
};

type RecommendationResponse = {
  recommendations: RecommendationItem[];
  unverified_recommendations: RecommendationItem[];
};
```

현재 Fake/Fake 모드에서는 고정 추천을 반환합니다. 실제 Geocoding 또는 Place 모드를
사용하면 좌표 변환, 주변 검색, 노출 ID 제외, 직선거리 계산까지 수행하지만 가중치
Scoring은 아직 없습니다.

### 공통 오류

```ts
type ErrorResponse = {
  error: {
    code: string;
    message: string;
    retryable: boolean;
    details: unknown | null;
  };
};
```

현재 확인된 대표 코드는 `invalid_request`, `location_not_found`,
`weather_no_data`, `geocoding_unavailable`, `weather_unavailable`,
`provider_timeout`, `provider_unavailable`, `place_not_found`,
`internal_server_error`입니다.

## 3. 목표 공개 Chat API (`TBD`)

### `ChatRequest`

```ts
type ChatRequest = {
  chatSessionId: string;
  message: string;
  context?: ChatContext;
  debug?: boolean;
};

type ChatContext = {
  currentPlaceId?: string;
  currentLocation?: {
    latitude: number;
    longitude: number;
  };
  // Frontend가 전달할 수 있는 추가 UI 컨텍스트는 TBD
};
```

- `chatSessionId`는 Frontend가 새 채팅 생성 시 생성합니다.
- `message` 원문은 Backend 영구 저장 대상이 아닙니다.
- `context`는 신뢰 가능한 서버 상태를 대체하지 않으며 검증이 필요합니다.
- 필드 naming을 camelCase로 유지할지 현재 snake_case와 통일할지는 `TBD`입니다.

### `ChatResponse`

```ts
type ChatResponse = {
  chatSessionId: string;
  recommendationRunId?: string;
  intent: Intent;
  message: string;
  recommendations?: RecommendationResult[];
  clarification?: ClarificationRequest;
  warnings?: string[];
  debug?: ChatDebugInfo;
};

type Intent =
  | "RECOMMEND"
  | "INFO"
  | "MODIFY"
  | "COMPARE"
  | "GENERAL"
  | "OUT_OF_SCOPE";

type ClarificationRequest = {
  field: string;
  question: string;
  options?: string[];
};
```

`RecommendationResult`, `ChatDebugInfo`, HTTP status별 오류 매핑은 현재 논의 중이며
`TBD`입니다. `debug`에는 API 키, 전체 Provider 원본, 내부 프롬프트를 포함하지
않습니다.

## 4. Backend 내부 계약

### Interpret 결과

현재 구현 모델은 `InterpretedConditions`입니다. 목표 모델은 Intent, 변경 연산,
명시 조건과 신뢰도/근거를 표현해야 하지만 최종 스키마는 `TBD`입니다.

```ts
type InterpretResultDraft = {
  intent: Intent;
  conditionPatch: ConditionPatch;
  missingRequiredFields: string[];
  // confidence/evidence 구조 TBD
};
```

Interpret 결과는 추천 장소나 Provider 원본 데이터를 포함하지 않습니다.

### 내부 `RecommendationRequest`

이 모델은 Frontend와 주고받는 공개 DTO가 아니라 Recommendation Engine 입력입니다.

```ts
type RecommendationRequest = {
  chatSessionId: string;
  recommendationRunId: string;
  origin: ResolvedLocation;
  conditions: NormalizedConditions;
  candidates: Candidate[];
  shownPlaceIds: string[];
  rejectedPlaceIds: string[];
  currentContext: CurrentExternalContext;
  scoringPolicyVersion: string;
};
```

각 하위 타입과 필수/선택 여부는 `TBD`입니다. Builder는 검증·정규화·이전 상태
병합·외부 데이터 보완을 마친 뒤에만 이 모델을 생성합니다.

### `Candidate` / Feature

현재 구현의 후보 모델은 다음 필드를 가진 `PlaceCandidate`입니다.

```ts
type PlaceCandidate = {
  place_id: string;
  content_type_id?: string | null;
  name: string;
  category: string;
  latitude: number;
  longitude: number;
  address?: string | null;
  operating_hours?: string | null;
  raw_source: string;
};
```

Scoring v1용 `Candidate`는 `backend/app/domain/models.py::ScoringCandidate`로
구현되어 있으며, `PlaceCandidate`와 별도 모델입니다.

```ts
type ScoringCandidate = {
  place_id: string;
  name: string;
  category: string;
  environment_type: "indoor" | "outdoor" | "unknown";
  distance_km: number;
  place_status: "open" | "closed" | "unknown";
  remaining_open_minutes: number | null;
  raw_source: string;
};
```

`backend/app/domain/scoring.py::score_candidates()`가 이 모델을 입력받아 category
match, remaining open time, weather fit, distance 4개 Feature로 가중치 점수를
계산하고 정렬합니다. congestion, evidence confidence Feature는 아직
미구현입니다. Feature·가중치·제외 규칙 상세는
[추천 점수 설계](./design/recommendation-scoring.md)를 참고합니다. 이 엔진은
아직 `/api/recommendations` 라우트에 연결되지 않았습니다.

### `RecommendationResult`

```ts
type RecommendationResult = {
  placeId: string;
  name: string;
  score?: number;
  rank?: number;
  reason: string;
  warnings: string[];
  featureScores?: Record<string, number | null>;
  snapshot?: RecommendationSnapshot;
};
```

점수 공개 범위, Feature 설명 형식, Snapshot 상세 스키마는 `TBD`입니다.

## 5. Provider 계약

모든 Provider 메서드는 외부 I/O를 고려해 비동기이며 Fake/Real 구현이 같은 계약을
따릅니다.

| Provider | 주요 메서드 | 내부 반환 타입 |
| --- | --- | --- |
| `GeocodingProvider` | `geocode(location_query)` | `GeocodeResult` |
| `WeatherProvider` | `get_current_condition(latitude, longitude)` | `WeatherCondition` |
| `PlaceProvider` | `search_places(...)` | `list[PlaceCandidate]` |
|  | `search_by_keyword(...)` | `list[PlaceCandidate]` |
|  | `get_details(content_id, content_type_id)` | `PlaceDetails` |
|  | `find_details_by_name(...)` | `PlaceDetails` |
| `ConcentrationProvider` | `get_forecast(...)` | `ConcentrationResult` |
| `HolidayProvider` | `get_holidays(year, month)` | `HolidayResult` |

`PlaceDetails`는 정규화된 제목, 주소, 소개, 홈페이지, 연락처, 운영시간과 진단용
`raw_common`, `raw_intro`를 포함합니다. Provider 상세 계약은
[`backend/docs/provider-contract-v1.md`](../backend/docs/provider-contract-v1.md)를
참고합니다.

## 6. Tool 계약 초안

Tool은 아직 코드로 구현되지 않았습니다. 다음 이름과 책임은 방향이며 입력·출력
스키마는 `TBD`입니다.

| Tool | 책임 | 예상 Provider |
| --- | --- | --- |
| `resolveLocation` | 장소명/주소를 좌표로 해석 | Geocoding |
| `searchNearbyPlaces` | 기준 좌표 주변 후보 수집 | Place |
| `getPlaceDetails` | 특정 장소 식별 및 상세정보 조회 | Place |
| `estimateTravelTime` | 이동수단별 예상 시간 계산 | 지도/위치 Provider TBD |
| `getCurrentWeather` | 현재 날씨 조회 및 정규화 | Weather |
| `getCongestion` | 장소/지역 혼잡도 조회 | Concentration |
| `searchPlaceFeatureEvidence` | 조용함·분위기 근거 수집 | Naver Blog Search TBD |

Tool 오류는 `success`, `data`, `warnings`, `error`처럼 공통 envelope를 사용할지
현재 논의 중입니다.

## 7. 세션과 실행 식별자

| 필드 | 생성 주체 | 역할 | 현재 구현 |
| --- | --- | --- | --- |
| `chatSessionId` | Frontend | 채팅 하나 식별, 사용자 ID 아님 | 미구현 |
| `recommendationRunId` | Backend | 추천 실행·로그·Snapshot 연결 | 미구현 |

형식은 UUID 사용 방향이지만 버전, 저장 위치, 중복/재시도 정책은 `TBD`입니다.
