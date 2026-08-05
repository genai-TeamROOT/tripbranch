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

- 상태: `Accepted`, Fake/Real Gemini Provider 구현
- 결정: Frontend는 LLM Provider를 직접 호출하지 않고 FastAPI Backend만 호출한다.
- 이유: API 키 보호, 프롬프트·모델 교체의 캡슐화, 로깅과 오류 정책 일원화
- 후속: LLM Provider와 모델 선정 `TBD`

### D-002 — Interpret와 Recommendation 분리

- 상태: `Accepted`, `/api/interpret`와 `/api/recommendations` 분리 구현
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
  `frontend/src/types.ts` 동기화. 당시 레거시 stub 응답에도 필드를 맞췄으나
  이후 실제 Fake/Real 공통 파이프라인으로 대체되어 제거됨. 날씨 조회
  성공/실패 대응 E2E 테스트, 동일
  입력 결정성 테스트, 재사용 가능한
  `backend/tests/fixtures/recommendation_pipeline_fixture_v1.py`를 추가.
- 범위 제외: 자연어 추천 이유 생성(`recommendation_reason`은 기존 고정
  템플릿 유지), Persistence/Snapshot 연결, 카테고리 하드 필터
- 이유: D-02(D-027)에서 준비해 둔 Evidence 모델을 실제 `/api/recommendations`
  응답과 연결해, 추천 점수 근거를 Frontend/사용자가 그대로 소비할 수 있게 함

### D-029 — Recommendation Explainability Layer v1 (Rule 기반)

- 상태: `Accepted` — A(Agent Runtime) 담당과 API Contract 협의 반영 완료.
  상세는 [추천 Explainability Layer 설계](./design/recommendation-explainability.md) 참고
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

### D-030 — 임계값 미달·날씨 결측 시 warning 커버리지 보완

- 상태: `Implemented`
- 결정: D-029 이후 남아 있던 빈틈 — (1) 날씨 결측으로 `weather` Feature
  점수가 `None`인 경우, (2) 세 Feature 모두 0.7 미만이라 `explanations`가
  완전히 비는 경우 — 둘 다 지금까지 아무 warning 없이 조용히 생략되던
  것을 확인하고, `warnings` 문구를 추가해 안내하기로 결정. 운영시간 결측처럼
  `unverified_recommendations`로 분리하지는 않는다 — "존재 자체를 모르는"
  운영시간 결측과 달리, 날씨 결측·낮은 점수는 그 정도로 심각한 불확실성이
  아니라고 판단했기 때문. 두 케이스는 원인이 다르므로(데이터 없음 vs.
  데이터는 있으나 애매함) 문구도 분리했다. `distance`는 `ScoringCandidate.
  distance_km`가 필수 필드라 결측 케이스 자체가 존재하지 않으므로 대상에서
  제외
- 구현: `backend/app/services/recommendation_pipeline.py::_extra_warnings()`
  신설, `_build_response()`에서 기존 상세정보 결측 warning과 함께 조립.
  `backend/tests/test_recommendation_pipeline.py`에 날씨 결측·전체 임계값
  미달 케이스 각각 검증하는 테스트 추가
- 범위 제외: `recommendation_reason` 존폐 여부, Explanation Rule 정의
  문서화 — 둘 다 A 담당과의 협의 이후로 보류
- 이유: Explainability Layer 협의를 준비하며 발견한 실사용자 관점의 빈틈으로,
  A의 결정이 아니라 우리 쪽 구현 책임 영역이라고 판단해 협의 전에 먼저 해결

### D-031 — Explanation 문장 구체화: 고정 텍스트 → 계산값 기반 사실 문장

- 상태: `Implemented`
- 결정: D-029의 Feature별 고정 문장(예: "지금 날씨 조건에 잘 맞는 장소예요.")을
  실제 계산값이 들어간 문장으로 교체한다(`package_D/[D-06]explainability_detail.txt`
  구체화 요청). 거리는 1km 미만 m(10m 반올림)/이상 km(소수 첫째자리)로
  "직선거리"를 명시해 실제 이동거리로 오해되지 않게 하고, 남은 운영시간은
  "N시간 M분" 형태로, 날씨·환경은 `(weather_condition, environment_type)`
  9개 조합별 문장으로 조립한다. 문장은 "여유롭게 방문할 수 있어요" 같은
  평가·어투 없이 사실만 전달하도록 의도적으로 짧게 유지한다 — 평가·어투를
  더해 자연스러운 문단으로 잇는 것은 Response Generator(LLM, A 담당)의
  몫이라고 판단했다(둘 다 넣으면 최종 응답에서 비슷한 평가 표현이 중복될
  위험이 있음). 정렬 규칙(기여도 내림차순)과 임계값(0.7)·결측 시 생략 로직은
  D-029에서 그대로 유지.
- 구현: `backend/app/domain/scoring.py::RankedCandidate`에 원본 계산값
  (`distance_km`/`remaining_minutes`/`weather_condition`/`environment_type`)
  필드 추가, `backend/app/domain/evidence.py::RecommendationEvidence`로
  그대로 전달, `backend/app/domain/explanation.py`의 문장 생성 로직을 고정
  매핑에서 계산 함수로 교체. `backend/tests/test_explanation.py`에 거리
  단위 경계(3개)·운영시간 경계(4개)·날씨-환경 조합 매트릭스(2개) 테스트 추가
- 범위 제외: 여러 `explanations` 문장을 하나의 자연스러운 문단으로 잇는 것
  (A 담당 Response Generator 영역)
- 이유: task.txt 예시가 "Rule 계층은 사실만, 평가·어투는 LLM 몫"이라는
  경계를 명확히 보여주고 있어, 그 경계에 맞춰 문장 톤을 다시 다듬음

### D-032 — RecommendationContext → RecommendationResponse 신규 진입점

- 상태: `Implemented`
- 결정: A(Agent Runtime)가 C에서 받은 `RecommendationContext`를 그대로
  넘기면, D 내부(후보 변환→Scoring→Evidence→Explanation 조립)를 전부
  처리해 `RecommendationResponse`만 반환하는 공개 함수
  `run_recommendation_pipeline_from_context()`를 신설한다
  (`package_D/[A] RecommendationContext → RecommendationResponse 진입점
  요청.txt`). A가 D 내부 구현(`score_candidates()`/`build_evidence()`/
  `build_explanations()`/private `_build_response()`)에 직접 의존하지
  않도록 하기 위함. 기존 Tool 직접 호출 구조(`run_recommendation_pipeline()`,
  `recommendations.py`)는 이 시점엔 그대로 유지하고 대체하지 않기로
  했다 — 두 진입점이 공존하는 상태였다. **(주: 이 판단은 이후 D-034에서
  뒤집혔다. `run_recommendation_pipeline()`은 완전히 삭제됐고
  `recommendations.py`도 이 진입점 기반으로 마이그레이션됐다 — 상세는
  D-034 참고.)**
  - `candidate_limit`은 새 시그니처에 포함하지 않기로 판단했다. C가 이미
    최종 후보 목록을 확정해서 넘기는 구조라, D가 그 뒤에 개수를 다시
    제어할 근거가 없기 때문이다.
  - `search_radius_km`은 호출자(A)가 C가 해당 요청에서 실제로 후보를
    조회할 때 사용한 반경과 동일한 값을 넘겨야 한다는 전제를 docstring에
    명시했다 — Scoring의 거리 점수 정규화(`max_distance_km`)가 이 값을
    그대로 재사용하기 때문이며, 코드로는 이 일치 여부를 검증할 수 없다.
  - `context.location`/`context.places` 상태를 구분해서 처리한다:
    `success`/`partial`(정상 진행), `no_data`(정상 조회했지만 결과 없음 →
    빈 `RecommendationResponse`, 에러 아님), `unavailable`(조회 자체 실패
    → `AppError`). "확인 못 함"과 "확인했는데 없음"을 구분하기 위함이다.
- 구현: `backend/app/services/recommendation_pipeline.py`에
  `run_recommendation_pipeline_from_context()`, `_weather_condition_from_context()`
  추가. 기존 `_build_response()`/`_extra_warnings()`가 Tool 전용 타입
  `EnrichedPlace`에 의존하던 것을 "상세정보 결측 place_id 집합"
  (`frozenset[str]`)으로 일반화해 두 진입점에서 공유하도록 리팩터링.
  `backend/tests/test_recommendation_pipeline.py`에 정상/날씨 결측/후보
  없음/조회 실패/위치 결측 5개 시나리오 테스트 추가
- 범위 제외: `candidate_limit` 관련 논의는 A에게 별도로 공유하되 이번
  구현엔 반영하지 않음. 혼잡도(concentration) 조회는 `RecommendationResponse`
  자체에 포함되지 않는 부가 정보라 이 진입점에서 다루지 않음
- 이유: `map_context_to_scoring_candidates()`가 이미 존재하지만 유닛
  테스트로만 검증되고 어떤 파이프라인에도 연결되지 않은 상태였음. A가
  D 내부 함수 4개를 직접 조합하는 대신, 단일 공개 진입점을 통해 D 내부
  구현 변경에 영향받지 않도록 경계를 명확히 함

