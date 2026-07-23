# Provider Contract v1

## 1. 문서 정보

| 항목 | 값 |
| --- | --- |
| 대상 단계 | `Phase 1-A — Core AI Agent Flow` |
| 기준 브랜치 | `docs/provider-spec-v1` |
| 기준 코드 | `backend/app/providers`, `backend/app/domain/models.py` |
| 문서 상태 | 구현 기준 명세 |
| 대상 Provider | Geocoding, Weather, Place, Concentration, Holiday |

실행 명령과 키 설정은 [Provider 테스트 가이드](./provider-test-guide.md), 실제 응답
확인 기록은 [API 샘플](./api-samples.md)을 참고합니다.

## 2. 목적과 범위

Provider는 외부 API와 직접 통신하고 공급자별 요청·응답을 TripBranch 내부 모델로
변환하는 경계 계층입니다. 서비스와 향후 Tool은 외부 API의 원본 필드 대신
`providers/protocols.py`의 Protocol과 정규화 모델을 사용합니다.

이 문서가 다루는 범위:

- 현재 구현된 Fake/Real Provider의 공통 계약
- 외부 엔드포인트와 요청 파라미터
- 원본 응답에서 내부 모델로의 매핑
- 입력 검증, 빈 결과, 오류 처리
- 설정, 테스트, 현재 제약

이 문서가 확정하지 않는 범위:

- Tool 입력·출력 계약
- Provider 호출 순서를 결정하는 Orchestrator
- 가중치 Scoring과 fallback 정책
- 캐시, retry, rate limit, circuit breaker
- 운영 환경 Secret 관리 방식

위 항목은 아직 구현되지 않았거나 현재 논의 중입니다.

## 3. Provider와 Tool의 경계

```text
Recommendation Pipeline / Tool
            ↓ 내부 입력
         Provider
            ↓ 외부 요청
        External API
            ↓ 원본 응답
 Provider / Mapper 정규화
            ↓ 내부 모델
Recommendation Pipeline / Tool
```

- Provider: 인증, HTTP 요청, timeout, 공급자 오류 해석, 응답 정규화
- Tool: `resolve_location`, `get_place_details`처럼 업무 목적 단위로 Provider를 조합
- Provider는 추천 순위, 사용자 Intent, 조건 완화 여부를 결정하지 않음
- Tool은 외부 API 엔드포인트와 1:1로 대응할 필요가 없음
- 현재 저장소에는 별도의 Tool 계층이 아직 없음

## 4. 구현 현황 요약

| Provider | Protocol | Fake | Real | 외부 시스템 | 현재 추천 서비스 연결 |
| --- | --- | --- | --- | --- | --- |
| Geocoding | `GeocodingProvider` | `FakeGeocodingProvider` | `RealGeocodingProvider` | Naver Geocoding | 연결됨 |
| Weather | `WeatherProvider` | `FakeWeatherProvider` | `RealWeatherProvider` | 기상청 초단기예보 | 미연결 |
| Place | `PlaceProvider` | `FakePlaceProvider` | `RealPlaceProvider` | TourAPI KorService2 | 연결됨 |
| Concentration | `ConcentrationProvider` | `FakeConcentrationProvider` | `RealConcentrationProvider` | TourAPI 집중률 예측 | 미연결 |
| Holiday | `HolidayProvider` | `FakeHolidayProvider` | `RealHolidayProvider` | 한국천문연구원 특일 정보 | 미연결 |

`InterpretProvider`와 `RecommendationProvider` Protocol도 같은 파일에 존재하지만,
현재 외부 API Provider v1의 다섯 종류에는 포함하지 않습니다. 두 계약은 동기
메서드이며 기존 Stub 서비스 호환용입니다.

## 5. 공통 설계 원칙

### 5.1 비동기 계약

외부 I/O가 가능한 다섯 Provider의 공개 메서드는 모두 `async`입니다. Fake도 Real과
같은 호출 형태를 유지합니다.

### 5.2 의존성 주입

Real Provider는 생성자에서 공유 가능한 `httpx.AsyncClient`와 timeout을 받습니다.
Factory가 설정에 따라 Fake 또는 Real 구현을 반환합니다.

```python
provider = get_place_provider(client)
```

### 5.3 응답 정규화

- JSON/XML 원본 구조는 Provider 또는 Mapper 내부에서 처리
- 서비스는 `PlaceCandidate`, `PlaceDetails`, `GeocodeResult` 같은 내부 모델 사용
- 필요한 경우 원본은 `raw_data`, `raw_common`, `raw_intro`에 보존
- 필수 식별정보가 없는 Place 항목은 후보에서 제외
- 빈 목록은 정상적인 빈 tuple/list로 표현할 수 있음

### 5.4 Secret

- API 키를 반환 모델에 포함하지 않음
- Inspection Test는 `serviceKey`, Naver 인증 헤더를 `<redacted>`로 마스킹
- `.env`는 Git 추적 대상이 아님
- Holiday Provider는 원본 `httpx` 예외 체인을 숨겨 URL의 키 노출을 방지
- 나머지 Real Provider는 현재 원본 예외를 chaining하므로 실패 traceback에 URL이
  포함될 가능성이 있음. 공통 보안 보완이 필요한 상태이며 `TBD`

### 5.5 현재 공통 미구현 항목

- `EXTERNAL_API_RETRY_COUNT` 설정은 존재하지만 retry 로직에는 사용되지 않음
- 캐시, rate limit, circuit breaker 없음
- Provider별 metrics/tracing 없음
- 요청 ID와 `recommendation_run_id` 연결 없음
- 공통 pagination 추상화 없음

### 5.6 공통 결과 메타데이터

모든 Provider 정상 결과는 다음 메타데이터를 포함하는 것으로 계약을 확정합니다.
현재 도메인 모델에는 아직 일괄 반영되지 않았으며 후속 구현 작업에서 적용합니다.

```ts
type ProviderMetadata = {
  source: ProviderSource;
  status: ProviderResultStatus;
  retrieved_at: string;
};

type ProviderResultStatus = "success" | "no_data" | "partial";
```

Python 모델과 JSON 직렬화 결과 모두 `retrieved_at`을 사용합니다. Backend 계약에는
camelCase alias를 두지 않습니다. Provider 결과는 Backend 내부 계약이므로 실제 공개
API에 노출할지는 별도로 결정합니다.

#### `source`

`source`는 구현 클래스명이 아니라 데이터의 실제 출처와 기능을 식별합니다. v1은
임의 문자열 대신 다음 폐쇄 목록을 사용합니다.

