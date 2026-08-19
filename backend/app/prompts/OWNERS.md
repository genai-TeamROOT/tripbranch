# Prompt Library Ownership

| 영역 | 주 소유자 | 현재 역할 |
| --- | --- | --- |
| `router/`, `modify/`, `compare/`, `general/`, `out_of_scope/`, `_shared/` | A | 인텐트 경계, 대화 흐름, 공통 응답 규칙 |
| `recommend/` | D | 추천 조건·RAG/Scoring 연계 규칙 |
| `info/` | C | 관광 데이터·외부 API 기반 정보 질의 규칙 |
| `schedule/` | B | 일정 편성·부분 재편성 규칙 |

공유 규칙을 바꿀 때는 영향받는 모든 슬롯의 단일 턴 평가와
`backend/test_results/agent_quality/`의 다중 턴 회귀를 함께 확인합니다.
