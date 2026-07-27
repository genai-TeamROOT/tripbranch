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

- 상태: Provider `Implemented`, 다건 장소 상세조회 Tool `Implemented`, 나머지 Tool `TBD`
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

- 상태: `Implemented`; Recommendations API 파이프라인에 연결
- 결정: 명시적 필수 조건은 하드 필터, 선호 조건은 가중치 점수로 처리한다.
- 현재: `backend/app/domain/scoring.py::score_candidates()`로 날씨·남은 운영
  시간·거리 Feature 기반 가중치 점수 계산과 정렬을 구현. 이전 노출·거절 ID
  하드 필터에 더해, `now`와 `OperatingHours`(개장~마감)를 비교해 폐점 여부를
  최종 하드 필터로 직접 판정한다(운영 유무는 가중치 Feature가 아니라 필터).
  운영시간 미확인(`operating_hours=None`)은 폐점과 달리 하드 필터에서
  제외하지 않고, 남은 운영시간 Feature만 결측 처리한다. 상세는
  [추천 점수 설계](./design/recommendation-scoring.md) 참고.
- 카테고리는 가중치 계산에서 제외한다: place_type/place_tag 1차 하드 필터가
  이미 처리한다고 보고, `category`는 표시용 메타데이터로만 남긴다.
- 기본 가중치: 날씨 0.40 / 남은 운영시간 0.40 / 거리 0.20. 남은 운영시간은
  boolean이 아니라 `now` 기준 마감까지 남은 분을 정규화한 값(120분 이상이면
  만점)이다.
- 결측 시 재분배: 날씨와 남은 운영시간은 후보마다 독립적으로 결측될 수 있어
  (날씨는 실행 전체 공통, 남은 운영시간은 후보별 `operating_hours` 유무에
  따름) 결측된 Feature(들)의 가중치를 나머지 Feature에 기존 비중 비례로
  재분배한다. 이 때문에 `weights_used`는 `ScoringResult` 전체가 아니라
  `RankedCandidate`마다 따로 노출한다.
- tie-break: score 내림차순 → distance_km 오름차순 → place_id 오름차순
- 입력 모델: `ScoringCandidate`(Provider/Tool 독립적인 Candidate Model v1).
  C-01 Tool 계약이 아직 없어 현재는 Stub 데이터로 검증했으며, Tool 확정 후
  "Tool 출력 → `ScoringCandidate`" 매퍼만 추가하면 됨
- 범위 제한: `OperatingHours`는 `open_time <= close_time`인 당일 운영만
  다루며 자정을 넘기는 운영시간은 `TBD`
- 미결: 카테고리 하드 필터 자체(및 다중 카테고리 허용 시 우선순위 표현),
  혼잡도·근거 신뢰도 Feature, 실제 이동시간 기반 거리, 예산/동행 하드 필터,
  실제 운영시간 원문("0900~1800" 등)을 `OperatingHours`로 정규화하는 파서
  (`PLC-03`과 동일 범위), 자정을 넘기는 운영시간, 기준 시각(`now`)의 실제
  출처(즉시 방문 vs 방문 예정 시각, D-022 연계)

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

- 상태: `Accepted`, 다건 장소 상세조회에 일부 적용, 공통 envelope 구현은 후속 작업
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
- 현재 주요 P1: metadata/공통 Tool envelope, Place 운영정보,
  Weather/Concentration 연결,
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

- 상태: `Accepted`, Weather Tool 구현 완료
- 결정: MVP Weather 기본 데이터는 현재 관측이 아닌 기상청 초단기예보
- 즉시 방문: 현재 시각과 가장 가까운 예보 사용
- 특정 시간/일정: 방문 예정 시각과 가장 가까운 예보 사용
- 현재 관측 날씨: MVP 필수 범위에서 제외
- 향후 관측값 추가 시에도 방문 예정 시각 예보가 우선이며 관측은 보완 정보로만 사용
- 추가 검토 조건: 실제 테스트에서 즉시 방문 추천 품질 부족이 확인된 경우
- Weather metadata: `data_type=forecast`, `retrieved_at`, `forecast_for`,
  `observed_at=null`
