# INT-01: RECOMMEND

## 문서 정보

| 항목 | 값 |
|------|-----|
| 버전 | v0.1 |
| 상태 | 초안 (Draft) |
| 최종 수정 | 2026-07-22 |

---

## 1. 정의

**목적:** 사용자의 현재 상황과 조건에 맞는 새로운 장소를 추천한다.

**판별 기준:**
- 추천/알려줘/갈 만한 곳 등 요청 표현이 있음
- 특정 장소를 지정하지 않고 조건만 제시함
- 이전 추천 이력이 없는 상태에서의 장소 요청

**RECOMMEND가 아닌 경우:**
- "경복궁 오늘 열어?" → `INFO` (특정 장소 정보 요청)
- "다른 곳 보여줘" (이전 추천 존재 시) → `MODIFY`
- "첫 번째랑 두 번째 중 어디가 좋아?" → `COMPARE`

---

## 2. 처리 흐름

```
사용자 입력
    ↓
LLM Intent 분류 → RECOMMEND
    ↓
LLM Structured Output → Conditions 추출
    ↓
위치 확정 (current_location + search_center 좌표 변환)
    ↓
사용자 확인/수정
    ↓
API 호출 (장소 + 날씨, 병렬)
    ↓
Hard Filter (필수 조건 미충족 제외)
    ↓
Score 계산 (가중치 적용)
    ↓
정렬 → 상위 3~5개 추천
```

---

## 3. Conditions 스키마

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
  max_travel_time: number | null;  // 분

  // 시간
  time_available: number | null;  // 분

  // 환경
  environment: "indoor" | "outdoor" | "any" | null;

  // 동행
  companion: "solo" | "couple" | "friend" | "parent" | "child" | "pet" | null;

  // 예산
  budget: "free" | string | null;

  // 태그 (복수 가능)
  preference_tags: string[];
  exclude_tags: string[];
  special_requirements: string[];
}
```

---

## 4. Conditions 필드 정의

### 위치 필드

| 필드 | 타입 | 설명 | 처리 방식 | 예시 |
|------|------|------|-----------|------|
| `current_location` | string \| null | 사용자의 현재 위치 | Update | "강남역", GPS 좌표 문자열 |
| `search_center` | string \| null | 장소 검색 기준점. null이면 current_location 사용 | Update | "경복궁", "성수동", null |

### 장소 유형 필드

| 필드 | 타입 | 설명 | 처리 방식 | 예시 |
|------|------|------|-----------|------|
| `place_types` | PlaceType[] | 추천 장소 유형 (복수 가능) | Update (전체 교체) | ["cultural_facility", "restaurant"] |
| `place_tags` | PlaceTag[] | 세부 장소 분류 (복수 가능) | Add / Remove | ["박물관", "카페"] |

### 날씨 필드

| 필드 | 타입 | 설명 | 처리 방식 | 예시 |
|------|------|------|-----------|------|
| `weather` | enum \| null | 현재 날씨 상태 | Update | `rain`, `snow`, `hot`, `cold`, `good` |
| `weather_intent` | enum \| null | 날씨에 대한 사용자 의도 | Update | `AVOID`, `ENJOY`, `IGNORE` |

### 이동 필드

| 필드 | 타입 | 설명 | 처리 방식 | 예시 |
|------|------|------|-----------|------|
| `transport` | enum \| null | 이동 수단 | Update | `walk`, `public`, `car` |
| `max_travel_time` | int \| null | 최대 이동 시간 (분) | Update | 10, 30, 60 |

### 기타 필드

| 필드 | 타입 | 설명 | 처리 방식 | 예시 |
|------|------|------|-----------|------|
| `time_available` | int \| null | 남은 관광 가능 시간 (분) | Update | 60, 120 |
| `environment` | enum \| null | 실내/야외 선호 | Update | `indoor`, `outdoor`, `any` |
| `companion` | enum \| null | 동행자 유형 | Update | "solo", "parent", "child", "couple" |
| `budget` | string \| null | 예산 조건 | Update / Remove | "free", "10000", "30000" |
| `preference_tags` | string[] | 선호 분위기/특성 | Add / Remove | ["조용한", "감성", "사진찍기좋은"] |
| `exclude_tags` | string[] | 제외 조건 | Add / Remove | ["붐비는", "시끄러운"] |
| `special_requirements` | string[] | 필수 편의시설 | Add / Remove | ["주차", "휠체어", "반려동물"] |

---

## 5. 위치 처리 상세

### 필드 역할 구분

| 필드 | 역할 | 데이터 소스 |
|------|------|------------|
| `current_location` | 사용자가 지금 있는 곳 | ① 기기 GPS (기본) ② 사용자 직접 입력 |
| `search_center` | 장소 검색 반경의 중심점 | ① 사용자 발화에서 추출 ② 없으면 current_location과 동일 |

### 위치 확보 순서

```
current_location 확보:
  ① 앱 접속 시 기기 GPS로 자동 획득 (기본)
  ② GPS 사용 불가 또는 거부 시 → 사용자에게 현재 위치 직접 입력 요청
  ③ 사용자가 "나 지금 ~~야"로 현재 위치를 명시 → GPS 대신 사용

