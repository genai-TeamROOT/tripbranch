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
  score: number;
  feature_scores: Record<string, number | null>; // Feature별 원점수(weather/remaining_operating_time/distance)
  weights_used: Record<string, number>; // 실제 적용된 가중치(재분배 후, 결측 Feature는 키 자체가 없음)
};

type RecommendationResponse = {
  recommendations: RecommendationItem[];
  unverified_recommendations: RecommendationItem[];
  elapsed_ms: number; // 전체 추천 파이프라인 처리시간(ms)
};
```

`elapsed_ms`는 위치 해석 시작부터 장소·날씨·공휴일 조회, Candidate 변환,
Scoring, 상위 후보 집중률 후조회와 응답 조립이 끝날 때까지 Backend에서 측정한
wall-clock 시간입니다. HTTP 전송시간과 Frontend 렌더링 시간은 포함하지 않습니다.

`score`/`feature_scores`/`weights_used`는
`backend/app/domain/evidence.py::build_evidence()`가 만든
`RecommendationEvidence`를 그대로 반영한 값입니다(D-028). `feature_scores`는
`contributions`의 `{feature: score}`를, `weights_used`는 `{feature: weight}`를
평탄화한 값이며, 날씨나 남은 운영시간이 결측이었던 Feature는 `weights_used`
키 자체에서 빠집니다. 자연어 추천 이유(`recommendation_reason`)는 아직 고정
템플릿 문자열이며 Feature 근거를 문장으로 변환하는 로직은 별도 범위입니다.

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
  chat_session_id: string;
  message: string;
  context?: ChatContext;
  debug?: boolean;
};

type ChatContext = {
  current_place_id?: string;
  current_location?: {
    latitude: number;
    longitude: number;
  };
  // Frontend가 전달할 수 있는 추가 UI 컨텍스트는 TBD
};
```

- `chat_session_id`는 Frontend가 새 채팅 생성 시 생성합니다.
- `message` 원문은 Backend 영구 저장 대상이 아닙니다.
- `context`는 신뢰 가능한 서버 상태를 대체하지 않으며 검증이 필요합니다.
- Backend Python과 JSON 필드는 프로젝트 공통 규칙에 따라 `snake_case`를 사용합니다.

### `ChatResponse`

```ts
type ChatResponse = {
  chat_session_id: string;
  recommendation_run_id?: string;
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
  condition_patch: ConditionPatch;
  missing_required_fields: string[];
  // confidence/evidence 구조 TBD
};
```

Interpret 결과는 추천 장소나 Provider 원본 데이터를 포함하지 않습니다.

### 내부 `RecommendationRequest`

이 모델은 Frontend와 주고받는 공개 DTO가 아니라 Recommendation Engine 입력입니다.

```ts
type RecommendationRequest = {
  chat_session_id: string;
  recommendation_run_id: string;
  origin: ResolvedLocation;
  conditions: NormalizedConditions;
  candidates: Candidate[];
  shown_place_ids: string[];
  rejected_place_ids: string[];
  current_context: CurrentExternalContext;
  scoring_policy_version: string;
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
  lcls_systm1?: string | null;
  lcls_systm2?: string | null;
  lcls_systm3?: string | null;
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
type OperatingHours = {
  open_time: string;  // "HH:MM", 당일 개장 시각
  close_time: string; // "HH:MM", 당일 마감 시각
};

type ScoringCandidate = {
  place_id: string;
  name: string;
  category: string;
  environment_type: "indoor" | "outdoor" | "unknown";
  distance_km: number;
  operating_hours: OperatingHours | null; // null이면 운영시간 미확인
  raw_source: string;
};
```