- 구현: timezone 없는 입력은 KST로 가정하고, 가장 가까운 예보를 선택하며 동률이면
  미래 예보를 우선
- 이유: 사용자의 요청 시점보다 실제 장소 도착·방문 시점의 날씨가 추천 판단에 중요

### D-023 — 장소 다건 상세조회 Provider 교체 경계

- 상태: `Accepted`, DB 구현은 `TBD`
- 결정: 후보 검색과 상세조회를 각각 `PlaceSearchProvider`,
  `PlaceDetailsProvider`로 분리하고 `NearbyPlaceDetailsTool`에서 조합한다.
- 근거: TourAPI로 장소 10개의 상세정보를 조회하면 목록 1회와 장소별 상세 2회로
  최대 21회의 외부 요청이 발생하며, 2026-07-23 로컬 실측에서 동시성 3 기준 약
  20초가 소요됐다.
- 방향: 실서비스에서는 상세정보를 우선 DB 다건 조회로 교체하고, 누락되거나 오래된
  데이터만 TourAPI로 보완한다. 필요하면 후보 검색도 이후 DB로 이전한다.
- 미확정: DB 종류·스키마, 갱신 주기, stale 기준, 캐시 및 fallback 정책

### D-024 — 여행코스 운영시간 누락 처리

- 상태: `Accepted`, 운영 상태 evaluator는 `TBD`
- 결정: 여행코스(`content_type_id=25`)에 운영시간 원본이 없으면 `all_day`로
  정규화한다.
- 구분: 실제 Provider 명시값과 혼동하지 않도록 `parse_status=assumed`,
  `assumption_reason=course_without_operating_hours`를 기록한다.
- 예외: 다른 장소 유형의 운영시간 누락은 `unknown`을 유지한다.
- 원문: 운영시간과 휴무 원문은 그대로 보존하고 HTML을 정리한 별도 필드를 둔다.
- 이유: 여행코스 자체는 개별 시설의 입장시간과 다른 이동 경로 데이터이며, 누락을
  이유로 후보 전체를 운영 미확인으로 제외하지 않기 위함

### D-025 — `resolve_location` 종로구 범위와 재질문 정책

- 상태: `Accepted`, Tool 구현 완료
- 지원 범위: MVP는 서울특별시 종로구로 한정하며 범위 밖은 `unsupported`
- alias: 공식 주소를 우선 조회하고 정상 빈 결과에만 원문으로 1회 fallback
- 장애: timeout·인증·통신·파싱 실패에는 fallback하지 않고 `unavailable`
- 모호성: 직접·fallback 결과가 복수이면 임의 선택하지 않고 `no_data`와
  `details.reason=ambiguous_location`으로 사용자에게 구체적인 위치를 요청
- 검증: 좌표 bounding box가 아니라 Provider의 행정구 정보를 사용

### D-026 — Weather Tool v1 시간·범위 정책

- 상태: `Accepted`, Tool 구현 완료
- 서비스 전제: 국내 사용자·국내 장소, 별도 표기 없는 시각은 `Asia/Seoul`
- 즉시 방문: `visit_at=None`이면 Backend Clock 사용
- 명시 시각: 예보 범위 밖이면 마지막 예보로 대체하지 않고 `unsupported`
- 지역: Weather Tool은 좌표만 검증하며 서비스 지역 통제는 위치 Tool과 상위 계층 책임
- v1 필드: condition, SKY, PTY와 예보·조회 시각만 사용
- 범위 밖: 온도·습도·강수량·풍속, 해외 현지 시간, DST

### D-027 — 추천 Evidence·평가 Fixture v1

- 상태: `Accepted`, `Implemented`
- 결정: `RankedCandidate`의 `feature_scores`/`weights_used`를 자연어 없이
  Feature별 기여도(score × weight)로 재구성하는 `RecommendationEvidence`를
  도입하고, 반복 검증 가능한 고정 평가 Fixture v1을 구축한다.