| 값 | 생성 Provider |
| --- | --- |
| `naver_geocoding` | `RealGeocodingProvider` |
| `kma_ultra_short_forecast` | `RealWeatherProvider` |
| `tour_api_place` | `RealPlaceProvider` |
| `tour_api_concentration` | `RealConcentrationProvider` |
| `kasi_holiday` | `RealHolidayProvider` |
| `fake_geocoding` | `FakeGeocodingProvider` |
| `fake_weather` | `FakeWeatherProvider` |
| `fake_place` | `FakePlaceProvider` |
| `fake_concentration` | `FakeConcentrationProvider` |
| `fake_holiday` | `FakeHolidayProvider` |

한 Provider가 여러 엔드포인트를 호출하더라도 v1에서는 기능 단위 source 하나를
사용합니다. Place의 `searchKeyword2`, `detailCommon2`, `detailIntro2`는 모두
`tour_api_place`입니다. 엔드포인트별 추적은 로그/trace 영역이며 metadata source를
늘리지 않습니다.

#### `status`

| 값 | 판정 기준 | 데이터 필드 |
| --- | --- | --- |
| `success` | 요청한 범위의 정상 데이터를 반환 | 유효 데이터 1건 이상 |
| `no_data` | 외부 호출과 파싱은 성공했으나 유효 데이터가 없음 | 정상적인 빈 list/tuple 또는 빈 단건 결과 |
| `partial` | 사용할 수 있는 데이터는 있으나 요청 범위 일부가 누락됨 | 유효 데이터와 누락 경고가 함께 존재 |

`unavailable`은 정상 Provider 결과의 status가 아닙니다. timeout, 인증 실패, 네트워크
오류, 파싱 불가처럼 데이터 존재 여부를 판단할 수 없는 경우 Provider는 오류를
발생시킵니다. 다음 단계에서 Tool이 이를 공통 오류 코드로 변환합니다.

`partial`은 다음 경우에만 사용합니다.

- 복수 업스트림 호출 중 일부가 실패했지만 안전하게 반환 가능한 데이터가 있음
- 응답 항목 일부를 필수 필드 누락으로 제외했으며 나머지 항목을 반환함
- 상세정보의 필수 데이터는 있으나 선택 데이터 소스가 실패함

선택 필드가 원래 빈 값인 것만으로는 `partial`이 아닙니다. `partial` 결과에는 누락
내용을 설명하는 별도 warning 계약이 필요하며 그 구조는 Tool 오류 계약 단계에서
확정합니다.

#### `retrieved_at`

- 의미: Provider가 외부 응답을 수신하고 정상 결과로 정규화를 완료한 시각
- 표준: UTC ISO 8601, 밀리초, `Z` 표기
- 예: `2026-07-23T05:30:00.123Z`
- 시스템 로컬 timezone을 사용하지 않음
- 예보 기준시각, 공휴일 날짜처럼 데이터 자체의 기준시각을 대신하지 않음
- 캐시 결과는 캐시 반환 시각이 아니라 최초 외부 조회의 `retrieved_at`을 유지
- 여러 호출을 조합한 결과는 마지막 필수 호출의 정규화 완료 시각 사용
- Fake도 호출 시각을 기록하며 테스트에서는 Clock을 고정해 재현성 확보

Provider 내부에서 직접 `datetime.now()`를 흩어 쓰지 않고 공통 UTC Clock을 주입할지
구현 단계에서 결정합니다. 의미와 출력 형식은 본 계약으로 확정합니다.

#### 실패 결과: `ProviderError`

`ProviderMetadata`는 정상적으로 반환된 데이터에만 존재합니다. Provider 호출이
실패하면 정상 결과나 `retrieved_at`을 만들지 않고 다음 공통 오류를 발생시킵니다.

```ts
type ProviderError = {
  source: ProviderSource;
  code: ProviderErrorCode;
  cause: ProviderErrorCause;
  occurred_at: string;
  retryable: boolean;
  message: string;
  details?: Record<string, unknown>;
};

type ProviderErrorCode =
  | "invalid_input"
  | "not_found"
  | "unavailable"
  | "internal_error";

type ProviderErrorCause =
  | "timeout"
  | "unauthorized"
  | "rate_limited"
  | "network"
  | "upstream_error"
  | "parse_error"
  | "validation_error"
  | "unknown";
```

| 필드 | 의미 |
| --- | --- |
| `source` | 실패한 Provider 데이터 출처 |
| `code` | Provider 경계의 공통 오류 분류 |
| `cause` | timeout·인증·파싱 등 기술 원인 |
| `occurred_at` | 오류를 감지한 UTC ISO 8601 시각 |
| `retryable` | 같은 입력을 그대로 재시도할 수 있는지 |
| `message` | Secret과 원본 URL이 제거된 안전한 메시지 |
| `details` | 선택적인 비민감 진단정보 |

`retrieved_at`은 데이터 조회·정규화에 성공한 시각이고 `occurred_at`은 실패를 감지한
시각입니다. 실패 시 `retrieved_at`을 현재시각으로 채우지 않습니다.

```text
정상 또는 정상 빈 결과
→ ProviderResult(data, ProviderMetadata)

호출·인증·파싱 실패
→ ProviderError
→ ToolError로 변환
```

`no_data`는 외부 호출과 파싱이 성공한 정상 결과이므로 `ProviderError`가 아닙니다.
반대로 응답을 파싱하지 못해 데이터 존재 여부를 알 수 없으면
`ProviderError(code="unavailable", cause="parse_error")`입니다.

ProviderError의 `details`와 예외 문자열에는 API 키, 인증 헤더, 전체 요청 URL,
사용자 원문을 포함하지 않습니다. 기존 `AppError` 계층을 이 계약에 맞춰 확장하거나
새 오류 모델로 교체하는 방식은 구현 단계에서 결정합니다.

#### 모델별 적용

| 결과 모델 | metadata 위치 | `no_data` 판정 |
| --- | --- | --- |
| `GeocodeResult` | `metadata` | 단건 결과가 없으면 현재는 `location_not_found`; `no_data` 반환으로 바꾸지 않음 |
| `WeatherCondition` | wrapper 결과의 `metadata` | SKY/PTY 없음; 현재 `weather_no_data` 오류와의 마이그레이션 필요 |
| `list[PlaceCandidate]` | 목록 wrapper의 `metadata` | 유효 후보 0건 |
| `PlaceDetails` | `metadata` | 정확한 장소 또는 필수 상세 결과 없음; 현재 오류 유지 |
| `ConcentrationResult` | `metadata` | `forecasts`가 비어 있음 |
| `HolidayResult` | `metadata` | `entries`가 비어 있음 |