`backend/app/domain/scoring.py::score_candidates(candidates, *, now, ...)`가 이
모델을 입력받아 weather fit, 남은 운영시간(remaining_operating_time), distance
3개 Feature로 가중치 점수를 계산하고 정렬합니다. 운영 유무(폐점 여부)는 `now`와
`operating_hours`를 비교해 최종 하드 필터로 판정하며(가중치 Feature가 아님),
`operating_hours`가 `null`이면 폐점으로 보지 않고 남은 운영시간 Feature만
결측 처리해 나머지 가중치로 재분배합니다. `category`는 1차 하드 필터
(place_type/place_tag)가 이미 처리한다고 보고 가중치 계산에는 사용하지 않으며
표시용 메타데이터로만 남깁니다. `weights_used`는 날씨/남은 운영시간이 후보마다
다르게 결측될 수 있어 `ScoringResult` 전체가 아니라 `RankedCandidate`마다
따로 노출됩니다. congestion, evidence confidence Feature는 아직 미구현입니다.
Feature·가중치·제외 규칙 상세는
[추천 점수 설계](./design/recommendation-scoring.md)를 참고합니다. 이 엔진은
`backend/app/services/recommendation_pipeline.py`를 통해
`/api/recommendations` 라우트에 연결되어 있으며, 결과 근거(`score`/
`feature_scores`/`weights_used`)도 `RecommendationItem`에 노출됩니다(D-028,
아래 참고).

`backend/app/domain/evidence.py::build_evidence_list()`는 `RankedCandidate`를
자연어 없이 Feature별 기여도(score × weight)로 재구성한
`RecommendationEvidence`로 변환합니다.

```ts
type FeatureContribution = {
  feature: string;
  score: number | null;
  weight: number | null;
  contribution: number | null; // score * weight; 결측 시 null
};

type RecommendationEvidence = {
  place_id: string;
  name: string;
  category: string;
  rank: number;
  score: number;
  contributions: FeatureContribution[];
  is_unverified: boolean;
  warnings: string[];
};
```

상세와 고정 평가 Fixture v1은
[추천 Evidence·평가 Fixture 설계](./design/recommendation-evidence-fixture.md)를
참고합니다.

### `RecommendationResult`

```ts
type RecommendationResult = {
  place_id: string;
  name: string;
  score?: number;
  rank?: number;
  reason: string;
  warnings: string[];
  feature_scores?: Record<string, number | null>;
  snapshot?: RecommendationSnapshot;
};
```

점수 공개 범위, Feature 설명 형식, Snapshot 상세 스키마는 `TBD`입니다. 참고로
현재 REST `/api/recommendations`의 `RecommendationItem`(§2)은 이미
`score`/`feature_scores`/`weights_used`를 노출하고 있어(D-028), 통합 Chat API
설계 시 이를 그대로 재사용할 수 있는지 우선 검토합니다.

## 5. Provider 계약

모든 Provider 메서드는 외부 I/O를 고려해 비동기이며 Fake/Real 구현이 같은 계약을
따릅니다.

### 공통 결과 메타데이터

Provider의 정상 결과에는 다음 공통 metadata를 포함합니다. 이 계약은 설계상
확정됐지만 현재 코드 모델에는 아직 반영되지 않았습니다.

```ts
type ProviderMetadata = {
  source: ProviderSource;
  status: "success" | "no_data" | "partial";
  retrieved_at: string; // UTC ISO 8601: 2026-07-23T05:30:00.123Z
};

type ProviderSource =
  | "naver_geocoding"
  | "kma_ultra_short_forecast"
  | "tour_api_place"
  | "tour_api_concentration"
  | "kasi_holiday"
  | "fake_geocoding"
  | "fake_weather"
  | "fake_place"
  | "fake_concentration"
  | "fake_holiday";
```

- `success`: 유효 데이터가 하나 이상 있는 정상 결과
- `no_data`: 호출·파싱은 성공했지만 유효 데이터가 없는 정상 결과
- `partial`: 일부 누락이 있으나 안전하게 사용할 데이터가 있는 결과
- `unavailable`: 결과 status가 아니라 Provider/Tool 오류로 처리
- `retrieved_at`: 캐시 반환 시각이 아닌 최초 외부 조회·정규화 완료 시각
- Python 모델과 Backend JSON 모두 `retrieved_at` 사용

단건 Geocoding과 정확 장소 조회는 찾지 못한 경우 기존 `not_found` 오류 의미를
유지합니다. `no_data`는 장소 후보, 집중률, 공휴일 같은 목록 또는 선택 Feature의
빈 결과에 사용합니다.

### Provider 실패 계약

정상 결과에는 `ProviderMetadata`가 붙고, 호출 실패 시에는 정상 결과 대신
`ProviderError`가 발생합니다.

```ts
type ProviderError = {
  source: ProviderSource;
  code: "invalid_input" | "not_found" | "unavailable" | "internal_error";
  cause:
    | "timeout"
    | "unauthorized"
    | "rate_limited"
    | "network"
    | "upstream_error"
    | "parse_error"
    | "validation_error"
    | "unknown";
  occurred_at: string;
  retryable: boolean;
  message: string;
  details?: Record<string, unknown>;
};
```

