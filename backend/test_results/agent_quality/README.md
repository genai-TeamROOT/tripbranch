# Agent 품질 골드셋

`evaluation_dev.csv`은 프롬프트·조건 병합을 수정하면서 반복 실행하는 개발용 35건이다.
`evaluation_final.csv`은 변경 직전에만 실행하는 최종 평가용 15건이다. 최종셋 결과를 보고
프롬프트를 다시 조정하면 평가 과적합이 되므로, 개발 중에는 개발셋만 사용한다.

```bash
cd backend
.venv/bin/python -m scripts.evaluate_agent_quality --split dev
.venv/bin/python -m scripts.evaluate_agent_quality --split final
```

매 실행 결과는 아래처럼 날짜·시각·평가셋·케이스 수를 알 수 있는 폴더에 저장된다.

```text
runs/2026-08-14_1551_dev_35cases_2d4e276eed53/
```

`history.csv`에는 실행 요약이 누적된다. 동일 split·동일 골드셋 해시의 직전 실행과만
Macro F1·조건 정확도·전체 통과율을 비교한다.

## 실행 결과 읽는 법

| 파일 | 용도 | 읽는 방법 |
| --- | --- | --- |
| `report.md` | 사람이 읽는 실행 보고서 | 가장 먼저 열어 핵심 점수·불일치 사례를 확인한다. |
| `summary.json` | 기계 처리용 종합 지표 | 장표·대시보드에 수치를 가져갈 때 사용한다. |
| `case_results.csv` | 케이스별 기대/실제 비교 | 어떤 문장과 필드가 실패했는지 확인한다. |
| `intent_metrics.csv` | Intent별 P/R/F1 | 특정 Intent의 정밀도·재현율 저하를 확인한다. |
| `confusion_matrix.csv` | 기대 Intent × 실제 Intent | 행은 기대값, 열은 실제값이다. 대각선 밖 숫자가 혼동 사례다. |
| `history.csv` | 실행 요약 누적 | 같은 골드셋의 전후 Macro F1·조건 정확도·지연시간을 비교한다. |

예를 들어 `RECOMMEND` 행의 `MODIFY` 열이 3이면, 실제 RECOMMEND여야 한 발화 3건을
MODIFY로 오분류했다는 의미다. `report.md`에는 이 표와 함께 해당 실행의 실패 케이스가
사람이 읽을 수 있게 정리된다.

평가셋의 `expected_final_conditions`에는 그 케이스에서 반드시 확인할 필드만 넣는다.
비어 있는 객체(`{}`)는 Intent만 평가한다. 라벨은 모델이 만든 값이 아니라 팀 합의로
검토해야 하는 기대 동작이다.

## `expected_turn_subtypes` — 인텐트 "안"의 축 (2026-09-14 신설)

턴 하나당 객체 하나인 JSON 배열이다. `{}`는 그 턴에 서브타입을 주장하지 않는다는 뜻이고,
길이는 `turns`·`expected_turn_intents`와 같아야 한다.

| 키 | 해당 Intent | 값 |
| --- | --- | --- |
| `question_type` | INFO | `QuestionType` 16종 |
| `topic` | GENERAL | `GeneralTopic` 8종 |
| `category` | OUT_OF_SCOPE | `OutOfScopeCategory` 4종 |
| `modify_type` | MODIFY | `ModifyType` 3종 |
| `criteria` | COMPARE | `CompareCriteria` 3종 |
| `interaction_mode` · `situation_kind` | 모든 Intent와 직교 | `InteractionMode` · `SituationKind` |

**아직 채점에 연결되어 있지 않다.** `evaluate_agent_quality.py`는 Intent와 조건 필드
둘만 채점한다. 이 칸은 라벨을 먼저 모아 두려고 만든 것이고, 무엇을 어떻게 점수로 낼지는
팀 협의 뒤에 붙인다. `dataset_digest`에도 안 들어가므로 이 칸만 고쳐도 digest는 그대로다.

