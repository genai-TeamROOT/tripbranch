# TripBranch 의사결정 로그

## 사용 방법

이 문서는 구현에 영향을 주는 합의와 아직 결정되지 않은 항목을 기록합니다.

- `Accepted`: 현재 설계 원칙으로 채택
- `Implemented`: 코드에 반영됨
- `Proposed`: 제안 상태
- `TBD`: 결론 필요
- `Superseded`: 다른 결정으로 대체

날짜는 저장소 기록 또는 현재 작업일을 기준으로 합니다.

## 결정 목록

### D-001 — LLM은 Backend에서만 호출

- 상태: `Accepted`, 실제 LLM 연결은 미구현
- 결정: Frontend는 LLM Provider를 직접 호출하지 않고 FastAPI Backend만 호출한다.
- 이유: API 키 보호, 프롬프트·모델 교체의 캡슐화, 로깅과 오류 정책 일원화
- 후속: LLM Provider와 모델 선정 `TBD`

### D-002 — Interpret와 Recommendation 분리

- 상태: `Accepted`; 현재 API도 분리되어 있으나 실제 Interpret는 Stub
- 결정: Interpret는 자연어를 조건으로 추출하고 최종 장소 선택은 하지 않는다.
- 이유: 언어 해석과 결정적 추천 정책의 책임을 분리하고 외부 사실을 검증하기 위함

### D-003 — 내부 `RecommendationRequest` Builder 도입

- 상태: `Proposed`
- 결정: Interpret 결과를 추천기에 바로 전달하지 않고 검증, 정규화, 이전 상태 병합,
  외부 API 보완 후 내부 요청을 생성한다.
- 미결: 최종 필드, 출처/신뢰도 표현, 버전 정책 `TBD`

### D-004 — Provider와 Tool 분리

- 상태: Provider `Implemented`, Tool `TBD`
- 결정: Provider는 외부 통신, Tool은 추천 파이프라인의 업무 단위를 담당한다.
- 이유: Tool과 외부 엔드포인트의 1:1 결합을 피하고 Provider 교체 영향을 제한

### D-005 — Provider 독립 내부 모델 사용

- 상태: `Implemented`
- 결정: 외부 응답은 Provider/Mapper에서 `PlaceCandidate`, `PlaceDetails`,
  `GeocodeResult` 등으로 정규화한다.
- 이유: Provider별 필드 차이와 변경을 추천 로직에서 격리

### D-006 — 장소 기준 데이터는 TourAPI 사용

- 상태: `Accepted`, 주요 조회 `Implemented`
- 결정: 위치 기반 후보, 키워드 후보, 상세정보의 기준 데이터로 TourAPI를 사용한다.
- 현재: `locationBasedList2`, `searchKeyword2`, `detailCommon2`, `detailIntro2` 연결
- 미결: 데이터 누락 시 보완 Provider와 충돌 해결 정책 `TBD`

### D-007 — 특정 장소 조회는 정확 일치 우선

- 상태: `Implemented`
- 결정: `find_details_by_name()`은 키워드 결과에서 정규화된 이름이 정확히 일치하는
  후보만 상세조회하고 유사 결과를 임의 선택하지 않는다.
- 이유: 동명·유사 장소의 잘못된 운영정보를 반환하는 위험 방지

### D-008 — 추천은 하드 필터와 가중치 점수 조합

- 상태: `Accepted`; Scoring v1 엔진 `Implemented` (아직 API 라우트에는 미연결)
- 결정: 명시적 필수 조건은 하드 필터, 선호 조건은 가중치 점수로 처리한다.
- 현재: `backend/app/domain/scoring.py::score_candidates()`로 날씨·운영 유무·
  거리 Feature 기반 가중치 점수 계산과 정렬을 구현. 폐점/이전 노출·거절 ID는
  하드 필터, 운영시간 미확인은 하드 필터에서 제외하고 중립 점수 처리. 상세는
  [추천 점수 설계](./design/recommendation-scoring.md) 참고.
- 카테고리는 가중치 계산에서 제외한다: place_type/place_tag 1차 하드 필터가
  이미 처리한다고 보고, `category`는 표시용 메타데이터로만 남긴다. 남은
  영업시간(분)도 세분화하지 않고 운영 유무(OPEN/UNKNOWN)로만 구분한다.
