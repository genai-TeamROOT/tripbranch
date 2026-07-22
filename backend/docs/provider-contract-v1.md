# Provider Contract v1

## 범위

Geocoding, Weather, Place Provider의 Stub/Real 구현이 공유하는 최소 계약이다.
서비스는 구체 Provider를 직접 알지 않고 `providers/protocols.py`의 Protocol만 사용한다.

## 공통 원칙

- 외부 I/O 가능성을 고려해 모든 메서드는 `async`다.
- Stub과 Real은 동일한 입력과 반환 타입을 사용한다.
- 외부 응답은 Provider 또는 Mapper에서 내부 모델로 정규화한다.
- API 키와 원본 응답은 API 응답이나 테스트 로그에 노출하지 않는다.

## Provider 모드

`PROVIDER_MODE`가 Provider들의 공통 기본값이다. `GEOCODING_PROVIDER`,
`WEATHER_PROVIDER`, `PLACE_PROVIDER`, `CONCENTRATION_PROVIDER`에 값이 있으면
해당 Provider만 재정의한다.

```env
PROVIDER_MODE=real
PLACE_PROVIDER=fake
```

위 예시는 Geocoding과 Weather는 Real, Place만 Fake로 실행한다.

## Geocoding

입력은 자유 텍스트 위치 질의다. 출력은 `GeocodeResult`이며 원문 질의,
정규화된 위치명, 위도, 경도를 포함한다.

```python
async def geocode(location_query: str) -> GeocodeResult
```

## Weather

입력은 위도와 경도다. 출력은 `good`, `neutral`, `bad` 중 하나인
`WeatherCondition`이다.

```python
async def get_current_condition(latitude: float, longitude: float) -> WeatherCondition
```

## Place

입력은 중심 좌표, 선호 카테고리, 검색 반경이다. 출력은 정규화된
`PlaceCandidate` 목록이다. 결과가 없으면 빈 목록을 반환한다.

```python
async def search_places(
    latitude: float,
    longitude: float,
    preferred_categories: list[str],
    search_radius_km: float,
) -> list[PlaceCandidate]
```

나담당에게 공유 가능한 장소 필드는 `place_id`, `name`, `category`, `latitude`,
`longitude`, `address`, `operating_hours`, `raw_source`다. 현재 TourAPI
`locationBasedList2`만으로 운영시간을 얻을 수 없어 `operating_hours`는 `None`이다.

## Concentration

관광지 집중률 Provider는 한국관광공사 `TatsCnctrRateService`를 사용한다.
장소 검색과 달리 법정동 시도·시군구 코드와 선택적인 관광지명을 입력받는다.

```python
async def get_forecast(
    area_code: str,
    district_code: str,
    place_name: str | None = None,
) -> ConcentrationResult
```

종로구 경복궁의 기본 조회값은 `area_code="11"`,
`district_code="11110"`, `place_name="경복궁"`이다. Real Provider는 Place
Provider와 같은 `TOUR_API_SERVICE_KEY`를 사용한다. 원본 응답 필드가 변경되더라도
Mapper에서 `ConcentrationForecast`와 `raw_data`로 정규화한다.

## 오류 상태

| 코드 | 의미 | 재시도 |
| --- | --- | --- |
| `invalid_request` | 입력값이 유효하지 않음 | 아니오 |
| `location_not_found` | 위치를 식별하지 못함 | 아니오 |
| `weather_no_data` | 유효한 좌표지만 날씨 항목이 없음 | 가능 |
| `geocoding_unavailable` | Geocoding 호출 또는 응답 오류 | 가능 |
| `weather_unavailable` | Weather 호출 또는 응답 오류 | 가능 |
| `provider_timeout` | 외부 Provider 시간 초과 | 가능 |
| `provider_unavailable` | Place Provider 호출 또는 응답 오류 | 가능 |

Provider 공통 오류에는 `provider`와 선택적인 `details` 메타데이터를 함께 둔다.

## 실제 Smoke Test 실행 조건

일반 테스트에서는 실제 API를 호출하지 않는다. 아래 값을 준비한 뒤 명시적으로
실행한 경우에만 `tests/test_provider_smoke.py`가 외부 호출을 수행한다.

```bash
RUN_REAL_PROVIDER_TESTS=true \
NAVER_MAP_CLIENT_ID=... \
NAVER_MAP_CLIENT_SECRET=... \
WEATHER_API_KEY=... \
TOUR_API_SERVICE_KEY=... \
pytest -m smoke
```

요청 파라미터와 원본 JSON 응답을 확인할 때는 별도 Inspection Test를 사용한다.
인증 쿼리와 헤더는 `<redacted>`로 마스킹되며, 일반 테스트에서는 실행되지 않는다.

```bash
RUN_REAL_PROVIDER_INSPECTION=true pytest -m inspection -v -s
```