search_center 결정:
  ① 사용자가 "~~ 근처", "~~ 주변", "~~ 가려는데"로 목적지 명시
     → search_center = 해당 장소
  ② 목적지 언급 없음
     → search_center = null → current_location을 기준점으로 사용
```

### 동작 케이스

| 케이스 | 입력 | current_location | search_center | 검색 기준 | 거리 계산 기준 |
|--------|------|-----------------|---------------|-----------|--------------|
| 근처 검색 | "근처 카페 추천" | GPS 좌표 | null | current_location | current_location → 후보 |
| 목적지 지정 | "경복궁 근처 맛집" | GPS 좌표 | "경복궁" | search_center | search_center → 후보 |
| 현재 위치 직접 입력 | "나 지금 성수야. 카페 추천" | "성수" | null | current_location | current_location → 후보 |
| 출발지+목적지 | "종로 가려는데 근처 볼거리" | GPS 좌표 | "종로" | search_center | search_center → 후보 |

### API 호출 시 위치 사용

| 용도 | 사용 필드 |
|------|-----------|
| `locationBasedList2` (mapX, mapY, radius) | search_center 좌표 (null이면 current_location) |
| 거리 계산 (후보까지의 거리) | search_center 좌표 (null이면 current_location) |
| 날씨 API 호출 | current_location 좌표 |

### 좌표 변환

```
문자열 위치 → 좌표 변환:
  ① 정확한 주소 → 지오코딩 API
  ② 대표 장소명 (경복궁, 강남역) → 장소 검색 → 대표 좌표 사용
  ③ 지역명 (성수동, 종로) → 해당 지역 중심 좌표

검색 결과 처리:
  - 결과 1개 → 자동 선택
  - 결과 여러 개 → 사용자에게 후보 목록 제공
  - 결과 없음 → 더 구체적으로 입력 요청
```

---

## 6. place_types 정의

### enum 목록

```typescript
type PlaceType =
  | "attraction"         // 관광지 (contentTypeId: 12)
  | "cultural_facility"  // 문화시설 (contentTypeId: 14)
  | "festival"           // 축제/공연/행사 (contentTypeId: 15)
  | "leisure"            // 레포츠 (contentTypeId: 28)
  | "shopping"           // 쇼핑 (contentTypeId: 38)
  | "restaurant";        // 음식점/카페 (contentTypeId: 39)
```

### 상세 정의

| place_type | contentTypeId | 정의 | 포함 범위 | MVP |
|-----------|--------------|------|-----------|-----|
| `attraction` | 12 | 관광지·자연·역사·체험 | 공원, 궁궐, 자연경관, 전망대, 테마파크, 체험관광, 사찰 | ✅ |
| `cultural_facility` | 14 | 문화시설 | 박물관, 미술관, 도서관, 공연장, 과학관, 전시관 | ✅ |
| `festival` | 15 | 축제/공연/행사 | 축제, 전시회, 공연, 콘서트, 스포츠경기 | ✅ |
| `leisure` | 28 | 레포츠 | 자전거, 수상레저, 스키, 캠핑, 골프 | ⬜ 심화 |
| `shopping` | 38 | 쇼핑 | 시장, 쇼핑몰, 면세점, 백화점, 아웃렛 | ✅ |
| `restaurant` | 39 | 음식점·카페·주점 | 한식, 양식, 카페, 찻집, 바, 분식 | ✅ |

### API 호출 매핑

```python
PLACE_TYPE_TO_CONTENT_TYPE_ID = {
    "attraction": "12",
    "cultural_facility": "14",
    "festival": "15",
    "leisure": "28",
    "shopping": "38",
    "restaurant": "39",
}
```

### 복수 선택 시 API 호출 전략

```
place_types 개수에 따른 전략:

1개
  → locationBasedList2(contentTypeId=해당값) 단일 호출

2~3개
  → 각 contentTypeId별 병렬 호출
  → 결과 병합 → 통합 점수 계산 → 정렬

  예) place_types: ["cultural_facility", "restaurant"]
  → locationBasedList2(contentTypeId=14) 호출
  → locationBasedList2(contentTypeId=39) 호출
  → 병합 후 정렬

0개 (빈 배열, 전체 검색)
  → contentTypeId 미지정으로 전체 조회
  → 응답에서 contenttypeid 기준 후처리 필터링

4개 이상
  → contentTypeId 미지정으로 전체 조회
  → 응답에서 해당 유형만 필터링
```

### 빈 배열의 의미

```
place_types: []  → 전체 유형 검색 (사용자가 유형을 지정하지 않음)
place_types: ["restaurant"]  → 음식점/카페만 검색
```

---

## 7. place_tags 정의

### enum 목록 (MVP)

```typescript
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
```

### place_tags → place_type 소속 매핑

| place_tag | 소속 place_type | 신분류 코드 (참고) |
|-----------|----------------|-------------------|
| 공원 | attraction | VE0301~VE0305 |
| 궁궐 | attraction | HS010100 |
| 산 | attraction | NA010100 |
| 해변 | attraction | NA020900 |
| 호수 | attraction | NA020200 |
| 계곡 | attraction | NA010400 |
| 전망대 | attraction | VE010200 |
| 테마파크 | attraction | VE020100 |
| 동물원 | attraction | VE020300 |
| 수목원 | attraction | NA040700 |
| 사찰 | attraction | HS030100 |
| 성곽 | attraction | HS010200 |
| 마을 | attraction | VE040200 |
| 둘레길 | attraction | VE040300 |
| 전통체험 | attraction | EX010100 |
| 공예체험 | attraction | EX0201xx |
| 웰니스 | attraction | EX0501xx |
| 박물관 | cultural_facility | VE070100 |
| 미술관 | cultural_facility | VE070600 |
| 도서관 | cultural_facility | VE090300 |
| 공연장 | cultural_facility | VE060100 |
| 과학관 | cultural_facility | VE070500 |
| 전시관 | cultural_facility | VE070300 |
| 축제 | festival | EV0101xx |
| 전시회 | festival | EV030100 |
| 공연 | festival | EV0201xx |
| 콘서트 | festival | EV020700 |
| 시장 | shopping | SH0601~SH0602 |
| 쇼핑몰 | shopping | SH020100 |
| 면세점 | shopping | SH0401xx |
| 백화점 | shopping | SH010100 |
| 한식 | restaurant | FD0101xx |
| 일식 | restaurant | FD020200 |
| 중식 | restaurant | FD020100 |
| 양식 | restaurant | FD020300 |
| 카페 | restaurant | FD050100 |
| 찻집 | restaurant | FD050200 |
| 주점 | restaurant | FD0401xx |
| 분식 | restaurant | FD030400 |

### place_tags 처리 규칙

```
규칙 1: place_tags가 있으면 소속 place_type을 자동 추론 가능
  예) place_tags: ["박물관"] → place_types에 "cultural_facility" 자동 포함

규칙 2: place_types + place_tags 둘 다 있으면 place_tags로 세부 필터링
  예) place_types: ["attraction"], place_tags: ["공원"]
  → attraction 조회 후 공원만 필터

규칙 3: place_types만 있고 place_tags 없으면 해당 유형 전체 검색
  예) place_types: ["restaurant"], place_tags: []
  → 음식점/카페 전체

규칙 4: place_tags만 있고 place_types 없으면 매핑에서 place_type 자동 설정
  예) place_tags: ["카페", "박물관"]
  → place_types: ["restaurant", "cultural_facility"] 자동 설정

규칙 5: place_tags 언급 순서가 선호 순위
  예) "박물관이나 카페" → rank_1: 박물관, rank_2: 카페
