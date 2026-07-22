## 문서 정보

| 항목 | 값 |
| --- | --- |
| 버전 | v0.1 |
| 상태 | 초안 (Draft) |
| 브랜치 | `docs/intent-definition` |
| 경로 | `docs/design/intent-definition.md` |

---

## 1. 구조 원칙

```
사용자 입력
    ↓
① Intent 분류 (목적 1개)
    ↓
② Intent별 Structured Output 추출
    ↓
③ 처리 엔진으로 전달
```

**핵심 분리:**

- **Intent** = 사용자의 질문 목적 (항상 1개)
- **Conditions** = 추천 조건 (여러 개 동시 가능)

---

## 2. MVP Intent 목록 (5개)

| ID | Intent | 정의 | 후속 처리 | 대표 질문 |
| --- | --- | --- | --- | --- |
| INT-01 | `RECOMMEND` | 조건에 맞는 장소를 추천받고 싶음 | 조건 추출 → 필터링 → 점수 계산 → 추천 | 비 오는데 갈 만한 곳 추천, 부모님과 갈 카페 추천 |
| INT-02 | `INFO` | 특정 장소의 정보를 알고 싶음 | 장소 식별 → API 조회 → 정보 응답 | 경복궁 오늘 열어?, 주차 가능해? |
| INT-03 | `MODIFY` | 기존 추천을 변경하고 싶음 | 변경 조건 추출 → 기존 상태 병합 → 재추천 | 다른 곳 추천해줘, 더 가까운 곳으로 |
| INT-04 | `COMPARE` | 추천받은 장소들을 비교하고 싶음 | 비교 대상 식별 → 항목별 비교 → 설명 | A랑 B 중 어디가 좋아?, 더 조용한 곳은? |
| INT-05 | `GENERAL` | 여행 관련 일반 질문 또는 대화 | LLM 일반 응답 | 서울 여행 팁 알려줘, 아이랑 가기 좋은 계절은? |

## 3. 심화 Intent

| ID | Intent | 정의 | 대표 질문 |
| --- | --- | --- | --- |
| INT-06 | `REPLAN` | 여러 장소를 조합하거나 기존 일정을 재구성 | 추천해준 곳 포함해서 일정 짜줘, 2시간 코스 만들어줘 |
| INT-07 | `IMAGE` | 현장 사진을 분석 | 이 안내문 뭐라고 써있어?, 휴관이야? |

---

## 4. Intent별 추출 변수 상세 -> 각 인텐트 별 md 파일 참고 

---


## 5. Intent 판별 규칙

### 판별 우선순위

```
1. IMAGE    → 이미지 첨부 여부 (즉시 판별) - 심화 
2. MODIFY   → 이전 추천 이력 존재 + 변경/거절 표현
3. COMPARE  → 이전 추천 이력 존재 + 비교 표현
4. INFO     → 특정 장소명 + 정보성 질문
5. RECOMMEND → 장소 추천 요청 (명시적 또는 조건 제시)
6. REPLAN   → 일정/코스/시간 재구성 표현
7. GENERAL  → 위 어디에도 해당하지 않음
```

### 맥락 의존 판별

| 이전 상태 | 입력 | 판정 | 이유 |
| --- | --- | --- | --- |
| 추천 이력 있음 | "다른 곳" | MODIFY | 변경 의도 |
| 추천 이력 없음 | "다른 곳" | → 안내 후 RECOMMEND 유도 | 전제조건 미충족 |
| 추천 이력 있음 | "어디가 좋아?" | COMPARE | 비교 의도 |
| 추천 이력 없음 | "어디가 좋아?" | GENERAL or RECOMMEND | 맥락에 따라 |
| INFO 응답 직후 | "거기 근처 카페는?" | RECOMMEND | 위치 기준 새 추천 |
| 추천 이력 있음 | "카페 말고 맛집" | MODIFY | 조건 변경 |
| 추천 이력 없음 | "카페 말고 맛집" | RECOMMEND | place_type=restaurant |