- 구현: `backend/app/domain/evidence.py::build_evidence()`/`build_evidence_list()`,
  `backend/tests/fixtures/scoring_fixture_v1.py`(7개 시나리오),
  `backend/tests/test_scoring_fixture.py`(정렬·제외·미확인 검증 + 동일 입력
  반복 실행 결정성 검증 + Evidence 대응 검증, 21개 테스트). 상세는
  [추천 Evidence·평가 Fixture 설계](./design/recommendation-evidence-fixture.md)
  참고.
- 범위 제외: `/api/recommendations` 라우트 연결, Provider 운영시간 원문
  정규화(`operating_hours.py`의 `OperatingSchedule`↔`ScoringCandidate.operating_hours`
  매퍼 포함), 카테고리 하드 필터, 혼잡도·신뢰도 Feature, LLM 기반 자연어
  추천 이유 생성
- 이유: Scoring 결과를 사용자에게 설명 가능한 형태로 준비하면서도, 아직
  확정되지 않은 Response Generator(LLM)나 Persistence(Snapshot) 설계에
  선행 결합되지 않도록 순수 데이터 변환으로 한정함

### D-028 — 추천 파이프라인 1차 E2E 통합: Evidence 응답 노출

- 상태: `Accepted`, `Implemented`
- 결정: D-027에서 만든 `evidence.py::build_evidence()`를
  `recommendation_pipeline.py`의 응답 조립 단계에 연결해 `RecommendationItem`에
  `score`/`feature_scores`/`weights_used`를 추가 노출한다. 상위 추천 개수는
  기존 `RECOMMENDATION_RESULT_LIMIT`(기본 5)을 그대로 유지한다 — 작업 지시
  문서에 한때 "2~3개"로 적혀 있었으나 팀 논의 후 "5개"로 정정되어 별도
  설정 변경은 필요하지 않았음.
- 구현: `backend/app/schemas.py::RecommendationItem`(신규 필드),
  `backend/app/services/recommendation_pipeline.py::_build_response()`,
  `backend/app/services/recommendations.py`의 레거시 stub 응답 및
  `frontend/src/types.ts` 동기화. 날씨 조회 성공/실패 대응 E2E 테스트, 동일
  입력 결정성 테스트, 재사용 가능한
  `backend/tests/fixtures/recommendation_pipeline_fixture_v1.py`를 추가.
- 범위 제외: 자연어 추천 이유 생성(`recommendation_reason`은 기존 고정
  템플릿 유지), Persistence/Snapshot 연결, 카테고리 하드 필터
- 이유: D-02(D-027)에서 준비해 둔 Evidence 모델을 실제 `/api/recommendations`
  응답과 연결해, 추천 점수 근거를 Frontend/사용자가 그대로 소비할 수 있게 함

### D-029 — Recommendation Explainability Layer v1 (Rule 기반)

- 상태: `Implemented`(초안) — Chat API 통합 시점의 A(Agent Runtime) 담당과의
  API Contract 협의는 아직 진행 전이라 필드 형태가 바뀔 수 있음
- 결정: `RecommendationEvidence.contributions`(D-027)를 입력으로 받아, LLM을
  호출하지 않는 Rule 기반·결정적 방식으로 Feature별 한국어 설명 문장을
  생성한다. Feature 점수가 0.7 이상인 것만 "기여도(score × weight) 큰
  순서"로 문장화하고, 결측이거나 애매한 점수(<0.7)는 생략한다(결측은 이미
  `warnings`가 별도로 안내하므로 중복 설명하지 않음). 기존
  `recommendation_reason`(고정 템플릿 한 줄)은 유지하고, `explanations:
  string[]`을 신규 필드로 추가한다(대체가 아니라 추가 — Frontend가 이미
  `recommendation_reason`을 렌더링하고 있어 하위 호환 유지).
- 구현: `backend/app/domain/explanation.py::build_explanations()`,
  `backend/app/services/recommendation_pipeline.py::_build_response()`
  연결, `backend/app/schemas.py::RecommendationItem.explanations`,
  `frontend/src/types.ts` 동기화, `backend/tests/test_explanation.py`(D-02
  Fixture 재사용, 결정성·순서·빈 리스트 케이스 검증)
