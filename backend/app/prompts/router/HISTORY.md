# Router Prompt History

## 현재 활성 슬롯

| 슬롯 | 관리 버전 | 템플릿 | 공유 규칙 |
| --- | --- | --- | --- |
| router.classify | v1 | intent_definitions.md, intent_priority.md, context_rules.md, boundary_cases.md | service_scope, safety |

## Draft

- 2026-08-19: 직전 INFO 상세 카드 장소를 분류 컨텍스트에 전달해 `여기`·`이곳` 등 지시어를
  INFO로 이어서 해석하도록 보강했습니다. 커밋·평가 후 승인 이력으로 승격합니다.

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
