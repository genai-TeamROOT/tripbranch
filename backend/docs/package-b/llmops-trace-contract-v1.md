# LLMOps Trace Contract v1 (Package B)

- 작성자: 이태화
- 작성일: 2026-07-28
- 상태: Implemented (2026-08-05, B-07 반영 완료 — Q1~Q3 해결, 7절 참고)
- 협의 대상: Package A, Package D
- 적용 범위: AF-12 중 Trace·버전 기록만 (A/B 집계·재현성은 범위 밖 — 7절 참고)

## 이 문서의 목적

`agent-state-contract-v1.md` 4절(식별자)과 5.6절(저장 범위)에 이미 예고돼 있던
`prompt_version`/`scoring_version`/`variant_id`, 실행 메타데이터(지연 시간·토큰
사용량·오류 유형), `trace_id` 발급을 실제로 구현하기 위한 계약이다.

이 문서는 새로운 약속을 만드는 게 아니라, **B-01이 이미 한 약속을 지키는 문서**다.

## 전제

- B-01 계약을 상속한다. 여기 없는 내용(세션·조건·이력 등)은 `agent-state-contract-v1.md`를 따른다.
- Phase 1 범위는 "기록"까지다. A/B 실행 결과 집계, 동일 조건 재현 기능은 다음 단계로
  미룬다 — 기록이 먼저 쌓여야 집계할 게 생기기 때문이다.
- B는 여기서도 해석하지 않는다. `prompt_version` 같은 값이 무엇을 의미하는지는 몰라도
  되고, 그냥 받아서 `trace_id`와 묶어 저장한다.

---

## 1. 왜 지금 시작하나

B-01 5.6절 "저장한다" 목록에 이미 있던 항목인데, B-02/B-03 어디서도 구현되지 않았다.

```
- 실행 메타데이터 (지연 시간, 토큰 사용량, 오류 유형)
- 버전 정보 (prompt_version, scoring_version, variant_id)
```

B-01 4.5절도 `trace_id`를 "정의만, 발급은 Agent Runtime 연결 이후"라고 이미 표시해뒀다.

**현재 상태 (코드로 확인)**

```
StateApplyRequest.prompt_version   존재하지만 항상 None (state_transform.py에 TODO만 있음)
new_trace_id()                     존재하지만 어디에도 저장 안 됨 —
                                    agent_runtime.py에서 C 호출 request_id로
                                    1회성으로 쓰이고 버려짐
scoring_version / variant_id       필드 자체가 없음
latency / token / error_type       필드 자체가 없음
```

즉 AF-12는 완전히 새로 설계하는 게 아니라, B-01이 남겨둔 빈칸을 채우는 작업이다.

---

## 2. 무엇을 기록하나

| 필드 | 타입 | 의미 | 채우는 주체 |
| --- | --- | --- | --- |
| `trace_id` | string | run 내부 한 단계(LLM 호출·Tool 호출·Scoring 등) | B가 발급 |
| `run_id` | string | 이 trace가 속한 요청 | 기존과 동일 |
| `session_id` | string | 이 trace가 속한 대화 | 기존과 동일 |
| `step` | string | 어느 단계인지 (`"llm_interpret"`, `"tool_fetch"`, `"scoring"` 등) | 호출자(A/C/D) |
| `prompt_version` | string \| null | 이 단계에 쓰인 Prompt 버전 | 호출자(A) |
| `scoring_version` | string \| null | 이 단계에 쓰인 Scoring 버전 | 호출자(D) |
| `variant_id` | string \| null | A/B 실험 variant | 호출자 |
| `latency_ms` | int \| null | 소요 시간 | 호출자 |
| `token_usage` | int \| null | 토큰 사용량 (LLM 단계만 해당) | 호출자 |
| `error_type` | string \| null | 실패 시 오류 분류 | 호출자 |
| `recorded_at` | datetime | 기록 시각 | B가 채움 |

B는 이 값들의 의미를 모른다. `step`이 `"llm_interpret"`이든 `"scoring"`이든 그냥
문자열로 받아서 저장할 뿐이고, 어떤 버전이 "더 나은" 버전인지는 판단하지 않는다 —
B-01의 경계 원칙(1절)을 그대로 따른다.

---

## 3. 언제 발급·기록되나

B-01 4.4절 "처리 순서"를 그대로 확장한다.

```
run_id 발급 (조건 병합 이전, 기존과 동일)
  → 각 단계(LLM 호출 / Tool 호출 / Scoring)마다 trace_id 발급
  → 그 단계가 끝나면 record_trace() 호출 (호출자가 결과를 들고 옴)
```

`trace_id`는 **단계 시작 시점**에 발급하고, 기록은 **단계가 끝난 시점**에 한다 —
진행 중에는 `latency_ms`를 알 수 없기 때문이다.

---

## 4. 계약 (신규 진입점 1종)

```
record_trace(session_id, run_id, step, *, prompt_version=None, scoring_version=None,
             variant_id=None, latency_ms=None, token_usage=None, error_type=None)
  → trace_id 발급 + 저장, TraceRecordResponse 반환
```

