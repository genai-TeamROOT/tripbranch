# RECOMMEND Prompt History

## 현재 활성 슬롯

| 슬롯 | 관리 버전 | 템플릿 | 공유 규칙 |
| --- | --- | --- | --- |
| recommend.extract | v1 | extract.md, location_rules.md, place_tag_rules.md | budget, weather, concentration, environment |
| recommend.summary | v1 | summary_instruction.md | persona, factuality |

## 승인 이력

| 기준선 | 날짜 | 커밋 | 슬롯·의존성 | 변경 내용 | 변경 이유 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| legacy-1.0.3 | 2026-08-06 | `0bfdcfc` | `recommend.extract` | RECOMMEND 추출에 실내외 환경 규칙 보강 | 위치 변경 뒤 environment 조건 소실 방지 | 승인됨 |
| legacy-1.0.5 | 2026-08-07 | `bfad75f` | `recommend.summary` | 추천 카드 요약 생성 슬롯 신설 | 카드 목록을 짧은 자연어 말풍선으로 소개 | 승인됨 |
| legacy-1.0.9 | 2026-08-10 | `86a9cd1` | `recommend.extract` | 위치 되묻기와 검색 중심점 유지 규칙 보강 | TP-67 후속 | 승인됨 |
| legacy-1.0.13 | 2026-08-18 | `585a045` | 공유 weather/concentration/environment | 비·혼잡·야외 허용 표현을 조건 완화로 분류 | 후보를 불필요하게 좁히거나 재정렬하는 문제 방지 | 승인됨 |

공유 규칙의 원문 이력은 [`_shared/HISTORY.md`](../_shared/HISTORY.md)에서 관리합니다.