단건 조회의 “찾을 수 없음”을 정상 `no_data`로 반환할지 `not_found` 오류로 유지할지는
업무 의미가 다릅니다. v1에서는 Geocoding과 Place 정확조회는 `not_found` 오류를
유지하고, 목록/선택 Feature 조회의 빈 결과에 `no_data`를 사용합니다.

## 6. 설정과 Factory

### 6.1 모드 결정

`PROVIDER_MODE`는 다섯 Provider의 공통 기본값입니다. 개별 설정이 비어 있으면 공통
값을 사용합니다.

```env
PROVIDER_MODE=fake
GEOCODING_PROVIDER=
WEATHER_PROVIDER=
PLACE_PROVIDER=
CONCENTRATION_PROVIDER=
HOLIDAY_PROVIDER=
```

예를 들어 전체를 Real로 실행하되 Place만 Fake로 유지할 수 있습니다.

```env
PROVIDER_MODE=real
PLACE_PROVIDER=fake
```

지원 모드는 문자열 `fake`, `real`입니다. 다른 값은 Factory에서 `ValueError`를
발생시킵니다.

### 6.2 환경변수

| Provider | 선택 변수 | Real 인증 변수 |
| --- | --- | --- |
| Geocoding | `GEOCODING_PROVIDER` | `NAVER_MAP_CLIENT_ID`, `NAVER_MAP_CLIENT_SECRET` |
| Weather | `WEATHER_PROVIDER` | `WEATHER_API_KEY` |
| Place | `PLACE_PROVIDER` | `TOUR_API_SERVICE_KEY` |
| Concentration | `CONCENTRATION_PROVIDER` | `TOUR_API_SERVICE_KEY` |
| Holiday | `HOLIDAY_PROVIDER` | `TOUR_API_SERVICE_KEY` |

`TOUR_API_SERVICE_KEY`는 공공데이터포털 인증키로 Place, Concentration, Holiday가
공유합니다. 이전 변수명 `PLACE_API_KEY`는 `Settings`의 호환 alias로만 남아 있으며
신규 설정은 `TOUR_API_SERVICE_KEY`를 사용합니다.

### 6.3 Factory 함수

| 함수 | 반환 Protocol | 키 누락 시 메시지 |
| --- | --- | --- |
| `get_geocoding_provider(client)` | `GeocodingProvider` | Naver 키별 환경변수 필요 |
| `get_weather_provider(client)` | `WeatherProvider` | `WEATHER_API_KEY` 필요 |
| `get_place_provider(client)` | `PlaceProvider` | `TOUR_API_SERVICE_KEY` 필요 |
| `get_concentration_provider(client)` | `ConcentrationProvider` | `TOUR_API_SERVICE_KEY` 필요 |
| `get_holiday_provider(client)` | `HolidayProvider` | `TOUR_API_SERVICE_KEY` 필요 |

Fake Weather는 `FAKE_WEATHER_CONDITION=good|neutral|bad`를 사용합니다. 범위 밖 값은
Factory에서 `ValueError`가 발생합니다.

## 7. 공통 내부 모델

### `GeocodeResult`

| 필드 | 타입 | 의미 |
| --- | --- | --- |
| `query` | `str` | 원본 위치 질의 |
| `resolved_name` | `str` | Provider가 해석한 주소/장소명 |
| `latitude` | `float` | 위도 |
| `longitude` | `float` | 경도 |

### `WeatherCondition`

`good`, `neutral`, `bad` 세 값만 Provider 밖으로 노출합니다.

### `PlaceCandidate`

| 필드 | 타입 | 의미 |
| --- | --- | --- |
| `place_id` | `str` | TourAPI `contentid` 또는 Fake ID |
| `content_type_id` | `str \| None` | TourAPI `contenttypeid` |
| `lcls_systm1` | `str \| None` | TourAPI 신분류 대분류 `lclsSystm1` |
| `lcls_systm2` | `str \| None` | TourAPI 신분류 중분류 `lclsSystm2` |
| `lcls_systm3` | `str \| None` | TourAPI 신분류 소분류 `lclsSystm3` |
| `name` | `str` | 장소명 |
| `category` | `str` | 내부 대분류 |
| `latitude` / `longitude` | `float` | 좌표 |
| `address` | `str \| None` | 기본 주소 |
| `operating_hours` | `str \| None` | 후보 단계 운영시간; Real 검색에서는 현재 `None` |
| `raw_source` | `str` | 생성 Provider 식별값 |

### `PlaceDetails`

| 필드 | 타입 | 의미 |
| --- | --- | --- |
| `content_id` | `str` | TourAPI 장소 ID |
| `content_type_id` | `str` | TourAPI 장소 유형 ID |
| `title` | `str \| None` | 장소명 |
| `address` | `str \| None` | `addr1`과 `addr2` 결합 |
| `overview` | `str \| None` | 장소 소개 |
| `homepage` | `str \| None` | 홈페이지 원문 |
| `telephone` | `str \| None` | 공통 `tel`, 없으면 소개 `infocenter` |
| `operating_hours` | `str \| None` | 유형별 운영시간 원문 |
| `rest_date` | `str \| None` | 유형별 휴무 정보 원문 |
| `raw_common` | `Mapping` | `detailCommon2` 첫 항목 |
| `raw_intro` | `Mapping` | `detailIntro2` 첫 항목 |
| `provider` | `str` | `tour_api` 또는 `fake_place` |

### `ConcentrationResult`

`area_code`, `district_code`, 요청 장소명, `ConcentrationForecast` tuple, Provider
식별값을 포함합니다. 각 Forecast는 장소명, 예측일, `float | None` 집중률과
`raw_data`를 보존합니다.

### `HolidayResult`

조회 연도·월, `HolidayEntry` tuple, Provider 식별값을 포함합니다. `holidays`
property는 `is_holiday=True` 항목만 다시 필터링합니다.

## 8. GeocodingProvider

### 8.1 책임과 구현

- Protocol: `GeocodingProvider`
- Fake: `app/providers/geocoding.py::FakeGeocodingProvider`
- Real: `app/providers/geocoding.py::RealGeocodingProvider`
- 목표 Tool: `resolve_location` (`TBD`)

```python
async def geocode(location_query: str) -> GeocodeResult
```

### 8.2 Real 외부 계약

| 항목 | 값 |
| --- | --- |
| Provider | Naver Cloud Platform Geocoding |
| Method | `GET` |
| URL | `https://maps.apigw.ntruss.com/map-geocode/v2/geocode` |
| Query | `query`, `count=1` |
| Headers | `x-ncp-apigw-api-key-id`, `x-ncp-apigw-api-key`, `Accept: application/json` |