B-01의 4계약(조회 / 적용 / 기록 / api 갱신) 패턴을 그대로 따라 5번째 계약으로 추가한다.

조회 전용 함수(`get_traces(run_id)`)는 필요해지면 그때 추가한다 — 지금은 "쌓기"만
하고 "꺼내 쓰는 쪽"은 아직 아무도 없다(YAGNI. B-02에서 검증/적용을 분리했던 것과
같은 이유로, 안 쓰는 기능을 미리 만들지 않는다).

---

## 5. 저장 정책

B-01 5.6절과 동일한 원칙을 따른다.

**저장한다**: 위 2절 필드 전부 (구조화된 값만)

**저장하지 않는다**: LLM 원문 응답, Prompt 원문 텍스트, Chain-of-Thought — 계약
문서 5.6절과 동일한 이유(원문은 AF-11 평가 Fixture 영역이지 B의 역할이 아님)

**append-only**: `ChangeLog`와 동일하게 trace 기록도 삭제 메서드를 만들지 않는다
(B-02 3-5절 "실수를 막는 장치"와 동일한 원칙 — 실행 이력은 지울 이유가 없다).

---

## 6. 이번 범위 밖 (다음 단계)

```
- A/B 실행 결과 집계 (variant별 성공률·평균 latency 비교)
- 동일 입력·Context·버전으로 재현 실행
- Version Registry (버전 자체를 등록·조회하는 기능) — 지금은 버전 "값"만 기록하고,
  그 버전이 뭘 의미하는지 등록하는 건 범위 밖
```

이 셋은 전부 "기록이 먼저 쌓인 뒤에" 의미가 생기는 기능이라, 지금 만들면 가짜
데이터로 설계하게 된다. 기록 장치부터 완성하고 실제로 값이 쌓이는 걸 본 다음에
설계하는 게 안전하다.

---

## 7. 확인 필요 (A·D에게) — 2026-08-05 해결됨

```
Q1  step 이름을 누가 정하나 — B가 enum으로 강제할지, 호출자가 임의 문자열로
    넘기게 할지. (B-01 경계 원칙상 B가 값의 의미를 모르므로 자유 문자열이
    맞다고 보는데, 그러면 오타로 같은 단계가 다른 이름으로 쌓일 위험이 있어
    A/D와 미리 이름을 맞춰두는 게 나을 수 있음)
    → 해결: A 확인 완료. "llm_interpret"/"tool_fetch"/"scoring" 그대로 사용.
      바꾸고 싶은 이름 없음(A 회신). enum 강제 없이 자유 문자열로 확정.

Q2  prompt_version/scoring_version/variant_id를 실제로 누가 언제 채워서
    보낼 준비가 됐는지 — A는 Prompt 버전을 어떻게 관리 중인지, D는 Scoring
    버전을 어떻게 매기고 있는지
    → 해결(prompt_version/scoring_version): A가 `app.providers.gemini_prompts.
      PROMPT_VERSION`("agent-interpret-prompts-1.0.0"), D가 `app.domain.
      scoring.SCORING_VERSION`("recommendation-scoring-1.0.0")을 각각 모듈-semver
      패턴으로 신설. agent_runtime.py의 llm_interpret/scoring 단계 호출부에
      연결 완료(커밋 9ef8295, PR #92).
    → 미해결(variant_id): 아직 아무도 값을 채울 준비가 안 됨. A/B 실험이
      실제로 필요해지기 전까지 None으로 유지(6절 "이번 범위 밖"과 동일한
      YAGNI 판단 — 실험 설계 없이 값만 미리 채우지 않는다).

Q3  이 trace 기록을 실제 HTTP 흐름 어디에 꽂을지 — run_agent_flow() 안에
    자연스러운 자리(LLM 호출 직후, Tool 호출 직후, Scoring 직후)가 있어
    보이는데, run_agent()가 아직 라우터에 안 물려 있는 상태(B-03 참고)라
    지금 넣어도 실제로 쌓이진 않음. A와 연결 시점 조율 필요
    → 해결: B-07 착수 시점엔 run_agent()가 이미 라우터에 연결돼 있어서
      더 이상 유효한 블로커가 아니었음(B-03에서 해소됨). run_agent_flow()를
      직접 읽어 LLM(2단계)/Tool(5단계)/Scoring(6단계) 호출 지점이 코드
      구조상 이미 명확히 분리돼 있음을 확인하고 B가 직접 판단해 배선함 —
      A/D 확인 없이도 코드로 풀리는 질문이었음.
```

---

## 8. 갱신 이력

| 일자 | 변경 |
| --- | --- |
| 07-28 | 초안 작성 (AF-12 시작) |
| 08-05 | B-07 완료 반영: record_trace()를 run_agent_flow() 3단계(llm_interpret/tool_fetch/scoring)에 배선. 7절 Q1(step 이름)·Q2(prompt_version/scoring_version, variant_id는 미해결로 유지)·Q3(연결 지점) 해결 상태 반영. 상태 Draft → Implemented |