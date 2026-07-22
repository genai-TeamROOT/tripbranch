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
- Tool: `resolveLocation`, `getPlaceDetails`처럼 업무 목적 단위로 Provider를 조합
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
- 요청 ID와 `recommendationRunId` 연결 없음
- 공통 pagination 추상화 없음

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
- 목표 Tool: `resolveLocation` (`TBD`)

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
- 목표 Tool: `getCurrentWeather` (`TBD`)

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

### 9.4 Fake 동작

생성 시 전달된 `WeatherCondition`을 그대로 반환합니다. Factory에서는
`FAKE_WEATHER_CONDITION`으로 값을 결정합니다.

### 9.5 오류와 제약

| 상황 | 결과 |
| --- | --- |
| HTTP/JSON 오류 | `weather_unavailable`, retryable |
| KMA `resultCode != 00` | `weather_unavailable`, retryable |
| SKY/PTY 없음 | `weather_no_data`, retryable |

- 메서드 이름은 current지만 실제 데이터는 가장 가까운 초단기 **예보** 시각임
- 추천 서비스에는 아직 연결되지 않음
- 날씨 결측 시 가중치 재정규화 정책은 추천 계층의 `TBD`

## 10. PlaceProvider

### 10.1 책임과 구현

- Protocol: `PlaceProvider`
- Fake: `app/providers/stub.py::FakePlaceProvider`
- Real: `app/providers/real_place.py::RealPlaceProvider`
- 후보 Mapper: `app/providers/mappers.py`
- 목표 Tool: `searchNearbyPlaces`, `getPlaceDetails` (`TBD`)

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

운영시간은 `usetime`, `usetimeculture`, `opentimefood`, `checkintime`,
`openperiod` 중 처음 존재하는 값을 사용합니다. 장소 유형에 따라 `restdate`,
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
- 목표 Tool: `getCongestion` (`TBD`)

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

## 16. 미결 사항과 후속 작업

| 우선순위 | 항목 | 상태 |
| --- | --- | --- |
| 높음 | Provider 예외에서 인증 쿼리가 traceback에 노출되지 않도록 공통 처리 | `TBD` |
| 높음 | Place 후보별 상세정보 조회 전략과 호출량 제어 | `TBD` |
| 높음 | 운영시간·휴무·공휴일 정규 모델 및 parser | `TBD` |
| 높음 | Weather/Concentration 결측 시 Feature 제외 정책 | 현재 논의 중 |
| 중간 | `preferred_categories` 실제 필터 적용 | `TBD` |
| 중간 | pagination 및 최대 후보 수 정책 | `TBD` |
| 중간 | retry/backoff에 `EXTERNAL_API_RETRY_COUNT` 적용 | `TBD` |
| 중간 | 현재 혼잡도와 예측 집중률의 의미 구분 | 현재 논의 중 |
| 낮음 | Provider별 캐시 TTL과 invalidation | `TBD` |
| 낮음 | 입력 오류를 공통 `AppError`로 통일 | `TBD` |

## 17. 변경 이력

| 날짜 | 버전 | 변경 |
| --- | --- | --- |
| 2026-07-23 | v1 상세화 | 5개 Provider의 실제 요청·응답·오류·제약·테스트 명세 확장 |