Naver Geocoding은 주소 검색 중심이며 일반 POI 이름을 직접 찾지 못할 수 있습니다.
현재 종로구 MVP를 위해 경복궁, 광화문, 창덕궁, 종묘 등 일부 장소명을 공식 주소로
치환하는 `_JONGNO_LANDMARK_ADDRESS_ALIASES`를 사용합니다.

### 8.3 응답 매핑

- `status`가 `OK`인지 확인
- `addresses`의 첫 항목만 선택
- `resolved_name`: `roadAddress` → `jibunAddress` → 원 질의 순 fallback
- `y` → latitude, `x` → longitude
- 후보가 여러 건이어도 사용자에게 재질문하지 않음

### 8.4 Fake 동작

경복궁, 광화문, 창덕궁, 종묘, 인사동의 고정 좌표만 substring 방식으로 인식합니다.
그 외는 `location_not_found`입니다.

### 8.5 오류와 제약

| 상황 | 결과 |
| --- | --- |
| 공백 입력 | `invalid_request` |
| 결과 없음 | `location_not_found`, HTTP 404 |
| HTTP/JSON/상태 오류 | `geocoding_unavailable`, retryable |

- POI 검색 Provider가 아니므로 alias 밖의 관광지명 성공을 보장하지 않음
- 첫 결과 자동 선택에 따른 모호성 해소 정책은 `TBD`
- 좌표 유효 범위 검증은 별도로 하지 않음

## 9. WeatherProvider

### 9.1 책임과 구현

- Protocol: `WeatherProvider`
- Fake: `app/providers/stub.py::FakeWeatherProvider`
- Real: `app/providers/weather.py::RealWeatherProvider`
- 보조 모듈: `app/providers/kma_grid.py`
- 목표 Tool: `get_current_weather` (`TBD`)

```python
async def get_current_condition(
    latitude: float,
    longitude: float,
) -> WeatherCondition
```

### 9.2 Real 외부 계약

| 항목 | 값 |
| --- | --- |
| Provider | 기상청 단기예보 조회서비스 |
| 기능 | `getUltraSrtFcst` |
| Method | `GET` |
| URL | `https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtFcst` |
| Format | JSON |

요청 파라미터는 `serviceKey`, `pageNo=1`, `numOfRows=100`, `dataType=JSON`,
`base_date`, `base_time`, `nx`, `ny`입니다. 위경도는 기상청 5km 격자 좌표로
변환합니다.

조회 기준시각은 KST로 계산합니다. 매시 45분 이후에는 해당 시각의 `HH30`, 그
이전에는 직전 시간의 `HH30` 발표분을 사용합니다.

### 9.3 날씨 매핑

가장 이른 `fcstDate`/`fcstTime`의 `SKY`, `PTY`를 선택합니다.

| 원본 | 내부 상태 |
| --- | --- |
| `PTY` 1~7 | `bad` |
| `PTY=0`, `SKY=1` | `good` |
| `PTY=0`, `SKY=3` 또는 `4` | `neutral` |
| 필요한 값 없음/알 수 없는 코드 | `weather_no_data` |

Temperature, 강수량, 습도, 풍속 등 다른 초단기예보 항목은 현재 반환하지 않습니다.

### 9.4 Weather 데이터 기준

TripBranch의 `WeatherProvider`는 현재 관측 날씨가 아니라 기상청 초단기예보를
사용합니다. 장소 추천에서는 요청 시점의 관측값보다 사용자가 장소에 도착하거나
방문할 예정 시각의 날씨가 더 중요하므로, MVP 추천 판단의 기본 데이터는
초단기예보로 확정합니다.

예보 선택 원칙:

- 즉시 방문 추천: 현재 시각과 가장 가까운 예보 시각 사용
- 특정 시간 또는 일정 기반 추천: 방문 예정 시각과 가장 가까운 예보 사용
- 현재 관측 날씨는 MVP 필수 범위에서 제외
- 실제 사용자 테스트에서 즉시 추천 품질이 부족한 경우 현재 관측 데이터 추가 검토

현재 구현은 방문 예정 시각을 입력받지 않고 응답 중 가장 이른 예보 slot을 선택하므로
“즉시 방문 추천”만 지원합니다. 일정 기반 예보 선택은 후속 구현 대상입니다.

Weather 결과에는 공통 `ProviderMetadata`와 함께 다음 시간 기준을 포함합니다.

```ts
type WeatherMetadata = ProviderMetadata & {
  data_type: "forecast";
  forecast_for: string;
  observed_at: string | null;
};
```

| 필드 | 의미 |
| --- | --- |
| `data_type` | MVP에서는 항상 `forecast` |
| `retrieved_at` | Provider가 예보를 조회하고 정규화한 시각 |
| `forecast_for` | 실제 추천 판단에 선택한 예보 대상 시각 |
| `observed_at` | 관측 데이터의 관측 시각; MVP에서는 `null` |

시간 필드는 timezone-aware ISO 8601로 표현하고 Backend 내부/JSON 모두
`snake_case`를 사용합니다. 기상청의 KST `fcstDate`/`fcstTime`은 내부 모델에서
timezone을 명시한 시각으로 변환해야 하며, UTC `Z`로 정규화할지는 구현 단계에서
공통 시간 규칙과 함께 확정합니다.

향후 현재 관측값과 예보를 함께 제공하더라도 방문 예정 시각의 예보를 우선합니다.
현재 관측값은 가까운 시간대 추천의 품질을 보완하는 정보로만 사용하고 예보를
대체하지 않습니다.

### 9.5 Fake 동작

생성 시 전달된 `WeatherCondition`을 그대로 반환합니다. Factory에서는
`FAKE_WEATHER_CONDITION`으로 값을 결정합니다.

### 9.6 오류와 제약

| 상황 | 결과 |
| --- | --- |
| HTTP/JSON 오류 | `weather_unavailable`, retryable |
| KMA `resultCode != 00` | `weather_unavailable`, retryable |
| SKY/PTY 없음 | `weather_no_data`, retryable |

- 메서드 이름은 current지만 실제 데이터는 가장 가까운 초단기 **예보** 시각임
- 특정 방문 예정 시각 입력과 가장 가까운 예보 slot 선택은 아직 미구현
- `WeatherMetadata`는 설계 확정 상태이며 현재 반환 모델에는 미반영
- 추천 서비스에는 아직 연결되지 않음
- 날씨 결측 시 가중치 재정규화 정책은 추천 계층의 `TBD`

## 10. PlaceProvider

### 10.1 책임과 구현