```

---

## 8. weather_intent 판별

| 값 | 의미 | 예시 입력 | 추천 정책 |
|----|------|-----------|-----------|
| `AVOID` | 날씨를 피하고 싶음 | "비 오는데 갈 곳", "더운데 시원한 곳" | environment=indoor 설정 |
| `ENJOY` | 날씨를 즐기고 싶음 | "눈 오는 거리 걷고 싶어", "단풍 보러" | environment=outdoor 설정 |
| `IGNORE` | 날씨 무관 | 날씨 언급 없음 | 날씨 가중치 제외 |
| `null` | 판별 불가 | "눈 오는데 추천" (의도 모호) | 사용자에게 추가 질문 |

**모호한 경우 처리:**

```
LLM이 AVOID/ENJOY 판별 불가
  → weather_intent: null 반환
  → 사용자에게 "실내 장소를 원하시나요, 눈 오는 풍경을 즐기고 싶으신가요?" 질문
  → 응답 반영 후 추천 진행
```

---

## 9. 날씨 정보 확보 순서

```
① 사용자 입력에 날씨 포함
  → LLM이 weather + weather_intent 추출
  → 사용자 확인

② 사용자가 날씨를 입력하지 않음
  → 날씨 API 호출 (current_location 좌표 기준)

③ 날씨 API 실패
  → 사용자에게 현재 날씨 입력 요청

④ 사용자도 날씨를 제공하지 않음
  → 날씨 항목을 추천 계산에서 제외
  → 나머지 가중치 재정규화