- 범위 제외: LLM 기반 자연어 생성, 점수가 애매하거나(0.4~0.7) 낮은(<0.4)
  Feature에 대한 부정적 근거 문장 생성, Chat API(`RecommendationResult`)로의
  최종 반영(A 담당과 협의 후 확정)
- 이유: 순수 Rule 기반이라 비용·지연시간이 없고, 동일 입력에 항상 동일한
  설명이 나와 D-02 Fixture로 그대로 회귀 검증 가능함. 추후 LLM 기반 Response
  Generator가 붙을 때도 이 Feature별 판단을 근거 재료로 재사용할 수 있도록
  설계함

## 현재 논의가 필요한 항목

| 항목 | 선택지/질문 | 상태 |
| --- | --- | --- |
| LLM Provider | 공급자, 모델, timeout, fallback | `TBD` |
| Chat 계약 naming | Backend Python/JSON `snake_case` | `Accepted` |
| Backend 상태 저장 | Supabase 테이블과 캐시 역할 | `TBD` |
| Frontend 저장 | `sessionStorage` 유지 또는 `localStorage` 전환 | `TBD` |
| Scoring v1 | Feature/가중치/tie-break `Implemented`(D-008); Evidence·평가 Fixture `Implemented`(D-027); 응답 Evidence 노출·E2E 통합 `Implemented`(D-028); Explainability Layer v1 `Implemented`(초안, D-029) | 구현 완료(Explainability는 A 협의 전 초안) |
| 혼잡도 fallback | 장소 근접치, 구 단위, Feature 제외 | 현재 논의 중 |
| 운영시간 파싱 | 기본 시간·월별·주간 휴무 구현, 공휴일·회차 예외 확대 | `부분 구현` |
| 이동시간 | 지도 Provider 및 교통수단별 계산 | `TBD` |
| 조건 완화 | 자동 완화 범위와 사용자 확인 UX | `TBD` |
| 관측성 | 구조화 로그, tracing, 보존기간 | `TBD` |
| Provider metadata 구현 | 5개 Provider 공통 `ProviderResult`와 UTC metadata 적용 | 구현 완료 |
| Tool 오류 구현 | 5개 Tool에 공통 상태·오류·warning·provider metadata 적용 | 구현 완료 |
| Provider Blocker | P0~P3 표의 해결 조건 기준으로 추적 | 목록 확정/해결 진행 `TBD` |
| ProviderError 구현 | 공통 오류 모델, sanitize, ToolError 변환 | 설계 확정/구현 `TBD` |
| Weather 방문시각 선택 | visit_at 입력, forecast_for 선택, 범위 초과 처리 | 구현 완료 |
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
| 2026-07-23 | 종로구 `resolve_location` 범위·fallback·재질문 정책 구현 반영 |
| 2026-07-23 | D-008 재설계: 운영 유무를 가중치에서 제외하고 `now`/`OperatingHours` 기반 최종 하드 필터로 이동, 가중치 Feature를 남은 운영시간(분 정규화)으로 교체 (날씨 0.40/남은 운영시간 0.40/거리 0.20), `weights_used`를 후보별로 노출하도록 변경 |
| 2026-07-23 | Weather Tool v1의 KST·방문시각·예보 범위 정책 구현 반영 |
| 2026-07-24 | D-027 추천 Evidence·평가 Fixture v1 구현 반영 (Feature 기여도 모델, 고정 Fixture v1, 결정성 검증) |
| 2026-07-24 | D-028 추천 파이프라인 1차 E2E 통합 구현 반영 (응답에 score/feature_scores/weights_used 노출, 날씨 유무·결정성 E2E 테스트, 재사용 가능한 파이프라인 Fixture) |
| 2026-07-27 | D-029 Recommendation Explainability Layer v1(Rule 기반) 구현 반영 (초안, A 담당과 API Contract 협의 전) |