- Protocol: `PlaceProvider`
- Fake: `app/providers/stub.py::FakePlaceProvider`
- Real: `app/providers/real_place.py::RealPlaceProvider`
- 후보 Mapper: `app/providers/mappers.py`
- 목표 Tool: `search_nearby_places`, `get_place_details` (`TBD`)

### 10.2 좌표 기반 후보 검색

```python
async def search_places(
    latitude: float,
    longitude: float,
    preferred_categories: list[str],
    search_radius_km: float,
) -> list[PlaceCandidate]
```

| 항목 | 값 |
| --- | --- |
| Endpoint | `GET https://apis.data.go.kr/B551011/KorService2/locationBasedList2` |
| 좌표 | `mapX=longitude`, `mapY=latitude` |
| 반경 | `radius=int(search_radius_km * 1000)`, 최대 20,000m |
| 정렬 | `arrange=E` |
| 페이지 | `numOfRows=20`, `pageNo=1` |
| 공통 | `serviceKey`, `MobileOS=ETC`, `MobileApp=TripBranch`, `_type=json` |

`preferred_categories`는 Protocol 입력에 존재하지만 현재 API 요청 필터나 결과 후처리에
사용되지 않습니다. 카테고리 필터 적용 방식은 `TBD`입니다.

### 10.3 키워드 검색

```python
async def search_by_keyword(
    keyword: str,
    region_code: str | None = None,
    district_code: str | None = None,
    limit: int = 20,
) -> list[PlaceCandidate]
```

| 항목 | 값 |
| --- | --- |
| Endpoint | `GET .../searchKeyword2` |
| 검색어 | trim된 `keyword` |
| 지역 | `lDongRegnCd`, `lDongSignguCd` |
| 정렬 | `arrange=A` |
| 건수 | `limit`을 1~100으로 clamp |

`district_code`만 단독 지정할 수 없고 `region_code`가 함께 필요합니다. 종로구 경복궁
검색은 `region_code="11"`, `district_code="110"`입니다.

### 10.4 후보 매핑

필수 원본 필드는 `contentid`, `title`, `mapx`, `mapy`입니다. 누락되거나 좌표를
float로 변환할 수 없으면 해당 항목을 제외합니다.

| `contenttypeid` | 내부 category |
| --- | --- |
| `12` | `attraction` |
| `14` | `museum` |
| `15` | `event` |
| `25` | `course` |
| `28` | `activity` |
| `32` | `lodging` |
| `38` | `shopping` |
| `39` | `restaurant` |
| 그 외 | `unknown` |

후보 검색 단계의 `operating_hours`는 Real Provider에서 항상 `None`입니다. 운영시간이
필요하면 상세조회를 추가로 수행해야 합니다.

### 10.5 ID 기반 상세조회

```python
async def get_details(
    content_id: str,
    content_type_id: str,
) -> PlaceDetails
```

호출 순서:

1. `GET .../detailCommon2?contentId=...`
2. `GET .../detailIntro2?contentId=...&contentTypeId=...`
3. 양쪽 첫 항목을 `PlaceDetails`로 결합

운영시간은 `usetime`, `usetimeculture`, `playtime`, `usetimeleports`, `opentime`,
`opentimefood`, `checkintime`, `openperiod` 중 처음 존재하는 값을 사용합니다.
휴무 정보는 `restdate`, `restdateculture`, `restdateleports`,
`restdateshopping`, `restdatefood` 중 처음 존재하는 값을 사용합니다. 이외에도
`parking`, `infocenter`, 체험 정보 등이 `raw_intro`에 추가로 존재할 수 있습니다.

### 10.6 장소명 기반 상세조회

```python
async def find_details_by_name(
    name: str,
    region_code: str | None = None,
    district_code: str | None = None,
) -> PlaceDetails
```

1. `search_by_keyword(..., limit=100)` 호출
2. trim + `casefold()` 기준으로 장소명이 정확히 일치하는 첫 후보 선택
3. 후보의 `content_type_id` 검증
4. `get_details()` 호출

유사 이름만 존재할 때 임의로 선택하지 않습니다. 정확 일치가 없으면
`place_not_found`와 최대 5개 후보명을 details에 포함합니다.

### 10.7 Fake 동작

- 좌표 기준 테스트 박물관과 테스트 카페 반환
- 키워드 substring으로 후보 필터
- 상세정보에 Fake 소개와 후보 운영시간 반환
- `find_details_by_name`은 Real과 마찬가지로 정확 일치 요구

### 10.8 오류와 제약

| 상황 | 결과 |
| --- | --- |
| 빈 keyword/name 또는 ID | `ValueError` |
| district만 입력 | `ValueError` |
| timeout | `provider_timeout` |
| HTTP/JSON/업스트림 오류 | `provider_unavailable` |
| 정확 일치 장소 없음 | `place_not_found`, HTTP 404 |
| 정확 후보의 type ID 없음 | `provider_unavailable` |

- 검색 반경의 음수/0 입력 검증은 현재 없음
- 첫 페이지 최대 20/100건만 사용하며 pagination 없음
- 상세조회 2회 중 부분 성공 캐시 없음
- 홈페이지와 운영시간은 HTML/복합 문자열 원문일 수 있음
- 휴무일, 주차 등은 정규 필드가 아니라 현재 `raw_intro`에서만 접근 가능

## 11. ConcentrationProvider

### 11.1 책임과 구현

- Protocol: `ConcentrationProvider`
- Fake/Real: `app/providers/concentration.py`
- 목표 Tool: `get_congestion` (`TBD`)

```python
async def get_forecast(
    area_code: str,
    district_code: str,
    place_name: str | None = None,
) -> ConcentrationResult
```

### 11.2 Real 외부 계약

| 항목 | 값 |
| --- | --- |
| Provider | 한국관광공사 관광지 집중률 예측정보 |
| Endpoint | `GET https://apis.data.go.kr/B551011/TatsCnctrRateService/tatsCnctrRatedList` |
| Format | JSON (`_type=json`) |
| 지역 | `areaCd`, `signguCd` |
| 선택 장소명 | `tAtsNm` |
| 페이지 | `pageNo=1`, `numOfRows=100` |

종로구 기본 예시는 `area_code="11"`, `district_code="11110"`,
`place_name="경복궁"`입니다. Place Provider의 `lDongSignguCd="110"`과 코드 체계가
다르므로 혼용하지 않습니다.

### 11.3 응답 매핑

Provider 응답 필드 변화에 대비해 다음 alias를 순서대로 확인합니다.