- 기본 가중치: 날씨 0.40 / 운영 유무 0.40 / 거리 0.20
- 날씨 결측 시: 날씨 가중치를 나머지 2개 Feature(운영 유무, 거리)에 기존 비중
  비례로 재분배
- tie-break: score 내림차순 → distance_km 오름차순 → place_id 오름차순
- 입력 모델: `ScoringCandidate`(Provider/Tool 독립적인 Candidate Model v1).
  C-01 Tool 계약이 아직 없어 현재는 Stub 데이터로 검증했으며, Tool 확정 후
  "Tool 출력 → `ScoringCandidate`" 매퍼만 추가하면 됨
- 미결: 카테고리 하드 필터 자체(및 다중 카테고리 허용 시 우선순위 표현),
  혼잡도·근거 신뢰도 Feature, 실제 이동시간 기반 거리, 예산/동행 하드 필터,
  `services/recommendations.py`/`/api/recommendations`와의 실제 연결
  (D-03에서 진행)

### D-009 — Naver Blog Search는 보완 근거로 사용

- 상태: `Accepted`, 구현은 `TBD`
- 결정: TourAPI에 없는 조용함·분위기 등의 근거를 보완하되 기준 장소 데이터로
  사용하지 않는다.
- 미결: 검색어, 신뢰도, 최신성, 인용/저장 정책

### D-010 — 사용자 자연어 원문은 Supabase에 영구 저장하지 않음

- 상태: `Accepted`, Persistence 미구현
- 결정: 서버에는 정규화 조건과 실행·결과 Snapshot 중심으로 저장한다.
- 이유: 개인정보와 불필요한 원문 보존 최소화
- 미결: 보존기간, 삭제 정책, 민감정보 필터링, Supabase RLS

### D-011 — 채팅 복원 원문은 브라우저 저장소 사용 가능

- 상태: 목표 `Accepted`, 구현 차이 존재
- 결정: 채팅 복원용 원문은 Frontend 저장소에 둘 수 있다.
- 현재: `sessionStorage` 키 `tripbranch_state`, 버전 2 사용
- 목표 문맥: `localStorage`
- 미결: `localStorage` 전환 여부, 만료와 사용자 삭제 UX

### D-012 — 과거 조회는 Snapshot, 후속 입력 시 현재 데이터 재조회

- 상태: `Accepted`, 구현은 `TBD`
- 결정: 과거 채팅을 열 때 당시 외부 데이터와 추천 결과를 표시하고, 사용자가
  대화를 이어갈 때만 현재 Provider 데이터를 조회한다.
- 미결: Snapshot 스키마와 TTL

### D-013 — 세션 ID와 추천 실행 ID 분리

- 상태: `Accepted`, 구현은 `TBD`
- 결정: Frontend가 `chat_session_id`, Backend가 매 실행 `recommendation_run_id`를 생성한다.
- 이유: 하나의 채팅 안에서 여러 추천 실행과 Snapshot을 구분

### D-014 — Provider 모드는 공통 플래그와 개별 Override 사용

- 상태: `Implemented`
- 결정: `PROVIDER_MODE`로 일괄 Fake/Real 전환하고 `*_PROVIDER`로 개별 재정의한다.
- 테스트: 일반 pytest는 Real 설정이어도 Fake/Mock으로 격리

### D-015 — 공휴일은 `getRestDeInfo` 사용

- 상태: `Implemented`
- 결정: 기념일용 `getAnniversaryInfo`가 아니라 공휴일 전용 `getRestDeInfo`를 사용한다.
- 응답: XML을 Provider에서 `HolidayResult`로 정규화

### D-016 — 공개 Chat API 통합

- 상태: `Proposed`
- 결정 후보: `POST /api/chat`에서 Intent 분류부터 추천·응답 생성을 오케스트레이션
- 현재: `/api/interpret`, `/api/recommendations` 분리
- 미결: 기존 API 유지/폐기, streaming 여부, idempotency

### D-017 — Provider 공통 결과 메타데이터

- 상태: `Accepted`, 코드 반영은 후속 작업
- 결정: 모든 Provider 정상 결과는 `source`, `status`, `retrieved_at` metadata를
  포함한다.