### 경계 사례

| 입력 | 판정 | 이유 |
| --- | --- | --- |
| "경복궁" (단독) | INFO | 정보 조회 의도 |
| "경복궁 같은 곳" | RECOMMEND | 유사 장소 추천 |
| "경복궁 근처 카페" | RECOMMEND | 경복궁은 location 조건 |
| "경복궁 오늘 열어?" | INFO | 운영시간 질문 |
| "경복궁 오늘 열어? 안 열면 다른 곳" | INFO (우선) | 복합 입력 → 첫 번째 의도 처리 후 결과에 따라 다음 턴 유도 |
| "첫 번째 괜찮아, 거기 몇 시까지 해?" | INFO | 장소 선택 + 정보 질문 |
| "더 조용한 곳" (추천 이력 있음) | MODIFY | 조건 변경 |
| "더 조용한 곳" (추천 이력 없음) | RECOMMEND | preference_tags=["조용한"] |

---

## 6. Conditions 공통 스키마

RECOMMEND, MODIFY, REPLAN이 공유하는 조건 구조:

```tsx
interface Conditions {
  // 위치
  location: string | null;

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
  budget: "free" | string | null;  // "free" 또는 금액

  // 태그 (복수 가능)
  preference_tags: string[];
  exclude_tags: string[];
  special_requirements: string[];
}

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
```

### 필드별 변경 규칙

| **필드** | **단일/복수** | **변경 방식** | **MODIFY 시 동작** |
| --- | --- | --- | --- |
| **`place_types`** | 복수 | **Update** (전체 교체) | "카페 말고 맛집" → ["restaurant"], tags에서 "카페" 제거 |
| **`place_tags`** | 복수 | **Add / Remove** | "박물관도 추가" → 기존에 추가 |
| **`location`** | 단일 | Update |  |
| **`weather`** | 단일 | Update |  |
| **`weather_intent`** | 단일 | Update |  |
| **`transport`** | 단일 | Update |  |
| **`max_travel_time`** | 단일 | Update |  |
| **`time_available`** | 단일 | Update |  |
| **`environment`** | 단일 | Update |  |
| **`companion`** | 단일 | Update |  |
| **`budget`** | 단일 | Update / Remove |  |
| **`preference_tags`** | 복수 | Add / Remove |  |
| **`exclude_tags`** | 복수 | Add / Remove |  |
| **`special_requirements`** | 복수 | Add / Remove |  |

---

## 7. 조건 부족 시 기본 정책

| 상황 | 처리 |
| --- | --- |
| location 없음 | "현재 위치나 기준 장소를 알려주세요" 질문 |
| place_type 없음 | 위치 기반 전체 카테고리에서 가까운 순 추천 |
| weather 없음 + API 실패 | 날씨 가중치 제외, 나머지 재정규화 |
| weather_intent 모호 | 사용자에게 실내/야외 선호 추가 질문 |
| 모든 조건 없음 ("추천해줘") | location 질문 우선 |
| transport 없음 | 기본값 도보 기준 (default_transport: walk) |
| max_travel_time 없음 | 기본 검색 반경 1km 적용 |

---

## 8. 심화 Intent 요약 (상세 미작성)

| Intent | 추출 대상 | 비고 |
| --- | --- | --- |
| `REPLAN` | 포함 장소, 시간 제약, 이동 수단, 우선순위 | Conditions 공통 스키마 재사용 |
| `IMAGE` | 이미지 데이터, 질문 유형 (OCR/장소식별/상태확인) | 별도 처리 파이프라인 |

---

## 9. 변경 이력

| 버전 | 날짜 | 변경 내용 |
| --- | --- | --- |
| v0.1 | 2026-07-22 | 초안 작성 - ntent 5개 확정, 추출 스키마 정의, Conditions 공통화, 판별 규칙 추가 |

