**문서 버전:** v2.0
**작성일:** 2026-08-06
**관련 인텐트:** INT-01 RECOMMEND (파생), 신규 INT-07 SCHEDULE

**v2.0 변경 이력 (A의 1차 구현과 병합, v1.3 대비)**
- A(mintee)가 이 문서와 같은 경로로 독립적으로 작성한 1차 구현 설계(v0.1,
  PR #113/#114, 커밋 `da9f4cc`)가 이미 develop에 병합돼 있던 것을 발견 —
  두 문서를 하나로 합침
- "0. 구현 현황" 절 신설 — 이미 배포된 범위(Intent 분류 + 안전한 안내
  메시지)를 명시
- 3절 판별 경계 표를 A가 만든 구체적 예시 표로 교체(더 명확함)
- 8절 영향 파일 표 정정 — `Intent.SCHEDULE`은 이미 존재(추가 아님),
  `response_composer.py`는 기존 스텁 분기를 교체하는 작업으로 정정,
  A만 알던 `orchestrator.py`(조기 반환 로직)를 신규 항목으로 추가
- 9절에 "A에게 D 협의 결과 공유 필요" 항목 추가 — A의 원문서는 아직
  top_k/혼잡도 재계산을 "D 협의 후 결정"으로 미해결로 남겨둔 상태였음

**v1.1 변경 이력 (v1.0 대비)**
- 일정 편성 LLM 호출 주체를 B(Agent State)에서 신규 독립 모듈로 변경 — B는 코드 변경 없음
- 5절 D 변경안을 실제 코드 구조에 맞게 수정 (`recommendation_transform.py`에 없는 함수 참조 제거)
- `AnswerConditions` → `UserConditions`로 정정 (존재하지 않는 타입명이었음)
- top_k 5→10 확장이 D-040(혼잡도 2차 Scoring) 설계와 충돌하는 지점을 명시, D 협의 선행 항목으로 분리
- 7절 응답 형식에서 신규 `response_type` 필드 대신 기존 `llm_output.intent`를 판별 기준으로 재사용
- 8절 영향 파일 목록을 Protocol/Fake 구현체까지 포함해 재작성
- 9절 미결 사항 정리 (해소된 항목 제거, 신규 항목 추가)

**v1.2 변경 이력 (착수 준비 단계, v1.1 대비)**
- `SchedulePlanningRequest.candidates` 타입을 `RecommendationItem`으로 확정
- `RecommendationItem`/`RankedCandidate` 둘 다 위경도가 없어 `pairwise_distances_km`를
  D 응답만으로 계산할 수 없다는 것을 확인 — A가 C의 `AgentContextResponse.places`를
  place_id로 매칭해 계산하는 방식으로 확정 (4절, 6.1절)
- `docs/design/package_work_breakdown.md`에 일정 편성 모듈 담당 정보 반영 완료

**v1.3 변경 이력 (D 협의 결과 반영, v1.2 대비)**
- top_k 5→10 확장: D 확인 완료(`limit` 파라미터, 기본값 5 유지)
- D-040 혼잡도 2차 Scoring: SCHEDULE에서는 10개 전부 재계산으로 확정
  (API 비용보다 `concentration_intent` 품질 우선)
- (신규) 1차 점수·근거 문장이 단일 `visit_at` 기준이라 뒷 순서 스탑에는
  부정확할 수 있다는 문제를 D가 발견 — `ScheduleResult.basis_note` 고정
  안내 문구로 대응하기로 결정 (6.2.1절 신설)

---

## 0. 구현 현황

아래는 A가 이미 develop에 배포한 1차 구현이다(PR #113/#114, 커밋
`da9f4cc`). 이 문서의 나머지 절(1~10)은 이 위에 이어 붙일 후속 구현
설계다 — 아래 항목을 다시 만들 필요는 없다.

- `backend/app/schemas.py`: `Intent` enum에 `SCHEDULE` 이미 존재
- `backend/app/services/interpret/orchestrator.py`: `intent is
  Intent.SCHEDULE`이면 조건 추출 없이 즉시
  `LLMOutput(intent=Intent.SCHEDULE, status=OutputStatus.COMPLETE)`로
  조기 반환 — 후속 구현에서 이 조기 반환을 제거·확장해야 조건 추출·D
  호출·일정 편성 모듈로 이어진다
- `backend/app/services/runtime/response_composer.py`: `intent is
  Intent.SCHEDULE`이면 고정 문구 `"일정 추천 기능은 아직 준비
  중이에요."`만 반환 — 후속 구현(6.2절)의 `compose_schedule_message()`가
  이 분기를 **교체**한다(추가 아님)
- 목적: 일정 요청이 RECOMMEND로 오분류돼 단일 장소 추천으로 잘못
  처리되는 걸 막는 안전장치. B/C/D 쪽은 전혀 건드리지 않음

---

## 1. 배경 및 목적

현재 RECOMMEND 인텐트는 조건에 맞는 장소를 **상위 5개** 카드로 반환한다.
사용자가 "오늘 하루 일정 짜줘", "반나절 코스 추천해줘" 같이 **시간 순서가
있는 복수 장소 방문 계획**을 요청할 때는 단순 카드 목록보다 방문 순서·이동
동선·시간 배분이 담긴 일정 형태의 응답이 적합하다.

이를 처리하는 **INT-07 SCHEDULE** 인텐트와 일정 계획 전용 흐름을 신설한다.

부가적으로, 지금까지 LLM이 실제 판단에 쓰이는 지점이 A(인텐트 분류·조건
추출)에 집중돼 있고 추천 채점(D)은 고정 가중치 공식이라 "AI를 잘 안 쓴
프로젝트로 보인다"는 피드백이 있었다. 일정 편성(후보 중 선택·순서·이유
판단)은 LLM이 실제로 판단하는 지점을 늘릴 수 있는 기능이라, 이번 기능은
이 문제에 대한 답이기도 하다.

