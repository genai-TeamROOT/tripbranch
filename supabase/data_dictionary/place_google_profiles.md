# place_google_profiles 데이터 딕셔너리

## 개요

`public.place_google_profiles`는 `public.places`의 장소와 Google Places API 결과를 1:1로 연결한 프로필 테이블입니다. `content_id`로 조인하며, API가 값을 제공하지 않은 항목은 `NULL`일 수 있습니다.

| 필드 | 타입 | NULL 허용 | 정의 | 값 예시 | 활용 예시 |
| --- | --- | --- | --- | --- | --- |
| `content_id` | text | 아니오 | `places.content_id`와 같은 장소 식별자. PK이자 FK입니다. | `2824887` | `places`와 조인해 제목·주소·좌표를 가져옵니다. |
| `google_place_id` | text | 아니오 | 매칭된 Google Places의 고유 식별자입니다. | `ChIJVYNIcr6ifDURi9hDZMj-sPM` | 이후 Google Places API 재조회·사진 요청의 기준값으로 사용합니다. |
| `google_name` | text | 아니오 | Google 지도에 표시된 장소명입니다. | `준수방키친` | 원본 장소명과의 차이를 검토하거나 사용자 화면에 Google 명칭을 보조 표시합니다. |
| `google_maps_uri` | text | 예 | 해당 Google 지도 장소로 가는 링크입니다. | `https://maps.google.com/?cid=...` | 운영자가 매칭 결과를 빠르게 확인하는 링크로 사용합니다. |
| `matched_distance_m` | double precision | 아니오 | TourAPI 좌표와 Google 장소 좌표 사이의 거리(m)입니다. | `0` | 값이 큰 장소를 우선 검토해 잘못된 매칭 가능성을 확인합니다. |
| `google_review_total` | integer | 예 | Google에 표시된 전체 사용자 리뷰 수입니다. | `58` | 평점과 함께 신뢰도·후보 정렬을 위한 보조 신호로 사용합니다. |
| `google_rating` | numeric(2,1) | 예 | Google 사용자 평점(0~5)입니다. | `4.4` | 같은 조건의 장소 후보를 보조적으로 정렬합니다. |
| `google_primary_type` | text | 예 | Google이 지정한 대표 장소 유형입니다. | `italian_restaurant` | 음식점·공원·박물관 등 1차 카테고리 필터에 사용합니다. |
| `google_types` | jsonb array | 아니오 | 대표 유형을 포함한 Google 장소 유형 목록입니다. | `["italian_restaurant","restaurant","food"]` | 여러 업종을 포괄하는 조건 검색·집계에 사용합니다. |
| `google_price_level` | text | 예 | Google의 상대 가격 등급입니다. | `PRICE_LEVEL_MODERATE` | 가성비·특별한 식사 등 가격 성향 추천의 보조 기준으로 사용합니다. |
| `google_price_range` | jsonb object | 예 | Google이 제공하는 시작·종료 가격 범위입니다. | `{"startPrice":{"units":"20000"},"endPrice":{"units":"30000"}}` | 예산 조건을 만족하는 음식점 후보를 좁힙니다. |
| `google_regular_opening_hours` | jsonb object | 예 | 요일별 영업 시간·영업 여부 등 정규 영업시간 정보입니다. | `{"weekdayDescriptions":["Monday: 11:00 AM–9:00 PM"]}` | “지금 영업 중인 곳”, 특정 요일 방문 가능 장소 안내에 사용합니다. |
| `google_outdoor_seating` | boolean | 예 | 야외 좌석 제공 여부입니다. | `true` | 날씨가 좋은 날 야외 좌석이 있는 카페·식당을 추천합니다. |
| `google_good_for_children` | boolean | 예 | 아이 동반에 적합하다고 Google이 분류했는지 여부입니다. | `true` | “아이와 함께 갈 곳” 후보를 우선 필터링합니다. |
| `google_good_for_groups` | boolean | 예 | 단체 방문에 적합하다고 Google이 분류했는지 여부입니다. | `true` | 모임·회식·여럿이 방문하기 좋은 장소 후보를 찾습니다. |
| `google_allows_dogs` | boolean | 예 | 반려견 동반 허용 여부입니다. | `true` | 반려견 동반 가능 장소 검색에 사용합니다. |
| `google_reservable` | boolean | 예 | 예약 가능 여부입니다. | `true` | 예약 가능한 식당·체험 장소를 우선 추천합니다. |
| `google_serves_breakfast` | boolean | 예 | 아침 식사 제공 여부입니다. | `true` | 이른 시간 식사 장소 추천에 사용합니다. |
| `google_serves_lunch` | boolean | 예 | 점심 식사 제공 여부입니다. | `true` | 점심 식사 장소 추천에 사용합니다. |
| `google_serves_dinner` | boolean | 예 | 저녁 식사 제공 여부입니다. | `true` | 저녁 식사·데이트 장소 추천에 사용합니다. |
| `google_serves_coffee` | boolean | 예 | 커피 제공 여부입니다. | `true` | 카페·식후 커피 가능 장소를 찾는 조건에 사용합니다. |
| `google_serves_dessert` | boolean | 예 | 디저트 제공 여부입니다. | `true` | 디저트 카페·식후 디저트 장소 추천에 사용합니다. |
| `google_serves_vegetarian_food` | boolean | 예 | 채식 메뉴 제공 여부입니다. | `true` | 채식 식사 선택지가 있는 음식점을 찾습니다. |
| `google_dine_in` | boolean | 예 | 매장 내 취식 가능 여부입니다. | `true` | 현장 식사가 가능한 장소만 골라 안내합니다. |
| `google_takeout` | boolean | 예 | 포장 가능 여부입니다. | `true` | 공원 피크닉·숙소 식사처럼 포장 가능한 장소를 추천합니다. |
| `google_parking_options` | jsonb object | 예 | 무료·유료 주차장, 노상 주차, 발레파킹 등 주차 정보입니다. | `{"paidParkingLot":true,"freeStreetParking":false}` | 차량 방문자의 주차 가능 여부와 비용을 안내합니다. |
| `google_accessibility_options` | jsonb object | 예 | 휠체어 진입·주차·좌석·화장실 접근성 정보입니다. | `{"wheelchairAccessibleEntrance":true}` | 이동 약자를 위한 접근성 조건 검색에 사용합니다. |
| `google_photo_count` | integer | 예 | API 응답에 포함된 Google 사진 메타데이터 개수입니다. | `10` | 추후 멀티모달 기능용 사진 수집 우선순위를 정합니다. |
| `google_photos` | jsonb array | 예 | 사진 리소스명·가로·세로·기여자 등 사진 메타데이터 목록입니다. 실제 이미지 파일은 아닙니다. | `[{"name":"places/.../photos/...","widthPx":3000,"heightPx":4000}]` | 대표 이미지 선택·이미지 재호출 대상 선정에 사용합니다. |
| `created_at` | timestamptz | 아니오 | 이 프로필 행이 처음 저장된 시각입니다. | `2026-08-25T11:27:20+09:00` | 적재 시점·데이터 최신성 점검에 사용합니다. |
| `updated_at` | timestamptz | 아니오 | 이 프로필 행이 마지막으로 갱신된 시각입니다. 업데이트 트리거가 관리합니다. | `2026-08-25T11:27:20+09:00` | 재수집·upsert 이후 변경 여부를 추적합니다. |

## 사용 시 유의사항

- `google_*` 값은 Google Places API가 제공한 경우에만 채워지므로, `NULL`은 “아니오”가 아니라 “정보 없음”일 수 있습니다.
- `matched_distance_m`는 매칭 검토 지표이며, 넓은 공원·시장처럼 기준점이 다른 장소는 실제 동일 장소여도 값이 클 수 있습니다.
- `google_photos`의 리소스명은 장기 보관용 이미지 URL이 아닙니다. 실제 표시 시에는 사진 API를 다시 호출하고 Google의 표시·기여 정책을 따라야 합니다.
