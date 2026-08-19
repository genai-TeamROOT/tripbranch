# COMPARE Prompt History

## 현재 활성 슬롯

| 슬롯 | 관리 버전 | 템플릿 | 공유 규칙 |
| --- | --- | --- | --- |
| compare.extract | v1 | extract.md, target_rules.md, criteria_rules.md | shown_place_list |
| compare.summary | v1 | summary_instruction.md | persona, factuality |

## 승인 이력

| 기준선 | 날짜 | 커밋 | 슬롯 | 변경 내용 | 변경 이유 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| legacy-1.0.10 | 2026-08-11 | `6904af7` | `compare.summary` | 검증된 비교 사실을 3~6줄 답변으로 만드는 슬롯 신설 | COMPARE가 준비 중 안내로 끝나던 상태 해소 | 승인됨 |
| legacy-git-bea1e86 | 2026-08-11 | `bea1e86` | `compare.summary` | 거리·운영시간 표기를 도보 시간·시간 단위로 바꾸고 여행 안내 문체 보정 | 기계적인 수치 나열 대신 선택 가능한 비교 제공 | 승인됨 |
| legacy-git-52ec573 | 2026-08-13 | `52ec573` | `compare.extract` | 노출된 장소 이름으로도 비교 대상을 식별 | 이름 지목 시 엉뚱한 장소가 비교에 섞이는 문제 방지 | 승인됨 |

## 실행 가능한 과거 기준선

- `compare-summary@legacy-1.0.10`: `6904af7` 당시의 비교 요약과 페르소나 조합입니다.
  [compare_summary__legacy-1.0.10.md](archive/compare_summary__legacy-1.0.10.md)는 설명·코드
  블록 없이 그대로 모델에 전달할 수 있는 원문이며, 필요한 공유 페르소나는
  [`_shared` 기준선](../_shared/archive/persona__legacy-1.0.5.md)과 함께
  [variants.json](archive/variants.json)에서 묶습니다.
