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
