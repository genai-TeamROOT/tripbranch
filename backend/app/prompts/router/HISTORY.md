# Router Prompt History

## 현재 활성 슬롯

| 슬롯 | 관리 버전 | 템플릿 | 공유 규칙 |
| --- | --- | --- | --- |
| router.classify | v2.4.0 | intent_definitions.md, intent_priority.md, context_rules.md, boundary_cases.md | service_scope, safety |

## Draft

- 2026-08-31(v2.4.0): `_shared/rules/conversation_history.md`를 bundle에 넣고,
  `context_rules.md`의 "이전 추천 있음 + 지명 단독 → MODIFY" 규칙에 단서를 달았습니다 —
  "직전 턴이 정보 질문(INFO)이었고 이번 발화가 그 질문을 다른 장소로 이어가는 것으로
  보이면 INFO를 유지한다(되묻기 상태가 아니어도 적용)". 8-31 이전 두 번의 수정은
  **되묻기 상태(pending_clarification)가 있을 때**만 다뤘는데, 실사용에서 깨진 것은
  되묻기 없이 완결된 INFO 턴 뒤였습니다("안국역 혼잡도 알려줘" → "인사동은?" → 장소
  추천 5건). 규칙 22개 중 이 하나만 손댔습니다 — 나머지 예외 통폐합은 새 일반 원칙이
  실측으로 안정된 뒤 별도 변경으로 합니다(사용자 결정, 2026-08-31).
  실측·회귀 근거는 `_shared/HISTORY.md`의 같은 날짜 항목에 함께 적었습니다.

- 2026-08-31: INFO/SCHEDULE 되묻기 자유 텍스트 이어받기 버그(실사용 재현: "사람많아?"
  되묻기 뒤 "여의도 한강공원"이라고 답하면 MODIFY로 새어 혼잡도와 무관한 식당 추천이
  나옴)를 고치며 `context_rules.md`에 규칙 2개를 추가했습니다. ① 직전 턴이 INFO
  되묻기(장소 모름/후보 모호)로 끝났고 이번 발화가 그 답변으로 보이면 "이전 추천 있음 +
  지명 단독 → MODIFY" 규칙보다 INFO 유지를 우선합니다. ② `schedule06_ambiguous_recommend`
  되묻기("일정 계속 짤까요, 장소만 추천할까요?")는 두 선택지가 서로 다른 인텐트라 기존
  "SCHEDULE 되묻기 → SCHEDULE 유지" 규칙을 그대로 적용하면 "추천만 해줘"류 답변까지
  SCHEDULE로 잘못 강제되므로 전용 규칙을 별도로 뒀습니다. `interaction_mode.md`와 같은
  방식으로 `clarification_status`에 전용 값을 추가해 분류 프롬프트에 신호를 줍니다.
  `FakeLLMProvider`(테스트 대역)에도 같은 우선순위를 미러링했습니다
  (`tests/test_agent_runtime.py`의 `test_info_missing_place_free_text_answer_stays_info`,
  `test_schedule06_ambiguous_free_text_*` 참고). 실 서버 재확인 후 승인 이력으로
  승격합니다.
- 2026-08-20: 실시간 주차·지하철·버스정류장·행사 INFO 추가에 따라 API 조회 가능 사실
  정보의 범위와 지하철/주차/행사 경계 사례를 보강했습니다. 변경 전 INFO 정의 원문은
  `archive/intent_definitions__legacy-1.md`에 보관했습니다. INFO 추출 v3과 함께 단위
  테스트·실서버 질문 확인을 거쳐 승인 이력으로 승격합니다.
- 2026-08-21: COMPARE 실측 이동시간 연결(D-050) 검증 중 "빨리 갈까?", "얼마나 걸려?"
  같은 이동 소요시간 비교 표현이 COMPARE 트리거 예시에 없어 GENERAL로 새는 문제를
  발견했습니다. `intent_priority.md`(4번 COMPARE 항목)와 `context_rules.md`(이전 추천
  2개 이상 조건부 규칙)에 예시를 추가했습니다. 변경 전 원문은
  `archive/intent_priority__legacy-2.0.0.md`, `archive/context_rules__legacy-2.0.0.md`에
  보관했습니다. "덜 막힐까?"류 교통 정체 표현은 실시간 교통 API 연동 전까지 이번
  범위에서 제외합니다. 실 서버 재확인 후 승인 이력으로 승격합니다.

## 승인 이력

| 기준선 | 날짜 | 커밋 | 슬롯 | 변경 내용 | 변경 이유 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| legacy-1.0.1 | 2026-08-06 | `d476280` | `router.classify` | 이전 추천 뒤 위치만 제시한 발화를 MODIFY로 분류 | TP-67 위치 변경 시 조건 초기화 방지 | 승인됨 |
| legacy-1.0.3 | 2026-08-06 | `0bfdcfc` | `router.classify` | 단독 지명과 정보 질의 경계 사례를 재정렬 | D-053, 위치 표현의 오분류 방지 | 승인됨 |
| legacy-1.0.5 | 2026-08-07 | `bfad75f` | `router.classify` | 트리비 정체성·서비스 소개 문맥을 GENERAL로 구분 | 정체성 질문의 응답 경로 명확화 | 승인됨 |
| legacy-1.0.7 | 2026-08-08 | `c30bb68` | `router.classify` | SCHEDULE 되묻기 진행 상태를 분류 컨텍스트에 추가 | D-059, 일정 되묻기 답변이 MODIFY로 가는 문제 방지 | 승인됨 |
| legacy-1.0.9 | 2026-08-10 | `86a9cd1` | `router.classify` | 위치 되묻기 직후 단순 지명을 MODIFY의 검색 중심 변경으로 연결 | TP-67 후속, soft reset 뒤 위치·조건 보존 | 승인됨 |

## 실행 가능한 과거 기준선

- `router-context@legacy-1.0.0`: TP-67 전 `context_rules.md`만 바꾸는 슬롯 기준선입니다.
  [context_rules__legacy-1.0.0.md](archive/context_rules__legacy-1.0.0.md)와
  [variants.json](archive/variants.json)에서 파일·조합을 확인할 수 있습니다.
- 과거 `router.classify` 전체 원문은 프롬프트가 하나의 Python 파일에 있던 시기의 소스입니다.
  앞으로 승인된 행동 변경부터는 바뀐 슬롯마다 실행 가능한 Markdown 스냅샷을 보관합니다.