---

## 2. 기존 RECOMMEND와의 차이

| 항목 | INT-01 RECOMMEND | INT-07 SCHEDULE |
|------|-----------------|-----------------|
| 트리거 | "카페 추천해줘" | "오늘 오후 일정 짜줘", "반나절 코스 만들어줘" |
| D 반환 수 | 상위 5개 | **상위 10개 전부** (D 협의 완료, 5절 참고) |
| 일정 편성 주체 | 없음 | **신규 독립 모듈에서 LLM 호출로 편성** — B는 결과를 기존 방식으로 기록만 함 |
| 응답 형식 | 장소 카드 5개 | 시간순 일정 블록 (1일/반나절 등) |
| shown_ids | 노출된 5개 기록 | **일정에 포함된 장소만** 기록 (B의 기존 `record_recommendation()` 그대로 재사용) |

---

## 3. 인텐트 분류 기준 (INT-07 판별)

A가 1차 구현(0절)에서 이미 확정·배포한 판별 기준(아래 표)을 그대로 따른다.

| 발화 | Intent |
| --- | --- |
| "오늘 오후 종로 반나절 코스 짜줘" | `SCHEDULE` |
| "경복궁, 인사동 가고 싶은데 어디부터 갈까?" | `SCHEDULE` |
| "오늘 갈 만한 곳 추천해줘" | `RECOMMEND` |
| "경복궁 오늘 열어?" | `INFO` |
| "다른 곳 보여줘" | 이전 추천 이력이 있을 때 `MODIFY` |

일반적으로는 "일정/코스/루트 짜줘", "하루/반나절/N시간" + 복수 활동 암시,
"어디부터 갈지 순서" 같은 표현이 SCHEDULE로 분류된다. 단순 "추천해줘"
표현에 일정 맥락이 없으면 RECOMMEND로 유지한다.

### 3.1 SCHEDULE 다음 턴의 조건 변경 발화 (SCHEDULE-06)

위 표의 "다른 곳 보여줘" 판별 기준(이전 추천 이력이 있을 때 `MODIFY`)은 그대로
유지한다 — `classify_intent()`는 여전히 이런 발화를 MODIFY로 분류한다.