| 내부 필드 | 원본 후보 키 |
| --- | --- |
| 장소명 | `tAtsNm`, `tatsNm`, `touristAttractionName` |
| 예측일 | `fcastYmd`, `forecastYmd`, `baseYmd`, `forecastDate`, `ymd` |
| 집중률 | `cnctrRate`, `concentrationRate`, `congestionRate`, `rate` |

집중률은 `%` 접미사를 제거하고 `float`로 변환합니다. 변환 불가는 `None`이며 원본은
`raw_data`에 보존합니다. item이 없거나 예상 구조가 아니면 빈 forecasts를 반환합니다.

### 11.4 Fake 동작

요청 장소명 또는 기본 경복궁에 대해 2026-07-23~25의 42.0, 58.0, 76.0 고정
예측값을 반환합니다.

### 11.5 오류와 제약

| 상황 | 결과 |
| --- | --- |
| timeout | `provider_timeout` |
| HTTP/JSON 오류 | `provider_unavailable` |
| 업스트림 resultCode 오류 | `provider_unavailable` |
| 데이터 없음 | 빈 `forecasts` |

- 반환값은 실시간 “현재 혼잡률”이 아니라 제공 날짜별 상대 집중률 예측
- 임의 장소가 데이터셋에 없을 때 근처/구 단위 fallback은 미구현
- 집중률의 정확한 범위와 Scoring 정규화 정책은 추천 계층의 `TBD`
- 추천 서비스에는 아직 연결되지 않음

## 12. HolidayProvider

### 12.1 책임과 구현

- Protocol: `HolidayProvider`
- Fake/Real: `app/providers/holiday.py`
- 목표 Tool: 운영일 판정 보조 Tool (`TBD`)

```python
async def get_holidays(
    year: int,
    month: int | None = None,
) -> HolidayResult
```

### 12.2 Real 외부 계약

| 항목 | 값 |
| --- | --- |
| Provider | 한국천문연구원 특일 정보 |
| 기능 | 공휴일 전용 `getRestDeInfo` |
| Endpoint | `GET https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo` |
| Format | XML |
| 인증 Query | `serviceKey` |
| 기간 Query | `solYear`, 선택 `solMonth` |
| 페이지 | `pageNo=1`, `numOfRows=100` |

`getAnniversaryInfo`는 기념일 정보이므로 공휴일 Provider에서 사용하지 않습니다.
JSON 출력 옵션은 확인되지 않았으며 현재 구현은 XML만 처리합니다.

### 12.3 입력 검증

- `year`: 1~9999
- `month`: 생략 가능, 지정 시 1~12
- 월은 API 요청 시 2자리 문자열로 변환

### 12.4 XML 매핑

| XML 필드 | 내부 필드 |
| --- | --- |
| `locdate` | `date` (`YYYYMMDD` 원문) |
| `dateName` | `name` |
| `dateKind` | `kind` |
| `seq` | `sequence: int \| None` |
| `isHoliday` | `is_holiday: bool` |

날짜 또는 이름이 없는 item은 제외합니다. `resultCode`가 `00`, `0000`, 빈 값이
아니면 `provider_unavailable`입니다.

### 12.5 Fake 동작

2026년 삼일절과 어린이날을 고정 데이터로 보유하고 요청 연·월로 필터링합니다.

### 12.6 오류와 제약

| 상황 | 결과 |
| --- | --- |
| 연·월 범위 오류 | `ValueError` |
| timeout | `provider_timeout` |
| HTTP/XML 파싱 오류 | `provider_unavailable` |
| 업스트림 resultCode 오류 | `provider_unavailable` |
| 데이터 없음 | 빈 `entries` |

- 전체 연도 조회는 고정 `numOfRows=100`; 향후 공휴일 수가 이를 넘을 경우 pagination 필요
- 공휴일이 특정 장소의 실제 영업 여부를 보장하지 않음
- 장소 `restdate`와 공휴일이 겹치는 운영 규칙 해석은 별도 Tool/도메인 로직의 `TBD`
- 추천 서비스에는 아직 연결되지 않음

## 13. 오류 계약

### 13.1 공통 AppError 구조

| 속성 | 의미 |
| --- | --- |
| `code` | 애플리케이션 표준 오류 코드 |
| `message` | 사용자 표시 가능 메시지 |
| `status_code` | HTTP 변환 상태 |
| `retryable` | 동일 요청 재시도 가능성 |
| `provider` | 오류 Provider 식별값 |
| `details` | 선택적인 업스트림 상세 |

### 13.2 현재 오류 코드

| 코드 | 주요 발생 Provider | HTTP | 재시도 |
| --- | --- | ---: | --- |
| `invalid_request` | Geocoding Fake/Real | 400 | 아니오 |
| `location_not_found` | Geocoding | 404 | 아니오 |
| `place_not_found` | Place 이름 상세조회 | 404 | 아니오 |
| `weather_no_data` | Weather | 502 | 가능 |
| `geocoding_unavailable` | Geocoding | 502 | 가능 |
| `weather_unavailable` | Weather | 502 | 가능 |
| `provider_timeout` | Place, Concentration, Holiday | 504 | 가능 |
| `provider_unavailable` | Place, Concentration, Holiday | 502 | 가능 |

일부 입력 오류는 `AppError`가 아닌 `ValueError`입니다. 모든 Provider 입력 오류를
`invalid_request`로 통일할지는 `TBD`입니다.

## 14. 테스트 계약

### 14.1 일반 테스트 격리

`tests/conftest.py`는 일반 pytest에서 공통/개별 Provider 모드를 Fake로 강제합니다.
개발자의 `.env`가 Real이어도 일반 테스트가 외부 API를 호출하지 않습니다.

```bash
cd backend
python -m pytest -q
python -m pytest tests/test_provider_contracts.py -v
```

Provider별 단위 테스트:

```bash
python -m pytest tests/test_geocoding_provider.py -v
python -m pytest tests/test_weather_provider.py -v
python -m pytest tests/test_place_provider.py -v
python -m pytest tests/test_concentration_provider.py -v
python -m pytest tests/test_holiday_provider.py -v
```

### 14.2 실제 Smoke Test

```bash
RUN_REAL_PROVIDER_TESTS=true python -m pytest -m smoke -v -s
```

Smoke Test는 실제 API에 최소 요청을 보내고 정규화 결과의 핵심 조건을 검증합니다.
플래그나 키가 없으면 skip합니다.

### 14.3 실제 Inspection Test

```bash
RUN_REAL_PROVIDER_INSPECTION=true python -m pytest -m inspection -v -s
```

