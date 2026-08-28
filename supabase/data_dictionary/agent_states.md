# agent_states 데이터 딕셔너리

## 개요

`public.agent_states`는 대화 세션(`session_id`) 1개의 현재 상태를 담는 테이블입니다. Package B(Agent State/Memory) 소유이며, `session_id`가 PK입니다. 행 단위 부분 갱신이 아니라 애플리케이션이 상태를 통째로 읽고(`get_state`) 통째로 다시 쓰는(`save_state`) 방식으로 갱신됩니다. 클라이언트(anon/authenticated)는 직접 접근할 수 없고 FastAPI 서버(secret key)를 통해서만 사용합니다.

`user_conditions`/`api_context`는 여러 하위 값을 한 번에 담는 JSONB 객체 컬럼입니다 — 하위 필드는 이 문서의 "user_conditions 하위 필드"/"api_context 하위 필드" 표를 참고하세요.

| 필드 | 타입 | NULL 허용 | 정의 | 값 예시 | 활용 예시 |
| --- | --- | --- | --- | --- | --- |
| `session_id` | text | 아니오 | 세션 식별자. PK입니다. 생성 시각을 앞에 둬 문자열 정렬만으로 시간순이 됩니다. | `sess_1755840000000a1b2c3d4e5f6a` | 이 세션의 조건·이력·실행기록·피드백을 전부 조회하는 조인 키로 사용합니다. |
| `user_id` | uuid | 예 | 검증된 게스트/회원 신원(`Principal.user_id`)이 연결되면 채워집니다. 값이 비어 있을 때만 채우고, 이미 있으면 절대 덮어쓰지 않습니다(D-063 결정 3). `auth.users`로 FK를 걸지 않습니다(D-063 결정 4 — 익명 계정 정리와 충돌 방지). | `3fa85f64-5717-4562-b3fc-2c963f66afa6` | 세션 소유권 검증(`session.verify_ownership()`, D-073), "이 사용자의 세션 목록" 조회에 사용합니다. |
| `user_conditions` | jsonb object | 아니오(기본값 `{}`) | 사용자 발화에서 추출된 조건 15개+를 담는 객체입니다. B는 각 하위 값의 허용 범위를 검증하지 않습니다(Package A 책임). | `{"current_location":"경복궁","transport":"walk"}` | 다음 추천 요청 시 조건을 그대로 이어받아 재사용합니다. |
| `api_context` | jsonb object | 아니오(기본값 `{}`) | 외부 API로 확보한 GPS·날씨 데이터를 담는 객체입니다. `condition_version` 증가 판정에서 제외됩니다(조건 변경이 아니라 배경 데이터 갱신이라서). | `{"gps_location":"37.5,127.0","gps_location_updated_at":"2026-08-25T09:00:00+09:00"}` | 위치 재확인 UX(30분 경과 판정), 날씨 조건 판정에 사용합니다. |
| `condition_version` | integer | 아니오(기본값 `0`) | 조건이 몇 번 바뀌었는지 세는 카운터입니다. 0 이상이어야 합니다. | `4` | 클라이언트가 마지막으로 본 버전과 비교해 조건이 바뀐 걸 감지합니다. |
| `last_run_id` | text | 예 | 이 세션에서 마지막으로 처리한 요청의 run_id입니다. | `run_1755840005000b2c3d4e5f6a7b` | 직전 응답을 다시 참조하거나 재조정할 때 기준으로 씁니다. |
| `last_intent` | text | 예 | 마지막으로 분류된 인텐트입니다(예: `RECOMMEND`, `SCHEDULE`). SCHEDULE 재조정 시 relabel 직후 `set_last_intent()`로 재동기화됩니다. | `RECOMMEND` | 다음 발화가 이전 인텐트의 연속인지 판단하는 데 참고합니다. |
| `pending_clarification` | text | 예 | 직전 턴이 되묻기로 끝났다면 그 사유 코드입니다(예: `location_required`). B는 판단하지 않고 A가 준 값을 보관만 합니다. | `location_required` | 사용자의 다음 답변을 "새 요청"이 아니라 "되묻기 답변"으로 처리할지 판단합니다. |
| `pending_info_context` | jsonb object | 예 | INFO의 장소 후보 되묻기(`pending_clarification = "place_ambiguous"`)에서 원래 질문의 문맥을 보관합니다. `question_type`, `place_context`는 필수이고 `specific_question`, `visit_time`은 선택입니다. Package B는 값을 해석하지 않고 저장만 하며, 허용값 정의는 Package A의 책임입니다(D-100). | `{"question_type":"parking","place_context":"explicit","specific_question":"종각 주차장 정보"}` | 사용자가 후보 버튼을 누르면 장소명만으로 다시 분류하지 않고, 원래의 주차·혼잡도 등 질문 유형을 그대로 복원해 이어서 조회합니다. |
| `ignore_operating_hours_until` | timestamptz | 예 | "운영 중이 아닌 곳도 볼게요"를 선택하면, 이 시각까지는 매 턴 다시 묻지 않고 폐점 후보도 포함합니다. | `2026-08-25T15:00:00+09:00` | 하드 필터(영업시간)를 일시적으로 완화할지 판단합니다. |
| `status` | text | 아니오(기본값 `'active'`) | 세션 상태입니다. `active` 또는 `expired`만 허용됩니다. 만료 판정은 조회 시점에만 일어나는 lazy 방식이라, 실제로 30분간 활동이 없어도 이 컬럼 값이 즉시 `expired`로 바뀌진 않습니다. | `active` | 만료된 세션에 새 요청이 오면 오류 없이 새 세션을 자동 발급하도록 분기합니다. |
| `created_at` | timestamptz | 아니오(기본값 `now()`) | 세션이 처음 생성된 시각입니다. | `2026-08-20T09:00:00+09:00` | 세션 생애주기 분석, 만료 정리 스크립트의 기준일 계산 등에 사용합니다. |
| `updated_at` | timestamptz | 아니오(기본값 `now()`) | 조건이 바뀌는 등 상태가 갱신된 시각입니다. GPS 갱신처럼 `last_active_at`만 건드리고 이 컬럼은 안 건드리는 경우도 있어, 자동 갱신 트리거를 달지 않고 애플리케이션이 필드별로 다르게 관리합니다. | `2026-08-25T09:05:00+09:00` | 조건이 실제로 바뀐 마지막 시점을 확인합니다. |
| `last_active_at` | timestamptz | 아니오(기본값 `now()`) | 이 세션이 마지막으로 활동한 시각입니다(조건 변경뿐 아니라 GPS 갱신 등도 포함). 30분 세션 TTL 판정과 만료 세션 정리 스크립트(`cleanup_expired_sessions.py`, D-074, 30일 기준)의 기준 컬럼입니다. | `2026-08-25T09:10:00+09:00` | 세션 만료 여부 판정, 만료 세션 정리 대상 선별에 사용합니다. |

