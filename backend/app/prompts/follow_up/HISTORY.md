# 후속 질문 제안 Prompt History

## 현재 활성 슬롯

| 슬롯 | 관리 버전 | 템플릿 | 공유 규칙 |
| --- | --- | --- | --- |
| follow_up.suggest | 1.0.0 | suggest_instruction.md, capability_rules.md | persona |

## 승인 이력

| 기준선 | 날짜 | 커밋 | 슬롯 | 변경 내용 | 변경 이유 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| 1.0.0 | 2026-08-27 | `1d3142e` | `follow_up.suggest` | 한 턴이 끝난 뒤 다음 발화 후보를 만드는 슬롯 신설. 서비스가 실제로 처리할 수 있는 요청 목록(`capability_rules.md`)을 함께 싣는다 | 답변 뒤에 이어서 물을 만한 질문을 버튼으로 제안하는 기능 도입(D-102) | 승인됨 |

인텐트 폴더가 아닙니다 — 인텐트 하나에 속하지 않고 어떤 인텐트로 끝난 턴이든 그 뒤에 한 번
도는 슬롯이라 `meta.yaml`에 `intent` 키가 없습니다(`synthetic_review/`와 같은 형태).

`capability_rules.md`가 이 슬롯의 핵심입니다. 모델은 여기 적힌 목록만 보고 무엇을 제안할 수
있는지 판단하므로, **서비스에 기능이 늘거나 빠지면 이 파일을 함께 고쳐야 합니다.** 고치지
않으면 없는 기능을 권하는 버튼이 생기고, 누른 사용자는 OUT_OF_SCOPE 답변을 받습니다.

개수·길이·중복·직전 발화 반복은 프롬프트에도 적혀 있지만 실제 계약은
[`follow_up_suggester.py`](../../services/runtime/follow_up_suggester.py)의 코드 검사입니다.
이 슬롯의 문구를 손볼 때 상한을 바꾸려면 그쪽 상수(`MAX_SUGGESTIONS`, `MAX_LABEL_LENGTH`)를
함께 봅니다 — 지침에만 적으면 화면에 반영되지 않습니다.
