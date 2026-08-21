# COMPARE Prompt History

## 현재 활성 슬롯

| 슬롯 | 관리 버전 | 템플릿 | 공유 규칙 |
| --- | --- | --- | --- |
| compare.extract | 2.0.0 | extract.md, target_rules.md, criteria_rules.md | shown_place_list |
| compare.summary | 2.0.0 | summary_instruction.md | persona, factuality |

## 승인 이력

| 기준선 | 날짜 | 커밋 | 슬롯 | 변경 내용 | 변경 이유 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| legacy-1.0.10 | 2026-08-11 | `6904af7` | `compare.summary` | 검증된 비교 사실을 3~6줄 답변으로 만드는 슬롯 신설 | COMPARE가 준비 중 안내로 끝나던 상태 해소 | 승인됨 |
| legacy-git-bea1e86 | 2026-08-11 | `bea1e86` | `compare.summary` | 거리·운영시간 표기를 도보 시간·시간 단위로 바꾸고 여행 안내 문체 보정 | 기계적인 수치 나열 대신 선택 가능한 비교 제공 | 승인됨 |
| legacy-git-52ec573 | 2026-08-13 | `52ec573` | `compare.extract` | 노출된 장소 이름으로도 비교 대상을 식별 | 이름 지목 시 엉뚱한 장소가 비교에 섞이는 문제 방지 | 승인됨 |
| 2.0.0 | 2026-08-21 | (이 커밋) | `compare.extract`(criteria_rules.md), `compare.summary`(summary_instruction.md) | `distance` 기준을 폐지하고 `travel_time`으로 합친다 — "가까워?", "거리 차이?", "빨리 갈까?", "얼마나 걸려?"를 모두 travel_time으로 판별해, 직선거리 하나 대신 실측 거리 + 도보·자동차·대중교통 세 수단 소요시간을 함께 답한다(criteria enum 값이 빠지는 하위 호환 깨짐이라 MAJOR) | TP-105(네이버 자동차 실측)·TP-106(카카오 대중교통 실측) 연결 후, "이동이 얼마나 용이한지"를 직선거리 하나로 답하는 것보다 실제 경로·수단별 소요시간을 함께 보여주는 쪽이 실제 질문 의도에 맞다고 판단. "덜 막힐까?"(실시간 도로 정체)는 ROAD_TRAFFIC_STTS 연동 전이라 이번 범위에서 제외 — 우선 정체 미반영 실측으로 답하고 프롬프트에도 그렇게 명시 | Draft — 단위 테스트·pytest 회귀·실 서버 확인 진행 중 |

## 실행 가능한 과거 기준선

- `compare-summary@legacy-1.0.10`: `6904af7` 당시의 비교 요약과 페르소나 조합입니다.
  [compare_summary__legacy-1.0.10.md](archive/compare_summary__legacy-1.0.10.md)는 설명·코드
  블록 없이 그대로 모델에 전달할 수 있는 원문이며, 필요한 공유 페르소나는
  [`_shared` 기준선](../_shared/archive/persona__legacy-1.0.5.md)과 함께
  [variants.json](archive/variants.json)에서 묶습니다.
