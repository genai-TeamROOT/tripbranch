# LangGraph 도입 검토 및 사용법

## 문서 정보

| 항목 | 값 |
|------|-----|
| 버전 | v1.2 |
| 상태 | **이관 완료·검증 통과(2026-08-24)** — 0단계 스파이크(§9.6), 1단계 GENERAL(§9.7), 2단계 조기 반환 전체, 3단계 파이프라인(§9.8). 4단계는 전제가 틀려 하지 않는다(§9.9). §10.3 병합 판정 기준 6개 전부 통과(§9.10 회귀 비교·§9.11 되묻기 재진입·§9.12 지연 측정). §1~§5는 "처음부터 설계했다면 맞는가"에 대한 결론, §6~§11은 이관 계획·사용법·규모·브랜치 전략 |
| 작성일 | 2026-08-22 (최종 수정 2026-08-24) |
| 관련 결정 | D-072 (`docs/decision-log.md`) |
| 작업 브랜치 | `feature/langgraph-spike` (`feature/llm-interpret`에서 분기, 로컬 전용 — §10) |
| 관련 코드 | `backend/app/services/runtime/agent_runtime.py`(`run_agent_flow()`), `backend/app/state/store.py`(`StateStore`), `backend/app/state/schema.py`(`AgentState`), `backend/app/providers/gemini.py`(`classify_intent()`) |
| 관련 문서 | `docs/roadmap.md` 12·16번, `docs/design/agent-runtime-contract.md`, `docs/design/clarification-options.md`, `backend/docs/package-b/agent-state-contract-v1.md` |
| 강의 교재 근거 | 제61강(LangGraph 라우팅 개요: 61-2 순서도·핵심 개념, 61-5 StateGraph 구성, 61-6 RAG·단순응답 라우팅), 제91강(멀티턴·조건부 분기: 91-2 분기 라우팅과 Checkpointer, 91-5 분류 노드·조건부 엣지, 91-6 RAG 연결과 Checkpointer 멀티턴) |

이 문서는 **"바꾸기 번거로우니 안 쓴다"를 근거로 삼지 않는다.** 그 대신 "지금
저장소가 없다고 가정하고 강의 교재 기준으로 처음부터 설계했다면 LangGraph가
맞는 선택이었는가"를 코드 실측으로 판단하고, 맞다면 어떻게 옮겨갈지까지 적는다.

---

## 1. 결론

**맞다. 오히려 강의 예시보다 우리 쪽이 LangGraph가 더 필요한 모양이다.**

강의가 그래프를 쓰라고 판단하는 기준은 명확하다(61-2).

> "갈래가 둘뿐이면 if/else로도 됩니다. 하지만 길은 금방 늘어납니다. (…) 나중엔
> 멀티턴(여러 번 주고받기)까지 들어옵니다. 그러면 if/else 중첩 속에 흐름이 코드에
> 파묻혀 한눈에 안 보입니다."

이 기준으로 우리 코드를 실측했다.

---

## 2. 실측 — 우리가 이미 그 증상을 겪고 있다

```
app/services/runtime/agent_runtime.py
  - run_agent_flow() 단 하나의 함수가 1221~2440줄 (1200줄+)
  - 그 안에 Intent.RECOMMEND/INFO/COMPARE/SCHEDULE/GENERAL/MODIFY/OUT_OF_SCOPE
    분기가 40군데 흩어져 있음
```

강의의 토이 예제는 갈래가 2~3개(RAG/단순응답, 고객/직원/에스컬레이션)인데, 우리는
**7개 인텐트**를 한 함수 안에서 if/elif로 갈라놓았다. 강의가 "이 지점부터 그래프가
필요하다"고 말하는 바로 그 임계점을 이미 넘어선 상태다.

---

## 3. 강의의 핵심 개념이 우리 프로젝트에 이미 존재 — 단, 프레임워크 없이 직접 구현

| 강의 개념 (61강·91강) | 우리 프로젝트의 대응물 | 비고 |
|---|---|---|
| **State**(서류철, TypedDict) | `AgentState`(Pydantic, `app/state/schema.py`) | 구조는 같고, 우리는 검증까지 얹음 |
| **Checkpointer + thread_id** | ~~`StateStore` Protocol + `session_id`~~ **대응물 없음** | v1.0은 정확히 대응한다고 봤으나 **틀렸다(§7.4·§9.9)** — 우리 그래프는 한 턴에 끝나서 보관함이 필요 없고, `StateStore`는 도메인 데이터 저장소라 역할이 다르다 |
| **분류 노드 → 조건부 엣지** | `classify_intent()` → `run_agent_flow()` 내부 if/elif | 저장소에 명시적 그래프가 없을 뿐, 흐름 자체는 "분류 후 결정적 분기"로 이미 설계됨 |
| **에스컬레이션/fallback**(확신도 낮으면 사람에게) | `needs_clarification` + `location_required`/`no_data_closed` 되묻기 버튼 | 조건부 엣지를 코드로 흉내 낸 것과 같은 역할 |
| **90강 vs 91강 — 결정권이 누구에게 있나** | 우리는 이미 "명시적 그래프" 편에 서 있음 — LLM이 도구를 즉석 선택하는 `create_agent`형이 아니라, 코드가 라우팅을 못 박음(`agent_runtime.py`의 if/elif 자체가 그 역할) | 이 판단 자체는 이미 옳게 했다는 뜻 — 다만 그 판단을 표현하는 도구가 없었을 뿐 |

핵심은 이것이다. **우리는 이미 LangGraph의 설계 철학대로 만들었다.** 다만 "그 철학을
표현하는 프레임워크"를 안 쓰고 순수 Python if/elif와 직접 만든 State Store로
재발명한 것이다.

---

## 4. 강의가 "안 써도 된다"고 말하는 경우와 비교해도 결론은 같다

강의는 55강 사내규정봇을 "목적이 하나뿐이라 갈림길이 없는 외길"이라 그래프가 필요
없다고 명시한다. 우리는 그 반대 극단이다 — 인텐트 7개, 각각 되묻기·부분 재조회·조건
병합까지 얽혀 있어 91강의 "따로국밥이던 부품(RAG 여러 개·분류기·멀티턴)을 하나로
잇는" 상황과 구조적으로 동일하다.

---

## 5. 처음부터 설계했다면 구체적으로 이렇게 됐을 것

```
START → [classify_intent] 노드
           ↓ (조건부 엣지, route_by_intent)
    ┌──────┼──────┬──────┬──────┬──────┬──────┐
[recommend][info][compare][schedule][modify][general][out_of_scope]
    └──────┴──────┴──────┴──────┴──────┴──────┘
                   ↓
            [merge_conditions] (B 역할)
                   ↓
              [compose_response]
                   ↓
                  END
```

- **State**: 지금의 `AgentState`를 거의 그대로 `TypedDict`/Pydantic으로 옮기면 됨
  (이미 구조가 맞음)
