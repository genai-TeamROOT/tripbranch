# MODIFY Prompt History

## 현재 활성 슬롯

| 슬롯 | 관리 버전 | 템플릿 | 공유 규칙 |
| --- | --- | --- | --- |
| modify.extract | v1 | extract.md, type_rules.md, target_rules.md, relative_expression_rules.md, field_merge_rules.md | budget, weather, concentration, environment, shown_place_list |

## 승인 이력

| 기준선 | 날짜 | 커밋 | 슬롯·의존성 | 변경 내용 | 변경 이유 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| legacy-1.0.4 | 2026-08-07 | `d1701a4` | `modify.extract` | `concentration_intent` 판별 규칙 추가 | RECOMMEND와 MODIFY의 혼잡도 의도 판별 불일치 해소 | 승인됨 |
| legacy-1.0.9 | 2026-08-10 | `86a9cd1` | `modify.extract` | 위치 되묻기 답변을 `search_center` 변경으로 병합 | 기존 조건을 유지한 재추천 보장 | 승인됨 |
| legacy-1.0.12 | 2026-08-12 | `0c0a548` | `modify.extract` | 바뀐 필드만 채우는 병합 규칙과 되묻기 결정 경로 보강 | 누적 조건 덮어쓰기 방지 | 승인됨 |
| legacy-1.0.13 | 2026-08-18 | `585a045` | 공유 weather/concentration/environment | 허용 표현을 `IGNORE`·`any` 조건 완화로 해석 | 날씨·혼잡도 조건을 반대로 강화하는 문제 방지 | 승인됨 |

공유 규칙의 원문 이력은 [`_shared/HISTORY.md`](../_shared/HISTORY.md)에서 관리합니다.