다만 SCHEDULE 응답을 받은 바로 다음 턴에 이런 MODIFY 발화가 오면, 사용자는
방금 받은 "일정"을 바꿔달라는 것이므로 일반 RECOMMEND 재추천이 아니라 일정
재편성으로 처리해야 한다. 이건 A의 프롬프트/분류 로직을 바꾸는 대신, Agent
Runtime(`agent_runtime.py`)이 B가 이미 세션마다 저장해온 `last_intent` 값을
읽어 라우팅 단계에서만 처리한다:

- 직전 턴이 SCHEDULE로 완료됐고(`last_intent == "SCHEDULE"`, 되묻기 없이
  끝남 — `pending_clarification is None`) 이번 턴이 MODIFY로 분류되면,
  조건 병합은 원래 MODIFY 페이로드(`llm_output.modify`)로 정상 처리한 뒤
  `llm_output.intent`만 SCHEDULE로 바꿔치기해 기존 SCHEDULE 분기(D 10개 호출
  · 편성 모듈 호출)로 재진입시킨다.
- REJECT_ALL(그냥 "다른 데로")이면 직전 일정의 장소들이 `rejected`로
  기록되어 새 일정에서 자동 제외된다(기존 MODIFY 로직 그대로 재사용, B
  스키마 변경 불필요).
- classify_intent 프롬프트, `extract_modify_conditions()`는 변경하지 않는다.

---

## 4. 처리 흐름

```
사용자 입력 (SCHEDULE 인텐트)
  → A: Intent 분류 → SCHEDULE
  → A→B: 조건 병합 (기존과 동일)
  → A→C: AgentContextRequest (기존과 동일)
  → A→D: 추천 실행 — limit=10으로 요청 (D 협의 완료, 5절 참고)
  → D→A: RecommendationItem 10개 반환
  → A: C의 AgentContextResponse.places(위경도)를 place_id로 매칭해
       pairwise_distances_km 계산 (haversine_km 재사용)
  → A→일정편성모듈: candidates(10개), conditions, pairwise_distances_km
       ↳ 모듈 내부에서 LLM 호출 → 일정 JSON 생성
       ↳ 상태 저장소(StateStore) 비접근 — 순수 입력→출력 함수, D와 같은 위치
  → 일정편성모듈→A: ScheduleResult (방문 순서·시각·이동시간·장소·이유)
  → A→B: record_recommendation (기존 함수 그대로 재사용 — 일정에 포함된
       장소만 place_id+rank로 넘김. B 쪽 코드 변경 없음)
  → A: 일정 블록 형태로 응답 조립
```

concentration_intent가 AVOID/SEEK인 경우 D-040 분기(1차 10개 → C 혼잡도
후조회 → 2차 재순위)도 SCHEDULE에서는 **10개 전부** 재계산한다 (D 협의
완료). `rerank_with_concentration()`은 개수를 하드코딩하지 않아 D 쪽 구현
부담은 없다. 5개만 재계산하면 `concentration_intent`를 명시한 사용자
조건이 6~10번째 후보에서 조용히 무시되는 품질 문제가 생기므로, API 호출이
2배로 늘더라도 일관성 있게 10개 전부 적용하기로 확정했다.

---

## 5. D(추천 엔진) 변경

현재 D는 `RealRecommendationProvider.recommend()` 안에 `_RECOMMENDATION_LIMIT
= 5`가 모듈 상수로 하드코딩돼 있고, 이 값을 `run_recommendation_pipeline_
from_context()`의 `recommendation_limit` 파라미터로 그대로 전달한다. 슬라이싱
(상위 N개로 자르기) 자체는 이미 `recommendation_pipeline.py`가
`scoring.ranked[:recommendation_limit]`로 처리하고 있으므로, **`domain/
scoring.py`의 `score_candidates()`는 건드릴 필요가 없다.**

필요한 변경은 이 하드코딩된 상수를 호출자가 넘기는 값으로 바꾸는 것뿐이다.

```python
# app/services/runtime/protocols.py — RecommendationProvider Protocol
class RecommendationProvider(Protocol):
    async def recommend(
        self,
        conditions: UserConditions,
        context: RecommendationContext,
        excluded_place_ids: list[str],
        limit: int = 5,            # 신규 파라미터. 미지정 시 기존과 동일
    ) -> RecommendationResponse:
        ...
```