- ~~**checkpointer**: `STATE_STORE_BACKEND=supabase`가 그대로 커스텀
  `BaseCheckpointSaver` 구현이 됨 — 이미 Protocol로 분리해둔 설계가 그대로 재사용 가능~~
  → **이 대응은 틀렸다(2026-08-24 실측으로 확인). 취소선으로 남긴다 — 왜 틀렸는지는
  §9.9 참고.** 요약하면 `StateStore`는 도메인 데이터를 담는 저장소이고 checkpointer는
  그래프를 중간에서 재개하기 위한 스냅샷이라, 이름만 닮았을 뿐 하는 일이 다르다
- **되묻기 버튼**: `location_required`/`no_data_closed` 각각이 91-4의 `escalate` 노드
  패턴과 동일 — 확신도 대신 "필드 누락"이 라우팅 조건이 되는 변형

### 5.1 다만 짚어야 할 차이 — "더 쉬워진다"가 아니라 "복잡함이 옮겨간다"

정직하게 말하면, LangGraph를 처음부터 썼어도 없어지지 않는 부분이 있다.

1. **Tool 병렬 조회**(`app/agent_context/service.py`의 날씨·위치·TourAPI 동시 호출)는
   61/91강이 다루는 단순 "노드 하나 = LLM/RAG 호출 하나" 모델보다 한 단계 더 나간다.
   LangGraph 자체는 병렬 엣지(fan-out/fan-in)를 지원하지만, 이건 61/91강이 직접
   보여주는 범위 밖이라 별도 학습이 필요했을 것이다.
2. **조건 병합의 Add/Update/Remove 의미론**(`field_spec.py`)은 강의의 "칸을 채워 넣기만
   하는" 리듀서보다 복잡한 커스텀 리듀서가 필요했을 것이다 — 불가능한 건 아니지만
   튜토리얼 수준을 넘어선다.

즉 **"if/elif 중첩을 그래프로 바꾸는 것"까지는 강의 그대로 깔끔하게 들어맞고, 그
이상(병렬 Tool 오케스트레이션, 정교한 상태 병합)은 우리가 지금 하고 있는 것과 비슷한
수준의 추가 설계가 여전히 필요했을 것**이라는 게 정직한 평가다.

---

## 6. 그래서 지금 어떻게 할 것인가 — 전면 재작성은 하지 않는다

§1~§5의 결론이 "처음부터라면 맞다"인 것과 "지금 당장 다 갈아엎는 게 맞다"는 다르다.
이미 2,478줄이 동작하고 테스트 2,130건이 통과하는 상태에서 한 번에 옮기면, 얻는 것은
구조 정리 하나인데 잃는 것은 검증된 동작 전부다.

대신 **위험이 낮은 곳부터 실제로 써보고, 그 경험을 근거로 다음 범위를 정한다.** 이
순서 자체가 강의 91-3이 말하는 "부품을 노드로 포장한다"는 감각을 그대로 따른다.

> "이미 잘 동작하는 부품(분류기·RAG 체인)을, 노드 함수 안에서 호출만 하는 것입니다.
> 부품의 속은 안 건드립니다." (91-3)

### 6.1 단계별 계획

| 단계 | 범위 | 목표 | 위험 |
|---|---|---|---|
| **0** ✅ | 학습용 스파이크 | 저장소 밖 스크립트에서 3노드 그래프를 굴려 개념 확인. 커밋하지 않음 | 없음 — **완료(§9.6)** |
| **1** ✅ | **GENERAL 인텐트 1개 이관** | 실제 저장소에서 그래프 1경로를 끝까지 태워본다. 기존 if/elif와 **병행 운영** | 낮음 — **완료(§9.7)** |
| **2** | OUT_OF_SCOPE + 되묻기 경로 | 같은 조기 반환 블록의 나머지. 91-4 `escalate` 노드 패턴 | 중간 |
| **3** | 인텐트 라우팅 본체 (나머지 5개) | `run_agent_flow()`의 if/elif 40군데를 `StateGraph`로 이관 | 높음 |
| ~~**4**~~ | ~~Checkpointer 이관~~ | **하지 않기로 함** — 전제가 틀렸다(§9.9) | — |
| **(별건)** | 취향 RAG 검색 | 로드맵 1·11번. **데이터가 저장소에 아직 없어 이 계획에서 제외** | — |

### 6.1.1 1단계를 "취향 RAG"에서 "GENERAL 인텐트"로 바꾼 이유 (2026-08-23)

v1.0에서는 1단계를 취향 RAG로 잡았다. **RAG가 아직 프로젝트에 적용되지 않아 그대로
쓸 수 없다** — `package_D/place_embeddings.jsonl`이 이 저장소에 없고(로드맵 1번,
담당 팀원이 별도 작업 중), 적재 스크립트만 있는 상태다. 없는 기능 위에 그래프를
얹는 계획은 착수 자체가 불가능하다.

대신 **이미 동작하는 것 중 가장 작은 인텐트 하나**를 고른다. 스파이크(§9.6)가
가짜 환경에서 증명한 것을, 실제 저장소에서 다시 증명하는 것이 목적이다.

### 6.1.2 왜 GENERAL인가

`agent_runtime.py:1745`의 조기 반환 블록이 자연스러운 경계다. 여기서 INFO·COMPARE·
GENERAL·OUT_OF_SCOPE가 Tool/Scoring 단계로 가지 않고 끝난다.

| 후보 | 장점 | 단점 |
|---|---|---|
| **GENERAL** | Tool·Scoring 없음. **SSE 스트리밍(`message_start`+`message_delta`)이 있음** | — |
| OUT_OF_SCOPE | 가장 단순(고정 템플릿) | 스트리밍이 없어 **최대 위험(§9.4)을 검증 못 함** |
| INFO / COMPARE | — | Tool 호출이 붙어 1단계로는 큼 |

**GENERAL을 고르는 결정적 이유는 스트리밍이 있다는 것이다.** §9.4가 지목한 30군데
SSE 결합이 실제 코드에서 풀리는지는 스트리밍이 있는 경로로만 확인할 수 있다.
OUT_OF_SCOPE는 더 쉽지만, 쉬운 만큼 아무것도 증명하지 못한다.

**1단계에서 증명할 것**(스파이크가 가짜로만 보여준 것들):

1. 그래프가 **실제 `chat.py` SSE 엔드포인트**를 통해 프론트 수정 없이 동작하는가
2. 기존 `run_agent_flow()`와 **병행**할 수 있는가(GENERAL만 그래프, 나머지는 기존 경로)
3. 회귀 테스트 2,293건이 그대로 통과하는가

**규모**: GENERAL 관련 테스트 24건, OUT_OF_SCOPE 10건. 1단계 코드는 신규 ~250줄,
기존 수정 ~30줄(분기 하나 추가) 수준으로 예상한다.

3·4단계는 1·2단계를 마친 뒤 **다시 판단한다.** 이 문서는 3·4단계를 "하기로 결정"한
문서가 아니라 "했을 때 어떤 모양이 되는지 그려둔" 문서다.

### 6.2 3단계를 실제로 할 때의 이관 원칙

- **한 번에 한 인텐트씩.** 7개를 동시에 옮기지 않는다. 그래프에 노드 하나를 추가하고,
  나머지 인텐트는 기존 if/elif로 남겨둔 채 병행시킨다.
