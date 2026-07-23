# INT-02: INFO

## 문서 정보

| 항목 | 값 |
|------|-----|
| 버전 | v0.1 |
| 상태 | 초안 (Draft) |
| 최종 수정 | 2026-07-22 |

---

## 1. 정의

**목적:** 특정 장소에 대한 사실 정보를 조회하여 사용자에게 제공한다.

**판별 기준:**
- 장소명이 명시적으로 포함되어 있거나 맥락에서 추론 가능함
- 운영시간, 요금, 시설 등 사실 정보를 질문함
- 장소 추천을 요청하지 않음

**INFO가 아닌 경우:**
- "경복궁 근처 카페 추천" → `RECOMMEND` (경복궁은 search_center)
- "경복궁 같은 곳 추천" → `RECOMMEND` (유사 장소 추천)
- "다른 곳 보여줘" → `MODIFY` (이전 추천 변경)

---

## 2. 처리 흐름

```
사용자 입력
    ↓
LLM Intent 분류 → INFO
    ↓
LLM Structured Output → InfoQuery 추출
    ↓
장소 식별 (place_name → contentId 확보)
    ↓
질문 유형에 따른 API 호출
    ↓
응답 가공 (HTML 태그 정리, 비정형 텍스트 처리)
    ↓
사용자에게 정보 제공
```

---

## 3. InfoQuery 스키마

```typescript
interface InfoQuery {
  // 대상 장소
  place_name: string | null;
  place_context: "explicit" | "from_recommendation" | "from_conversation";

  // 질문 내용
  question_type: QuestionType;
  specific_question: string | null;
}
```

---

## 4. InfoQuery 필드 정의

| 필드 | 타입 | 설명 | 예시 |
|------|------|------|------|
| `place_name` | string \| null | 질문 대상 장소명 | "경복궁", "서울역사박물관" |
| `place_context` | enum | 장소명이 어디서 왔는지 | `explicit`, `from_recommendation`, `from_conversation` |
| `question_type` | QuestionType | 질문 유형 | `operating_hours`, `fee`, `parking` |
| `specific_question` | string \| null | 사용자 원문 질문 (응답 생성 참고용) | "오늘 몇 시까지 해?", "주차 가능?" |

---

## 5. place_context 정의

| 값 | 의미 | 상황 | 처리 |
|----|------|------|------|
| `explicit` | 사용자가 장소명을 직접 언급 | "경복궁 오늘 열어?" | place_name으로 검색 |
| `from_recommendation` | 직전 추천 결과에서 추론 | "첫 번째 거기 몇 시까지 해?" | 추천 이력에서 장소 식별 |
| `from_conversation` | 이전 대화 맥락에서 추론 | (대화 중 언급된 장소) "거기 주차 돼?" | 대화 맥락에서 장소 식별 |

---

## 6. question_type 정의

### enum 목록

```typescript
type QuestionType =
  | "operating_hours"   // 운영시간/휴무
  | "fee"              // 입장료/이용료
  | "parking"          // 주차 가능 여부/요금
  | "facility"         // 편의시설
  | "event"            // 현재 전시/행사
  | "location_info"    // 위치/찾아가는 법
  | "general_info";    // 기타 일반 정보
```

### 상세 정의

| question_type | 정의 | 예시 입력 | 필요 API |
|---------------|------|-----------|----------|
| `operating_hours` | 운영시간, 휴무일, 현재 영업 여부 | "오늘 열어?", "몇 시까지?", "월요일 쉬어?" | detailIntro2 (유형별 필드) |
| `fee` | 입장료, 이용료, 무료 여부 | "입장료 얼마?", "무료야?", "어른 요금?" | detailIntro2 (유형별 필드) |
| `parking` | 주차 가능 여부, 주차 요금 | "주차 되나요?", "주차비 얼마?" | detailIntro2 (유형별 필드) |
| `facility` | 편의시설, 접근성 | "화장실 있어?", "유모차 가능?", "휠체어?" | detailIntro2 (유형별 필드) |
| `event` | 현재 진행 중인 전시/행사/프로그램 | "지금 전시 뭐 해?", "행사 있어?" | searchFestival2 + detailCommon2 |
| `location_info` | 위치, 주소, 찾아가는 방법 | "어디에 있어?", "주소가 뭐야?", "어떻게 가?" | detailCommon2 (addr1, mapx, mapy) |
| `general_info` | 장소 개요, 특징, 일반 설명 | "어떤 곳이야?", "뭐 하는 곳이야?" | detailCommon2 (overview) |

---

## 7. 장소 식별 처리

### 식별 순서

```
① place_context = explicit (장소명 직접 언급)
    → place_name으로 searchKeyword2 호출
    → contentId 확보

② place_context = from_recommendation (추천 결과 참조)
    → 추천 이력에서 장소 매칭
    → "첫 번째", "두 번째", "그 카페" 등 지시어 해석
    → 이미 보유한 contentId 사용

③ place_context = from_conversation (대화 맥락 참조)
    → 최근 대화에서 언급된 장소 추론
    → contentId 확보

④ place_name = null + 맥락 추론 실패
    → "어떤 장소를 확인할까요?" 되물음
```

