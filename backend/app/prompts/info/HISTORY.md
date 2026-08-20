# INFO Prompt History

## 현재 활성 슬롯

| 슬롯 | 관리 버전 | 템플릿 | 공유 규칙 |
| --- | --- | --- | --- |
| info.extract | v3 | extract.md, question_type_rules.md, place_context_rules.md, visit_time_rules.md | factuality |
| info.answer | v1 | answer_instruction.md | persona, factuality |

## Draft

- 2026-08-20: `question_type_rules.md`를 v2에서 v3로 변경했습니다. 카페·커피 한정
  `realtime_commercial`을 서울시 응답에 존재하는 모든 업종으로 확장하고,
  `realtime_parking`/`realtime_subway`/`realtime_bus`/`realtime_event`를 추가했습니다.
  기존 v2 원문은 `archive/question_type_rules__legacy-2.md`에 보관했습니다.
  평가: INFO 구조화 출력 단위 테스트, citydata 실응답 객체 검증, 프론트 빌드 및 질문별
  수동 점검을 완료한 뒤 승인 이력으로 승격합니다.

## 승인 이력

| 기준선 | 날짜 | 커밋 | 슬롯 | 변경 내용 | 변경 이유 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| legacy-1.0.12 | 2026-08-12 | `0c0a548` | `info.answer` | 검증된 INFO fields를 자연어 답변으로 변환하는 슬롯 신설 | 관광 데이터 결과를 사용자 답변으로 조립 | 승인됨 |

`Draft`는 승인 기준선이 아니므로 별도 Markdown 스냅샷으로 보관하지 않습니다.
