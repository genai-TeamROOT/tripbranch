# SCHEDULE Prompt History

## 현재 활성 슬롯

| 슬롯 | 관리 버전 | 템플릿 |
| --- | --- | --- |
| schedule.plan | v1.2 | plan.md |
| schedule.plan_context | v1.2 | plan_context.md |
| schedule.fill | v1.1 | fill.md |
| schedule.fill_context | v1.1 | fill_context.md |

## 승인 이력

| 기준선 | 날짜 | 커밋 | 슬롯 | 변경 내용 | 변경 이유 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| legacy-git-f640ec1 | 2026-08-07 | `f640ec1` | `schedule.plan`, `schedule.plan_context` | 일정 편성 프롬프트와 후보·거리 컨텍스트를 실제 Runtime에 연결 | INT-07 SCHEDULE 최초 실동작 | 승인됨 |
| legacy-1.0.7 | 2026-08-08 | `c30bb68` | Router 의존성 | SCHEDULE 되묻기 진행 상태를 Intent 분류에 반영 | 일정 답변이 MODIFY로 오분류되는 문제 방지 | 승인됨 |
| legacy-1.0.11 | 2026-08-12 | `16e3a9d` | `schedule.fill`, `schedule.fill_context` | 특정 순번·이름만 바꾸는 부분 재편성 슬롯 신설 | 전체 일정을 다시 만드는 제한 해소 | 승인됨 |
| legacy-git-f4d0526 | 2026-08-12 | `f4d0526` | `schedule.plan` | 짧은 활동 시간에 3~5개 장소를 강제하지 않도록 보정 | 비현실적 일정 방지 | 승인됨 |
| legacy-git-d2e516d | 2026-08-18 | `d2e516d` | `schedule.plan` | 운영시간·폐점 스탑 경고와 긴 일정 과소 채움 규칙 보정 | 닫힌 장소·짧은 일정 문제 방지 | 승인됨 |
| 2026-08-26-co-visited | 2026-08-26 | (커밋 예정) | `schedule.plan`, `schedule.plan_context`, `schedule.fill`, `schedule.fill_context` | place_associations(D-088) 기반 "함께 방문된 이력" 섹션·활용 규칙 추가(opt-in, co_visited_fetcher 미주입 시 항상 "(없음)"). 부분 재편성(fill) 경로는 pinned_items+candidates 전체 place_id로 조회 | SCHEDULE에 실제 co-visit 데이터를 참고 신호로 반영(전체 편성·부분 재편성 둘 다) | 검토 중 |
| 2026-08-31-must-include | 2026-08-31 | (커밋 예정) | `schedule.plan`, `schedule.plan_context` | 보관함에 담은 장소를 반드시 포함하라는 규칙과 `[반드시 포함]` 섹션 추가(비어 있으면 "(없음)"으로 항상 같은 구조로 렌더링). 개수 상한 안에서 이 장소를 먼저 배치하고 남는 자리를 다른 후보로 채우도록 지시 | SCHEDULE-12 — 후보 풀에 넣는 것만으로는 채점 순위에서 밀려 빠진다. 프롬프트 지시는 부탁이고 `planner.plan_schedule()`의 하드 검증이 계약이다(SCHEDULE-07과 같은 철학) | 검토 중 |