### D-033 — Agent Runtime RecommendationProvider 실제 구현체 연결

- 상태: `Implemented`
- 결정: `run_recommendation_pipeline_from_context()`(D-032)를 Agent
  Runtime의 `RecommendationProvider` Protocol(`app/services/runtime/
  protocols.py`, A 소유)에 연결하는 실제 구현체 `RealRecommendationProvider`를
  신설해 `run_agent()`의 기본 provider를 기존 `FakeRecommendationProvider`
  대신 이걸로 교체한다(`package_D/[TECH-02] C-D 직접 의존 제거 및
  RecommendationContext 경계 정리.txt`). Protocol 시그니처
  (`recommend(conditions, context, excluded_place_ids)`)는 A가 이미
  확정해둔 형태 그대로 사용했고 D 쪽에서 변경하지 않았다.
- 구현: `backend/app/services/runtime/recommendation_provider.py` 신설(주: 이
  파일은 이후 D-035에서 develop과의 중복으로 삭제되고
  `real_recommendation_provider.py`로 대체됐다 — 클래스명·시그니처는 동일).
  `search_radius_km`은 A가 이미 구현해둔
  `recommendation_transform.to_search_radius_km(conditions)`로 계산하고,
  `visit_at`은 `now_kst()`(현재 시각)를 쓴다 — 사용자가 미래 방문 시각을
  지정하는 입력 경로가 아직 없기 때문. `excluded_place_ids`는
  `shown_place_ids`로 그대로 전달한다(현재 `score_candidates()`에서
  `shown_place_ids`/`rejected_place_ids`는 둘 다 단순 제외로 동일하게
  동작하므로 구분할 실익이 없음). `run_agent()`/`agent_runtime.py`
  docstring, `stubs.py`/`protocols.py`의 "D 계약 확정 전" 관련 주석을
  현재 상태에 맞게 갱신
- 이유: A의 `agent_runtime.py`/`recommendation_transform.py`가 이미 D의
  진입점을 기다리는 상태로 배선까지 끝나 있었음(주석에 "D 확인 대기 중"
  명시). D-032에서 만든 진입점을 실제로 연결하는 것이 A-D 계약을
  "확정"하는 마지막 단계였음

### D-034 — Tool 직접 호출 파이프라인 완전 삭제 및 레거시 라우터 마이그레이션

- 상태: `Implemented`
- 결정: D-033에서 "레거시 라우터 전용으로 남긴다"고 판단했던
  `run_recommendation_pipeline()`(Tool 직접 호출 구조)을 완전히
  삭제하고, 그 유일한 호출자였던 `/api/recommendations` 라우터
  (`app/services/recommendations.py`)를 `run_recommendation_pipeline_
  from_context()` 기반으로 마이그레이션한다. "D 코드에서 C Tool
  Intelligence를 직접 호출하지 않는다"는 완료 기준을 예외 없이 만족시키기
  위함
- 구현: `recommendations.py`가 여전히 위치·날씨·장소 Tool
  (`ResolveLocationTool`/`GetWeatherForecastTool`/`NearbyPlaceDetailsTool`)을
  직접 호출하지만, 이 호출은 D 코드(`recommendation_pipeline.py`)가 아니라
  호출자 쪽(레거시 라우터 서비스)에서 일어난다 — Tool 결과를
  `app.agent_context.mappers`의 `map_location_context()`/
  `map_weather_context()`/`map_places_context()`(C가 실제
  `ContextService`에서 쓰는 것과 동일한 순수 변환 함수)로 `RecommendationContext`에
  조립한 뒤 D에 넘긴다. 위치 조회 실패 시 404/422/502로 세분화하던 기존
  에러 매핑(`_location_error()`)은 그대로 `recommendations.py`로 옮겨
  동일하게 유지했다 — Context 기반 진입점의 위치 실패 처리(일괄 502)에
  맡기면 API 응답 status_code가 달라지는 회귀가 생기기 때문
- 범위 축소: 혼잡도(concentration)·공휴일(holiday) Tool 호출은
  라우터에서 제거했다. 기존에도 두 값 모두 `RecommendationPipelineResult.
  context`/`.concentrations`에만 담기고 실제 `RecommendationResponse`
  (`build_recommendations()`가 반환하는 값)에는 전혀 반영되지 않던 죽은
  코드였음을 확인했다 — 기능 회귀 없이 제거
- 함께 삭제: `RecommendationPipelineRequest`/`RecommendationTools`/
  `RecommendationPipelineResult`/`build_pipeline_request()`/
  `CandidateConcentration`/`_fetch_ranked_concentrations()`/
  `_build_context()`/`_aggregate_concentration_status()`
  (`recommendation_pipeline.py`), 이들만 참조하던
  `app/domain/agent_context.py`(`AgentToolContext`, A-C 계약 이전의
  중복 Context 모델)와 그 단위 테스트, Tool 직접 호출 전용 Fixture
  (`tests/fixtures/recommendation_pipeline_fixture_v1.py`)와 그 테스트
  (`test_recommendation_pipeline_fixture.py`). 하드 필터·이전 노출/거절
  제외·날씨 결측 재분배 같은 D-03 완료 기준은 `test_scoring.py`(단위)와
  `test_recommendation_pipeline.py`의 Context 기반 E2E 테스트(결정성,
  shown_place_ids 제외 테스트 추가)로 계속 커버됨을 확인했다
- 이유: 처음엔 조건 스키마(`InterpretedConditions`→`UserConditions`)
  통합이 끝나야만 라우터를 옮길 수 있다고 판단했으나, 실제로는
  `ContextService`/`UserConditions`를 거칠 필요 없이 C의 순수 매퍼
  함수만 재사용하면 조건 스키마와 무관하게 `RecommendationContext`를
  조립할 수 있다는 것을 확인했다. 따라서 별도 트랙 마이그레이션을
  앞당기지 않고도 완료 기준을 예외 없이 만족시킬 수 있었음
- 추가 정리: 완료 후 재검증 과정에서 `app/domain/candidate_mapper.py`의
  `map_places_to_scoring_candidates()`(D-01/D-02 시절, `NearbyPlaceDetailsResult`를
  직접 받는 함수)가 `run_recommendation_pipeline()` 삭제로 production에서
  전혀 쓰이지 않는 죽은 코드가 된 것을 발견했다. C Tool 결과 타입
  (`app.tools.nearby_place_details.NearbyPlaceDetailsResult`) import가
  D 도메인 코드에 남아있던 마지막 잔재라 이 함수와 전용 헬퍼
  (`_operating_hours_for_visit()`), 관련 테스트 2개(`test_candidate_mapper.py`)까지
  함께 삭제해 D 도메인 코드에서 C Tool 타입 의존을 완전히 제거했다

### D-035 — develop 재병합 시 RecommendationProvider 중복 구현 정리

- 상태: `Implemented`
- 결정: `feature/tech-02-context-boundary`에 최신 `develop`(mintee의
  A-04 작업 포함)을 재병합하는 과정에서, D-033에서 만든
  `recommendation_provider.py`(`RealRecommendationProvider`)와 develop에
  이미 병합돼 있던 mintee의 `real_recommendation_provider.py`가 같은
  `RecommendationProvider` Protocol을 사실상 동일하게 구현한 중복임을
  확인했다. 우리 쪽 파일을 삭제하고 `real_recommendation_provider.py`
  하나로 통합한다
- 구현: `backend/app/services/runtime/recommendation_provider.py`와
  `tests/test_recommendation_provider.py` 삭제. `agent_runtime.py`의
  `run_agent()`가 주입하는 provider를
  `app.services.runtime.real_recommendation_provider.RealRecommendationProvider`
  로 교체. `protocols.py` docstring의 파일 경로 참조도 함께 갱신
- 이유: 두 구현이 로직상 동일(`run_recommendation_pipeline_from_context()`
  호출, `to_search_radius_km()`로 반경 계산)해 어느 쪽을 남겨도 기능
  차이는 없었다. develop에 이미 병합되어 있고 자체 단위 테스트
  (`test_real_recommendation_provider.py`)까지 갖춘 mintee 쪽을 정본으로
  채택해 이후 develop과의 재충돌을 줄이는 쪽을 택했다
- 확인: 병합 후 `ruff check .` 전체 통과, `pytest` 596 passed / 20
  skipped로 회귀 없음을 확인했다. 이 병합으로 develop이 함께 가져온
  `place_search_policy.py`의 `DEFAULT_PLACE_SEARCH_RADIUS_KM`(1.0→2.0)/
  `MIN_PLACE_SEARCH_RADIUS_KM`(0.1→0.3) 변경은 D 코드가 상수를 import해서
  쓰는 값이라 D 쪽 수정 없이 그대로 반영됐다

### D-036 — 혼잡도 fallback: 장소 근접치 채택 (INFO 전용)