- `retrieved_at`: 데이터를 성공적으로 조회하고 정규화한 시각
- `occurred_at`: Provider 오류를 감지한 시각
- 실패 결과에 `retrieved_at`을 생성하지 않음
- `no_data`는 오류가 아니라 `status="no_data"`인 정상 결과
- 파싱 실패는 `unavailable/parse_error`
- `message`와 `details`에는 Secret과 전체 요청 URL을 포함하지 않음

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
`raw_common`, `raw_intro`를 포함합니다. `operating_schedule`은 원문을 보존하면서
해석 가능한 시간·월·휴무 규칙을 구조화합니다. `parse_status`는 `parsed`,
`partial`, `unknown`, `assumed`이며, 여행코스의 운영시간 누락을 24시간 이용
가능으로 처리한 경우 `assumed`와 `course_without_operating_hours` 사유를 함께
반환합니다. Provider 상세 계약은
[`backend/docs/provider-contract-v1.md`](../backend/docs/provider-contract-v1.md)를
참고합니다.

### Weather 시간 metadata

Weather 결과는 관측과 예보를 혼동하지 않도록 Provider 공통 metadata를 확장합니다.

```ts
type WeatherMetadata = ProviderMetadata & {
  data_type: "forecast";
  forecast_for: string;
  observed_at: string | null;
};
```

- `data_type`: MVP에서는 `forecast`
- `retrieved_at`: Provider 조회·정규화 시각
- `forecast_for`: 추천 판단에 사용한 예보 대상 시각
- `observed_at`: 현재 관측값은 사용하지 않으므로 `null`
- 즉시 추천은 현재와 가장 가까운 예보 선택
- 특정 시간 추천은 방문 예정 시각과 가장 가까운 예보 선택

`GetWeatherForecastTool`이 방문 시각에 가장 가까운 예보를 선택하고 위 시간
metadata를 반환합니다. 공통 `ProviderMetadata` wrapper가 Fake/Real Provider에
적용되어 Tool Context로 전달됩니다.

## 6. Tool 계약 초안

`ResolveLocationTool`, `GetWeatherForecastTool`, `NearbyPlaceDetailsTool`,
`GetConcentrationTool`, `GetHolidaysTool`은 코드로 구현되어 있습니다. 각 Tool은
업무별 payload를 유지하되 `status`, `error`, `warnings`, `provider_metadata`
필드를 공통으로 제공하며 `ToolResult<T>` Protocol을 만족합니다.

| Tool | 책임 | 예상 Provider |
| --- | --- | --- |
| `resolve_location` | 장소명/주소를 좌표로 해석 | Geocoding |
| `search_nearby_places` | 기준 좌표 주변 후보 수집 | Place |
| `get_place_details` | 특정 장소 식별 및 상세정보 조회 | Place |
| `get_nearby_place_details` | 주변 후보 수집 후 제한된 동시성으로 다건 상세조회 | Place Search + Place Details |
| `estimate_travel_time` | 이동수단별 예상 시간 계산 | 지도/위치 Provider TBD |
| `get_weather_forecast` | 방문 예정 시각의 초단기예보 선택 | Weather |
| `get_congestion` | 장소/지역 혼잡도 조회 | Concentration |
| `search_place_feature_evidence` | 조용함·분위기 근거 수집 | Naver Blog Search TBD |

### `resolve_location` 구현 계약

```python
ResolveLocationTool(provider: GeocodingProvider)
```

- 입력: `location_query` 1~200자
- 지원 범위: 서울특별시 종로구
- alias 우선 조회 후 정상 빈 결과에만 원문으로 1회 fallback
- Provider 장애에는 fallback하지 않고 `unavailable`
- 종로구 밖 또는 행정구를 확인할 수 없는 결과는 `unsupported`
- 직접·fallback 조회의 복수 후보는 `no_data`,
  `details.reason="ambiguous_location"`으로 사용자 재질문
- 성공 method: `direct`, `alias`, `fallback`
- fallback 성공 시 `fallback_used` warning
- Provider 결과에는 `candidate_count`, `administrative_district` 포함

### `get_weather_forecast` 구현 계약