- **노드는 얇게.** 91-3대로 기존 함수를 호출만 하는 포장지로 만든다. 노드 안에서
  로직을 새로 쓰기 시작하면 이관이 아니라 재작성이 된다.
- **스냅샷으로 동등성을 증명한다.** 프롬프트 이관(D-064~065) 때 쓴 것과 같은 방식 —
  이관 전후 응답이 바이트 단위로 같은지 고정한다. 구조만 바꾸는 작업이므로 출력이
  달라지면 그건 버그다.

---

## 7. 사용법 — 우리 코드에 대입한 예시

강의 61-2·91-2·91-3의 개념을 우리 도메인 이름으로 옮긴 것이다. 아직 저장소에 없는
코드이므로 **작성 시 참고용 스케치**로 본다.

### 7.1 State — 서류철 양식

강의는 `TypedDict`를 쓰지만(61-2), 우리는 이미 Pydantic `AgentState`가 있어 그대로
쓰거나 감싸면 된다.

```python
from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages

class TripState(TypedDict):
    # 사용자 발화와 봇 응답이 누적되는 칸 (91-3의 respond_node가 여기 쌓는다)
    messages: Annotated[list, add_messages]
    # 분류 노드가 채우는 칸
    intent: str | None
    # 조건 추출·병합 결과 — 지금의 UserConditions에 해당
    conditions: dict
    # 되묻기가 필요한 경우 그 코드 (location_required 등)
    clarification_code: str | None
    # 최종 응답 텍스트
    answer: str | None
```

`messages`에 `add_messages` 리듀서를 붙이면 노드가 반환한 메시지가 기존 대화 위에
자동으로 쌓인다(91-3). 지금 우리가 손으로 관리하는 대화 이력 누적이 이 한 줄로 대체된다.

### 7.2 노드 — 기존 함수를 감싸기만 한다

```python
async def classify_node(state: TripState) -> dict:
    """기존 classify_intent()를 그대로 호출하는 얇은 포장지."""
    user_input = state["messages"][-1].content
    result = await llm.classify_intent(
        user_input,
        has_previous_recommendation=...,
        shown_place_count=...,
    )
    return {"intent": result.data.intent.value}   # 채운 칸만 반환


async def recommend_node(state: TripState) -> dict:
    """기존 추천 파이프라인을 그대로 호출한다. 속은 안 건드린다."""
    response = await run_recommendation_pipeline(state["conditions"])
    return {"answer": compose_recommendation_message(response)}
```

노드 규칙은 강의와 동일하다 — **상태 전체를 받아서, 자기가 채운 칸만 딕셔너리로
반환한다.**

### 7.3 조건부 엣지 — 지금의 if/elif가 여기로 모인다

```python
def route_by_intent(state: TripState) -> str:
    """지금 run_agent_flow()에 흩어져 있는 40군데 분기의 목적지."""
    if state.get("clarification_code"):
        return "clarify"          # 91-4의 escalate 자리
    return state["intent"]         # "RECOMMEND" | "INFO" | ...


graph.add_conditional_edges(
    "classify",
    route_by_intent,
    {
        "RECOMMEND": "recommend",
        "MODIFY": "modify",
        "INFO": "info",
        "COMPARE": "compare",
        "SCHEDULE": "schedule",
        "GENERAL": "general",
        "OUT_OF_SCOPE": "out_of_scope",
        "clarify": "clarify",      # 되묻기 = 우리 버전의 에스컬레이션
    },
)
```

### 7.4 Checkpointer — 우리는 쓰지 않는다

> **이 절은 2026-08-24에 결론이 뒤집혔다.** v1.0은 "`session_id`가 곧 `thread_id`이고
> `StateStore`가 곧 `BaseCheckpointSaver`"라고 적었으나, 실제로 붙여 보니 **틀렸다.**
> 실측 근거는 §9.9에 있다. 아래는 뒤집힌 뒤의 내용이며, 옛 대응표를 따라 하면 안 된다.

강의는 `MemorySaver`로 시작해 운영에선 DB 보관함으로 바꾸라고 한다(91-2). 그 조언이
전제하는 것은 **"그래프가 턴 중간에 멈췄다가 나중에 이어서 돈다"**는 상황이다.

**우리 그래프는 한 턴 안에서 시작하고 끝난다.** 요청이 들어오면 돌고, 응답을 내면
끝난다. 이어서 돌 지점이 없으니 보관함이 할 일이 없다. 그래서 두 그래프 모두
인자 없이 컴파일한다.

```python
# 우리 방식 — checkpointer 없음
app = graph.compile()

# 한 턴에 필요한 값은 전부 입력으로 넣는다. thread_id도 쓰지 않는다.
await app.ainvoke({"llm_output": llm_output, "answer": None}, config=config)
```

붙였다가 뗀 이유는 두 가지다(자세한 실측은 §9.9).

1. **이전 턴 값이 새 턴에 새어 들어온다** — 같은 `thread_id`로 다시 부르면 입력에
   안 넣은 칸이 지난 턴 값으로 남는다
2. **메모리가 계속 쌓인다** — 세션 6개에 체크포인트 21건이 남고 줄지 않는다

실수로 다시 붙는 것은 `test_graphs_have_no_checkpointer`가 막는다.

**그럼 턴 사이 상태는 누가 관리하나** — `StateStore`(Package B)다. 이건 checkpointer의
대체재가 아니라 **다른 층의 물건**이다.

| | `StateStore` (우리 것) | LangGraph checkpointer |
|---|---|---|
| 담는 것 | 조건·추천이력·Trace·피드백 | 그래프 실행 중간 상태 |
| 목적 | 도메인 데이터 영속 | 중단 지점에서 재개 |
| 계약 | B의 `agent-state-contract-v1.md` | 프레임워크 내부 |
| 키 | `session_id` | `thread_id` |
| 지금 상태 | 씀 | **안 씀** |

### 7.5 그래프 조립

```python
from langgraph.graph import StateGraph, START, END

graph = StateGraph(TripState)
graph.add_node("classify", classify_node)
graph.add_node("recommend", recommend_node)
graph.add_node("clarify", clarify_node)
# ... 나머지 인텐트 노드

graph.add_edge(START, "classify")
graph.add_conditional_edges("classify", route_by_intent, { ... })

# 모든 경로가 응답 노드로 합류한다 (91-4)
for node in ("recommend", "info", "compare", "schedule",
             "general", "out_of_scope", "clarify"):
    graph.add_edge(node, "respond")
graph.add_edge("respond", END)

app = graph.compile()  # checkpointer는 달지 않는다 — §7.4
```

---

## 8. 도입 시 확인할 것

- **비용**: LangGraph는 MIT 라이선스 오픈소스로 무료다. 유료는 별도 제품인
  LangSmith(관측 도구)이고, 우리는 그 자리에 Langfuse를 검토 중이라(로드맵 13번)
  겹치지 않는다.
- **의존성**: `langgraph` 패키지 추가가 필요하다. LangChain 전체를 끌어올 필요는
  없다 — 로드맵 12번이 말하는 "취향 검색 기능에만 LangChain"과 별개로 도입 가능하다.