- 상태: `Accepted` (INFO 전용)
- 결정: 카페·음식점처럼 집중률 API가 다루는 "관광지" 콘텐츠에 없는 장소를 물으면,
  기존 미결이었던 세 선택지(장소 근접치·구 단위·Feature 제외) 중 **장소
  근접치**를 채택한다 — 대상 장소 자체의 데이터가 없으면
  `search_nearby_places`(`place_types=["attraction"]`)로 가장 가까운 관광지를
  찾아 그 예측치를 "근처 관광지 기준 추정"이라고 명시하며 대체 제공한다
- 이유: "데이터 없음"만 반환하는 것보다 사용자에게 참고할 만한 근사치를 주는
  편이 유용하고, 이미 구현된 `NearbyPlaceDetailsTool`을 그대로 재사용할 수 있어
  새 Provider 연동 없이 구현 가능하다. 구 단위 평균은 데이터를 왜곡할 소지가
  크고, Feature 제외는 사용자 질문에 아예 답하지 못한다는 문제가 있어 제외했다
- 범위: INFO(`question_type=concentration`)의 단일 장소 질의에만 적용한다.
  RECOMMEND 후보에는 직접 조회된 혼잡도만 사용하며, 근접치 fallback은 적용하지 않는다.
  추후 혼잡도 데이터 부족으로 추천 품질 또는 결과 수에 문제가 확인될 때만, C·D 사전
  협의 후 확장을 검토한다.
- 상세 설계: [`docs/design/concentration-conditions.md`](./design/concentration-conditions.md) §3.3
- 탐색 반경: INFO fallback 전용 기본값을 0.5km로 적용한다. 실제 테스트 결과에 따라
  조정할 수 있으며, 코드 단일 기준은 `INFO_CONCENTRATION_FALLBACK_RADIUS_KM`이다.

### D-037 — 혼잡도 반영 방식 재검토: 초기 Context 확장 vs 1차 Scoring 후 상위 5개 보강 재계산 (A-C 협의, D 미확인)

- 상태: `Proposed` (A-C 협의 완료, **D는 아직 확인하지 않음** — 최종 확정 아님)
- 배경: D-036 이전에 확정해뒀던 안(concentration-conditions.md v0.4)은
  "concentration을 초기 Context 요청 단계에서 지역 전체 한 번에 받아오고 D는
  1회만 호출한다"였다. 세션 중 Real Provider로 직접 실측한 결과:
  - 장소 후보 10개 검색(`NearbyPlaceDetailsTool`) — 약 3.0초
  - 집중률 종로구 전체(113곳) 병렬 페이지 조회(20페이지) — 약 3.5초, 순차는
    약 11.8초(`numOfRows=100` 하드코딩이라 페이지네이션 필수)
  - 집중률 장소 1곳 `tAtsNm` 지정 개별 조회 — 약 0.12초

  즉 이미 후보 검색에만 3초가 드는데 지역 전체 집중률까지 얹으면 6.5초 이상으로
  늘어나 이득이 없었다. 반대로 좁혀진 소수 후보만 개별 조회하면 압도적으로 빠르다.
- 제안: "1차 Scoring(10개 후보, concentration 없음 — 기존과 완전 동일) → 상위
  5개 추출 → 그 5개만 기존 `CandidateEnrichmentRequest`/`Response`
  (`CandidateEnrichmentService.enrich()`, 이미 C가 구현해둔 인프라)로 집중률
  보강 조회 → 2차 Scoring(5개+concentration, D 신규 인터페이스)으로 재순위
  계산 → 최종 3개만 사용자에게 노출"로 방향 전환을 제안한다.
- D의 1차/2차 호출 모양(정밀하게 구분): 1차는 입력 10개·concentration 없음
  (기존과 완전 동일, 새로 만들 것 없음). 2차는 입력이 **5개로 축소**되고
  concentration이 추가되는 **신규 인터페이스** — `score_candidates()`는 현재
  단일 호출만 지원해 이런 진입점 자체가 없다(0단계 확인 결과). **D가 이 2차
  인터페이스를 만들어줄 수 있는지 확인이 이 제안의 핵심 블로커다.**
