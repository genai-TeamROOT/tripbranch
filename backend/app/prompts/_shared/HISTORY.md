# Shared Prompt History

## 현재 활성 슬롯

| 슬롯 | 관리 버전 | 템플릿 |
| --- | --- | --- |
| shared.persona | v1 | persona/trivi.md |
| shared.service_scope | v1 (Draft) | rules/service_scope.md |
| shared.safety | v1 (Draft) | rules/safety.md |
| shared.factuality | v1 (Draft) | rules/factuality.md |
| shared.budget / weather / concentration / environment | v1 | rules/*.md |
| shared.shown_place_list / validation_retry | v1 | rules/*.md |

## 승인 이력

`_shared/`는 여러 인텐트가 함께 사용하는 모델 지침의 원본 이력을 관리합니다. 아래는 Git
커밋과 기존 전역 changelog에서 확인된 행동 변경만 옮긴 기록입니다.

| 기준선 | 날짜 | 커밋 | 슬롯·규칙 | 변경 내용 | 영향 인텐트 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| legacy-1.0.0 | 2026-08-05 | `9ef8295` | 전역 Trace 표기 | `PROMPT_VERSION`을 LLMOps Trace·State Apply에 연결 | 전체 | 승인됨 |
| legacy-1.0.5 | 2026-08-07 | `bfad75f` | `shared.persona` | 트리비 페르소나와 느낌표·질문부호 응답 규칙 도입 | GENERAL, INFO, RECOMMEND, COMPARE | 승인됨 |
| legacy-1.0.13 | 2026-08-18 | `585a045` | weather, concentration, environment | `~도 괜찮아`를 조건 완화로 해석하도록 보강 | RECOMMEND, MODIFY | 승인됨 |

## 실행 가능한 과거 기준선

- [persona__legacy-1.0.5.md](archive/persona__legacy-1.0.5.md)는 `bfad75f`에서 복원한 실제
  모델 입력 원문입니다. 단독으로 선택하지 않고, 해당 페르소나를 필요로 하는 인텐트 기준선의
  `archive/variants.json`에서 함께 지정합니다.

행동이 달라지는 변경에서만 바꾸기 전 Markdown을 `archive/<slot>__legacy-<version>.md`로
보관합니다. 원문을 정확히 복원할 수 없는 과거 변경은 커밋과 이력만 남기며, 추정한 원문 파일은
만들지 않습니다.