- **스트리밍**: 지금 SSE로 진행 상태(`progress`)와 답변 델타를 내보내고 있다
  (`agent-response-streaming.md`). LangGraph도 노드 단위 스트리밍을 지원하지만
  이벤트 모양이 다르므로, 3단계 착수 전에 **기존 SSE 계약을 유지할 수 있는지 먼저
  확인**해야 한다. 이게 3단계의 가장 큰 미확인 항목이다.
- **테스트**: 노드를 얇게 유지하면 기존 단위 테스트는 대부분 그대로 살아남는다
  (호출 대상 함수가 그대로이므로). 새로 필요한 건 라우팅 함수(`route_by_intent`)에
  대한 테이블 테스트 정도다.

---

## 9. 변경 규모 실측 (2026-08-22)

"대대적인 변경 아닌가"를 감이 아니라 숫자로 확인했다.

### 9.1 코드 규모

| 항목 | 실측값 | 이관 시 의미 |
|---|---|---|
| `run_agent_flow()` 함수 하나 | **1,227줄** | 이게 통째로 그래프로 바뀌는 대상 |
| `agent_runtime.py` 전체 | 2,526줄 | 위 함수 + 헬퍼 24개 |
| 인텐트 분기 | 40군데 | → 조건부 엣지 1개 + 라우팅 함수 1개로 수렴 |
| early return | **13개** | 각각이 종착 노드 후보 |
| `await` 지점 | 51개 | 노드 경계를 가르는 I/O 지점 |
| SSE 이벤트 발신 | **30군데** | §9.4의 최대 위험 요소 |
| 되묻기·상태 복원 참조 | 32군데 | 재진입 경로 — 그래프 이관 시 가장 까다로운 부분 |

**진입점은 좁다.** 외부에서 이 흐름을 부르는 곳은 단 3곳이다.

```
app/routes/chat.py:48    → run_agent()          (REST)
app/routes/chat.py:132   → run_agent()          (SSE 스트리밍)
app/routes/agent.py:25   → run_agent()          (개발용 디버그)
```

`app/services/runtime/__init__.py`가 `run_agent`/`run_agent_flow` 두 개만
export하므로, **그래프로 바꿔도 이 세 줄과 `__init__.py`만 그대로면 바깥은 변화를
모른다.** 이관을 단계적으로 할 수 있는 근거가 여기 있다.

### 9.2 예상 변경 라인 수 (단계별)

| 단계 | 신규 작성 | 기존 수정 | 삭제 | 합계(체감) |
|---|---|---|---|---|
| 1단계 (GENERAL) | ~250줄 | ~30줄 | ~0줄 | **~280줄** — 기존 경로 병행 유지 |
| 2단계 (OUT_OF_SCOPE·되묻기) | ~150줄 | ~80줄 | ~50줄 | ~280줄 |
| 3단계 (나머지 인텐트 5개) | ~600줄 | ~300줄 | ~900줄 | **~1,800줄** |
| 4단계 (Checkpointer) | ~250줄 | ~100줄 | ~0줄 | ~350줄 |

3단계가 압도적으로 크다. 인텐트 7개를 한 번에 옮기면 저 1,800줄이 한 PR에
들어오는데, 이건 리뷰가 사실상 불가능한 크기다. **§6.2의 "한 번에 한 인텐트씩"
원칙을 지키면 PR당 200~300줄로 쪼개진다**(7개 인텐트 × 약 250줄).

### 9.3 폴더 구조 변경

새 폴더 하나가 생기고, 기존 폴더는 그대로 둔다.

```
backend/app/services/runtime/
├── agent_runtime.py          (2,526줄 → 단계적으로 축소, 최종 진입점만 남김)
├── response_composer.py      변경 없음  ← 노드가 호출만 함
├── recommendation_transform.py  변경 없음
├── info_response_transform.py   변경 없음
│
└── graph/                    ★ 신규
    ├── __init__.py           그래프 조립·컴파일
    ├── state.py              TripState 정의
    ├── routing.py            route_by_intent 등 조건부 엣지 함수
    ├── checkpointer.py       StateStore ↔ BaseCheckpointSaver 어댑터 (4단계)
    └── nodes/
        ├── classify.py
        ├── recommend.py
        ├── info.py
        ├── compare.py
        ├── schedule.py
        ├── general.py
        ├── modify.py
        ├── out_of_scope.py
        └── clarify.py        (91-4 escalate 대응)
```

**기존 파일 대부분은 손대지 않는다.** `response_composer.py`(900줄),
`*_transform.py` 5개, `protocols.py` 등은 노드가 호출만 하므로 그대로다. 이게
91-3의 "부품 속은 안 건드리고 얇은 포장지만 씌운다"를 지킨 결과다.

변경이 필요한 기존 파일은 다음 정도다.

| 파일 | 변경 내용 |
|---|---|
| `app/services/runtime/__init__.py` | export 유지하되 내부를 그래프로 교체 |
| `app/services/runtime/agent_runtime.py` | 단계별로 로직이 `graph/nodes/`로 빠져나감 |
| `backend/pyproject.toml` | `langgraph` 의존성 추가 |
| `app/routes/chat.py` · `agent.py` | **가급적 무변경** — 시그니처 유지가 목표 |

**실제로 만들어진 구조 (2026-08-24)** — 위는 2026-08-22의 예상이고, 이관을 끝낸
지금 모습은 이렇다. 인텐트별 노드 9개 대신 **파이프라인 단계별 노드 4개 + 답변
노드 2개**가 됐다. 인텐트 분기 40개가 전부 조기 반환 앞에 몰려 있어서, 그 뒤는
"인텐트별로 갈라지는 흐름"이 아니라 순차 파이프라인이었기 때문이다(§9.8).

```
backend/app/services/runtime/
├── agent_runtime.py          2,526줄 → 2,700줄(전체) / run_agent_flow()는 1,227 → 640줄
├── stream_events.py          ★ 신규 99줄 — SSE 유틸을 떼어냄(순환 import 차단용)
└── graph/                    ★ 신규
    ├── __init__.py           181줄  그래프 2개 조립·진입 함수
    ├── state.py               31줄  EarlyReturnState
    ├── pipeline_state.py      55줄  RecommendPipelineState
    ├── routing.py             68줄  조건부 엣지 3개
    ├── sink.py                81줄  config에서 sink·llm·deps 꺼내기
    └── nodes/
        ├── general.py         50줄  스트리밍 답변
        ├── static_answer.py   29줄  한 번에 만드는 답변
        └── pipeline.py       157줄  tool_fetch·scoring·schedule·finalize
```

예상과 다른 점 셋:

- **`checkpointer.py`를 안 만들었다** — 4단계 자체를 하지 않기로 했다(§9.9)
- **`classify.py`가 없다** — 분류는 그래프 밖(`run_agent_flow()`)에 남겼다. 조건
  병합까지가 B 계약 영역이라 그래프로 끌어들이면 소유권이 흐려진다
- **`stream_events.py`가 예상에 없었다** — `graph/`가 `agent_runtime.py`의 sink 타입을
  필요로 하는데 반대 방향 import도 있어 순환이 생겼다. 먼저 순수 리팩터링으로
  떼어내고 그 위에 그래프를 얹었다

### 9.4 가장 큰 위험 — SSE 스트리밍 (30군데)

