# GENERAL Prompt History

## 현재 활성 슬롯

| 슬롯 | 관리 버전 | 템플릿 | 공유 규칙 |
| --- | --- | --- | --- |
| general.extract | v1 | extract.md, topic_rules.md | service_scope |
| general.answer | v1 | answer_instruction.md | persona, factuality |

## 승인 이력

| 기준선 | 날짜 | 커밋 | 슬롯 | 변경 내용 | 변경 이유 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| legacy-pre-version | 2026-07-24 | `21aad22` | `general.extract`, `general.answer` | Gemini 구조화 출력 기반 GENERAL 추출·답변 초기 구현 | 인텐트별 기본 응답 경로 구축 | 승인됨 |

전역 `PROMPT_VERSION` 도입 전 변경이므로 버전 번호를 추정하지 않고 커밋 기준으로만 기록합니다.