### user_conditions 하위 필드

| 필드 | 타입 | 정의 |
| --- | --- | --- |
| `current_location` | string \| null | 현재 위치(지명 또는 좌표 문자열). |
| `search_center` | string \| null | 검색 기준점. 조사("~에서/까지")로 출발점이 명시된 발화만 채워지며, 그 외에는 null로 두어 사용자 위치 기준 거리 계산이 적용되게 합니다(D-067, D-071). |
| `place_types` | string[] | 장소 유형 목록(예: `["카페","공원"]`). 기본값 빈 배열. |
| `place_tags` | string[] | 장소 태그 목록. 기본값 빈 배열. |
| `weather` | string \| null | 사용자가 언급한 날씨 조건. |
| `weather_intent` | string \| null | 날씨에 대한 태도(예: 더위를 피하고 싶다). |
| `concentration_intent` | string \| null | 혼잡도 선호. |
| `transport` | string \| null | 이동수단. |
| `max_travel_time` | int \| null | 이동 가능 시간(분). |
| `time_available` | int \| null | 머무를 수 있는 시간(분). |
| `environment` | string \| null | 실내/실외 등 환경 선호. |
| `companion` | string \| null | 동행 정보. |
| `budget` | string \| null | 예산. |
| `exclude_tags` | string[] | 제외할 태그. 추가/삭제만 허용되고 통째로 교체는 안 됩니다. 기본값 빈 배열. |
| `special_requirements` | string[] | 기타 특수 요구사항. 기본값 빈 배열. |
| `taste_query` | string \| null | 취향 근거 검색용 자유 텍스트 질의(Package D의 RAG 파이프라인 입력). |
| `travel_origin` | string \| null | 이동시간 기준점 판정. `user_location` 또는 `search_center` 중 하나(B는 값을 검증하지 않음, D-071). |

### api_context 하위 필드

| 필드 | 타입 | 정의 |
| --- | --- | --- |
| `gps_location` | string \| null | 마지막으로 확보한 GPS 좌표 문자열. |
| `api_weather` | string \| null | 외부 날씨 API로 확보한 원문 값. |
| `gps_location_updated_at` | datetime \| null | GPS 값이 갱신된 시각(기술적 TTL 판정용, 1시간). |
| `api_weather_updated_at` | datetime \| null | 날씨 값이 갱신된 시각. |
| `gps_location_confirmed_at` | datetime \| null | 사용자가 "현재 위치 다시 가져오기"로 실제 재확인한 시각(PR #188). `gps_location_updated_at`과 별개 — "N분 전 위치로 계속"을 선택하면 이 값은 갱신되지 않습니다. 기존 세션은 null(최초 재확인 대상). |

## 사용 시 유의사항

- `user_conditions`/`api_context`는 애플리케이션이 통째로 읽고 통째로 다시 쓰는 JSONB 객체입니다 — 특정 하위 키만 부분 갱신(`jsonb_set` 등)하는 별도 경로는 없습니다.
- `pending_info_context`는 `pending_clarification = "place_ambiguous"`일 때만 유효합니다. 다른 되묻기 코드로 바뀌거나 되묻기가 해제되면 애플리케이션이 함께 `NULL`로 비웁니다. 이 값만 남아 있다고 해서 활성 INFO 되묻기 상태라는 뜻은 아닙니다.
- `status`가 `active`라고 해서 세션이 진짜로 살아있다는 보장은 없습니다 — 만료 판정이 조회 시점에만 일어나는 lazy 방식이라, `last_active_at` 기준 30분이 지났는데도 이 컬럼 값은 그대로 `active`로 남아 있을 수 있습니다.
- `user_id`가 비어 있는 것은 정상입니다 — 게스트가 아직 신원 발급을 안 받았거나, `Authorization` 헤더 없이 온 요청일 수 있습니다.
- 30일 이상 미사용 세션은 `scripts/cleanup_expired_sessions.py`가 `condition_change_logs`/`trace_records`/`recommendation_histories`를 먼저 지우고 마지막으로 이 테이블 행을 지웁니다(D-074) — 삭제된 `session_id`로의 조회는 "세션 없음"으로 처리됩니다.
