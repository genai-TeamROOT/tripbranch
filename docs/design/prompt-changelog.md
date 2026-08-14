# 프롬프트 버전 히스토리 (PROMPT_VERSION Changelog)

## 사용 방법

`backend/app/providers/gemini_prompts.py`의 `PROMPT_VERSION`은 판별·추출 규칙에 영향을
주는 변경이 있을 때만 올린다(문구·주석만 바뀐 사소한 수정은 올리지 않는다 — 파일 상단
주석 참고). 이 문서는 그 버전들을 시간순으로 인덱싱해서, git log를 뒤지지 않고도
**"이 버전에서 무엇이 왜 바뀌었는지"**를 바로 찾을 수 있게 한다.

**PROMPT_VERSION을 올리는 커밋을 만들 때마다 아래 표에 한 줄을 추가한다.** 커밋 메시지의
"변경 이유" 섹션을 요약해서 넣으면 된다 — 새 항목 추가 비용은 몇 줄이면 충분하다.

관련 문서: 설계 결정 자체(왜 이런 규칙을 채택했는지)의 더 긴 논의는
[decision-log.md](../decision-log.md)에 D-번호로 남는 경우가 많다 — 이 표에서 해당
D-번호를 찾으면 더 깊은 배경을 볼 수 있다.

## 프롬프트 목록 (15개)

아래 번호는 표의 "프롬프트" 컬럼에서 그대로 참조한다.

**① 분류 · 추출 (인텐트/조건 해석)**

1. `build_intent_classification_instruction` — 7종 인텐트 분류
2. `build_recommend_extraction_instruction` — RECOMMEND 조건 추출
3. `build_modify_extraction_instruction` — MODIFY 조건 추출
4. `build_info_extraction_instruction` — INFO 질의(8종) 추출
5. `build_compare_extraction_instruction` — COMPARE 대상/기준 추출
6. `build_general_extraction_instruction` — GENERAL 주제 추출

**② 답변 문장 생성**

7. `build_general_answer_instruction` — GENERAL 답변 생성
8. `build_info_answer_instruction` — INFO 답변 생성
9. `build_recommendation_summary_instruction` — 추천 카드 요약 말풍선
10. `build_compare_summary_instruction` — COMPARE 비교 요약

**③ SCHEDULE(일정 편성) 전용**

11. `build_schedule_planning_instruction` — SCHEDULE 일정 편성
12. `format_schedule_planning_context` — SCHEDULE 편성 컨텍스트 포맷
13. `build_schedule_fill_instruction` — SCHEDULE 부분 재편성
14. `format_schedule_fill_context` — SCHEDULE 부분 재편성 컨텍스트 포맷

**④ 공통 유틸**

15. `format_validation_retry_note` — Validation Retry 재시도 안내 문구

## 버전 이력