`run_agent_flow()`는 `StreamEventSink`를 인자로 받아 흐름 곳곳에서 진행 상태와
답변 델타를 내보낸다. **이 30군데가 함수 전체에 퍼져 있다는 게 문제다.**

```python
StreamEventSink = Callable[[str, dict[str, object]], Awaitable[None]]
```

LangGraph는 노드 단위 스트리밍(`astream_events`)을 제공하지만, 이벤트 모양이 우리
SSE 계약(`progress`/`message_start`/`message_delta`/`done`)과 다르다. 두 가지 길이
있다.

1. **sink를 그래프 config로 넘겨 노드 안에서 지금처럼 직접 호출** — 계약이 그대로
   유지되고 변경이 작다. LangGraph의 스트리밍 기능은 안 쓰게 된다.
2. **`astream_events`를 우리 SSE 형식으로 번역하는 어댑터** — 더 "LangGraph답지만"
   진행 문구(`"요청 의도와 조건을 파악하고 있어요"` 같은 도메인 문구)를 노드
   메타데이터로 옮겨야 해서 작업이 커진다.

**→ 0단계 스파이크에서 검증 완료. 방식 1을 채택한다(§9.6).**

### 9.5 테스트 영향

- 회귀 대상: **2,316건**. `tests/test_agent_runtime.py` 하나가 4,600줄이다.
- 노드를 얇게 유지하면 **대부분 그대로 통과한다** — 호출 대상 함수(`compose_*`,
  `*_transform`)가 바뀌지 않기 때문이다.
- 다만 `test_agent_runtime.py`는 `run_agent_flow()`를 직접 부르는 테스트가 많아,
  진입점 시그니처를 유지하는 것이 **테스트 4,600줄을 지키는 조건**이다.
- 신규 필요: 라우팅 함수 테이블 테스트, 노드별 단위 테스트, 그래프 컴파일 스모크
  테스트.

---

### 9.6 0단계 스파이크 결과 (2026-08-23) — 방식 1 채택

`langgraph 1.2.11`을 저장소 밖 임시 venv에 설치해, 우리 SSE 계약을 그대로 흉내 낸
3노드 그래프(`classify → general → respond`)로 두 방식을 실제로 돌려 비교했다.
저장소에는 커밋하지 않았다.

| | 방식 1 (sink를 config로) | 방식 2 (`astream_events` 번역) |
|---|---|---|
| 이벤트 순서 재현 | **완전 일치** | 불일치 |
| `message_start` | ✅ | ❌ 나오지 않음 |
| `message_delta` × N | ✅ 3건 그대로 | ❌ 0건 — 노드 **내부** 루프라 그래프 이벤트로 노출되지 않음 |
| `result` payload | ✅ 그대로 | ⚠️ 노드 반환값 전체가 실려 형태가 다름 |

```
기준 계약 : progress, progress, message_start, message_delta×3, result
방식 1    : progress, progress, message_start, message_delta×3, result   ← 일치
방식 2    : progress, progress, result                                    ← 불일치
```

**방식 2가 실패한 이유가 핵심이다.** `astream_events`는 *노드 경계*에서 이벤트를
낸다. 그런데 우리 `message_delta`는 노드 하나 **안에서** LLM 스트림을 돌며 나오는
것이라(`stream_general_answer()`), 그래프 입장에서는 "노드 하나가 실행 중"일 뿐
관측 대상이 아니다. 노드를 델타 단위로 쪼개지 않는 한 이 격차는 메울 수 없고,
쪼개면 그래프가 토큰 수만큼 노드를 갖는 이상한 모양이 된다.

**결정 — 방식 1.** 노드 시그니처를 `(state, config: RunnableConfig)`로 두고
`config["configurable"]["stream_event_sink"]`에서 기존 sink를 꺼내 지금과 똑같이
호출한다. 이렇게 하면:

- `chat.py`의 큐 기반 `emit()`을 **한 줄도 안 고친다** — sink는 그냥 콜백이라
  그래프가 그걸 부르든 `run_agent_flow()`가 부르든 차이가 없다
- 프론트 계약도 그대로다(§10.3 판정 기준 3번 충족 가능)
- 대신 LangGraph의 스트리밍 기능은 안 쓴다 — 우리 계약이 이미 더 세밀하다

**부수 확인 2건**

- **노드 시그니처**: `config` 파라미터를 `RunnableConfig`로 **타입 어노테이션해야**
  LangGraph가 주입한다(`dict`로 적으면 `TypeError: missing 1 required positional
  argument`). 1.2.x의 `_runnable.py`가 어노테이션으로 판별한다.
- **`MemorySaver` 멀티턴**: 같은 `thread_id`로 2턴 호출 시 `add_messages` 리듀서가
  대화를 4건으로 누적하는 것을 확인했다(human/ai × 2). ~~우리 `session_id`를
  `thread_id`로 그대로 쓰면 된다는 §7.4 서술이 실제로 성립한다.~~
  → **여기서 내린 결론은 이후 뒤집혔다(§9.9).** "동작한다"는 확인했지만 "우리에게
  필요하다"까지 확인한 게 아니었다. 실제로는 이득 없이 이전 턴 값 유출과 메모리
  증가만 남아 떼어냈다.

**의존성 정정**: `langgraph`를 설치하면 `langchain-core`가 함께 딸려온다
(1.2.11 기준 `langchain-core 1.6.0`, `langgraph-checkpoint`, `langgraph-sdk` 등).
§8의 "LangChain 전체를 끌어올 필요는 없다"는 여전히 맞지만(`langchain` 본체·
통합 패키지는 안 들어옴), **`langchain-core`는 불가피**하다.

---

### 9.7 1단계 구현 결과 (2026-08-23) — GENERAL 이관 완료

**§6.1.2가 증명하겠다고 한 3가지가 전부 확인됐다.**

| 증명 대상 | 결과 |
|---|---|
| 실제 `chat.py` SSE로 프론트 수정 없이 동작 | ✅ 프론트 **0줄 변경** |
| 기존 `run_agent_flow()`와 병행 가능 | ✅ GENERAL만 그래프, 나머지 6개는 기존 경로 |
| 회귀 2,293건 통과 | ✅ 2,298건 통과(신규 5건 포함) |

**SSE 동등성 실측** — 같은 엔드포인트로 플래그를 켜고 끄며 비교한 결과, 이벤트
11건의 이름·순서·`stage` 문구가 **완전히 동일**했다(답변 텍스트만 LLM 특성상 매번
다름).

```
기존 경로 : progress×3 → message_start → message_delta×6 → done
그래프 ON : progress×3 → message_start → message_delta×6 → done
```

실서버(`/api/chat/stream`)에서도 "안녕" 요청이 5.0초에 정상 완료됐다.

**추가된 것**

```
app/services/runtime/
├── stream_events.py          ★ 신규 — agent_runtime.py에서 SSE 헬퍼를 추출
└── graph/                    ★ 신규
    ├── __init__.py           그래프 조립 + run_general_answer_graph()
    ├── state.py              GeneralAnswerState
    ├── sink.py               config에서 sink/LLM 꺼내는 통로
    └── nodes/general.py      GENERAL 답변 노드
tests/graph/test_general_graph.py  ★ 신규 — 동등성 테스트 5건
```