```python
# app/services/runtime/real_recommendation_provider.py
class RealRecommendationProvider:
    async def recommend(
        self,
        conditions: UserConditions,
        context: RecommendationContext,
        excluded_place_ids: list[str],
        limit: int = _RECOMMENDATION_LIMIT,   # 기존 하드코딩 상수를 기본값으로
    ) -> RecommendationResponse:
        search_radius_km = to_search_radius_km(conditions)
        return await run_recommendation_pipeline_from_context(
            context,
            conditions=conditions,
            visit_at=datetime.now(_KST),
            search_radius_km=search_radius_km,
            shown_place_ids=frozenset(excluded_place_ids),
            recommendation_limit=limit,   # 이미 있는 파라미터를 그대로 재사용
        )
```

**주의**: `RecommendationProvider` Protocol을 구현하는 곳이 여기 하나가
아니다 — `app/services/runtime/stubs.py`의 Fake 구현체와 `tests/
test_agent_runtime.py` 등에 흩어진 테스트 더블(최소 4곳)도 같은 시그니처로
맞춰야 기존 테스트가 깨지지 않는다.

기존 RECOMMEND 흐름은 `limit` 미지정 시 기본값 5로 동작해 영향 없음.

---

## 6. 일정 편성 모듈 — 신규, B/D와 독립

### 6.0 모듈 배치 결정

상태 저장소에 의존하지 않는 **신규 모듈**(`app/schedule/`)로 분리한다.
입력(후보+조건)을 받아 계산된 결과(편성된 일정)를 반환하는 구조로, A가
이 모듈을 호출하는 방식은 지금 A가 D를 호출하는 방식과 동일하다 — 다만
점수 공식 대신 LLM 판단을 쓴다는 차이만 있다.

### 6.1 LLM 입력 구성

```python
class SchedulePlanningRequest(BaseModel):
    candidates: list[RecommendationItem]  # D의 공개 응답 스키마(app.schemas.RecommendationItem)
                                         # 사용 확정. D 내부 도메인 타입(RankedCandidate)은
                                         # 레이어 경계를 넘어가므로 쓰지 않는다.
    conditions: UserConditions          # 기존 15개 조건 그대로 사용
                                         # (time_available, transport 등 이미 있는 필드 재사용)
    visit_datetime: datetime | None     # 방문 예정 시각
    pairwise_distances_km: dict[tuple[str, str], float]
                                         # app.geo.haversine_km()로 계산해 LLM에 근거로 제공.
                                         # RecommendationItem에는 위경도가 없어(distance_km만
                                         # 검색 중심 기준 거리) D 응답만으로는 후보 간 거리를
                                         # 못 구한다 — A가 C의 AgentContextResponse.places(위경도
                                         # 보유)를 place_id로 매칭해 계산한다. D/C 스키마 변경 불필요.
```

### 6.2 LLM 출력 스키마

```python
class ScheduleItem(BaseModel):
    order: int                  # 방문 순서 (1부터)
    place_id: str
    place_name: str
    estimated_arrival: str      # "14:30" 형식
    estimated_duration_min: int # 해당 장소 체류 예상 시간
    travel_to_next_min: int | None  # 다음 장소까지 이동 시간 (마지막은 null)
    reason: str                 # 이 장소를 이 순서에 배치한 이유 1~2문장

class ScheduleResult(BaseModel):
    items: list[ScheduleItem]   # 최종 일정 (3~5개)
    total_duration_min: int
    route_summary: str          # 동선 요약 1~2문장
    basis_note: str             # 신규(D 피드백 반영) — 근거 데이터 기준 시각 안내.
                                 # LLM이 생성하지 않고 A가 visit_at 값을 넣어 고정
                                 # 템플릿으로 채운다(6.2.1 참고)
```

#### 6.2.1 basis_note — 근거 시각 안내 (D 피드백 반영)

D가 발견한 문제: 후보 10개의 1차 점수·근거 문장(운영시간·날씨)은 단일
`visit_at`(현재 시각) 기준으로 계산된다. 일정 뒷 순서 장소는 실제 방문
시점이 몇 시간 뒤인데도 근거 문장은 "지금 기준"으로 나와 부정확할 수
있다(예: 마감 임박 안내가 실제 방문 시점과 다를 수 있음).