| 버전 | 날짜 | 커밋 | 프롬프트 | 무엇을 바꿨나 | 왜 |
|---|---|---|---|---|---|
| 1.0.0 | 2026-08-05 | `9ef8295` | — | `PROMPT_VERSION` 상수를 최초 도입해 LLMOps 실행 기록에 연결 | 그 전까지는 프롬프트가 바뀌어도 실행 기록으로 버전을 구분할 방법이 없었음 |
| 1.0.1 | 2026-08-06 | `d476280` | 1 | 이전 추천이 있는 상태에서 위치만 제시하는 발화("광화문 근처에서" 등)를 MODIFY로 분류하도록 보강 | TP-67 — 위치 변경 발화가 판별 규칙에 안 걸려 분류가 흔들림 |
| 1.0.3 | 2026-08-06 | `0bfdcfc` | 1, 2 | 맥락 규칙에서 단독 지명("경복궁")을 제외하고 INFO로 유지, RECOMMEND 추출에 environment 규칙 추가 | D-053(TP-67 후속) — 단독 지명이 MODIFY로 잘못 재정렬되던 문제, environment 조건이 사라지던 문제 |
| 1.0.4 | 2026-08-07 | `d1701a4` | 3 | MODIFY 추출 프롬프트에 `concentration_intent` 규칙 추가 | RECOMMEND 프롬프트에만 있던 규칙이 MODIFY엔 없어 "좀 조용한 공원 가고싶어"가 SEEK로 잘못 추출됨 |
| 1.0.5 | 2026-08-07 | `bfad75f` | 1, 9(신설) | 트리비 페르소나 도입, `build_recommendation_summary_instruction` 신설(추천 카드 요약 말풍선) | "넌 누구야?" 정체성 질문 응답, 추천 카드를 자연어로 소개하는 말풍선 필요 |
| 1.0.7 | 2026-08-08 | `c30bb68` | 1 | SCHEDULE 되묻기 진행 여부를 classify_intent 컨텍스트에 명시 | D-059 — SCHEDULE 되묻기 답변이 MODIFY로 오분류되어 엉뚱한 장소 추천이 나감 |
| 1.0.9 | 2026-08-10 | `86a9cd1` | 1, 2, 3 | 위치 되묻기 직후 지명 답변을 MODIFY의 `search_center` 변경으로 연결, soft reset 후에도 기존 `search_center` 유지 | TP-67 후속 — 위치 응답 처리와 검색 중심 유지가 여전히 불안정했음 |
| 1.0.10 | 2026-08-11 | `6904af7` | 10(신설) | `build_compare_summary_instruction` 신설(COMPARE 비교 요약, 3~6줄 구조화 출력) | `ComparisonResult`를 문장으로 바꾸는 단계가 없어 COMPARE가 "준비 중" 안내만 하던 상태 |
| 1.0.11 | 2026-08-12 | `16e3a9d` | 13, 14(신설) | SCHEDULE 부분 재편성(REJECT_SPECIFIC) 프롬프트 신설 — 순번/이름 지목, 부분 재편성 | 기존엔 SCHEDULE 결과 일부만 마음에 안 들어도 전체(REJECT_ALL)를 다시 짜야 했음 |
| 1.0.12 | 2026-08-12 | `0c0a548` | 3, 8(신설) | MODIFY 필드 병합 규칙 조정, `build_info_answer_instruction` 신설(INFO 답변 생성) | 되묻기 결정적 해소 경로 추가와 함께 INFO 질의 유형 확장 반영 |

## 참고 — 버전 번호가 튀는 지점 (병렬 브랜치 병합)

아래 두 지점은 이 문서를 만들며 git log를 재구성하는 과정에서 발견한 것으로, **같은 베이스
버전에서 서로 다른 브랜치가 동시에 작업하다 병합되며 버전 번호가 건너뛴 사례**다. 문서화된
이유가 없다면 "왜 1.0.4가 아니라 1.0.6에서 시작하지?" 같은 질문이 인수인계 때마다 반복될
수 있어 기록해 둔다.

- **1.0.3 → 1.0.5 / 1.0.3 → 1.0.4**: `bfad75f`(페르소나·요약)와 `d1701a4`(concentration_intent)가
  같은 날(2026-08-07) 같은 베이스(1.0.3)에서 병렬로 작업됨. 병합 순서상 1.0.4는 최종
  히스토리에 남았지만 그 사이 1.0.6으로 이어지는 커밋은 이 파일의 diff 이력만으로는
  특정되지 않았다 — 필요 시 `git log --all -- backend/app/providers/gemini_prompts.py`로
  추가 확인 필요.
- **1.0.9 → 1.0.10 / 1.0.9 → 1.0.11**: `6904af7`(COMPARE 요약)과 `16e3a9d`(REJECT_SPECIFIC)가
  같은 베이스(1.0.9)에서 병렬로 작업된 뒤 병합됨.

이런 상황을 줄이려면, PROMPT_VERSION을 올리는 작업을 시작하기 전에 팀 채널에 "지금
X.Y.Z에서 작업 시작합니다"라고 짧게 공유하는 것만으로도 충돌을 미리 알아챌 수 있다.

## 현재 버전

`agent-interpret-prompts-1.0.12` (2026-08-12 `0c0a548` 기준 최신 — 이 문서 갱신 시점 이후
버전이 더 올랐을 수 있으니, 실제 값은 `backend/app/providers/gemini_prompts.py`의
`PROMPT_VERSION` 상수를 우선한다)