### 장소 검색 결과 처리

```
searchKeyword2 결과:
  - 1개 → 자동 선택
  - 여러 개 → 사용자에게 후보 목록 제공 ("혹시 이 중에 어떤 곳인가요?")
  - 0개 → "장소를 찾지 못했어요. 정확한 이름을 알려주세요" 안내
```

### 추천 이력에서의 지시어 해석

"첫 번째", "두 번째" 등 순서 지시어는 `get_session_context` 반환값의
`shown_place_ids`(현재 노출된 장소 ID 목록, 순서 보장)를 기준으로 해석한다.

| 지시어 | 해석 |
|--------|------|
| "첫 번째" / "1번" | `shown_place_ids[0]` |
| "두 번째" / "2번" | `shown_place_ids[1]` |
| "그 카페" / "아까 그 곳" | 직전 대화에서 언급된 장소 |
| "마지막 거" | `shown_place_ids`의 마지막 항목 |

---

## 8. API 호출 전략

### question_type별 필요 API

| question_type | 1차 API | 2차 API (필요 시) |
|---------------|---------|-------------------|
| `operating_hours` | detailIntro2 | — |
| `fee` | detailIntro2 | — |
| `parking` | detailIntro2 | — |
| `facility` | detailIntro2 | — |
| `event` | searchFestival2 | detailCommon2 |
| `location_info` | detailCommon2 | — |
| `general_info` | detailCommon2 | — |

### detailIntro2 유형별 필드 매핑

운영시간, 휴무일, 요금, 주차 등은 contentTypeId에 따라 필드명이 다르다.

| 개념 | 관광지(12) | 문화시설(14) | 축제(15) | 쇼핑(38) | 음식점(39) |
|------|-----------|-------------|---------|---------|-----------|
| 운영시간 | `usetime` | `usetimeculture` | `playtime` | `opentime` | `opentimefood` |
| 휴무일 | `restdate` | `restdateculture` | — | `restdateshopping` | `restdatefood` |
| 요금 | — | `usefee` | `usetimefestival` | — | — |
| 문의처 | `infocenter` | `infocenterculture` | `sponsor1tel` | `infocentershopping` | `infocenterfood` |
| 주차 | `parking` | `parkingculture` | — | `parkingshopping` | `parkingfood` |

**구현 시:** 유형→필드명 매핑 테이블을 코드에서 관리한다.

### 호출 시 필수 파라미터

```
detailIntro2:
  - contentId (장소 식별 단계에서 확보)
  - contentTypeId (장소의 유형 코드)

detailCommon2:
  - contentId

searchFestival2:
  - eventStartDate (오늘 날짜)
  - areaCode (선택)
```

---

## 9. 응답 가공 규칙

### HTML 태그 처리

TourAPI 응답에는 HTML 태그가 혼입된다.

```
원본: "09:00~18:00<br>매주 월요일 휴관<br />설날·추석 당일 휴관"
가공: "09:00~18:00 / 매주 월요일 휴관 / 설날·추석 당일 휴관"
```

처리 규칙:
- `<br>`, `<br />`, `<br/>` → 줄바꿈 또는 구분자
- `<a href="...">텍스트</a>` → URL 추출
- 기타 HTML 태그 → 제거

### 비정형 텍스트 처리

운영시간, 요금 등은 자유 서술 형태이므로 자동 파싱하지 않는다.

```
원본: "어른 3,000원 / 청소년 1,500원 / 어린이 무료 (6세 이하)"
→ 그대로 사용자에게 표시 (가공하지 않음)
```

### 데이터 없음 처리

```
필드 값이 빈 문자열 또는 누락:
  → "해당 정보를 확인할 수 없어요. 직접 문의하시는 게 좋을 것 같아요."
  → 문의처(tel, infocenter) 정보가 있으면 함께 제공
```

---

## 10. 응답 구조

### 정상 응답

```json
{
  "intent": "INFO",
  "place": {
    "name": "경복궁",
    "content_id": "126508",
    "content_type_id": "12"
  },
  "answer": {
    "question_type": "operating_hours",
    "main_info": "09:00~18:00 (6~8월 09:00~18:30)",
    "sub_info": "매주 화요일 휴관",
    "raw_value": "09:00~18:00<br>6~8월 09:00~18:30",
    "data_available": true
  },
  "additional": {
    "tel": "02-3700-3900",
    "homepage": "http://www.royalpalace.go.kr"
  }
}
```

### 데이터 없음 응답

```json
{
  "intent": "INFO",
  "place": {
    "name": "경복궁",
    "content_id": "126508",
    "content_type_id": "12"
  },
  "answer": {
    "question_type": "parking",
    "main_info": null,
    "sub_info": null,
    "raw_value": "",
    "data_available": false
  },
  "fallback_message": "주차 정보를 확인할 수 없어요. 직접 문의해보시는 게 좋을 것 같아요.",
  "additional": {
    "tel": "02-3700-3900"
  }
}
```

---