`stream_events.py` 분리가 필요했던 이유: `StreamEventSink`와 발신 헬퍼가
`agent_runtime.py` 안에 있었는데, `agent_runtime`이 그래프를 import하므로 그래프가
반대로 `agent_runtime`을 import하면 순환이 된다. **정의 위치만 옮기고 동작은 그대로**
두었고(옛 이름은 비공개 별칭으로 유지), 이 리팩터 직후 2,293건이 그대로 통과하는
것을 먼저 확인한 뒤 그래프를 붙였다.

**되돌리기 경로**: `USE_LANGGRAPH_GENERAL=false` 하나로 기존 `compose_chat_message()`
직접 호출로 즉시 복귀한다. 이 경로가 살아있는지도 테스트로 고정했다
(`test_flag_off_falls_back_to_legacy_path`).

**남은 것**: 그래프가 아직 노드 하나짜리 외길이라 **조건부 엣지를 쓰지 않는다.**
라우팅의 진짜 값어치(§2의 40군데 분기 수렴)는 2단계에서 OUT_OF_SCOPE·되묻기가
붙어 갈림길이 생겨야 드러난다. 1단계는 "배선이 되는가"까지만 증명한 것이다.

---

### 9.8 3단계 구현 결과 (2026-08-23) — 파이프라인 이관 완료

§6.1.2의 3단계. 착수 직전 측정에서 **계획의 전제가 틀린 것**이 드러났다.

**정정 — §5의 그림은 실제 코드 모양이 아니다.** 인텐트 분기 40군데가 전부 조기 반환
*이전*에 있고, 그 이후 693줄에는 **2군데뿐**이었다(`is_schedule` 하나 + 되묻기 옵션
하나). 즉 남은 구간은 인텐트 부챗살이 아니라 **순차 파이프라인**이고,
RECOMMEND·MODIFY·SCHEDULE이 같은 길을 지난다.

따라서 3단계는 "인텐트 7개를 노드로"가 아니라 **"파이프라인 4단계를 노드로"**가 됐다.
"40군데 분기가 한 곳에 모인다"는 효과는 이미 1·2단계에서 달성돼 있었다.

**작업 순서** — 위험을 둘로 나눴다.

1. 먼저 `run_agent_flow()` 안에서 **순수 함수로만 추출**(커밋 2개). 본문은 한 줄도
   바꾸지 않았고, 이 시점에 테스트가 그대로 통과하는 것을 확인했다
2. 그다음 그 함수들을 **얇은 노드로 감싸** 그래프에 붙였다(커밋 1개)

옮기는 것과 고치는 것을 같은 커밋에 섞지 않으려는 것이다. 1번만으로도 그 자체로
안전한 리팩터라 되돌릴 지점이 남는다.

**결과**

```
START → [tool_fetch] → ◇중간에 끝나는가
                          ├─ 예   → END                    (C 되묻기/no_data)
                          └─ 아니오 → [scoring] → ◇SCHEDULE인가
                                                    ├─ [schedule] → END
                                                    └─ [finalize] → END
```

| | 이관 전 | 이후 |
|---|---|---|
| `run_agent_flow()` | 1,227줄 | **640줄** |
| 테스트 | 2,293건 | 2,310건 |

동등성은 실제 실행으로 확인했다 — RECOMMEND·SCHEDULE 각각 플래그 on/off로 돌려
`message`·`intent`·`recommendations`·`schedule`이 전부 일치했다.

---

### 9.9 4단계는 하지 않는다 (2026-08-24) — 전제가 틀렸다

§5와 §7.4는 `STATE_STORE_BACKEND=supabase`가 "그대로 커스텀 `BaseCheckpointSaver`가
된다"고 적었다. **이 대응은 성립하지 않는다.**

| | `StateStore`(우리 것) | LangGraph checkpointer |
|---|---|---|
| 담는 것 | 조건·추천이력·조건변경로그·Trace·피드백 | 그래프 실행 중간 상태 |
| 의미론 | 필드별 Add/Update/Remove(`field_spec.py`), append-only 감사 로그 | 슈퍼스텝 사이 스냅샷 |
| 계약 | B의 `agent-state-contract-v1.md` | 프레임워크 내부 |
| 목적 | 도메인 데이터 영속 | **중단 지점에서 재개** |

이름이 둘 다 "상태 저장"이라 같아 보였을 뿐, checkpointer를 `StateStore`로 갈아끼우면
조건 병합의 소유권이 B 계약에서 그래프로 넘어간다 — 이관이 아니라 계약 위반이다.

**게다가 1~3단계에서 붙여둔 `MemorySaver`는 이득 없이 해롭기만 했다.** 실측으로
확인한 것(2026-08-24):

1. **이전 턴 값 유출** — 같은 `thread_id`로 다시 부르면, 입력 dict에 넣지 않은 칸이
   이전 턴 값으로 남는다. 우리 파이프라인은 매 턴 모든 칸을 덮어써서 지금은 사고가
   안 났지만, 설계가 아니라 운이다
2. **메모리 무한 증가** — 세션 6개를 돌리자 체크포인트 21건이 RAM에 남았고 줄지 않는다

우리 그래프는 **한 턴 안에서 시작하고 끝난다.** 턴 사이 상태는 B가 이미 관리하므로
보관함이 할 일이 없다. 그래서 **두 그래프에서 checkpointer를 떼어냈고**, 실수로 다시
붙는 것을 `test_graphs_have_no_checkpointer`로 막았다.

**나중에 필요해진다면** — "되묻기에서 멈췄다가 사용자 답변으로 재개" 같은 진짜 중단·
재개가 필요해지는 시점이다. 그때는 `StateStore`를 갈아끼우는 게 아니라, **B의 상태와
별개로** 그래프 재개용 보관함을 새로 설계해야 한다. 지금 그 기능은 되묻기 코드
(`clarification_choice`)가 이미 다른 방식으로 해결하고 있다.

### 9.10 이관 검증 결과 (2026-08-24)

이관은 **출력이 같아야 하는 작업**이므로(§6.2), "그래프가 동작한다"가 아니라
**"그래프를 켜도 기존과 결과가 같다"**를 확인했다.

**방법** — 같은 발화를 기능 플래그 끈 상태(기존 경로)와 켠 상태(그래프 경로)로 각각
돌려, ① 최종 `AgentResponse` JSON 전체 ② SSE 이벤트 이름 순서 두 가지를 비교했다.
세션 ID·`request_id`·타임스탬프·소요시간처럼 실행마다 달라지는 값은 제외했다.

| 케이스 | Fake Provider | 실제 Provider |
|---|---|---|
| GENERAL (정체성 / 지식) | 동일 | 동일 |
| OUT_OF_SCOPE (무관 / 주입 / 유해) | 동일 ×3 | 동일 ×3 |
| INFO (운영시간 / 혼잡) | 동일 | 동일 |
| RECOMMEND | 동일 | 동일 |
| SCHEDULE | 동일 | API 잡음(아래) |
| MODIFY (전체거절 / 조건변경) | 동일 | 동일 |
| COMPARE | 미도달(아래) | 동일 |
| 되묻기(위치 없음) | 동일 | API 잡음(아래) |