Inspection Test는 마스킹된 요청, 원본 응답, 정규화 결과를 출력합니다. 응답에는 장소
설명처럼 긴 텍스트가 포함될 수 있으며 최대 출력 길이는 테스트 코드에서 제한합니다.

## 15. 추천 파이프라인 연결 현황

현재 `services/recommendations.py`의 Real 경로는 다음만 사용합니다.

```text
InterpretedConditions.location_query
→ GeocodingProvider.geocode
→ PlaceProvider.search_places
→ shown_place_ids 제외
→ Haversine 직선거리 계산
→ RecommendationResponse
```

다음 연결은 아직 없습니다.

- Weather를 이용한 환경 적합도 점수
- Place 상세조회 기반 운영시간/휴무 판정
- Holiday를 이용한 공휴일 운영 규칙 보완
- Concentration을 이용한 혼잡도 Feature
- 실제 이동시간 Provider
- Naver Blog Search의 분위기/조용함 근거
- 가중치 Scoring과 tie-break

## 16. Provider Blocker

### 16.1 우선순위

| 등급 | 의미 | 처리 기준 |
| --- | --- | --- |
| `P0` | 보안 또는 데이터 손상 위험 | 실제 운영/공유 전에 반드시 해결 |
| `P1` | Core 추천 실행 또는 정확도를 직접 차단 | Phase 1-A 핵심 파이프라인 연결 전에 해결 |
| `P2` | 부분 기능은 가능하지만 품질·복원력 저하 | 제한사항과 fallback을 명시하고 후속 해결 가능 |
| `P3` | 확장성·운영 효율 문제 | MVP 이후 계획 가능 |

상태는 `Open`, `정책 확정/구현 대기`, `현재 논의 중`, `Resolved` 중 하나를
사용합니다. Blocker가 `Resolved`가 되려면 해결 조건과 관련 테스트를 모두
충족해야 합니다.

### 16.2 공통 Blocker

| ID | 우선순위 | Blocker | 영향 | 현재 대응 | 해결 조건 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| `COM-01` | `P0` | 일부 Real Provider가 인증 쿼리를 포함한 `httpx` 예외를 chaining | 실패 traceback에서 API 키 노출 가능 | ProviderError 안전 메시지 계약 확정, Inspection 로그 마스킹, Holiday만 예외 체인 제거 | 모든 Provider 오류에서 URL/헤더 sanitize 테스트 통과 | `정책 확정/구현 대기` |
| `COM-02` | `P1` | `ProviderMetadata`가 코드 모델에 없음 | 출처·결측·조회시각을 일관되게 판단 불가 | 본 문서에서 계약 확정 | 모든 Fake/Real 결과에 source/status/retrieved_at 적용 및 Clock 테스트 | `정책 확정/구현 대기` |
| `COM-03` | `P1` | Tool 계층과 공통 오류 envelope 미구현 | no_data와 장애를 Orchestrator가 구분 불가 | `ToolResult<T>`와 오류 매핑 문서 확정 | 대표 Provider 오류의 Tool 매핑 테스트 통과 | `정책 확정/구현 대기` |
| `COM-04` | `P2` | `EXTERNAL_API_RETRY_COUNT`가 실제 호출에 미적용 | 일시 장애에 취약 | timeout과 retryable 오류만 표시 | 제한된 retry/backoff 구현 및 중복 호출 테스트 | `Open` |
| `COM-05` | `P2` | 구조화 metrics/tracing 없음 | Provider 지연·실패율과 fallback 추적 불가 | Smoke/Inspection 수동 확인 | source/tool/run ID 기반 latency·결과 로그 확정 | `Open` |
| `COM-06` | `P3` | 캐시와 rate limit 보호 없음 | 호출량 증가 시 quota와 latency 위험 | 후보 수와 페이지 고정 제한 | Provider별 TTL·cache key·quota 정책 및 테스트 | `Open` |
| `COM-07` | `P2` | 입력 오류가 `AppError`와 `ValueError`로 혼재 | API/Tool 오류 변환이 불균일 | Tool 매핑에서 둘 다 invalid_input 처리 예정 | 공통 validation 오류 타입 또는 일관된 경계 변환 | `Open` |

### 16.3 GeocodingProvider Blocker

| ID | 우선순위 | Blocker | 영향 | 현재 대응 | 해결 조건 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| `GEO-01` | `P1` | Naver Geocoding은 일반 POI 이름 검색에 제한 | alias 밖 관광지명이 `location_not_found`가 될 수 있음 | 종로구 주요 장소를 주소 alias로 변환 | Place 키워드 검색 연계 또는 POI Provider 확정, alias 밖 시나리오 통과 | `Open` |
| `GEO-02` | `P2` | 다중 주소 결과에서 첫 항목 자동 선택 | 모호한 지명이 잘못된 좌표로 결정될 수 있음 | `count=1` 사용 | confidence/후보 확인 또는 사용자 clarification 정책 확정 | `현재 논의 중` |
| `GEO-03` | `P2` | 지원 지역과 좌표 범위 검증 없음 | 서울 외 요청 또는 비정상 좌표 통제 불가 | MVP 문맥상 종로구 중심 | 지원 지역 정책과 좌표 validation 테스트 | `Open` |

### 16.4 WeatherProvider Blocker

| ID | 우선순위 | Blocker | 영향 | 현재 대응 | 해결 조건 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| `WTH-01` | `P1` | 메서드는 current지만 실제로 가장 가까운 초단기예보 사용 | 사용자가 “현재 날씨”로 오해할 수 있음 | 예보 우선 정책과 WeatherMetadata 확정 | Tool/모델 명칭 변경, forecast_for 반환 테스트 | `정책 확정/구현 대기` |
| `WTH-02` | `P1` | 추천 파이프라인에 Weather가 미연결 | 날씨 조건이 실제 추천 점수에 반영되지 않음 | Interpret Stub 값만 존재 | Weather Tool 연결 및 유/무날씨 Scoring 테스트 | `Open` |
| `WTH-03` | `P2` | SKY/PTY를 세 단계로만 축약 | 온도·습도·강수량·풍속 기반 조건 사용 불가 | `good/neutral/bad`만 반환 | Weather Feature 요구사항 확정 후 모델 확장 여부 결정 | `현재 논의 중` |
| `WTH-04` | `P2` | 발표 제공 시각을 45분 기준으로 고정 | 지연 시 최신 base time에 데이터가 없을 수 있음 | 직전 시간 fallback 계산 | no_data 시 이전 발표분 제한 재조회 정책과 테스트 | `Open` |
| `WTH-05` | `P1` | 방문 예정 시각을 입력받지 않아 일정 기반 예보 선택 불가 | 미래 방문 추천도 가장 이른 예보로 판단할 위험 | 즉시 방문 시나리오만 지원 | visit_at 입력, 가장 가까운 forecast_for 선택 및 범위 초과 정책 테스트 | `Open` |

