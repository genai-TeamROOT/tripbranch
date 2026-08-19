# INFO Prompt History

## 현재 활성 슬롯

| 슬롯 | 관리 버전 | 템플릿 | 공유 규칙 |
| --- | --- | --- | --- |
| info.extract | v1 | extract.md, question_type_rules.md, place_context_rules.md, visit_time_rules.md | factuality |
| info.answer | v1 | answer_instruction.md | persona, factuality |

## Draft

- 2026-08-19: 이전 INFO 카드 장소를 `from_conversation` 지시어 대상으로 이어서 해석하도록
  추출 규칙을 보강했습니다. 커밋·평가 후 승인 이력으로 승격합니다.

## 승인 이력

| 기준선 | 날짜 | 커밋 | 슬롯 | 변경 내용 | 변경 이유 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| legacy-1.0.12 | 2026-08-12 | `0c0a548` | `info.answer` | 검증된 INFO fields를 자연어 답변으로 변환하는 슬롯 신설 | 관광 데이터 결과를 사용자 답변으로 조립 | 승인됨 |

`Draft`는 승인 기준선이 아니므로 별도 Markdown 스냅샷으로 보관하지 않습니다.
