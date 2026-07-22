# 지오코딩 / 날씨 API 요청·응답 샘플

`GeocodingProvider`(Naver Geocoding), `WeatherProvider`(KMA 단기예보) 구현 시
실제로 확인한 요청·응답 형태를 기록한다. Provider 코드에서 이 필드명들을 그대로
파싱하므로, 업스트림 스펙이 바뀌면 이 문서도 함께 갱신할 것.

## KMA 단기예보 조회서비스 - getUltraSrtFcst(초단기예보)

실제 서비스키로 호출해 확인함(2026-07-22, 서울 중구 nx=60, ny=127).

- 엔드포인트: `GET https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtFcst`
- 필수 쿼리 파라미터: `serviceKey`(디코딩 키), `pageNo`, `numOfRows`, `dataType=JSON`, `base_date`(YYYYMMDD), `base_time`(HHMM, 매시 30분 발표·40분부터 조회 가능), `nx`, `ny`
- 초단기실황(getUltraSrtNcst)과 달리 SKY(하늘상태)를 PTY(강수형태)와 함께 제공하므로, good/neutral/bad 판정에 필요한 두 값을 한 번의 호출로 얻을 수 있다.

응답(일부, 카테고리당 6시간치 시간별 값이 반복됨):

```json
{
  "response": {
    "header": { "resultCode": "00", "resultMsg": "NORMAL_SERVICE" },
    "body": {
      "dataType": "JSON",
      "items": {
        "item": [
          { "baseDate": "20260722", "baseTime": "1030", "category": "LGT", "fcstDate": "20260722", "fcstTime": "1100", "fcstValue": "0", "nx": 60, "ny": 127 },
          { "baseDate": "20260722", "baseTime": "1030", "category": "PTY", "fcstDate": "20260722", "fcstTime": "1100", "fcstValue": "1", "nx": 60, "ny": 127 },
          { "baseDate": "20260722", "baseTime": "1030", "category": "RN1", "fcstDate": "20260722", "fcstTime": "1100", "fcstValue": "1mm 미만", "nx": 60, "ny": 127 },
          { "baseDate": "20260722", "baseTime": "1030", "category": "SKY", "fcstDate": "20260722", "fcstTime": "1100", "fcstValue": "4", "nx": 60, "ny": 127 }
        ]
      }
    }
  }
}
```

- 카테고리: `SKY`(1 맑음/3 구름많음/4 흐림), `PTY`(0 없음/1 비/2 비·눈/3 눈/4 소나기/5 빗방울/6 빗방울눈날림/7 눈날림), `LGT`(낙뢰), `RN1`(1시간 강수량, 숫자가 아닌 "강수없음"/"1mm 미만" 같은 문자열도 옴 - 현재 매퍼는 SKY/PTY만 사용).
- 실패 시 `response.header.resultCode`가 `"00"`이 아님(예: `"03"` NODATA_ERROR) → `WeatherProvider`는 이 경우 `AppError(code="weather_unavailable")`.
- SKY/PTY 어느 한쪽도 응답에 없는 좌표(관측 범위 밖 등) → `AppError(code="weather_no_data")`.

구현: [`app/providers/weather.py`](../app/providers/weather.py), [`app/providers/kma_grid.py`](../app/providers/kma_grid.py)(위경도→nx,ny 변환).

## Naver Cloud Platform Geocoding API

- 엔드포인트: `GET https://naveropenapi.apigw.ntruss.com/map-geocode/v2/geocode`
- 필수 헤더: `Accept: application/json`, `x-ncp-apigw-api-key-id`, `x-ncp-apigw-api-key`
- 쿼리 파라미터: `query`(필수), `count`(결과 개수, provider는 `1`로 고정해 top1을 채택)

응답 스키마(공식 문서 기준, 실제 키로는 아래 "확인된 문제" 참고):

```json
{
  "status": "OK",
  "meta": { "totalCount": 1, "page": 1, "count": 1 },
  "addresses": [
    {
      "roadAddress": "서울특별시 종로구 사직로 161",
      "jibunAddress": "서울특별시 종로구 세종로 1-1",
      "englishAddress": "161, Sajik-ro, Jongno-gu, Seoul, Republic of Korea",
      "x": "126.9770",
      "y": "37.5796",
      "distance": 0,
      "addressElements": ["..."]
    }
  ]
}
```

- `x`는 경도, `y`는 위도(둘 다 문자열) - 순서가 직관과 반대라 실수하기 쉬움.
- 결과 없음: `status: "OK"` + `addresses: []`로 추정(공식 문서에 명시 안 됨) → `AppError(code="location_not_found")`.
- 이 API는 도로명/지번 주소 검색에 최적화되어 있어 "경복궁" 같은 순수 장소명 인식률은 검증 전.

**확인된 문제(2026-07-22 실제 키로 호출)**: 인증 헤더는 통과했으나 모든 요청이
`401 Permission Denied`(`errorCode: "210", "A subscription to the API is required."`)로
실패함. NCP 콘솔에서 해당 애플리케이션에 **Maps > Geocoding** 서비스 이용 신청이
안 되어 있을 가능성이 높음 (Client ID/Secret 발급과 API별 이용 신청은 별개 절차).
→ 콘솔에서 구독 처리 후 재검증 필요. `RealGeocodingProvider` 코드는 공식 응답
스키마 기준으로 작성·단위테스트(mock)까지 마쳤으며, 구독 활성화 후 실호출
샘플로 이 섹션을 갱신할 것.

구현: [`app/providers/geocoding.py`](../app/providers/geocoding.py).