**다만 커버리지는 테스트가 지킨다.** `tests/test_evaluate_agent_quality.py`가 위 축의
**모든 열거값**과 `UserConditions`의 **모든 필드**가 최소 1건씩 있는지 검사한다. 열거값을
새로 추가하면 그 테스트가 먼저 깨져서 골드셋에 케이스를 넣게 만든다 — `review_opinion`이
develop에서 들어온 뒤 한동안 골드셋에 없었던 일(2026-09-14에 메움)을 다시 겪지 않으려는
장치다.

**기존 35케이스는 note가 서브타입을 이미 적어 둔 8건만 채웠다.** 나머지는 추측이 되므로
비워 뒀다 — 채우는 것은 라벨 소유자의 몫이다.

## 케이스를 몇 건씩 둘 것인가

**"모든 값에 5건"이 아니다.** 집계 방식이 축마다 달라서 필요한 건수도 다르다.

| 축 | 최소 | 왜 |
| --- | --- | --- |
| **Intent (7종)** | **5** | `macro_f1`이 **인텐트별 F1의 평균**이다. n=1이면 한 건만 뒤집혀도 그 클래스 F1이 1.0 → 0이 되고 Macro F1이 14%p 움직인다. 모델을 비교하려면 여기가 바닥이다 |
| 조건 필드 (17종) | 2~3 | `condition_field_accuracy`는 전체 필드 검사의 **미시 평균**이라 필드별 건수가 평균을 흔들지 않는다. 건수는 "그 필드가 깨진 걸 알아볼 수 있는가"의 문제다 |
| 서브타입 축 | **1** | 점수가 아니라 **커버리지 체크리스트**로 읽는다. 평균에 넣으면 n=1 문제가 그대로 옮겨붙는다 |

그래서 인텐트 턴 수는 대개 **그 인텐트가 가진 서브타입 수가 정한다** — 한 턴은
`question_type`을 하나만 가지므로 16종을 덮으려면 INFO 턴이 그만큼 필요하다.

## 읽을 때 갈라야 하는 것 둘

**① 실시간 API 의존 케이스.** `realtime_*` 계열(DEV-046·047·049)과 `operating_hours`는
답이 외부 API의 그때 상태에 달려 있다. **Intent와 question_type 판정까지만 보고 답변
내용은 채점에서 뺀다.** 영업시간 케이스 때문에 골드셋은 주간에 돌린다.

**①-1 채점에 무게를 줄 수 없는 필드.** `budget`은 지금 후보 필터링·스코어링·검색
어디에도 안 들어간다 — `gemini_prompts._stated_conditions_line()`이 답변 생성 프롬프트에
`"예산 free"` 같은 **문자열로 끼워 넣는 것이 유일한 소비처**다. 틀려도 추천 결과는 바뀌지
않고 요약 문장의 말투만 달라진다(DEV-073). 조건 정확도에 같은 무게로 섞어 읽지 않는다.
필터로 승격되면 그때 무게가 생긴다.

**② 경계 케이스.** `note`에 "경계"라고 적힌 케이스(DEV-041·044·048·054·056·059·069·070 등)는
`router/boundary_cases.md`가 정한 판정 경계다. **모델 간 차이가 가장 크게 벌어지는
자리라 모델 비교에는 제일 유용하지만, 일반 케이스와 한 숫자로 섞지 않는다** — 경계는
원래 점수가 낮은 게 정상이라 평균이 모든 걸 가린다.

## 반복 횟수

**전수 1회 → 판정이 갈린 케이스만 5회.** `intent_experiments_2026-08.md` §2가 정한
설계이고, 전수 repeat-3은 `model_tier_2026-09-08/1단계_분류.md` §4가 낭비로 기록했다.
설정이 같은 실행끼리 비교하면 `condition_field_accuracy`는 소수점까지 재현된다
(08-25 세 실행 0.920/0.920/0.920) — 흔들리는 것은 `case_pass_rate`이고 1~2건 수준이다.