```

날씨 정보가 없다는 이유로 임의로 처리하지 않는다.

---

## 10. 조건 부족 시 기본 정책

| 상황 | 처리 |
|------|------|
| current_location 없음 (GPS 실패) | "현재 위치를 알려주세요" 질문 |
| search_center 없음 | current_location을 검색 기준으로 사용 |
| place_types 빈 배열 | 전체 유형에서 검색 기준점 가까운 순 추천 |
| weather 없음 + API 실패 | 날씨 가중치 제외, 나머지 재정규화 |
| weather_intent null (모호) | 사용자에게 실내/야외 선호 추가 질문 |
| 모든 조건 없음 ("추천해줘") | current_location 확인 우선 |
| transport 없음 | 기본값 도보 기준 (default_transport: walk) |
| max_travel_time 없음 | 기본 검색 반경 1km 적용 |
| budget 없음 | 예산 필터 미적용 |
| companion 없음 | 동행자 필터 미적용 |

---

## 11. 필드별 변경 규칙

| 필드 | 단일/복수 | 변경 방식 | MODIFY 시 동작 예시 |
|------|-----------|-----------|-------------------|
| `current_location` | 단일 | Update | GPS 갱신 또는 "나 지금 ~~야" |
| `search_center` | 단일 | Update | "경복궁 말고 인사동 근처로" |
| `place_types` | 복수 | Update (전체 교체) | "카페 말고 맛집" → ["restaurant"], tags 조정 |
| `place_tags` | 복수 | Add / Remove | "박물관도 포함" → 기존에 추가 |
| `weather` | 단일 | Update | API 최신값 또는 사용자 변경 |
| `weather_intent` | 단일 | Update | "실내로" → AVOID |
| `transport` | 단일 | Update | "차로 갈게" → car |
| `max_travel_time` | 단일 | Update | "30분 이내로" → 30 |
| `time_available` | 단일 | Update | "1시간밖에 없어" → 60 |
| `environment` | 단일 | Update | "야외로" → outdoor |
| `companion` | 단일 | Update | "아이랑 같이" → child |
| `budget` | 단일 | Update / Remove | "무료만" → "free" / "가격 상관없어" → null |
| `preference_tags` | 복수 | Add / Remove | "조용한 곳" → 추가 |
| `exclude_tags` | 복수 | Add / Remove | "시끄러운 곳 빼줘" → 추가 |
| `special_requirements` | 복수 | Add / Remove | "주차 가능한 곳" → 추가 |

**`place_types`가 Update인 이유:**
- "카페 말고 맛집"이면 기존 types를 통째로 교체하는 게 자연스러움
- Add/Remove로 하면 매번 2개 동작으로 해석해야 함

**`place_tags`가 Add/Remove인 이유:**
- "박물관도 보고 싶어"처럼 기존 태그에 누적하는 것이 자연스러움
- 단, MODIFY에서 place_types가 교체되면 소속되지 않는 place_tags는 자동 제거

---

## 12. LLM 추출 예시

### 기본 추출

| 입력 | current_location | search_center | place_types | place_tags | 기타 조건 |
|------|-----------------|---------------|------------|------------|-----------|
| "근처 카페 추천" | GPS | null | ["restaurant"] | ["카페"] | — |
| "경복궁 근처 맛집" | GPS | "경복궁" | ["restaurant"] | [] | — |
| "나 지금 성수야. 카페 추천" | "성수" | null | ["restaurant"] | ["카페"] | — |
| "비 오는데 갈 만한 곳" | GPS | null | [] | [] | weather=rain, weather_intent=AVOID, environment=indoor |
| "부모님과 걸어서 갈 카페" | GPS | null | ["restaurant"] | ["카페"] | companion=parent, transport=walk |
| "30분 안에 갈 수 있는 무료 전시" | GPS | null | ["festival"] | ["전시회"] | max_travel_time=30, budget=free |
| "종로 가려는데 근처 볼거리" | GPS | "종로" | ["attraction"] | [] | — |

### 복수 유형 추출

| 입력 | place_types | place_tags |
|------|------------|------------|
| "박물관이나 카페 가고 싶어" | ["cultural_facility", "restaurant"] | ["박물관", "카페"] |
| "공원 산책하고 근처 카페" | ["attraction", "restaurant"] | ["공원", "카페"] |
| "시장 구경하고 맛집 갈래" | ["shopping", "restaurant"] | ["시장"] |
| "박물관이나 미술관, 쇼핑도 괜찮아" | ["cultural_facility", "shopping"] | ["박물관", "미술관"] |
| "오늘 전시 볼 만한 곳" | ["festival", "cultural_facility"] | ["전시회", "전시관"] |

### 전체 JSON 예시

```json
{
  "intent": "RECOMMEND",
  "conditions": {
    "current_location": "37.5665,126.9780",
    "search_center": "경복궁",
    "place_types": ["cultural_facility", "restaurant"],
    "place_tags": ["박물관", "미술관", "카페"],
    "weather": "rain",
    "weather_intent": "AVOID",
    "transport": "walk",
    "max_travel_time": 15,
    "time_available": null,
    "environment": "indoor",
    "companion": "parent",
    "budget": null,
    "preference_tags": ["조용한"],
    "exclude_tags": [],
    "special_requirements": []
  }
}
```

---

## 13. 추천 점수 카테고리 반영

### Hard Filter (추천 후보 제외)

```
다음 조건을 만족하지 않으면 후보에서 제외:
- 운영 종료 / 휴무
- 검색 반경 초과
- 예산 초과 (budget 기준)
- place_types 불일치 (place_types가 비어있지 않은 경우)
- environment 불일치 (weather_intent=AVOID일 때 outdoor 제외)
```

### 카테고리 점수

```
place_tags 언급 순서 기반 (선호 순위):
  rank_1: 1.00  (첫 번째 언급)
  rank_2: 0.85  (두 번째 언급)
  rank_3: 0.70  (세 번째 언급)
  rank_4+: 0.60 (네 번째 이후)

place_types에는 포함되지만 place_tags에 매칭되지 않는 장소:
  → 카테고리 점수 0.50 (기본값)

place_types 빈 배열 (전체 검색) + place_tags 없음:
  → 카테고리 점수 일괄 1.00 (차등 없음)
```

---

## 14. 경계 사례

| 입력 | 판정 | 이유 |
|------|------|------|
| "경복궁" (단독) | INFO | 정보 조회 의도 |
| "경복궁 같은 곳" | RECOMMEND | 유사 장소 추천, search_center는 미설정 |
| "경복궁 근처 카페" | RECOMMEND | search_center="경복궁" |
| "나 경복궁인데 카페 추천" | RECOMMEND | current_location="경복궁", search_center=null |
| "맛집 추천" | RECOMMEND | place_types: ["restaurant"] |
| "더 가까운 곳" (추천 이력 있음) | MODIFY | 조건 변경 |
| "더 가까운 곳" (추천 이력 없음) | RECOMMEND | preference로 처리 |

---

## 15. 관련 문서