- `source`: 데이터 공급자와 기능을 나타내는 폐쇄 목록 사용; Real/Fake를 구분
- `status`: `success`, `no_data`, `partial`
- `unavailable`: 정상 결과 status에 포함하지 않고 오류로 처리
- `retrieved_at`: UTC ISO 8601 밀리초 `Z`; 외부 응답 정규화 완료 시각
- 캐시: 캐시 반환 시각이 아닌 최초 외부 조회의 `retrieved_at` 유지
- 복합 결과: 마지막 필수 호출의 정규화 완료 시각 사용
- naming: Python과 Backend JSON 모두 `retrieved_at`
- 이유: 출처, 결측, 데이터 신선도를 Provider 종류와 무관하게 판단하고 Snapshot과
  로그에서 같은 의미로 사용하기 위함
- 후속: 공통 모델/wrapper 및 Clock 구현, 기존 `provider`/`raw_source` 필드와의
  마이그레이션

### D-018 — Tool 공통 오류와 no_data/unavailable 경계

- 상태: `Accepted`, Tool 구현은 후속 작업
- 공통 code: `invalid_input`, `not_found`, `no_data`, `unavailable`, `unsupported`,
  `internal_error`
- 결정: `no_data`는 호출·파싱 성공 후 데이터 없음이 확인된 상태
- 결정: `unavailable`은 데이터 존재 여부를 판단할 수 없는 외부 의존성 실패
- timeout, unauthorized, rate limit, network, parse error는 최상위 code가 아니라
  `unavailable`의 `cause`로 표현
- 동일 요청 retry: `no_data`는 기본 false, `unavailable`은 cause에 따라 결정
- 책임: Tool은 분류, Orchestrator는 중단·부분 진행·재질문 결정
- 보안: ToolError details에 Secret, 전체 요청 URL, 사용자 원문을 포함하지 않음
- 이유: 추천 파이프라인의 분기 수를 제한하면서 데이터 부재와 시스템 장애를
  혼동하지 않기 위함
- 후속: `ToolResult<T>`, Provider 오류 cause 보존, Orchestrator fallback 구현

### D-019 — Provider Blocker 우선순위와 관리 기준

- 상태: `Accepted`
- 등급: `P0` 보안/데이터 손상, `P1` Core 흐름 차단, `P2` 품질·복원력 저하,
  `P3` 확장성·운영 효율
- 결정: Provider별 Blocker는 영향, 현재 대응, 객관적인 해결 조건, 상태를 함께 기록
- 결정: `Resolved`는 해결 조건과 관련 테스트가 모두 충족된 경우에만 사용
- 현재 P0: 일부 Provider 예외 traceback의 인증 쿼리 노출 가능성
- 현재 주요 P1: metadata/Tool 오류 구현, Place 운영정보, Weather/Concentration 연결,
  혼잡도 coverage, Holiday와 장소 휴무 규칙 결합
- 상세 목록: `backend/docs/provider-contract-v1.md` 16장

### D-020 — Backend Python/JSON snake_case 통일

- 상태: `Accepted`
- 결정: Backend가 소유하는 Python 필드와 JSON 필드는 모두 `snake_case` 사용
- 결정: Python↔JSON 직렬화에 camelCase alias를 두지 않음
- 결정: Frontend API DTO도 Backend JSON 필드명을 그대로 사용
- 예외: Frontend 내부 상태와 외부 Provider 원본 요청·응답 필드는 각 소유자의 규칙
  사용 가능
- 이유: 현재 Pydantic 모델·공개 API·Frontend API 타입의 기존 규칙과 일치시키고
  계층 사이의 불필요한 alias 및 변환 비용을 제거하기 위함

### D-021 — Provider 정상 metadata와 오류 계약 분리

- 상태: `Accepted`, 코드 반영은 후속 작업
- 정상 결과: `ProviderMetadata(source, status, retrieved_at)` 포함
- 실패 결과: 정상 결과 대신 `ProviderError` 발생
- ProviderError: `source`, `code`, `cause`, `occurred_at`, `retryable`, 안전한
  `message`, 선택 `details`
- 시각 의미: `retrieved_at`은 데이터 정규화 성공 시각, `occurred_at`은 오류 감지 시각
- 결정: 실패 시 `retrieved_at`을 생성하지 않음
- 결정: `no_data`는 ProviderError가 아니라 정상 결과 status
- 결정: 파싱 실패처럼 존재 여부를 판단할 수 없는 경우 `unavailable`
- Tool 변환: source/cause/occurred_at/retryable을 ToolError에 보존
- 보안: ProviderError 메시지·details·traceback에 Secret과 전체 요청 URL을 포함하지 않음
- 이유: 데이터 부재와 호출 실패를 구분하면서 실패 시점과 출처를 추적하기 위함