- 참고 근거(develop 병합, 2026-07-30 발견): C가 `place_concentration_mappings`
  테이블(커밋 `019709e`, [place-database-schema.md §6.1](./design/place-database-schema.md#61-place_concentration_mappings))을
  이미 구축해뒀다 — `place_id` ↔ 집중률 API 대표명 매핑 100건(별칭 포함 101곳,
  미매칭 12곳). 아직 런타임 코드엔 미연결이지만, 제안 흐름의 5단계(후보→집중률
  이름 매칭)를 뒷받침하는 정황 근거다.
- 영향 범위: `concentration_intent`가 `AVOID`/`SEEK`일 때만 적용된다.
  `null`/`IGNORE`는 이 재검토와 무관하게 기존 그대로 D 1회 호출로 끝난다.
- "최종 3개" 노출은 기존 `RECOMMENDATION_RESULT_LIMIT`(5, `.env`)와 다른 새
  숫자다 — 기존 설정 어디에도 3을 만드는 상수가 없어 새 상수/자르기 단계가
  필요하다(정확히 3으로 고정할지도 미확정).
- 상세 설계: [`docs/design/concentration-conditions.md`](./design/concentration-conditions.md) §2.2,
  [`docs/design/agent-runtime-contract.md`](./design/agent-runtime-contract.md) §6.5
- TODO: D의 2차 Scoring 신규 인터페이스 확인(가장 중요), "최종 3개" 상수화 여부,
  안 A(초기 Context 확장)와 안 B(이번 제안) 중 최종 택1 — **D 확인 대기**

| 항목 | 선택지/질문 | 상태 |
| --- | --- | --- |
| LLM Provider | 공급자, 모델, timeout, fallback | `TBD` |
| Chat 계약 naming | Backend Python/JSON `snake_case` | `Accepted` |
| Backend 상태 저장 | Supabase 테이블과 캐시 역할 | `TBD` |
| Frontend 저장 | `sessionStorage` 유지 또는 `localStorage` 전환 | `TBD` |
| Scoring v1 | Feature/가중치/tie-break `Implemented`(D-008); Evidence·평가 Fixture `Implemented`(D-027); 응답 Evidence 노출·E2E 통합 `Implemented`(D-028); Explainability Layer v1 `Accepted`(D-029, A 협의 반영 완료); warning 커버리지 보완 `Implemented`(D-030); Explanation 문장 구체화 `Implemented`(D-031); RecommendationContext 진입점 `Implemented`(D-032); Agent Runtime RecommendationProvider 연결 `Implemented`(D-033); Tool 직접 호출 파이프라인 삭제·레거시 라우터 마이그레이션 `Implemented`(D-034); develop 재병합 시 RecommendationProvider 중복 정리 `Implemented`(D-035); 혼잡도 2차 Scoring(`rerank_with_concentration()`) `Implemented`(D-040) | 구현 완료 |
| 혼잡도 fallback | 장소 근접치, 구 단위, Feature 제외 | INFO 전용 장소 근접치 적용(D-036), RECOMMEND 확장은 후속 검토 |
| 혼잡도 반영 방식 | 초기 Context 확장(안 A) vs 1차 Scoring 후 상위 5개 보강 재계산(안 B) | 안 B 채택, `rerank_with_concentration()` 구현 완료(D-040) |
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

### D-038 — 날씨 warning 문구 분리(IGNORE vs 조회 실패) 및 날씨 조회 경로 이원화 정리

- 상태: `Implemented` (2026-08-05, TODO 1/2 해결 완료 — 아래 참고)
- 배경: `"경복궁 근처 카페 추천해줘"`처럼 날씨 언급이 없는 발화는 LLM이
  `weather_intent=IGNORE`로 판정하고([int-01-recommend.md §8](./design/int-01-recommend.md#8-weather_intent-판별)의
  정의: "날씨 언급 없음"), C가 Weather Tool을 실행하지 않는다
  (`tool_rules.py`). 정상 흐름인데도 사용자에게 "현재 날씨 정보를 확인하지
  못해 이 조건은 반영되지 않았어요"라는 **조회 실패 문구**가 나갔다.
- 결정 1 (`Implemented`): `recommendation_pipeline.py`의 날씨 warning을 두 개로
  나눈다. `context.weather`가 `None`이면 조회를 시도하지 않은 것(IGNORE)이므로
  `_WEATHER_IGNORED_WARNING`("날씨 조건을 따로 말씀하지 않으셔서 …"), 값이
  있는데 status가 실패면 기존 `_WEATHER_MISSING_WARNING`을 쓴다. 개발 단계에서는
  IGNORE로 처리됐다는 사실 자체를 보여줄 필요가 있어 warning을 없애지 않고
  문구만 구분했다 — 사용자 노출용 문구 확정은 UX 논의가 필요하다.
- TODO 1 (`Implemented`, 2026-08-05) — **§10과 구현 불일치 해결**: B(이태화)의
  리뷰를 계기로 재조사한 결과, "구현이 맞고 문서가 틀렸다"로 결론냈다 —
  `weather_intent=IGNORE`면 API 호출 자체를 안 하는 현재 구현이 의도된 동작이고
  (안 쓸 값을 굳이 조회할 이유가 없다), [int-01-recommend.md
  §10](./design/int-01-recommend.md#10-날씨-정보-확보-순서)을 이 실제 동작에
  맞게 재작성했다.
- TODO 2 (`Implemented`, 2026-08-05) — **날씨 조회 경로 이원화 해결**: 직접
  재검증한 결과 B 세션 `api_context.api_weather`를 실제로 읽는 소비자가
  backend/frontend 어디에도 없음을 확인했다(패스스루 복사와 TTL 타임스탬프
  판정만 있고, 값 자체를 쓰는 로직은 전무) — 실제 RECOMMEND 날씨 Feature는
  D가 `to_weather_condition()`으로 참조하는 C `context.weather` 경로 하나뿐이었다.
  `api_weather`를 채우던 A 소유 코드(`session_orchestrator.py::_refresh_weather()`
  와 그 호출부, `weather_provider` 파라미터 일체)를 제거해 조회 경로를 C
  하나로 통합했다. B 소유 스키마(`ApiContext.api_weather`/
  `api_weather_updated_at`/`weather_expired`, `is_weather_expired()`)는
  건드리지 않았다 — 값이 영구히 비게 될 뿐 깨지는 소비자가 없어서다. B가
  원하면 이 필드들을 스키마에서 정리(deprecate)하는 것도 가능하다는 걸
  제안으로 남긴다.
- 확인 방법: `device_location`을 넣어도 `weather_intent=IGNORE`면
  `feature_scores.weather`가 `null`이고 `weights_used`에서 날씨 0.4가 빠져
  나머지에 재분배된다(정상). 실제 응답으로 확인함. TODO 1/2 해결은 전체
  pytest 회귀(회귀 없음)와 `api_context.api_weather`가 항상 `None`으로
  응답에 남는지로 확인.

### D-039 — 되묻기 답변은 새 요청이 아닌 기존 요청의 연속으로 처리

- 상태: `Implemented` (PR #64)
- 배경: 첫 요청에 위치가 없어 C가 `needs_clarification`을 반환한 뒤 사용자가
  위치만 답하면, 두 번째 발화가 새 `RECOMMEND`로 분류되면서
  `reset_scope="soft"`가 적용됐다. 이 과정에서 첫 요청의 카테고리·선호 조건이
  초기화되어 사용자가 이미 말한 조건과 다른 후보가 추천될 수 있었다.
- 결정: LLM 또는 C 단계의 되묻기로 끝난 턴은 B에
  `pending_clarification`으로 기록한다. 다음 `RECOMMEND`/`MODIFY` 발화는 새 요청이
  아니라 같은 요청을 완성하는 답변으로 보고 `reset_scope=None`을 사용한다.
  답변에서 새로 추출된 조건만 Operation으로 전달하고, 언급되지 않은 기존 조건은
  B가 유지한다.
- 책임 분리:
  - A는 LLM/C 응답을 보고 되묻기 여부와 저장할 사유 코드를 결정한다.
  - B는 `pending_clarification`을 해석하지 않고 세션 상태에 저장·조회만 한다.
  - `pending_clarification` 갱신은 사용자 조건 변경이 아니므로
    `condition_version`을 증가시키지 않는다.
- 소비 규칙: 조건을 처리하는 `RECOMMEND`/`MODIFY`에서만 기존 플래그를 소비한다.
  `INFO`/`COMPARE`/`GENERAL` 같은 곁가지 발화는 이전 되묻기 상태를 유지한다. 같은
  턴이 다시 되묻기로 끝나면 새로운 사유 코드로 다시 저장한다.
- 예외: 사용자가 "처음부터 다시"처럼 명시적인 초기화 표현을 사용하면 되묻기
  답변 중이어도 새 요청으로 보고 기존 `reset_scope="soft"` 규칙을 적용한다.
- 구현: `AgentState`/`SessionContextResponse.pending_clarification`,
  `set_pending_clarification()`, `state_transform.transform()`의 조건 병합 분기,
  `agent_runtime.run_agent_flow()`의 LLM/C 되묻기 기록·소비 흐름.
- 확인: 위치 없는 카페 추천 → `location_required` 되묻기 → "경복궁 근처" 답변
  시 기존 `place_tags`가 유지되고 위치만 추가되는 흐름, 명시적 재시작 시 soft
  reset이 적용되는 흐름, 성공 추천 후 플래그가 남지 않는 흐름을 테스트한다.
- 제한사항: `pending_clarification`은 InMemory 상태에는 반영됐지만, 현재
  `SupabaseStateStore`와 DB migration에는 컬럼·영속화 매핑이 없다. Supabase 모드에서
  턴 간 되묻기 상태를 보존하려면 별도 migration과 store 매핑을 추가해야 한다. 단독 위치 답변이
  `INFO`로 분류되는 문제는 프롬프트·Intent 분류의 별도 과제로 유지한다.

### D-040 — 혼잡도(concentration) 2차 Scoring 구현: 안 B 채택, D 신규 인터페이스 확정

- 상태: `Implemented`
- 결정: D-037이 제안한 안 B(1차 Scoring 후 상위 5개만 혼잡도 보강 재계산)를
  D가 확인·채택한다. `RecommendationProvider.rerank_with_concentration()`(A가
  `protocols.py`에 미리 배선해둔 메서드)을 `RealRecommendationProvider`에
  실제로 구현했다.
- **A에 Protocol 시그니처 변경 요청**: `rerank_with_concentration(conditions,
  first_pass, concentration)`엔 원본 `RecommendationContext`가 없어 날씨
  근거 문장을 1차와 동일하게 재구성할 방법이 없었다 — 4번째 파라미터
  `context: RecommendationContext`를 추가해달라고 요청했고, `agent_runtime.py`의
  `_apply_concentration_rerank()`가 이미 갖고 있던 `tool_context`를 그대로
  전달하도록 배선을 바꿨다(`protocols.py`, `agent_runtime.py`, `stubs.py`의
  Fake 구현체, `tests/test_agent_runtime.py`의 테스트 더블 모두 시그니처 갱신).
- concentration_score 공식: 4단계 구간 매핑 대신 **선형 정규화**를 채택했다
  (`concentration_score(rate, seek) = clamp(rate/100, 0, 1)`, AVOID는
  `1 - rate/100`). distance/remaining_operating_time과 같은 연속값 스타일을
  유지하고 정보 손실을 피하기 위함(`domain/scoring.py::concentration_score()`).
- 가중치: A 제안값(`CONCENTRATION_WEIGHTS` — 날씨 0.35/운영시간 0.35/거리
  0.15/혼잡도 0.15)을 그대로 채택했다. 이 상수는 2차 Scoring 전용이라 1차
  `DEFAULT_WEIGHTS`(0.40/0.40/0.20)에는 영향이 없다 — D-037이 걱정했던
  "혼잡도 무관심 실행에도 기존 가중치가 미세하게 바뀌는 문제"는 안 B 구조라
  애초에 발생하지 않는다.
- 구현 방식: 2차 Scoring은 새 `ScoringCandidate`를 다시 만들지 않고, 1차
  `RecommendationItem.feature_scores`(weather/remaining_operating_time/distance,
  concentration과 무관하게 불변)를 그대로 재사용해 concentration만 추가하고
  `redistribute_weights()`(기존 함수 재사용)로 재분배한 뒤 재정렬한다.
  결측(C가 `no_data`/`unavailable` 반환) 처리는 weather/remaining_operating_time과
  동일한 개별 결측 패턴을 따른다.
- Evidence/Explanation 확장: `evidence.py`의 `_FEATURE_ORDER`(1차, 3-Feature)는
  그대로 두고 `CONCENTRATION_FEATURE_ORDER`(4-Feature)를 별도로 추가했다 —
  `_FEATURE_ORDER`를 직접 확장하면 1차 결과의 `feature_scores`에도 `concentration:
  null`이 항상 끼어들어 `test_scoring_fixture.py`의 `{c.feature for c in
  evidence.contributions} == set(ranked.feature_scores)` 검증이 깨지는 걸
  구현 중 발견해서 분리했다. `RankedCandidate`/`RecommendationEvidence`에
  `concentration_level: ConcentrationLevel | None = None`(4단계 구간 원본)을
  추가했다 — concentration_score는 이미 SEEK/AVOID 방향이 반영된 값이라
  notable 여부만으로는 실제로 붐비는지 한적한지 알 수 없어서, 문장 조립에는
  방향과 무관한 원본 구간을 따로 보존해야 했다.
- 범위 제외: `_CONCENTRATION_FINAL_LIMIT`(최종 3개) 확정, 안 A(초기 Context
  확장) 대비 이번 선택의 재검토는 A/기획 몫 — D는 2차 인터페이스 구현까지만
  책임진다.
- 확인 방법: `tests/test_scoring.py`(concentration_score·재분배 단위),
  `tests/test_explanation.py`(4단계 구간별 문장·임계값·결측),
  `tests/test_recommendation_pipeline.py`(AVOID/SEEK 재정렬 실제로 뒤집히는지,
  부분 결측, unverified 분리 유지), `tests/test_real_recommendation_provider.py`
  (Protocol 위임·seek 변환)로 검증. 전체 회귀(709 passed, 20 skipped) 확인.

### D-041 — 장소명 위치 해석: `places` DB 우선 조회

- 상태: `Implemented` (정확 일치 MVP 범위)
- 결정: 장소명 입력을 Naver Geocoding에 바로 전달하지 않는다. `ResolveLocationTool`이
  활성 `places` 행을 정확 일치로 먼저 조회해 TourAPI 기준 좌표를 사용하고, 미조회 시에만
  기존 별칭·주소 Geocoding 경로로 진행한다.
- 배경: Geocoding은 주소 중심 API라 `쌈지길` 같은 장소명은 `location_not_found`가 될 수
  있지만, 해당 장소는 TourAPI `places` DB에 좌표가 존재한다.
- 집중률: 장소 행에 `place_concentration_mappings`가 있으면 대표 집중률명을 함께 읽어
  INFO 직접 조회에 사용한다. 직접 조회에 좌표가 필요 없더라도, 매핑이 없는 경우의 0.5km
  fallback에는 같은 DB 좌표를 사용한다.
- 안전장치: Fake Provider 모드에서는 실제 Supabase 조회를 주입하지 않아 일반 테스트가
  외부 데이터에 의존하지 않는다.
- 범위 제외: 별칭·부분 일치, Naver Local Search, DB 미등록 일반 상호명 처리, RECOMMEND
  후보 보강의 매핑 연결은 후속 작업이다.


### D-042 — Real Provider 실패 시 Fake로 자동 전환하지 않는다

- 상태: `Accepted`, 코드에 이미 반영됨(요청 중 Provider를 교체하는 경로가 없음)
- 결정: Provider는 부팅 시점에 설정(`PROVIDER_MODE`, `*_PROVIDER`)으로 한 번 정해지고,
  요청 처리 중 Real → Fake 전환은 하지 않는다. 실패는 `unavailable`로 드러내거나 같은
  성격의 다른 Real 경로로 넘어간다.
- 이유: 조용한 폴백은 "실데이터를 보고 있는지"를 판단 불가능하게 만든다. 잘못된 데이터가
  정상 응답처럼 나가면 사용자도 개발자도 문제를 인지하지 못한다.
- 근거 사례: `npm run dev`가 `backend/.env`를 읽지 못해 전 Provider가 fake로 뜬 사건
  (커밋 `f201f0b`). 오류 없이 `"테스트 카페"`가 추천됐고, 실행 위치 문제임을 찾는 데
  시간이 걸렸다. 이후 `env_file`을 절대경로로 고정하고 부팅 시 Provider 모드를 로그로
  남기도록 했다.
- 이미 이 원칙에서 나온 결정들:
  - `validate_provider_config()` — real 모드에 키가 없으면 첫 요청이 아니라 **부팅에서** 실패
  - Supabase 상세조회 실패 시 요청 중 TourAPI fallback 없음(D-041 관련)
  - Local Search 장애 시 Geocoding으로 진행 — Fake가 아니라 다른 Real이라 위배 아님(D-041)
- 범위 밖: 재시도(retry)와 서킷 브레이커는 이 결정과 별개다. 같은 Real Provider를 다시
  부르는 것은 허용된다.


### D-043 — 혼잡도 장소 결정은 이름 우선, 좌표는 최후수단

- 상태: `Accepted`, 2026-08-04 구현 완료. 마이그레이션(`20260804055402`)과 매핑 101건
  적재까지 반영했다.
- 배경: 집중률 API의 `tAtsNm`은 부분 일치 검색인데, **공백이 든 값을 넘기면 0건**이
  돌아온다(2026-08-04 실측: `운현궁` 30건, `서울 운현궁` 0건). 그래서 정식 명칭을 그대로
  조회에 쓸 수 없고, 공백 없는 검색어를 따로 뽑아야 한다.
- 확인된 오답(현재 실서비스):
  - `북촌 혼잡해?` → `tAtsNm='북촌'`이 2곳을 반환하고 첫 행인 **북촌생활사박물관 52.19**를
    답한다. 의도한 북촌한옥마을은 61.97이다.
  - `종로 혼잡해?` → 3곳이 걸리고 **낙지볶음 골목 77.08**을 "종로의 혼잡도"로 답한다.
  - `종묘` → 종묘광장공원(35.28)이 섞여 오지만 응답 순서 덕에 우연히 맞는다. 순서가
    바뀌면 조용히 틀린다.
- 결정한 우선순위:
  1. DB `places` 정확 일치 → 매핑 사용 (경복궁·종묘)
  2. 로컬 검색으로 이름을 얻은 뒤 **그 이름으로 DB 재조회** → 매핑 사용 (북촌)
  3. 좌표 최근접 매핑 장소 → `is_proxy=true`로 어느 장소인지 밝힘 (종로)
  4. 반경 밖 → 정보 없음
- 좌표를 주 경로로 올리지 않는 이유: 넓은 장소는 대표점이 부정확하다. 로컬 검색이 준
  "북촌 한옥마을" 좌표 기준 최근접은 **가회민화박물관(27m)**이고 북촌한옥마을은 293m로
  밀린다. 종묘와 종묘광장공원도 67m 차이라 지오코딩이 흔들리면 뒤바뀐다.
- 끊겨 있는 지점 두 곳:
  - `resolve_location.py`의 `_local_search_success()`가 `concentration_name`을 채우지
    않는다 — 로컬 검색이 얻은 이름으로 매핑을 다시 찾지 않는다.
  - `find_active_places_by_name()`이 정확 일치뿐이라 "북촌 한옥마을"이 "북촌한옥마을"과
    안 맞는다. 공백 무시 조회가 필요하다.
- 폴백 축소: `select_concentration_forecast()`는 이름이 안 맞으면 `forecasts[0]`을 쓴다.
  **여러 장소가 왔는데 정식 명칭 일치가 없으면 `no_data`**로 바꾼다. 한 곳만 왔을 때는
  표기 차이여도 그 장소가 맞으므로 현행을 유지한다. 틀린 값보다 "정보 없음"이 낫다.
- 검색어와 정식 명칭 분리: `primary_concentration_name`에 `앞길`·`100주년` 같은 검색어를
  넣으면 컬럼 의미가 어긋나고, "별칭 첫 항목이 정식 명칭"이라는 암묵 규약이 생긴다.
  `concentration_search_key` 컬럼을 추가해 조회용과 대조용을 나눈다(nullable로 두면 기존
  데이터가 그대로 동작해 배포 순서를 안 따져도 된다).
- 검색어 추출 규칙(`build_concentration_mappings.py`에 구현·테스트 완료):
  공백 없으면 그대로 → 괄호·대괄호 부기 제거 → 집중률 목록 안에서 유일한 최장 토큰.
  유일성은 **집중률 API 목록(113건) 안에서만** 따진다. `places`에 "한옥"을 쓰는 장소가
  25건 있어도 `tAtsNm`은 집중률 데이터셋만 검색하므로 무관하다. 짧고 흔한 토큰을 피해
  최장을 고르는 이유는, 나중에 장소가 추가되면 모호해질 수 있어서다. 이 계산은 수집한
  목록이 완전하다는 전제에 기대므로 **매핑할 때마다 다시 계산**해야 한다.
- 저장소 이름 조회는 좁은 것부터 넓힌다: 정확 일치 → 공백 무시(`북촌 한옥마을` ↔
  `북촌한옥마을`) → 괄호 부기(`종묘` → `종묘 [유네스코 세계유산]`) → 사람이 지정한 별칭
  (`창덕궁` → `창덕궁과 후원 [유네스코 세계유산]`). 접두 매칭으로 넓히지 않는다 —
  `창덕궁*`은 낙선재·약다방·상품관까지 11건을 끌어온다.
- 별칭은 "이 장소를 가리키는 다른 이름"이다. 집중률 API에 있을 필요가 없다(`창덕궁`은
  없다). 조회는 `concentration_search_key`가 맡으므로 별칭을 집중률 목록으로 거르지
  않는다. 이 완화로 넣어두고도 쓰이지 않던 `청와대` 별칭이 함께 살아났다.
- 구현 후 실측(2026-08-04):

  | 질의 | 이전 | 이후 |
  | --- | --- | --- |
  | 북촌 | 북촌생활사박물관 52.19 | **북촌한옥마을 61.97** |
  | 종로 | 낙지볶음 골목 77.08 | 되묻기 |
  | 종묘 | 67.69(응답 순서에 의존) | **67.69(이름 대조로 확정)** |
  | 종묘광장공원 | — | **35.28(별개로 구분)** |
  | 창덕궁 | 되묻기 | **창덕궁과 후원 60.91** |
  | 청와대 | 되묻기 | **청와대 앞길 33.43** |
  | 서울 운현궁 | 조회 0건 | **69.42** |
  | 내자상회 | 정보 없음 | **사직공원 43.3(`is_proxy`)** |

- fake 환경에는 저장소가 없어 INFO 혼잡도가 전부 `no_data`로 막힌다.
  `FakePlaceLocationRepository`를 추가하고 `ProviderSource.FAKE_PLACES`로 구분한다 —
  fake 저장소가 실저장소로 보이면 안 된다(D-042).
- 남은 과제: `종로`처럼 지역·도로 단위 질문은 최근접 한 곳으로 대표시키는 것이 맞는지
  자체가 의문이다(종로는 길이 2.7km). 우선 `is_proxy`로 밝히고 넘어가되 별도로 다룬다.
  매핑 101건 전수 조회 검증(`verify_concentration_mappings`)도 아직 실행하지 않았다.

### D-044 — 지원 지역 밖 위치는 해석 단계에서 unsupported로 끊는다

- 상태: `Accepted`, 2026-08-04 구현 완료.
- 문제: 종로구 밖 위치를 막는 코드가 없었다. `resolve_location`의 첫 줄은 "종로구 범위의
  좌표로 해석"이라고 적혀 있지만 실제로 좌표를 검사하지 않았고, 종로구 랜드마크 별칭
  테이블이 결과적으로 그 역할을 대신하는 것처럼 보였다.
- 증상: 세 경로가 각각 다른 이유로 실패하며 **모두 틀린 안내**를 냈다.

  | 경로 | 실패 지점 | 사용자에게 나간 말 |
  | --- | --- | --- |
  | 추천 | 좌표는 마포, 검색은 종로 고정 → 교집합 0건 | "조건에 맞는 곳을 찾지 못했어요. 검색 범위를 넓혀볼까요?" |
  | 혼잡도 | 매핑 없음 → 0.5km 내 종로 장소 없음 | "이 장소 유형은 혼잡도 데이터가 없어요." |
  | 되묻기 | 지역 검색 후보를 못 좁힘 | "종로구 안에서 어느 장소인지 알려주세요" |

  추천 문구가 특히 나쁘다 — 범위를 넓혀도 종로구 밖은 영영 나오지 않는데 넓혀보라고 한다.
- 결정: `ResolveLocationTool`이 좌표를 얻은 직후 한 곳에서 판정한다. 아래 로직은 모두
  "종로구 안"을 전제로 하므로(장소 검색이 `lDongSignguCd` 고정, 집중률 매핑도 종로구
  장소만 보유) 해석 단계에서 끊는 것이 맞다. 세 경로가 한 번에 정리된다.
- 상태·코드는 이미 계약에 있었다 — `ToolStatus.UNSUPPORTED`, `cause="outside_supported_region"`,
  `_error_message()`의 "현재는 서울특별시 종로구 내 장소만 지원합니다."까지 준비돼 있고
  A의 `response_composer`도 `unsupported`를 종결 처리한다. **판정하는 코드만 없었다.**
- 판정 방법으로 폴리곤을 쓴다.

  | 후보 | 채택 여부 |
  | --- | --- |
  | 경계 상자 | 기각. 종로구가 남북으로 길쭉하고 북악산 쪽으로 굽어 있다. 여유를 주면 중구 명동(37.5636)·서울역이 안쪽으로 들어온다. |
  | 역지오코딩 | 기각. 네이버는 별도 구독 상품이라 현재 키로 403이다. 구독하더라도 판정 하나에 외부 호출과 장애 지점을 매 요청 추가하게 된다. |
  | 폴리곤(채택) | 정적 데이터라 외부 호출 0. 좌표 194개, 8KB. 명동·서울역도 정확히 갈린다. |

- 저장소에서 해석된 장소는 판정을 생략한다. 이미 종로구 장소로 등록된 것이라 경계선에
  붙어 있어도 지원 대상이 맞다. 활성 844건 중 폴리곤 밖으로 판정되는 2건(북악산 숙정문,
  청계천 남쪽 행사)이 모두 저장소 장소라 이 규칙으로 해소된다.
- 지역 판정을 모호성 판정보다 앞에 둔다. 지원 범위 밖이면 "어느 장소인지" 되물어도
  소용없다. 지역 검색이 후보를 못 좁혔을 때도 찾은 후보가 전부 밖이면 지역 문제로 본다 —
  "부산 해운대"에 "종로구 안에서 어느 장소인지"라고 되묻지 않기 위해서다.
- 구현 후 실측(2026-08-04): 망원역·서울역·부산 해운대·강남역·제주도가 모두
  `unsupported`, 경복궁·북촌·내자상회·창덕궁·인사동길 44는 그대로 `success`.
- A 응답 문구도 함께 고쳤다. `_TOOL_UNSUPPORTED_MESSAGE`가 "죄송하지만 아직 지원하지 않는
  요청이에요"로 고정이라 무엇을 바꿔야 할지 알 수 없었다. `error.code`별 템플릿을 두고
  `unsupported_region`이면 "지금은 서울 종로구 안의 장소만 안내할 수 있어요."를 보낸다.
  RECOMMEND 경로는 코드를 받지 못하고 있어 `compose_chat_message(tool_error_code=...)`를
  추가했다. **A 담당 부재(2026-08-04)로 C에서 대신 수정했으므로 복귀 후 공유가 필요하다.**
- 경계 데이터 갱신: 행정구역 개편 시 `backend/resources/boundaries/README.md` 절차를 따른다.

### D-045 — 같은 역의 노선별 후보는 한 장소로 본다

- 상태: `Accepted`, 2026-08-04 구현 완료.
- 문제: "종로3가역 근처 카페"는 되묻기로 빠지는데 "종각역 근처 카페"는 추천이 나갔다.
  차이는 환승역 여부다. 지역 검색이 "종로3가역"에 1·3·5호선을 각각 돌려주는데, 이름이
  달라 정확 일치가 안 되고 첫 토큰은 셋 다 같아 못 좁히므로 재질문으로 떨어졌다.
- 되물어도 답이 될 수 없다. 카페를 찾는 사용자에게 몇 호선인지 묻는 것은 무의미하고,
  사용자가 "종로3가역 3호선"처럼 노선까지 적어야 진행된다. 검색 반경이 2km라 어느
  출입구를 골라도 결과는 같다.
- 결정: 첫 토큰이 모두 일치하는 후보가 **전부 교통 시설이고 서로 0.5km 이내**면 한
  장소로 보고 첫 후보를 쓴다. 둘 중 하나라도 어긋나면 기존대로 재질문한다.
- 거리 기준 근거 — 실측(2026-08-04) 역별 후보 간 최대 거리:

  | 역 | 후보 | 최대 거리 |
  | --- | --- | --- |
  | 청량리역 | 5 | 381m |
  | 서울역 | 5 | 341m |
  | 종로3가역 | 3 | 291m |
  | 시청역 | 2 | 267m |
  | 김포공항역 | 5 | 248m |
  | 공덕역 | 4 | 187m |
  | 왕십리역 | 5 | 137m |
  | 충무로역 | 2 | 47m |

  노선 수가 아니라 역사 구조가 거리를 결정한다(5개 노선인 왕십리역이 가장 좁다).
  관측 최대가 381m라 0.5km면 덮는다. 같은 역을 재조회했을 때 291m/170m로 흔들린 적이
  있어 여유가 필요하다.
- 카테고리를 함께 보는 이유: 거리만 보면 "종각역 김밥천국"처럼 역명을 그대로 앞에 붙인
  상호가 함께 묶인다. 그러면 "첫 후보를 임의로 고르지 않는다"는 원칙이 깨진다 — 쌈지길
  검색에서 정답이 3번째였던 것이 그 원칙의 근거다. 상호가 하나라도 섞이면 묶지 않는다.
- 카테고리 표기는 실측 4종을 덮는다: `지하철,전철` 25건, `KTX,SRT정차역`,
  `기차역`, `KTX정차역` 각 1건. 네이버가 표기를 바꾸면 조용히 재질문으로 돌아가므로,
  되묻기가 늘면 이 목록을 먼저 확인한다.
- 정확 일치가 중복인 경우(1단계)는 손대지 않았다. 이름이 완전히 같은 것은 서로 다른
  지점일 수 있어 성격이 다르다.
- `haversine_km`을 `app/geo.py`로 옮겼다. `tools`가 `agent_context`를 import하면 순환
  참조가 되고(agent_context가 tools를 쓴다), 같은 공식의 세 번째 사본을 만들지 않기
  위해서다. `app/domain/candidate_mapper.py`의 사본은 D 범위라 그대로 뒀다.

### D-046 — environment_type을 TourAPI 중분류(lcls_systm2) 기반으로 세분화

- 상태: `Implemented` (`app/domain/candidate_mapper.py::_environment_type()`)
- 배경: `environment_type`은 날씨 적합도(가중치 0.40)에 쓰이는데, 대분류(`category`)
  만으로는 실내외를 정확히 가릴 수 없다 — C의 실측 기준(2026-08-04 종로구 스냅샷) 관광지
  150건에 고궁·공원(실외)과 체험관(실내)이, 쇼핑 211건에 면세점 189건(실내)과 시장
  9건(실외)이 섞여 있다. C가 `bde29a3`(카테고리 어휘를 `PlaceType`으로 통일)·`5a3dacc`
  (C→A 계약에 `lcls_systm1/2/3` 3단계 분류 코드 추가)로 재료를 제공했고, 세분 판정
  규칙은 D가 정하기로 했다.
- 결정: 후보의 소분류 코드(`lcls_systm3`)를 `TourCategoryRegistry.get_by_small_code()`
  로 조회해 `(content_type_id, lcls_systm2)` 중분류 조합을 얻고, D가 정한 판정표와
  비교한다. 소분류 코드가 없거나 Registry에 없는 코드(과거 데이터 등)면 기존 대분류
  기반 최소 매핑(`_INDOOR_CATEGORIES`/`_OUTDOOR_CATEGORIES`)으로 폴백한다.
- 판정 기준: (1) 날씨를 실제로 막아주는 지붕·벽이 있는가를 핵심 질문으로 삼는다.
  (2) 중분류 안 소분류가 한쪽으로 쏠리면 그쪽으로, 진짜 애매하면 `unknown` 유지.
  (3) 같은 중분류 코드가 content_type에 따라 다른 뜻일 수 있어(`VE12`: 문화시설=서점,
  레포츠=카지노) `content_type_id`와 조합해서만 조회한다. (4) 확신 없으면 `unknown`
  유지 — 이미 안전한 중간값 폴백(맑음 0.85/보통 0.80/나쁨 0.60)이 있다.
- 결과: D가 다루는 6개 content_type(12/14/15/28/38/39)의 중분류 48개를 전수 검토해
  indoor 19개·outdoor 16개·unknown 13개로 판정했다(축제·공연·시장 일부 등 장소마다
  실내외가 갈리는 항목은 `unknown` 유지). 상세 판정 근거와 표는
  `package_D/feature-environment-type-classification.md` 참고(개인 기록, gitignored).
- 테스트: `tests/test_candidate_mapper_environment_type.py`에 48개 중분류 판정을
  고정하는 파라미터화 테스트, `tests/test_candidate_mapper.py`에 소분류 우선순위·폴백
  동작 검증 테스트를 추가했다.
- 경계 판단: `app/domain/`이 `app/providers/`(`TourCategoryRegistry`)를 직접 import하는
  첫 사례다. TECH-02가 없앤 건 "D가 실행 중에 C의 Tool을 직접 호출"하는 런타임 의존인데,
  이 조회는 JSON 파일을 프로세스 시작 시 한 번 로드해 참조만 하는 정적 테이블(부작용
  없음)이라 성격이 다르다고 보고 TECH-02 위반이 아니라고 판단했다. C도 `5a3dacc`에서 이
  조회 방식을 직접 지정했지만, 이 "정적 참조 vs 런타임 호출" 구분 자체는 C 확인 없이
  D가 내린 판단이라 별도로 확인 요청했다 — **C 승인 완료(2026-08-04): D의 판단대로
  진행하면 된다고 확인받음.**
- 범위 제한: 2차 Scoring(혼잡도, D-040)에는 영향 없음 — `environment_type`은 1차
  Scoring의 날씨 Feature 계산에만 쓰인다.

### D-047 — `rerank_with_concentration()` 시그니처 축소 제안: `RecommendationContext` → `WeatherCondition`

- 상태: `Implemented`(2026-08-05, 커밋 `baf4051`)
- 배경: D-040 구현 중 D가 요청해 `rerank_with_concentration()`에
  `context: RecommendationContext` 전체를 4번째 파라미터로 추가했다(날씨 근거
  문장을 1차와 동일하게 재구성하려면 원본 `WeatherCondition`이 필요하다는 이유).
  이후 D가 코드 리뷰 중 재확인한 결과, `services/recommendation_pipeline.py::
  rerank_with_concentration()`(141-282행) 안에서 `context`는 165행
  `_weather_condition_from_context(context)` 호출 **한 곳에서만** 쓰이고
  `location`/`places`/`concentration` 등 다른 필드는 전혀 참조하지 않는다는 걸
  확인했다 — "1차 호출과 반드시 동일한 context여야 한다"는 암묵적 전제를 없애기
  위해 시그니처를 `WeatherCondition` 값 하나로 좁히자고 A에 역제안했다.
- 제안 시그니처: `rerank_with_concentration(conditions, weather_condition:
  WeatherCondition | None, first_pass, concentration)` — 2번째 파라미터(현재
  `context`) 자리를 유지한 채 타입만 `RecommendationContext` → `WeatherCondition
  | None`로 좁힌다.
- **D 확인 필요 — 값 도출 필터 기준**: D 내부의 `_weather_condition_from_context()`
  (같은 파일 287-293행)는 `weather.status`가 `{"success", "partial"}`일 때 값을
  반환한다. A가 이미 갖고 있던 `to_weather_condition()`
  (`app/services/runtime/recommendation_transform.py:53-64`, 현재 프로덕션 어디서도
  호출되지 않는 dead code — 자체 테스트에서만 참조됨)은 `"success"`일 때만 값을
  반환해 필터 기준이 다르다. 시그니처를 좁히면서 A가 새 값을 도출할 때 D의 기존
  `{"success", "partial"}` 필터를 그대로 따라야 동작이 안 바뀐다 — A의 기존
  `to_weather_condition()`을 그대로 재사용하면 `"partial"` 상태일 때 결과가 조용히
  달라진다. 이 필터 기준을 D가 명시적으로 확인해달라.
- 변경 대상 파일: A 소유 — `app/services/runtime/protocols.py`(Protocol 선언),
  `app/services/runtime/agent_runtime.py`(`_apply_concentration_rerank()` 호출부),
  `app/services/runtime/stubs.py`(`FakeRecommendationProvider`, 내부에서
  `context`/`conditions` 둘 다 안 쓰므로 기계적 변경). D 소유 —
  `app/services/runtime/real_recommendation_provider.py`(48-58행, `context`를
  그대로 전달하던 부분), `app/services/recommendation_pipeline.py`(141-148행,
  실제 로직). 테스트 3파일(`test_agent_runtime.py`,
  `test_real_recommendation_provider.py`, `test_recommendation_pipeline.py`)
  총 12개 함수가 이 시그니처를 만든다.
- **왜 A가 지금 코드를 안 바꾸는지**: `protocols.py`의 Protocol 선언은 A 소유지만,
  Real 구현체(`RealRecommendationProvider`/`recommendation_pipeline.py`, D 소유)가
  같은 순간에 같이 안 바뀌면 실제 SEEK/AVOID 요청에서 D 코드가 `context.weather`를
  호출하려다 `WeatherCondition` 값 객체에 그 속성이 없어 `AttributeError`로 깨진다.
  D-040은 현재 정상 동작 중이므로, A 혼자 반영해서 이걸 망가뜨리지 않는다 — D가 위
  필터 기준을 확인하면 A/D 양쪽 파일을 같은 타이밍에 반영한다.
- 확인 방법(채택 시): 위 12개 테스트 함수 전부 시그니처 갱신 후 통과 확인, 특히
  `test_recommendation_pipeline.py`의 partial-weather 케이스로 필터 기준 회귀가
  없는지 확인.
- **구현 완료 메모(2026-08-05, 커밋 `baf4051`)**: 위에서 확인을 요청했던 필터
  기준은 D의 `{"success", "partial"}`로 확정됐다 — `to_weather_condition()`
  (`recommendation_transform.py`)의 필터를 `"success"` 단독에서
  `{"success", "partial"}`로 넓히고 반환 타입도 `WeatherCondition | None`로
  바꿔 그대로 재사용했다. `protocols.py`/`real_recommendation_provider.py`/
  `recommendation_pipeline.py`/`stubs.py`와 관련 테스트가 모두 이 커밋에서
  같은 타이밍에 반영됐다.

### D-048 — MODIFY 경로 exclude_tags/special_requirements Add/Remove 정합화 (제안, 범위 확정 필요)

- 상태: `Proposed`(A 제안, 구현 전 범위 확정 필요)
- 배경: B(이태화)가 티켓 댓글로 보고한 `_serialize()` int→str 버그를 고치면서,
  같은 세션에서 `_full_replace_operations()`(RECOMMEND 경로)의
  `exclude_tags`/`special_requirements`가 B의 field_spec.py(Add/Remove만 허용,
  Update 없음 — agent-state-contract-v1.md §2.2)와 안 맞아 `unsupported_operation`
  으로 조용히 드롭되던 버그도 함께 발견해 고쳤다(RECOMMEND는 `Add`로 변경
  완료). 그런데 `_changed_field_operations()`(MODIFY/CHANGE_CONDITION 경로,
  `state_transform.py:207-226`)는 `changed_fields`에 포함된 모든 필드에 동일하게
  `Update`를 쓴다 — `exclude_tags`/`special_requirements`가 MODIFY로 바뀔 때도
  똑같이 `unsupported_operation`으로 드롭된다(1a와 같은 계약 위반 패턴이 MODIFY
  경로에도 남아 있음).
- 왜 RECOMMEND와 같은 방식(무조건 `Add`)으로 못 고치는지: RECOMMEND는
  `reset_scope="soft"`로 baseline이 항상 비어 있어 `Add`-with-full-list가
  replace와 동치이지만, MODIFY는 incremental이라 기존 `exclude_tags`/
  `special_requirements`가 비어있지 않다. LLM이 전체 교체 리스트를 돌려줬을 때
  그대로 `Add`하면 새 값이 append+dedupe되어 기존 제외 목록과 합쳐질 뿐
  교체되지 않는다 — "이제 이것만 제외해줘"처럼 사용자가 치환을 의도했을 때
  의미가 달라진다.
- 제안(설계는 후속 세션): diff 기반으로 (LLM이 준 새 값 − 기존 값)은 `Add`,
  (기존 값 − LLM이 준 새 값)은 `Remove`로 나눠 보내는 방식이 필요해 보인다.
  다만 diff 대상이 되는 "기존 값"을 어디서 가져올지(`session_context.
  user_conditions` 재사용 가능해 보임), LLM이 항상 전체 교체 리스트를 주는지
  아니면 증분만 주는지(조건 추출 프롬프트 계약 재확인 필요)는 이번 세션에서
  답을 내지 않는다.
- 확인 필요: 이 diff 로직을 스코핑할 다음 세션에서 (1) LLM 프롬프트가
  exclude_tags/special_requirements를 항상 전체 리스트로 주는지 증분으로
  주는지, (2) diff 계산에 쓸 "기존 값" 소스가 `session_context.user_conditions`
  로 충분한지 확인한다.
- 변경 대상 파일(후속): `backend/app/services/interpret/state_transform.py`
  (`_changed_field_operations()`), `backend/tests/test_state_transform.py`.
- 왜 지금 구현하지 않는지: diff 알고리즘 설계와 LLM 프롬프트 계약 확인이 먼저
  필요한 별도 스코프의 작업이라, 이번 세션의 계약 위반 수정(1a 유형)과 섞으면
  리뷰 범위가 커진다. 이번 세션은 발견 사실을 기록만 한다.

### D-049 — `conditions.weather`(사용자 발화 기반 5단계 날씨 값)가 죽은 필드로 보임 (발견만, 미확정)

- 상태: `Observed`(발견만 기록, 코드 미변경 — 원 설계 의도 확인 필요)
- 배경: D-038(`api_context.api_weather` 죽은 코드 제거) 이후, "사용자가 '비 온다'고
  직접 말한 값과 기상청 API 값이 다르면 어떻게 되는지" 질문에 답하려고
  `conditions.weather`(LLM이 발화에서 추출하는 5단계 값 — rain/snow/hot/cold/good,
  `weather_intent`와는 별개 필드)의 실제 소비처를 grep으로 재확인했다.
- 발견: `conditions.weather`는 `to_agent_context_request()`를 통해 C의 요청
  페이로드에는 실리지만(`app/services/runtime/context_transform.py`), **C도 D도
  이 값을 읽는 코드가 없다** — `app/agent_context/*.py`, `app/domain/scoring.py`,
  `app/domain/candidate_mapper.py`, `app/services/runtime/response_composer.py`,
  `app/state/*.py` 전수 grep 결과 전무. 실제 Scoring의 날씨 Feature(가중치 0.40,
  `domain/scoring.py::_weather_fit_score()`)는 오직 `context.weather`(C가 기상청
  API로 직접 조회한 3단계 값, `weather_intent != IGNORE`일 때만 호출)만 사용한다.
  `environment`(indoor/outdoor 하드 필터) 역시 `weather_intent`(AVOID/ENJOY)를 보고
  LLM이 발화 시점에 직접 정하는 값이라, API 결과나 `conditions.weather`와는
  무관하게 이미 확정된다.
- 결과적으로 사용자가 "비 온다"고 말한 그 원문 판정값 자체는 필터에도 점수에도
  전혀 반영되지 않는다 — 하드 필터는 `weather_intent`(발화 즉시 판별)가, 연속
  점수는 `context.weather`(API 실측)가 각각 담당하고, 둘이 서로 다를 때 감지하거나
  사용자에게 알리는 로직은 존재하지 않는다.
- D-038의 `api_weather`(B 소유, 조회는 하되 아무도 안 읽음)와 증상은 비슷하지만
  원인 층위가 다르다 — `api_weather`는 "조회했지만 안 읽힘"이었고, 이건 "LLM이
  추출은 하지만(B에도 저장됨) 하류(C/D) 어디서도 안 읽힘"이다.
- 이번 세션에서 결정하지 않는 것: `conditions.weather`가 (1) 애초에 미완성으로
  남은 필드인지(예: "사용자 말과 API가 다르면 사용자 말을 우선하거나 재확인한다"
  같은 기능을 염두에 두고 만들어졌으나 그 소비 로직이 아직 없는 경우),
  (2) 이제는 불필요해진 필드인지(정보는 `weather_intent`/`environment`로 이미
  충분히 반영되므로) — 원 설계자(A/D) 확인이 먼저 필요해 코드는 건드리지 않는다.
- 확인 필요: `conditions.weather` 필드의 원래 설계 의도, 그리고 필요하다면
  "사용자 발화와 API 값이 다를 때" 처리 방침(무시/재확인/사용자 발화 우선) 결정.

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
| 2026-07-27 | D-030 날씨 결측·임계값 미달로 explanations가 비는 두 케이스에 warning 커버리지 보완 |
| 2026-07-27 | D-029 A 담당과 API Contract 협의 반영 완료, Explanation Rule 정의 문서(`docs/design/recommendation-explainability.md`) 추가 |
| 2026-07-27 | D-031 Explanation 문장을 고정 텍스트에서 거리/남은 운영시간/날씨·환경 계산값 기반 사실 문장으로 구체화 |
| 2026-07-28 | D-032 A 요청으로 `run_recommendation_pipeline_from_context()` 신규 진입점 추가, 기존 Tool 기반 파이프라인과 공존(이후 D-034에서 공존 종료, 완전 삭제) |
| 2026-07-28 | D-033 Agent Runtime `RecommendationProvider`에 `RealRecommendationProvider` 연결, `run_agent()` 기본 provider를 Fake에서 실제 구현으로 교체 |
| 2026-07-28 | D-034 `run_recommendation_pipeline()`(Tool 직접 호출) 완전 삭제, `/api/recommendations` 라우터를 `run_recommendation_pipeline_from_context()` 기반으로 마이그레이션 |
| 2026-07-28 | D-035 develop 재병합 시 발견된 `RealRecommendationProvider` 중복 구현 정리, mintee의 `real_recommendation_provider.py`로 통합 |
| 2026-07-31 | D-038 날씨 warning을 IGNORE(미언급)와 조회 실패로 분리, §10 불일치·날씨 조회 경로 이원화를 TODO로 기록 |
| 2026-08-02 | D-039 되묻기 답변을 기존 요청의 연속으로 처리하고 조건 유지·플래그 저장 및 소비 규칙을 기록 |
| 2026-08-02 | D-040 혼잡도 2차 Scoring 구현(안 B 채택), `rerank_with_concentration()` 신규 인터페이스와 concentration Feature를 Evidence/Explanation에 추가, A에 Protocol `context` 파라미터 추가 요청 |
| 2026-08-03 | D-042 Real Provider 실패 시 Fake 자동 전환을 하지 않는 공통 정책을 명시 |
| 2026-08-04 | D-043 혼잡도 장소 결정 순서(이름 우선·좌표 최후)와 `tAtsNm` 공백 제약·검색어 추출 규칙 기록 |
| 2026-08-04 | D-043 구현 완료 — `concentration_search_key` 컬럼 추가, 매핑 101건 적재, 저장소 이름 조회를 부기·별칭까지 확장 |
| 2026-08-04 | D-044 지원 지역 밖 위치를 해석 단계에서 `unsupported`로 끊도록 구현, 종로구 경계 폴리곤 리소스 추가 |
| 2026-08-04 | D-045 같은 역의 노선별 후보를 한 장소로 묶어 환승역 재질문을 없앰, `haversine_km`을 `app/geo.py`로 통합 |
| 2026-08-04 | D-046 environment_type을 TourAPI 중분류(lcls_systm2) 기반으로 세분화 구현 반영(indoor 19/outdoor 16/unknown 13), 판정표 고정 테스트 추가 |
| 2026-08-05 | D-047 D-040 리뷰 후 A에 `rerank_with_concentration()` 시그니처 축소(`RecommendationContext` → `WeatherCondition`) 역제안, D 확인 필요 사항으로 필터 기준 명시 |
| 2026-08-05 | B 리뷰 반영: `_serialize()` int→str 버그·RECOMMEND `exclude_tags`/`special_requirements` Update→Add 수정, `api_context.api_weather` 죽은 코드 제거, `PROMPT_VERSION` 신설(record_trace·StateApplyRequest 양쪽 연결) 및 D-040의 `SCORING_VERSION` 최초 연결. D-048로 MODIFY 경로의 동일 계약 위반은 제안만 기록 |
| 2026-08-05 | D-049 `conditions.weather`(발화 기반 5단계 값)가 C/D 어디서도 안 읽히는 죽은 필드로 보인다는 발견을 기록(코드 미변경, 원 설계 의도 확인 필요) |