스탑마다 D를 다시 호출해 방문 예정 시각 기준으로 재계산하는 방식은 이번
범위에서 비용이 크므로 채택하지 않는다. 대신 `basis_note`에 고정 문구를
넣는다 — LLM에게 문구 작성을 맡기지 않고 A/일정편성모듈이 결정적으로
채운다(예: `"이 정보는 {visit_at} 기준으로 계산됐어요. 실제 방문
시간에는 운영시간·날씨 상황이 달라질 수 있어요."`). 근본적인 재계산
정확도 개선은 이번 범위 밖으로 남겨둔다.

LLM은 10개 후보 중 시간·동선 효율을 고려해 **3~5개**를 선택하고 방문
순서를 결정한다. 나머지는 자동 제외된다.

`estimated_duration_min`/`travel_to_next_min`/`reason`은 SCHEDULE-06부터
B 히스토리에 함께 저장된다(6.3절 갱신 참고. SCHEDULE-04~05 시점에는 저장되지
않았다 — 해당 시점 알려진 한계는 9절 "해소된 항목" 참고).

### 6.3 B 기록 — SCHEDULE-06부터 일정 세부 필드도 함께 저장

일정에 **포함된 장소만** B의 `record_recommendation()`을 그대로 호출해
기록한다. `ScheduleItem.order`는 `rank`로 매핑한다.

(SCHEDULE-06) `RecommendedPlace`/`RecommendedItem`에 `estimated_arrival`/
`estimated_duration_min`/`travel_to_next_min`/`reason` 선택 필드가 추가되어,
SCHEDULE 항목은 이 값들도 함께 저장한다 — SCHEDULE 재조정 시 직전 일정
내용을 참고하기 위함이다. RECOMMEND/MODIFY 흐름은 이 필드들을 생략하면
되고(항상 None), 기존 동작에 영향 없다.

LLM이 제외한 후보 5~7개는 기록되지 않아 이후 일반 RECOMMEND 요청에서
재노출 가능하다.

### 6.4 LLM Provider 연동

- provider 획득은 A가 이미 쓰고 있는 `app.providers.factory.get_llm_provider()`를
  그대로 재사용한다 — 이 모듈만을 위한 별도 획득 경로를 새로 만들지 않는다.
- `LLMProvider` Protocol에 일정 편성용 메서드(예: `generate_schedule_plan()`)를
  추가할 때는 `app/providers/protocols.py`(Protocol 정의), `app/providers/
  gemini.py`(실제 구현), `app/providers/stub.py`의 `FakeLLMProvider`(가짜 구현)
  **세 곳을 동시에** 구현한다. GENERAL 인텐트 크래시 버그(실제 provider엔
  있고 Fake엔 없어서 `PROVIDER_MODE=fake`에서 500 크래시 났던 사고)와
  같은 패턴이 재발하지 않도록 하기 위함이다.
- 테스트는 `tests/conftest.py`의 기존 autouse fixture가 `provider_mode`를
  이미 강제로 `fake`로 고정해주므로, 이 모듈을 위한 별도 테스트 격리
  장치를 새로 만들 필요가 없다.

---

## 7. 응답 형식

새 `response_type` 필드를 추가하지 않는다 — `AgentResponse`는 지금
`llm_output`/`state`/`recommendations`/`message` 4개 필드뿐이고, 프론트는
이미 `llm_output`의 intent 값으로 화면을 분기하는 구조다. SCHEDULE도 같은
방식(`llm_output.intent == "SCHEDULE"`)으로 판별하게 해서 분기 기준이
두 군데로 갈라지지 않게 한다. `AgentResponse`에는 `schedule` 필드 하나만
추가한다.