### D-022 — 방문 예정 시각의 초단기예보 우선

- 상태: `Accepted`, 일정 기반 선택 구현은 후속 작업
- 결정: MVP Weather 기본 데이터는 현재 관측이 아닌 기상청 초단기예보
- 즉시 방문: 현재 시각과 가장 가까운 예보 사용
- 특정 시간/일정: 방문 예정 시각과 가장 가까운 예보 사용
- 현재 관측 날씨: MVP 필수 범위에서 제외
- 향후 관측값 추가 시에도 방문 예정 시각 예보가 우선이며 관측은 보완 정보로만 사용
- 추가 검토 조건: 실제 테스트에서 즉시 방문 추천 품질 부족이 확인된 경우
- Weather metadata: `data_type=forecast`, `retrieved_at`, `forecast_for`,
  `observed_at=null`
- 현재 구현 차이: 가장 이른 초단기예보만 선택하며 방문 예정 시각 입력과 metadata 없음
- 이유: 사용자의 요청 시점보다 실제 장소 도착·방문 시점의 날씨가 추천 판단에 중요

## 현재 논의가 필요한 항목

| 항목 | 선택지/질문 | 상태 |
| --- | --- | --- |
| LLM Provider | 공급자, 모델, timeout, fallback | `TBD` |
| Chat 계약 naming | Backend Python/JSON `snake_case` | `Accepted` |
| Backend 상태 저장 | Supabase 테이블과 캐시 역할 | `TBD` |
| Frontend 저장 | `sessionStorage` 유지 또는 `localStorage` 전환 | `TBD` |
| Scoring v1 | Feature/가중치/tie-break `Implemented`(D-008); 실제 파이프라인(route) 연결 | 연결은 `TBD` |
| 혼잡도 fallback | 장소 근접치, 구 단위, Feature 제외 | 현재 논의 중 |
| 운영시간 파싱 | 휴무·공휴일·계절별 시간과 unknown 처리 | `TBD` |
| 이동시간 | 지도 Provider 및 교통수단별 계산 | `TBD` |
| 조건 완화 | 자동 완화 범위와 사용자 확인 UX | `TBD` |
| 관측성 | 구조화 로그, tracing, 보존기간 | `TBD` |
| Provider metadata 구현 | 공통 wrapper, Clock, 기존 필드 마이그레이션 | 설계 확정/구현 `TBD` |
| Tool 오류 구현 | `ToolResult<T>`, 오류 매핑, fallback 연결 | 설계 확정/구현 `TBD` |
| Provider Blocker | P0~P3 표의 해결 조건 기준으로 추적 | 목록 확정/해결 진행 `TBD` |
| ProviderError 구현 | 공통 오류 모델, sanitize, ToolError 변환 | 설계 확정/구현 `TBD` |
| Weather 방문시각 선택 | visit_at 입력, forecast_for 선택, 범위 초과 처리 | 정책 확정/구현 `TBD` |
| 배포 | Hosting, CI/CD, Secret 관리 | `TBD` |

## 변경 이력

| 날짜 | 변경 |
| --- | --- |
| 2026-07-23 | Phase 1-A 실개발 시작용 최초 통합 의사결정 로그 작성 |
| 2026-07-23 | D-008 Scoring v1 엔진 구현 반영 (Feature/가중치/tie-break 확정) |
| 2026-07-23 | D-008 Scoring v1에서 카테고리 Feature 제외, 남은 영업시간 → 운영 유무로 단순화 (날씨 0.40/운영 유무 0.40/거리 0.20) |
| 2026-07-23 | Provider 공통 metadata의 source/status/retrieved_at 계약 확정 |
| 2026-07-23 | Tool 공통 오류와 no_data/unavailable 판정 기준 확정 |
| 2026-07-23 | Provider별 Blocker와 P0~P3 해결 기준 확정 |
| 2026-07-23 | Backend Python/JSON snake_case 공통 규칙 확정 |
| 2026-07-23 | ProviderMetadata와 ProviderError 분리 및 오류 시각 계약 확정 |
| 2026-07-23 | 방문 예정 시각의 초단기예보 우선 정책 확정 |