- 입력: 위도, 경도, 선택적 `visit_at`
- `visit_at=None`: Backend Clock의 현재 시각 사용
- timezone 없는 시각: `Asia/Seoul`로 간주하고 `timezone_assumed=true`
- timezone 포함 시각: `Asia/Seoul`로 변환
- 가장 가까운 예보 선택, 동률이면 미래 예보 우선
- 명시 시각이 예보 범위 밖이면 `unsupported/outside_forecast_range`
- 빈 예보는 `no_data/forecast_not_found`
- 장애는 `unavailable`이며 timeout과 upstream error를 구분
- Weather Tool 자체는 지역을 제한하지 않고 좌표 범위만 검증
- 결과: condition, SKY, PTY, forecast_for, retrieved_at, KMA 격자,
  data_type=forecast, observed_at=null

### `get_nearby_place_details` 구현 계약

`NearbyPlaceDetailsTool`은 목록과 상세 데이터 소스를 별도로 주입받습니다.

```python
NearbyPlaceDetailsTool(
    search_provider: PlaceSearchProvider,
    details_provider: PlaceDetailsProvider,
    max_concurrency: int = 3,
)
```

- 입력: 좌표, 검색 반경, 최대 결과 수, 선호 카테고리, TourAPI 분류 필터,
  제외할 `place_id`
- 제한: 반경 `0 < km <= 20`, 결과 수 `1..20`, 동시 상세조회 `1..10`
- 순서: 검색 결과 순서를 유지하며 제외 ID 적용 후 최대 결과 수만 반환
- 상세 상태: `success`, `no_data`, `unavailable`
- 전체 상태: 후보가 없으면 `no_data`, 모든 상세조회가 성공하면 `success`,
  일부 상세정보가 없거나 실패하면 `partial`
- 부분 실패: 한 장소의 상세조회 실패가 다른 장소 조회를 중단하지 않음
- 교체 경계: 현재는 두 역할 모두 `RealPlaceProvider`가 담당하지만,
  `details_provider`만 DB 구현으로 교체할 수 있음
- 관측 정보: 결과에 `source`, `retrieved_at`, 전체 `elapsed_ms` 포함

### 공통 Tool 결과

```ts
type ToolResult<T> =
  | {
      ok: true;
      data: T;
      warnings: ToolWarning[];
      provider_metadata: ProviderMetadata[];
    }
  | {
      ok: false;
      error: ToolError;
      provider_metadata: ProviderMetadata[];
    };

type ToolWarning = {
  code: "partial_data" | "stale_data" | "fallback_used";
  message: string;
};
```

Tool이 Provider를 호출하지 못한 경우 `provider_metadata`는 빈 배열일 수 있습니다.
복수 Provider를 조합하면 각 정상 결과의 metadata를 호출 순서대로 보존합니다.

### 공통 오류 코드

```ts
type ToolErrorCode =
  | "invalid_input"
  | "not_found"
  | "no_data"
  | "unavailable"
  | "unsupported"
  | "internal_error";

type ToolErrorCause =
  | "timeout"
  | "unauthorized"
  | "rate_limited"
  | "network"
  | "upstream_error"
  | "parse_error"
  | "validation_error"
  | "unknown";

type ToolError = {
  code: ToolErrorCode;
  message: string;
  retryable: boolean;
  tool: string;
  cause?: ToolErrorCause;
  source?: ProviderSource;
  occurred_at: string;
  details?: Record<string, unknown>;
};
```

`message`는 사용자 또는 상위 계층에 전달 가능한 비민감 문장입니다. ProviderError를
변환할 때 `source`, `cause`, `occurred_at`, `retryable`을 보존합니다. `details`에는
API 키, 인증 헤더, 전체 요청 URL, 원본 사용자 발화를 넣지 않습니다.

### `no_data`와 `unavailable`

| 구분 | `no_data` | `unavailable` |
| --- | --- | --- |
| 외부 호출 | 성공 | 실패 또는 응답 신뢰 불가 |
| 파싱 | 성공 | 실패할 수 있음 |
| 데이터 존재 여부 | 요청 조건에 없음을 확인 | 존재 여부를 판단할 수 없음 |
| 동일 요청 즉시 재시도 | 기본적으로 의미 없음 | 원인에 따라 가능 |
| 사용자 행동 | 조건/범위 변경 가능 | 잠시 후 재시도 또는 운영 조치 |
| 추천 처리 | 선택 Feature면 제외 가능 | 선택 Feature면 fallback 가능, 필수 데이터면 중단 |