SSE 순서도 전부 일치했다. 예를 들어 RECOMMEND는 양쪽 다
`progress ×5 → message_start → message_delta → result`였다.

**"API 잡음"으로 판정한 근거** — 실제 Provider에서 2건이 달랐는데, **그래프를 켜지
않고 기존 경로만 두 번** 돌려도 정확히 같은 2건에서 같은 종류의 차이가 났다. 네이버
지역검색이 호출마다 다른 장소를 돌려주는 것이지 이관 회귀가 아니다.

**Fake에서 COMPARE를 못 태운 이유** — COMPARE는 앞 턴에 노출된 장소가 2곳 이상이어야
분류되는데, Fake 장소 저장소는 어떤 질의로도 후보를 0건 반환한다. 이 브랜치가 만든
문제가 아니라 원래 있던 fixture 한계이며, Fake는 "터지지 않는지"만 보는 용도이므로
인텐트를 늘릴 때마다 손보지 않기로 했다.

**곁가지로 드러난 것 2건**(LangGraph와 무관, 기존 문제):

1. `.env`가 `PLACE_PROVIDER=real` 등 개별 키를 지정해서 **`PROVIDER_MODE=fake`가
   무력화된다.** fake로 돌리는 줄 알고 실제 API를 태우기 쉽다
2. `settings.fake_current_datetime`이 **정의만 있고 참조가 0건**이다
   ([config.py](../../backend/app/config.py) `fake_current_datetime`). 주석은
   "`app/core/clock.py`에서 사용"이라 되어 있으나 그런 모듈이 없다

### 9.11 되묻기 재진입 검증 (2026-08-24)

되묻기 해소는 사용자가 버튼을 눌러 보내는 **두 번째 요청**이라 발화 목록만으로는
재현되지 않는다. 프론트가 보내는 형태를 그대로 흉내 냈다 — 버튼 라벨을
`user_input`으로, 버튼 id를 `clarification_choice`로 함께 보낸다
([DeveloperChatPage.tsx](../../frontend/src/pages/DeveloperChatPage.tsx)
`requestSend(label, optionId)`).

실사용에서 나온 순서를 그대로 재생해 플래그 ON/OFF로 비교했다.

| 단계 | 결과 |
|---|---|
| 1. `경복궁 근처로 일정 짜줘` | 동일 |
| 2. **[버튼] 다른 종류의 장소도 포함해서 찾기** (`schedule_relax_category`) | 동일 |
| 3. `경복궁 근처 카페 추천해줘` | 동일 |
| 4. `다른 곳 보여줘` | 동일 |
| 5. `다른 곳 보여줘`(재차) | 동일 |

응답 JSON 전체와 SSE 이벤트 순서 모두 5단계 전부 일치했다.

**함께 확인한 것 — "조건에 맞는 곳이 없다"는 이관 탓이 아니다.** 실사용 중
일정·추천이 0건으로 끝나는 경우가 있어 원인을 봤다. Tool은 장소를 정상적으로
찾아왔고(`places: item_count=7`), 09:44 시점에 그 7곳이 전부 운영시간 하드 필터에
걸린 것이었다(주변 식당·카페 대부분이 10~11시 개점). 일정은 `time_available`에 맞는
최소 개수를 못 채우면 LLM을 부르지 않고 실패로 끝낸다([planner.py](../../backend/app/schedule/planner.py)
`len(request.candidates) < min_items`). 같은 요청을 운영시간 필터만 끄고 돌리면
일정 3개가 정상으로 나온다. 스코어링·필터·Tool·Provider는 이 브랜치에서 **변경 0줄**이다.

### 9.12 응답 지연 측정 (2026-08-24)

ON/OFF를 **번갈아** 12회씩 돌려 중앙값을 비교했다(한쪽을 몰아 돌리면 캐시 워밍이
한쪽에만 유리하다). 평균 대신 중앙값을 쓴 것은 첫 실행이 항상 느리기 때문이다.

**Fake Provider — 그래프가 씌운 순수 오버헤드**

| 경로 | 기존 | 그래프 | 차이 |
|---|---|---|---|
| GENERAL(조기 반환·스트리밍) | 3.4ms | 4.1ms | +0.7ms |
| OUT_OF_SCOPE(조기 반환·단발) | 3.2ms | 4.1ms | +0.8ms |
| RECOMMEND(파이프라인) | 4.1ms | 5.2ms | +1.1ms |
| SCHEDULE(파이프라인+일정) | 4.2ms | 5.2ms | +0.9ms |

**실제 Provider — 실사용에 가까운 조건**

| 경로 | 기존 | 그래프 | 차이 |
|---|---|---|---|
| GENERAL | 3.4ms | 4.1ms | +0.7ms |
| OUT_OF_SCOPE | 3.4ms | 4.0ms | +0.6ms |
| RECOMMEND | 428.0ms | 438.7ms | +10.7ms (+2.5%) |
| SCHEDULE | 425.9ms | 422.0ms | **−4.0ms** (−0.9%) |

**판정: 통과.** 그래프가 더한 것은 **호출당 약 1ms 고정 비용**이다. 퍼센트가 20%대로
보이는 케이스는 기준이 3~4ms라서 그런 것이고, 외부 호출이 붙는 순간(400ms+) 잡음에
묻힌다 — 실제로 SCHEDULE은 그래프 쪽이 오히려 빨랐다. 실 LLM이 붙으면 응답이 초
단위이므로 1ms는 체감되지 않는다.

측정 조건: LLM은 결정적 비교를 위해 fake. 따라서 위 수치에는 LLM 호출 시간이 빠져
있고, **그래프 오버헤드만** 분리해 본 값이다.

---

## 10. 브랜치 전략 — 별도 브랜치가 맞다

### 10.1 결론

**맞다. `feature/llm-interpret`에서 직접 하지 않는다.** 근거는 세 가지다.

**① 지금 작업 트리가 깨끗하지 않다.** 2026-08-22 기준 `feature/llm-interpret`에
**미커밋 변경 39개 파일(834줄 추가)**이 올라와 있다(다른 작업자의 진행 중 작업 —
프롬프트·프론트·상태 저장소에 걸쳐 있음). 여기서 1,800줄짜리 구조 변경을 시작하면
두 작업이 같은 파일에서 얽힌다.

**② 되돌릴 수 있어야 한다.** §9.2대로 3단계는 삭제만 900줄이다. 실패 판정이 났을 때
`feature/llm-interpret`을 되감으면 그 위에 쌓인 다른 작업까지 함께 날아간다. 별도
브랜치면 브랜치를 버리는 것으로 끝난다.

**③ 팀 관례와 일치한다.** 저장소에 이미
`feature/guest-auth`·`feature/int-07-schedule`·`feature/dev-panel-location-badges` 등
기능별 브랜치가 여럿 있다. 큰 작업을 별도 브랜치에서 하는 것이 이 팀의 기존 방식이다.

### 10.2 제안하는 브랜치 흐름

```
develop
  └── feature/llm-interpret          (평소 작업 — 계속 진행)
        └── feature/langgraph-spike   ★ 신규
```