## 11. 장소 식별 실패 처리

| 상황 | 처리 |
|------|------|
| place_name이 null + 추천 이력 없음 + 대화 맥락 없음 | "어떤 장소를 확인할까요?" 되물음 |
| place_name이 null + 추천 이력 있음 | "추천해드린 장소 중 어떤 곳을 확인할까요?" + 목록 표시 |
| searchKeyword2 결과 0개 | "장소를 찾지 못했어요. 정확한 이름을 알려주세요" |
| searchKeyword2 결과 여러 개 | "혹시 이 중에 어떤 곳인가요?" + 후보 목록 |
| contentId 확보했으나 detailIntro2 빈 응답 | "해당 정보를 확인할 수 없어요" + 문의처 제공 |

---

## 12. INFO → RECOMMEND 연계

INFO 결과에 따라 자연스럽게 RECOMMEND로 이어질 수 있다.

| INFO 결과 | 후속 안내 |
|-----------|-----------|
| 휴무일 확인 → 오늘 휴무 | "오늘은 쉬는 날이에요. 근처 다른 장소를 추천해드릴까요?" |
| 운영시간 확인 → 이미 종료 | "오늘 영업이 끝났어요. 지금 열려있는 곳을 찾아볼까요?" |
| 운영시간 확인 → 곧 종료 (30분 미만) | "곧 영업이 종료돼요. (정보 제공) 다른 곳도 볼까요?" |

이 경우 사용자가 "응" / "추천해줘"로 응답하면 → `RECOMMEND`로 전환한다.

전환 시 전달하는 조건:
- `search_center`: INFO 대상 장소의 좌표
- `environment`: 기존 대화 맥락 유지
- `place_types`: 기존 맥락 또는 빈 배열

---

## 13. LLM 추출 예시

| 입력 | place_name | place_context | question_type | specific_question |
|------|-----------|---------------|---------------|-------------------|
| "경복궁 오늘 열어?" | "경복궁" | explicit | operating_hours | "오늘 열어?" |
| "입장료 얼마야?" (추천 직후) | null → 추천 1번 | from_recommendation | fee | "입장료 얼마야?" |
| "거기 주차 가능해?" (대화 중) | null → 맥락 추론 | from_conversation | parking | "주차 가능해?" |
| "서울역사박물관 전시 뭐 해?" | "서울역사박물관" | explicit | event | "전시 뭐 해?" |
| "어떤 곳이야?" (추천 직후) | null → 추천 1번 | from_recommendation | general_info | "어떤 곳이야?" |
| "첫 번째 거기 몇 시에 닫아?" | null → 추천 1번 | from_recommendation | operating_hours | "몇 시에 닫아?" |
| "두 번째 주차 돼?" | null → 추천 2번 | from_recommendation | parking | "주차 돼?" |
| "경복궁" (단독 키워드) | "경복궁" | explicit | general_info | null |

### 전체 JSON 예시

```json
{
  "intent": "INFO",
  "info_query": {
    "place_name": "경복궁",
    "place_context": "explicit",
    "question_type": "operating_hours",
    "specific_question": "오늘 몇 시까지 해?"
  }
}
```

```json
{
  "intent": "INFO",
  "info_query": {
    "place_name": null,
    "place_context": "from_recommendation",
    "question_type": "fee",
    "specific_question": "입장료 얼마야?"
  }
}
```

---

## 14. 경계 사례

| 입력 | 판정 | 이유 |
|------|------|------|
| "경복궁" (단독) | INFO | 정보 조회 의도 (general_info) |
| "경복궁 오늘 열어?" | INFO | 운영시간 질문 |
| "경복궁 근처 카페" | RECOMMEND | 경복궁은 search_center |
| "경복궁 같은 곳" | RECOMMEND | 유사 장소 추천 |
| "거기 몇 시까지?" (추천 직후) | INFO | from_recommendation |
| "경복궁 가려는데 비 오면 어쩌지?" | RECOMMEND | 대안 추천 의도 |
| "경복궁이랑 창덕궁 중 어디가 좋아?" | COMPARE | 비교 요청 |
| "경복궁 오늘 열어? 안 열면 다른 곳" | INFO (우선) | 복합 입력 → 첫 번째 의도 처리 후 결과에 따라 RECOMMEND 유도 |

---

## 15. MVP 제한사항

다음 항목은 MVP에서 처리하지 않는다:

- 공휴일 특별 운영시간
- 임시 휴무
- 휴게시간 (런치 브레이크 등)
- 하루 여러 운영 구간
- 자정을 넘기는 운영시간
- 실시간 혼잡도
- 예약 가능 여부
- 리뷰/평점 정보

운영시간/휴무 데이터는 TourAPI 원본의 자유 서술 텍스트를 그대로 제공한다. 요일별 자동 파싱은 MVP에서 수행하지 않는다.

---

## 16. 관련 문서

- [INT-01: RECOMMEND](./int-01-recommend.md) — INFO → RECOMMEND 연계 시 참조
- [INT-03: MODIFY](./int-03-modify.md) — 조건 변경 및 재추천