```json
{
  "llm_output": { "intent": "SCHEDULE", "...": "..." },
  "state": { "...": "..." },
  "message": "오늘 오후 3시간 코스를 짜봤어요.",
  "schedule": {
    "total_duration_min": 180,
    "route_summary": "홍대 → 연남동 → 망원한강공원 순으로 이동 거리를 최소화했어요.",
    "basis_note": "이 정보는 15:00 기준으로 계산됐어요. 실제 방문 시간에는 운영시간·날씨 상황이 달라질 수 있어요.",
    "items": [
      {
        "order": 1,
        "place_id": "...",
        "place_name": "연남동 카페 A",
        "estimated_arrival": "15:00",
        "estimated_duration_min": 60,
        "travel_to_next_min": 15,
        "reason": "도보 이동 시작점에 가깝고 실내 공간이라 날씨 영향이 없어요."
      }
    ]
  }
}
```

---

## 8. 영향받는 파일 (예상)

| 파일 | 변경 종류 |
|------|---------|
| `backend/app/schemas.py` | `Intent.SCHEDULE`은 **이미 존재**(0절, PR #114) — 추가 작업은 `AgentResponse`에 `schedule` 필드 추가뿐 |
| `backend/app/services/interpret/orchestrator.py` | (신규 항목, A만 알던 파일) `intent is Intent.SCHEDULE`일 때의 조기 반환(0절)을 제거·확장해 조건 추출로 이어지게 함 |
| `backend/app/schedule/schemas.py` (신규) | `SchedulePlanningRequest`, `ScheduleResult`, `ScheduleItem` |
| `backend/app/schedule/planner.py` (신규) | 일정 편성 로직 — LLM 호출, candidates/conditions → ScheduleResult. 상태 비접근 |
| `backend/app/services/runtime/protocols.py` | `RecommendationProvider.recommend()`에 `limit` 파라미터 추가 |
| `backend/app/services/runtime/real_recommendation_provider.py` | 하드코딩된 `_RECOMMENDATION_LIMIT` 대신 `limit` 인자를 `run_recommendation_pipeline_from_context()`에 전달 |
| `backend/app/services/runtime/stubs.py` | Fake `RecommendationProvider`도 동일 시그니처로 반영 |
| `backend/tests/test_agent_runtime.py` 등 | `RecommendationProvider` Protocol을 구현하는 테스트 더블 시그니처 갱신 |
| `backend/app/providers/protocols.py`, `gemini.py`, `stub.py` | `LLMProvider`에 일정 편성용 메서드 추가 (Real+Fake 동시 구현) |
| `backend/app/services/runtime/agent_runtime.py` | SCHEDULE 분기 추가; D 호출 후 일정 편성 모듈 호출; B의 기존 `record_recommendation` 재사용 |
| `backend/app/services/runtime/response_composer.py` | `intent is Intent.SCHEDULE`일 때 고정 문구를 반환하던 기존 분기(0절)를 `compose_schedule_message()` 호출로 **교체**(추가 아님) — `tests/test_response_composer.py`의 관련 테스트도 갱신 필요 |
| `docs/design/package_work_breakdown.md` | 일정 편성 기능 담당자 정보 한 줄 추가 — 새 패키지 letter 아님 |
| `docs/design/int-07-schedule.md` | 본 문서 — A의 1차 구현 설계(v0.1)와 병합됨(v2.0) |

`backend/app/state/service.py`, `backend/app/domain/scoring.py`,
`backend/app/services/runtime/recommendation_transform.py`는 **변경 없음**
(v1.0에서 잘못 언급됐던 파일들).

---

## 9. 미결 사항

* **A에게 D 협의 결과 공유 필요.** A의 원 문서(0절, v0.1)에는 top_k
  5→10 확장과 혼잡도 2차 Scoring 처리를 아직 "D 협의 후 결정"으로
  남겨뒀는데, 이미 D와 합의 완료됨(top_k 10, 혼잡도 10개 전부 재계산,
  4·5절 참고) — A가 조건 추출·후속 구현에 들어가기 전에 알려줘야 함.
* `estimated_arrival`은 `visit_datetime`이 없을 때 현재 시각 기준으로 계산할지,
  LLM이 상대적 표현("1번째 방문", "약 1시간 후")만 반환하도록 할지 결정 필요.
* `travel_to_next_min`은 현재 TBD인 `estimate_travel_time` Tool과 연동
  가능. Tool 미구현 상태이므로 1차에서는 LLM 추정값을 쓰되, 근거 없는
  추측이 되지 않도록 `pairwise_distances_km`(haversine 기반)을 프롬프트에
  반드시 함께 제공한다. Tool 구현 완료 시 실측값으로 교체.
* FE 타임라인 UI 컴포넌트는 별도 이슈로 관리.
* SCHEDULE 다음 턴에 D 후보가 3개 미만이면 편성 동작이 정의돼 있지 않다
  (`ScheduleLLMPlan.items`에 `min_length=3` 제약을 걸면 하드 실패만
  늘어나므로 단순 제약 추가보다 신중한 설계 필요). SCHEDULE-06에는
  포함되지 않음, 후속 과제로 남김.

**해소된 항목(SCHEDULE-06)**
* `ScheduleItem`의 세부 근거(도착 시각·체류 시간·이유 문장)가 B 히스토리에
  저장되지 않던 문제: `RecommendedItem`에 선택 필드로 추가해 해소(6.3절
  참고). RECOMMEND/MODIFY 흐름은 영향 없음.
* SCHEDULE 다음 턴의 조건 변경 발화("다른 데로 바꿔줘")가 MODIFY로
  오분류되어 잘못 응답하던 문제: 라우팅 단계(agent_runtime.py)에서 B의
  `last_intent`를 읽어 해소(3.1절 참고). classify_intent는 변경 없음.

**해소된 항목(v2.0 → A의 1차 구현과 병합하며 확인)**
* INT-07 트리거 표현·분류 기준 문서화: 별도로 새로 쓸 필요 없음 — A가
  이미 판별 표를 만들어 구현·배포까지 끝냄(0절, 3절 참고).
* `Intent.SCHEDULE` 추가: 이미 완료(0절, PR #114) — 추가 작업 불필요.

**해소된 항목(v1.3 → D 협의 완료)**
* top_k 5→10 확장: D 확인 완료, `recommend()`에 `limit` 파라미터 추가(기본값
  5 유지)로 진행. 5절 참고.
* D-040 혼잡도 2차 Scoring: SCHEDULE에서는 **10개 전부** 재계산하는 것으로
  확정(`rerank_with_concentration()`은 개수 하드코딩 없어 D 쪽 구현 부담
  없음). API 호출 2배 비용을 감수하고 `concentration_intent` 품질을
  우선한 결정. 4절 참고.
* (D 피드백으로 신규 발견) 1차 점수·근거 문장이 단일 `visit_at` 기준으로
  계산돼 뒷 순서 스탑에는 부정확할 수 있다는 문제 → `ScheduleResult.basis_note`
  고정 안내 문구로 처리, 스탑별 재계산은 이번 범위 밖. 6.2.1절 참고.

**해소된 항목(v1.1 → 준비 단계에서 결정)**
* `SchedulePlanningRequest.candidates`는 `RecommendationItem`(D의 공개
  응답 스키마)으로 확정. 6.1절 참고.
* `pairwise_distances_km` 계산 주체: `RecommendationItem`에는 위경도가 없어
  D 응답만으로는 후보 간 거리를 못 구한다는 게 확인됨 → A가 C의
  `AgentContextResponse.places`(위경도 보유)를 place_id로 매칭해 계산하는
  것으로 확정. D/C 스키마 변경 불필요.
* 일정 편성 모듈의 담당자 표기는 `package_work_breakdown.md`에 반영 완료
  (새 패키지 letter 없이 "참고" 섹션으로 기록).

---

## 10. 기대 효과

"오늘 하루 어디 갈지 모르겠어" 유형의 고의도 사용자가 단일 메시지로 완성된
일정을 받을 수 있어, 여러 번 RECOMMEND → MODIFY를 반복하는 불편을 줄인다.
기존 Scoring·하드 필터 파이프라인을 재사용하므로 추천 품질이 유지되며,
LLM 일정 편성 로직은 B가 아니라 신규 독립 모듈에 격리되어 있어 B의 상태
관리 원칙과 RECOMMEND 흐름 어느 쪽에도 영향을 주지 않는다.