- **분기 지점**: `feature/llm-interpret`에서 딴다(develop이 아니라). 이 브랜치의 최신
  코드 위에서 이관해야 실제 상태와 맞는다.
- **분기 전 조건**: 위 39개 미커밋 변경이 **커밋된 뒤에** 딴다. 안 그러면 시작부터
  섞인다.
- **주기적 동기화**: `feature/llm-interpret` → `feature/langgraph-spike` 방향으로만
  머지해 최신 변경을 따라간다(반대 방향은 최종 판정 전까지 하지 않는다).
- **최종 병합**: §10.3 판정 기준을 통과했을 때만
  `feature/langgraph-spike` → `feature/llm-interpret`으로 PR을 올린다.

브랜치 이름에 `spike`를 넣은 것은 의도적이다 — **"도입 확정"이 아니라 "검증 중"임을
이름으로 드러내, 판정 전에 다른 작업이 이 위에 쌓이지 않게 한다.**

### 10.3 병합 판정 기준 (이걸 통과 못 하면 브랜치를 버린다)

| # | 기준 | 결과 (2026-08-24) |
|---|---|---|
| 1 | `pytest` 전부 통과 — 스킵으로 넘기지 않는다 | ✅ **2,311 passed / 24 skipped** (기준선 2,293 + 그래프 테스트 18건). 착수 시 적었던 "2,316"은 어림값이었다 |
| 2 | `ruff check .` 클린 | ✅ |
| 3 | **SSE 계약 무변경** — 프론트 한 줄도 안 고치고 `/dev-chat` 동작 | ✅ 프론트 변경 **0줄**(§10.5 파일 목록), SSE 순서 일치 확인(§9.10) |
| 4 | 7개 인텐트 각각 응답이 이관 전과 동일 | ✅ 13개 케이스 차등 비교(§9.10) |
| 5 | 되묻기 재진입(버튼 클릭 → 재요청) 정상 동작 | ✅ 5단계 시나리오 차등 비교, 차이 0건(§9.11) |
| 6 | 응답 지연이 유의미하게 나빠지지 않음 | ✅ 고정 오버헤드 약 1ms(§9.12) |

3번이 특히 중요하다. **프론트를 고쳐야 한다면 그건 "내부 구조 개선"이 아니라
"계약 변경"이므로, 범위를 다시 잡아야 한다는 신호다.**

5번이 자동 비교에서 빠진 이유는 구조적이다. 되묻기 해소는 사용자가 버튼을 눌러
`clarification_choice`를 실어 보내는 **두 번째 요청**이라, 발화 목록만으로는 재현할 수
없다. 확인할 되묻기는 `location_required`·`no_data_closed`·`no_data_empty`·
`no_data_exhausted` 네 종류다.

### 10.5 이 브랜치가 건드린 파일 (2026-08-24)

`feature/llm-interpret` 대비 **17개 파일, +1,823 / −290줄**. 그중 프론트엔드는 0개다.

| 구분 | 파일 |
|---|---|
| 신규 (그래프) | `graph/` 8개 파일, `stream_events.py` |
| 신규 (테스트) | `tests/graph/` 3개 파일 |
| 수정 | `agent_runtime.py`(+720/−290), `config.py`(플래그 2개), `pyproject.toml`(`langgraph>=1.2`) |
| 문서 | `docs/design/langgraph-adoption.md` |
| **프론트엔드** | **없음** |

**팀 병합 시 주의** — `langgraph`가 새 의존성이라 각자 재설치해야 한다. 특히
`npm run dev`는 `scripts/dev.mjs`가 PATH의 `python`을 그대로 쓰므로, 가상환경이 아닌
곳에 의존성이 깔려 있으면 그쪽에도 설치해야 백엔드가 뜬다.

### 10.6 기능 플래그를 언제 지울 것인가

`use_langgraph_early_return` / `use_langgraph_pipeline` 두 플래그는 기본값 `True`이고,
`False`로 두면 기존 경로가 그대로 돈다. 지금은 **롤백 스위치로 남겨둔다** — 실사용에서
문제가 안 나는 것을 한동안 지켜본 뒤 지운다.

비용은 명확하다. 플래그가 있는 동안은 **같은 일을 하는 코드가 두 벌** 남는다(기존
경로가 살아 있어야 `False`가 의미를 가지므로). 그래서 영구히 두지 않는다. 지울 때는
플래그 분기와 함께 `agent_runtime.py`의 기존 경로 호출부도 같이 걷어낸다.

### 10.4 착수 순서 요약

```
1. feature/llm-interpret의 미커밋 39개 파일 커밋       ← 선행 조건  ✅ 완료
2. git switch -c feature/langgraph-spike                            ✅ 완료 (2026-08-23)
3. 0단계 스파이크 — §9.4의 SSE 선택지 결정 (커밋 안 함)              ✅ 완료 → 방식 1 채택
4. 1단계(GENERAL 인텐트)만 구현                                       ✅ 완료
5. 2·3·4단계를 순차 진행 → 전 인텐트 대체 가능 상태에서 일괄 검증 후 push
```

**계획 변경(2026-08-23)**: v1.0은 1단계 후 멈춰 팀 검토를 받는 안이었으나, "한
인텐트만 옮긴 중간 상태로 올리지 않고 **완전히 대체 가능한 상태에서 검증한 뒤
적용**한다"는 방침으로 바꿨다. 따라서 2·3·4단계를 이어서 진행하고, push와 팀 검토는
전 인텐트 이관이 끝난 뒤 한 번에 한다. 단계별 커밋은 그대로 쪼개 남긴다 — 되돌릴
지점을 잃지 않기 위해서다.

**브랜치 현황(2026-08-23)**: `feature/langgraph-spike`를 `feature/llm-interpret`에서
분기했다. 분기 시점에 두 브랜치는 완전히 동일했고(파일 차이 0, 커밋 차이 양방향 0),
기준선으로 `pytest 2,293 passed / 24 skipped`, `ruff` 클린을 확인했다 — 이관 후
비교할 기준값이다. **원격에는 아직 push하지 않았다.** 지금 브랜치가 원본과
동일해 고유 내용이 없기 때문이며, 4번(1단계) 완료 시점에 push해 팀 검토를 받는다.

**4번에서 반드시 한 번 멈춘다.** 1단계는 기존 코드를 안 건드리므로, 여기까지의
결과물만으로도 "LangGraph를 프로젝트에 써봤다"는 목표(로드맵 16번)는 이미 달성된다.
3단계까지 갈지는 그 시점에 다시 판단한다.

---

## 11. 이 문서의 위치

- 로드맵 12번(LangChain)·16번(AI Agent 도구 경험)이 "여유 되면"으로 적어둔 항목의
  **판단 근거**에 해당한다. 이 문서의 결론은 그 우선순위 자체를 바꾸자는 것이 아니라,
  "쓸지 말지"는 이미 답이 나왔고 "언제·어디부터"만 남았다는 것이다.
- 3·4단계에 실제로 착수하기로 결정하면 그때 `docs/decision-log.md`에 D-번호를
  부여한다. 지금은 검토 결과일 뿐 결정이 아니다.