### 16.5 PlaceProvider Blocker

| ID | 우선순위 | Blocker | 영향 | 현재 대응 | 해결 조건 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| `PLC-01` | `P1` | `preferred_categories`가 검색/후처리에 미사용 | 사용자 선호와 무관한 후보가 섞임 | content type을 내부 대분류로만 매핑 | 카테고리 매핑·필터·빈 후보 정책 테스트 | `Open` |
| `PLC-02` | `P1` | Real 후보의 `operating_hours`가 항상 `None` | 현재 서비스에서 모든 Real 후보가 미검증 결과로 분류 | 특정 장소만 상세조회 가능 | 후보 상세조회 범위, 병렬성, quota 정책 및 운영시간 채움 테스트 | `Open` |
| `PLC-03` | `P1` | 운영시간·휴무일·주차가 복합 원문 또는 raw 필드 | 영업 여부와 남은 시간을 계산할 수 없음 | 원본을 `raw_intro`에 보존 | 정규 운영정보 모델, parser, unknown 규칙, 경복궁 회귀 테스트 | `Open` |
| `PLC-04` | `P2` | 위치 검색 20건, 키워드 검색 최대 100건의 첫 페이지만 사용 | 후보가 많은 지역에서 적합 장소 누락 가능 | 고정 pageNo=1 | 후보 예산과 pagination 중단 조건 확정 | `Open` |
| `PLC-05` | `P2` | 정확 이름 검색은 첫 exact match를 선택 | 동명 장소가 여러 지역에 있으면 오선택 가능 | 지역 코드 전달 가능 | 좌표/주소 기반 동명 tie-break와 clarification 정책 | `현재 논의 중` |
| `PLC-06` | `P2` | 반경 0/음수와 좌표 범위 검증 없음 | 잘못된 외부 요청 또는 예측 불가능한 빈 결과 | 최대 20km clamp만 적용 | 입력 validation 및 Tool invalid_input 매핑 테스트 | `Open` |
| `PLC-07` | `P2` | `detailCommon2`와 `detailIntro2`가 all-or-nothing | 소개 성공·운영정보 실패 시 부분 데이터도 반환하지 못함 | 두 호출 순차 실행 | 필수/선택 상세 정의와 `partial` 결과·warning 테스트 | `Open` |

### 16.6 ConcentrationProvider Blocker

| ID | 우선순위 | Blocker | 영향 | 현재 대응 | 해결 조건 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| `CON-01` | `P1` | 결과는 실시간 현재 혼잡도가 아닌 날짜별 상대 집중률 예측 | “지금 덜 붐비는 곳” 요청을 직접 충족하지 못함 | `forecast_date`와 rate 보존 | 현재 시각 추정 사용 여부와 표현 문구 확정 | `현재 논의 중` |
| `CON-02` | `P1` | 임의 장소가 집중률 데이터셋에 없을 수 있음 | 많은 Place 후보에 혼잡도 Feature를 부여할 수 없음 | 빈 forecasts 반환 | 근처 지점/지역 fallback 또는 Feature 제외 정책 확정 | `현재 논의 중` |
| `CON-03` | `P1` | 추천 파이프라인에 미연결 | 혼잡도 요청이 추천 결과에 반영되지 않음 | 수동 Provider 조회만 가능 | Tool 연결, no_data fallback, Scoring 적용 테스트 | `Open` |
| `CON-04` | `P2` | 여러 alias로 rate를 허용하지만 단위·범위 계약 미확정 | 다른 필드를 잘못 집중률로 해석하거나 점수 왜곡 가능 | `%` 제거 후 float 변환 | 공식 필드·범위 검증과 normalization 규칙 확정 | `Open` |
| `CON-05` | `P2` | Place 지역코드와 Concentration 법정동 코드 체계가 다름 | `110`/`11110` 혼용 시 빈 결과 | 문서와 Smoke Test에 종로구 값 고정 | 공통 지역코드 Resolver와 매핑 테스트 | `Open` |

### 16.7 HolidayProvider Blocker

| ID | 우선순위 | Blocker | 영향 | 현재 대응 | 해결 조건 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| `HOL-01` | `P1` | 공휴일 여부가 특정 장소의 실제 영업 여부를 보장하지 않음 | 공휴일이라는 이유만으로 영업/휴무를 단정할 수 없음 | 공휴일 목록만 정규화 | Place `restdate`와 공휴일 예외 규칙을 결합하는 운영 판정 정책 | `Open` |
| `HOL-02` | `P1` | 추천 파이프라인과 운영시간 계산에 미연결 | 공휴일 운영 예외가 추천 검증에 반영되지 않음 | 수동 Provider 조회만 가능 | 운영정보 Tool 연결 및 공휴일/대체공휴일 시나리오 테스트 | `Open` |
| `HOL-03` | `P2` | 공공데이터포털 서비스별 활용 승인·키 동기화 필요 | 같은 키라도 401/403 또는 승인 지연 가능 | Smoke/Inspection으로 확인 | 배포 환경별 승인 체크리스트와 health 진단 | `Open` |
| `HOL-04` | `P3` | 연간 조회도 `numOfRows=100`, 첫 페이지만 사용 | 데이터 증가 시 일부 누락 가능 | 현재 공휴일 수는 범위 내 | totalCount 기반 pagination 테스트 | `Open` |

### 16.8 다음 구현 순서

1. `COM-01` ProviderError와 Secret-safe 공통 예외 변환
2. `COM-02` ProviderMetadata 모델과 결과 wrapper
3. `COM-03` ToolResult/ToolError 변환 계층
4. `PLC-02`, `PLC-03`, `HOL-01` 운영정보 정규화 및 판정
5. `WTH-02`, `CON-02`, `CON-03` 선택 Feature와 fallback 연결
6. pagination, retry, cache, observability 보완

## 17. 변경 이력

| 날짜 | 버전 | 변경 |
| --- | --- | --- |
| 2026-07-23 | v1 상세화 | 5개 Provider의 실제 요청·응답·오류·제약·테스트 명세 확장 |
| 2026-07-23 | v1 계약 보완 | ProviderMetadata, Tool 오류, Provider별 Blocker 확정 |
| 2026-07-23 | v1 오류 계약 | ProviderError와 retrieved_at/occurred_at 경계 확정 |
| 2026-07-23 | v1 Weather 기준 | 방문 예정 시각의 초단기예보 우선 정책 확정 |