HTTP 200이더라도 응답 schema가 깨져 파싱할 수 없으면 `no_data`가 아니라
`unavailable(cause="parse_error")`입니다. 반대로 빈 `items`가 API의 정상 계약이면
`no_data`입니다.

### 코드 판정 기준

| 코드 | 의미 | 동일 요청 기본 retry |
| --- | --- | --- |
| `invalid_input` | Tool 입력 형식·범위가 잘못됨 | 아니오 |
| `not_found` | 위치나 특정 장소 같은 식별 대상을 찾지 못함 | 아니오 |
| `no_data` | 식별 대상은 유효하지만 요청한 부가/목록 데이터가 없음 | 아니오 |
| `unavailable` | 외부 의존성 문제로 결과를 확인할 수 없음 | 원인에 따라 |
| `unsupported` | 현재 Tool이 요청 기능·지역·형식을 지원하지 않음 | 아니오 |
| `internal_error` | Tool 자체의 예상하지 못한 오류 | 아니오, 운영 확인 |

`timeout`, `unauthorized`, `rate_limited`는 Orchestrator의 업무 분기를 불필요하게
늘리지 않도록 v1 최상위 code로 두지 않고 `unavailable`의 `cause`로 둡니다.

### Provider 오류 매핑

| Provider 결과/오류 | Tool 오류 code | cause | retryable 기본값 |
| --- | --- | --- | --- |
| `invalid_request`, `ValueError` | `invalid_input` | `validation_error` | `false` |
| `location_not_found` (`resolve_location`) | `no_data` | `location_not_found` | `false` |
| `place_not_found` | `not_found` | 생략 가능 | `false` |
| 정상 빈 후보/forecast/holiday 결과 | `no_data` | 생략 가능 | `false` |
| `weather_no_data` | `no_data` | 생략 가능 | `false` |
| `provider_timeout` | `unavailable` | `timeout` | `true` |
| 인증 401/403 | `unavailable` | `unauthorized` | `false` |
| HTTP 429 | `unavailable` | `rate_limited` | `true` |
| `geocoding_unavailable`, `weather_unavailable` | `unavailable` | `upstream_error` | `true` |
| `provider_unavailable` | `unavailable` | 실제 원인에 맞춤 | 원인에 따라 |
| Tool 내부 예상 밖 예외 | `internal_error` | `unknown` | `false` |

현재 Provider 오류가 HTTP status나 세부 원인을 구조화해 보존하지 않는 경우가 있어
`cause`를 정확히 설정하지 못할 수 있습니다. 이 경우 `upstream_error` 또는
`unknown`을 사용하고 후속 Provider 오류 모델 구현에서 보완합니다.

### Orchestrator 기본 처리

| Tool 오류 | 필수 데이터 | 선택 Feature |
| --- | --- | --- |
| `invalid_input` | 요청 검증 실패 또는 사용자 수정 요청 | 해당 Feature 입력 무시 금지; 수정 요청 |
| `not_found` | 위치/장소 재확인 요청 | 대상 Feature 제외 가능 |
| `no_data` | 조건 완화 여부를 사용자에게 확인 | Feature 제외 후 warning과 함께 진행 가능 |
| `unavailable` | 제한된 재시도 후 실행 실패 | fallback/Feature 제외 후 warning 가능 |
| `unsupported` | 지원 범위 안내 | Feature 제외 가능 |
| `internal_error` | 안전하게 실패하고 실행 ID 로그 | 원칙적으로 자동 무시하지 않음 |

명시적 필수 조건을 자동으로 완화하지 않습니다. Tool은 오류를 분류하고,
중단·부분 진행·재질문의 최종 결정은 Orchestrator가 담당합니다.

## 7. 세션과 실행 식별자

| 필드 | 생성 주체 | 역할 | 현재 구현 |
| --- | --- | --- | --- |
| `chat_session_id` | Frontend | 채팅 하나 식별, 사용자 ID 아님 | 미구현 |
| `recommendation_run_id` | Backend | 추천 실행·로그·Snapshot 연결 | 미구현 |

형식은 UUID 사용 방향이지만 버전, 저장 위치, 중복/재시도 정책은 `TBD`입니다.
