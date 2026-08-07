# INFO question_type 확장 — A 배선 인수인계

| 항목 | 값 |
|---|---|
| 작성 | 2026-08-07 |
| 보내는 쪽 | C (Tool Intelligence·External Context) |
| 받는 쪽 | A (Request Intelligence·Agent Runtime) |
| 관련 결정 | D-054 |
| 관련 문서 | `docs/design/int-02-info.md`, `docs/design/agent-response-generation.md` §6 |

## 요약

INFO의 `question_type` 8종 중 `concentration` 하나만 실제로 동작하고 있었다. C가
나머지를 처리할 수 있도록 계약과 서비스를 확장했다. **A 배선 3곳이 남아 있어 지금은
사용자에게 여전히 "아직 준비 중이에요"가 나간다.**

C 변경분은 기존 동작을 바꾸지 않는다 — `question_type` 기본값이 `concentration`이라
현재 A 호출부는 그대로 동작한다(전체 회귀 1231 passed).

## C가 지금 돌려주는 것

`InfoContextResponse.result`가 union이 됐다.

```python
result: ConcentrationInfoResult | PlaceInfoResult | None
```

- `question_type == "concentration"` → `ConcentrationInfoResult` (기존과 동일, 무변경)
- 그 외 → `PlaceInfoResult` (신규)

```python
class PlaceInfoResult(BaseModel):
    status: Literal["success", "no_data", "unavailable"]
    question_type: InfoQuestionType
    requested_place_name: str | None    # 사용자가 말한 이름
    resolved_place_name: str | None     # 해석된 정식 명칭 ("종묘 [유네스코 세계유산]")
    place_id: str | None
    fields: dict[str, str]              # 아래 표의 키만 들어온다
    error: ContextError | None
```

`fields`는 값이 있는 키만 담는다. 빈 문자열이나 "정보 없음" 같은 문구를 C가 지어내지
않는다. `fields`가 비면 `status="no_data"`이고, 이때도 `resolved_place_name`은 채워
보낸다("경복궁의 주차 정보는 없어요"처럼 장소를 짚어 안내할 수 있게).

### question_type별 fields 키

| question_type | fields 키 | 비고 |
|---|---|---|
| `operating_hours` | `operating_hours`, `rest_date` | provider 정규화 값 |
| `fee` | `fee` | |
| `parking` | `parking`, `parking_fee` | |
| `facility` | `baby_carriage`, `pet`, `credit_card`, `restroom` | 있는 것만 |
| `location_info` | `address` | 외부 API 호출 없음 |
| `general_info` | `overview`, `homepage` | HTML 태그 제거·공백 정리 완료 |
| `event` | — | `status="unsupported"`, `error.code="question_type_unsupported"` |
| `concentration` | — | 기존 `ConcentrationInfoResult` 경로 |

`general_info`의 `overview`는 TourAPI 원문이라 길 수 있다(수백 자). 요약이 필요하면
A 쪽 판단이다 — C는 정제만 하고 자르지 않는다.

## A가 해야 할 배선 3곳

### 1. `services/runtime/info_context_transform.py`

`to_info_context_request()`가 `question_type`을 안 넘긴다(계약이 concentration
고정이던 시절 그대로). 두 필드를 추가한다.

```python
return InfoContextRequest(
    request_id=request_id,
    place_name=info.place_name,
    place_context=info.place_context.value,
    question_type=info.question_type.value,   # 추가
    specific_question=info.specific_question,  # 추가
    visit_time=info.visit_time,
)
```

함수 docstring의 "question_type이 concentration이 아닌 InfoPayload로 호출하지
않는다" 전제도 함께 지워야 한다.

`app.schemas.QuestionType`과 `InfoQuestionType`은 값이 일치한다(8종 동일).

### 2. `services/runtime/agent_runtime.py`

INFO 게이트가 `CONCENTRATION`으로 한정돼 있다. 그 조건만 빼면 INFO 전체가 C를 탄다.

```python
if (
    llm_output.status is OutputStatus.COMPLETE
    and llm_output.intent is Intent.INFO
    and llm_output.info is not None
    # and llm_output.info.question_type is QuestionType.CONCENTRATION  ← 제거
    and hasattr(tool_provider, "fetch_info_context")
):
```

`hasattr` 방어는 그대로 두면 된다.

### 3. `services/runtime/response_composer.py`

여기가 배선만으로 안 끝나는 유일한 곳이다. `compose_info_concentration_message()`는
`concentration_label`/`forecast_date`/`is_proxy`를 직접 읽어 문장을 만든다. 상세
응답을 그대로 넣으면 그 필드들이 전부 `None`이라 `_TOOL_UNAVAILABLE_MESSAGE`로
떨어진다.

`result` 타입으로 분기하는 진입점을 앞에 두는 형태를 제안한다.

```python
if isinstance(response.result, PlaceInfoResult):
    return compose_place_info_message(response)   # 신규
return compose_info_concentration_message(response)  # 기존, 무변경
```

C 쪽 제안은 **고정 템플릿**이다. 집중률을 고정 템플릿으로 둔 이유(정확성이 걸린
문제라 LLM 스타일링을 넣지 않는다)가 요금·운영시간·주차에도 그대로 적용된다.
`general_info`처럼 원문이 긴 것만 LLM 요약을 붙일지는 A 판단 영역이라 C가 정하지
않았다.

`status`별로 필요한 문구:

| status | 상황 |
|---|---|
| `success` | `fields`를 문장으로 |
| `no_data` | 장소는 찾았지만 그 질문에 답할 값이 없음 |
| `unsupported` | `event` |
| `unavailable` | TourAPI 장애 / Tool 미배선 |
| `needs_clarification` | 장소명 없음·모호 (기존 `_CLARIFICATION_TEMPLATES` 재사용 가능) |

마지막 줄의 `_NOT_YET_SUPPORTED_MESSAGE`는 COMPARE용으로 남겨둔다.

## 확인 방법

C 단독 회귀는 끝나 있다.

```bash
cd backend
python -m pytest tests/agent_context/test_info_field_rules.py tests/agent_context/test_info_place_detail.py -v
python -m pytest -q          # 1231 passed / 22 skipped
python -m ruff check app tests
```

A 배선 후에는 실제 TourAPI로 한 번 확인하는 게 좋다 — Fake는 `raw_intro`를 흉내 낸
값이라 실 응답의 유형별 키 누락까지는 잡지 못한다.

```bash
RUN_REAL_PROVIDER_TESTS=true python -m pytest -m smoke -v -s
```

## 알려진 한계

- `event`는 `searchFestival2` 연동이 없어 `unsupported`다.
- 상세 질의는 TourAPI를 직접 호출한다(D-054). INFO 응답에 외부 API 지연이 붙고
  TourAPI 일일 한도를 소비한다. `location_info`만 호출 없이 답한다
  (`operating_hours`도 호출한다 — 이유는 D-054 참고).
- `facility`의 `restroom`은 쇼핑(38) 유형에만 있는 키라 대부분의 장소에서 비어 있다.
