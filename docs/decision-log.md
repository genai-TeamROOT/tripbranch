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
| LLM Provider | 공급자, 모델, timeout, fallback | 모델 fallback `Accepted`(D-052, 구현 완료). 공급자 전환·timeout 정책 자체는 여전히 `TBD` |
| Chat 계약 naming | Backend Python/JSON `snake_case` | `Accepted` |
| Backend 상태 저장 | Supabase 테이블과 캐시 역할 | `TBD` |
| Frontend 저장 | `sessionStorage` 유지 또는 `localStorage` 전환 | `TBD` |
| Scoring v1 | Feature/가중치/tie-break `Implemented`(D-008); Evidence·평가 Fixture `Implemented`(D-027); 응답 Evidence 노출·E2E 통합 `Implemented`(D-028); Explainability Layer v1 `Accepted`(D-029, A 협의 반영 완료); warning 커버리지 보완 `Implemented`(D-030); Explanation 문장 구체화 `Implemented`(D-031); RecommendationContext 진입점 `Implemented`(D-032); Agent Runtime RecommendationProvider 연결 `Implemented`(D-033); Tool 직접 호출 파이프라인 삭제·레거시 라우터 마이그레이션 `Implemented`(D-034); develop 재병합 시 RecommendationProvider 중복 정리 `Implemented`(D-035); 혼잡도 2차 Scoring(`rerank_with_concentration()`) `Implemented`(D-040) | 구현 완료 |
| 혼잡도 fallback | 장소 근접치, 구 단위, Feature 제외 | INFO 전용 장소 근접치 적용(D-036), RECOMMEND 확장은 후속 검토 |
| 혼잡도 반영 방식 | 초기 Context 확장(안 A) vs 1차 Scoring 후 상위 5개 보강 재계산(안 B) | 안 B 채택, `rerank_with_concentration()` 구현 완료(D-040) |
| 운영시간 파싱 | 기본 시간·월별·주간 휴무 구현, 요일 범위 전개·요일별 구간 분리·미열거 요일 휴무 유도 `Implemented`(D-058), 공휴일·회차 예외 확대 | `부분 구현` |
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
- 주의: 이후 D-049(2026-08-05)에서 `weather_intent`에 `NO_MENTION`을 도입하면서
  "언급 없음=IGNORE" 전제가 해소됐다. 이 항목의 IGNORE 서술은 당시 구현 기준의
  배경 설명이며, 현재 동작 기준은 D-049를 따른다.
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
  턴 간 되묻기 상태를 보존하려면 별도 migration과 store 매핑을 추가해야 한다. 단독 위치 답변의
  분류 문제는 TP-67(PR #113)과 D-053에서 결론이 났다 — 지명에 근처/조사가 붙은 발화는 이전
  추천이 있으면 `MODIFY`로 분류하고, 지명 단독은 정보 조회 의도로 보아 `INFO`를 유지한다.

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

### D-049 — `conditions.weather`(사용자 발화 5단계 날씨 값) 소비 경로 복구

- 상태: `Implemented` (2026-08-05)
- 배경: D-049 발견 시점에는 `conditions.weather`가 C 요청 페이로드에만 실리고
  실제 Scoring에서는 전혀 읽히지 않아 죽은 필드처럼 보였다.
- 결정:
  - `weather_intent` 의미를 분리한다.
    - `NO_MENTION`: 날씨 언급 없음(기본) → C가 날씨 API 조회
    - `IGNORE`: "날씨 상관없어" 명시 → API 미조회 + 날씨 가중치 제외
    - `AVOID`/`ENJOY`: 날씨 언급 있음 → API 미조회, 사용자 발화 weather를 사용
  - 사용자 발화 weather(5단계: rain/snow/hot/cold/good)의 D 입력 변환/판단은
    C가 담당하고, A는 기존처럼 조건을 C에 전달한다.
- 효과:
  - `conditions.weather`가 실제 1차 Scoring 날씨 Feature에 반영된다.
  - "언급 없음"과 "무관 명시"가 분리되어, 조회 게이팅과 문서/구현 불일치가 해소된다.
  - 날씨 API 호출은 `NO_MENTION` 경로에서만 일어난다.
- 후속 확인:
  - `AVOID/ENJOY` 방향(선호 반영) 자체는 별도 판정 로직 개선 범위로 유지한다.

### D-050 — 혼잡도 2차 Scoring 결과: "순서"는 B에 남지만 "값"은 안 남음 (발견만, 미확정)

- 상태: `Observed`(발견만 기록, 코드 미변경 — 필요 여부 확인 필요)
- 배경: `concentration-e2e-verification.md` 작성 중 "혼잡도까지 포함한 답변 내용이
  저장되는지" 질문에 답하려고 `agent_runtime.py`의 노출 기록 경로(7단계)를
  재확인했다.
- 발견: `recommendations` 변수가 6-1단계(`_apply_concentration_rerank()`)에서
  재순위 결과로 재할당된 뒤 7단계 `record_recommendation()`에 그대로 쓰이므로,
  B에 기록되는 노출 이력의 **순서(rank)는 혼잡도 반영 이후 최종 순서**가 맞다.
  다만 `RecommendedPlace`(`app/state/service.py:102-106`)는 `place_id`/`rank`
  두 필드만 가진 스키마라, 혼잡도 점수(`concentration_rate`)·등급(`혼잡`/`보통`/
  `한산`)·`feature_scores`/`weights_used` 같은 세부 근거 값은 그 턴의 HTTP 응답
  에만 존재하고 B에는 전혀 남지 않는다. 나중에 "그때 왜 이 순서였는지"를 다시
  보고 싶어도 저장된 건 순서뿐이다.
- 참고: 이건 혼잡도에만 국한된 문제가 아니라 날씨·운영시간·거리 등 1차 Scoring의
  다른 Feature 값도 마찬가지로 저장 안 된다 — `RecommendedPlace`가 원래부터
  순서만 기록하는 설계였다. 혼잡도 검증 과정에서 다시 확인된 것일 뿐 새로 생긴
  문제는 아니다.
- 이번 세션에서 결정하지 않는 것: 이 세부 근거 값들을 B에 남길 필요가 있는지
  (예: 추후 분석/디버깅/사용자에게 "왜 이 순서인지" 재설명 등의 용도) — 필요성
  자체가 불확실해 원 설계 의도·B팀 확인 없이 스키마를 확장하지 않는다.
- 확인 필요: `RecommendedPlace`에 세부 Feature 값을 남길 실익이 있는지, 있다면
  B의 저장 계약(`agent-state-contract-v1.md`) 확장이 필요한지 결정.

### D-051 — 날씨는 C가 사실을, D가 판정을 맡는다

- 상태: 사실 전달과 `NO_MENTION` 수용은 `Implemented`(2026-08-05, PR #97),
  판정 이관(사실 기반 + 발화 우선)은 `Implemented`(2026-08-05, D). 2차 Scoring
  배선 정리(A)와 `WeatherForecast.condition` 필드 제거(C)도 `Implemented`
  (2026-08-06). 도메인 모델 `WeatherForecastSlot.condition`과 그 연쇄
  (`SelectedWeatherForecast.condition`, `map_sky_pty_to_condition()`,
  `tool_intelligence` 계약, `fake_weather_condition` 설정)도 `Implemented`
  (2026-08-06, C가 D 소유 파일 1줄을 포함해 처리). 사실/판정 분리는 이로써
  완결됐다 — 남은 항목(`conditions.environment`, `tool_intelligence`의 벤더 코드
  노출)은 아래 "남은 것" 참고
- 배경: D-049(`conditions.weather` 미사용)를 확인하다가 날씨 처리 전반을 훑었고,
  서로 얽힌 문제 다섯 개가 나왔다. 하나씩 고치면 다른 하나가 어긋나는 구조라 함께
  정리한다.

#### 확인된 문제

1. **`ENJOY`일 때 결과가 반대로 나온다.** `weather_intent`를 읽는 곳은
   `tool_rules.py:47` 한 줄뿐이고 조회 여부만 정한다. `AVOID`와 `ENJOY`가 완전히
   동일하게 처리되어, "비 오는 날 산책하고 싶어"에 실내가 만점(BAD+indoor=1.00),
   야외가 최하점(BAD+outdoor=0.30)이 된다.
2. **기온이 판정에 없다.** `T1H`가 파싱 필터에서 제외돼 계약의
   `temperature_celsius`가 항상 `null`이었다. 폭염 35도에 SKY=맑음이면 `GOOD`이 되어
   야외를 우대한다.
3. **비와 눈이 구분되지 않는다.** PTY는 값과 무관하게 전부 `BAD`로 뭉개진다.
4. **`IGNORE`가 두 의미를 겸한다.** "언급 없음"과 "무관하다고 명시함"의 동작이
   반대인데 값이 하나다. `int-01-recommend.md §10`과 구현이 서로 반대다(D-038 TODO 1).
5. **`conditions.environment`도 소비처가 없다.** `app/` 전수 확인 결과 `stub.py`뿐이다.
   D-049는 이 필드를 "indoor/outdoor 하드 필터"로 서술했지만 **실제로 필터하는 코드는
   없다** — Scoring의 하드 필터는 영업시간뿐이다. 해당 서술은 정정이 필요하다.

#### 결정 — 역할 분리

```
C   기상청 조회 → 벤더 코드를 도메인 용어로 번역 → 사실만 전달
D   사실 + weather_intent → good/neutral/bad 판정 → 점수 계산
```

판정에는 사용자 의도가 필요하고, 그 값을 가진 쪽은 D다
(`RecommendationProvider.recommend(conditions, context, excluded_place_ids)`).
**A→D 계약 변경 없이** 의도를 쓸 수 있다.

C가 판정을 맡으면 `WeatherCondition`의 의미가 "날씨 상태"에서 "이 사용자에게 좋은가"로
바뀌어, `explanation.py:94`가 비 오는 날 "좋은 날씨에 적합한 야외 장소예요"라고 말하게
된다. 사실과 판단을 나누면 그 문제가 생기지 않는다.

기상청 코드(PTY/SKY)는 그대로 넘기지 않는다. 코드 체계가 D까지 새면 기상 API를 바꿀 때
D도 함께 고쳐야 한다. 번역만 C가 하고 판정은 하지 않는다.

#### 완료된 것 (`Implemented`, PR #97, C)

- 계약에 사실 3종 추가: `precipitation`(none/rain/snow/sleet/shower),
  `sky`(clear/cloudy/overcast), `temperature_celsius`
- `T1H` 파싱을 Provider부터 계약까지 연결 (문제 2)
- PTY 코드 번역으로 비·눈 구분 가능 (문제 3)
- `NO_MENTION` 수용과 게이팅 명시화 (문제 4의 C 몫)

#### 완료된 것 (`Implemented`, 2026-08-05, D)

- `app/domain/weather_judgment.py` 신설: `judge_weather_condition_from_facts()`
  (사실 기반, 강수 > 기온 > 하늘 순 판정 + 원인 태깅), `judge_weather_condition_from_stated()`
  (발화 5단계 기반), 공용 `_apply_intent()`(ENJOY는 원인이 강수(비/눈)인 BAD만
  GOOD으로 뒤집음 — 문제 1 해소, 기온이 원인인 BAD는 안 뒤집음).
- PR #102(C)가 `run_recommendation_pipeline_from_context()`에 연 `conditions`
  파라미터를 받아, `resolve_weather_condition()`(구 `_weather_condition_from_context()`,
  public으로 전환)이 `context.weather`(사실)를 우선 쓰고 없으면 `conditions.weather`
  (발화값)로 대체하도록 배선(`recommendation_pipeline.py`). AVOID/ENJOY에서 발화
  날씨가 조용히 빠지던 문제(PR #102가 부분 해결)가 완전히 해소된다.
- `weather_ignored` 판별도 함께 정리: `conditions`가 있으면 `IGNORE`만 "제외했어요"
  문구를 쓰고, 그 외 날씨 결측은 전부 "확인 못 했어요"로.
- `resolve_weather_condition(context, conditions)`을 **public 함수로 노출**했다 —
  1차 Scoring 내부에서만 쓰던 걸 2차 Scoring 호출자(A, `agent_runtime.py`)도 같은
  판정을 재사용할 수 있게 하려는 목적이다(아래 "남은 것" 참고). Fixture 검증
  테스트(`test_recommendation_context_fixture_quality.py`)도 이 함수를 직접
  import해서 쓰도록 정리해, 판정 로직 중복을 없앴다.
- 테스트: `tests/test_weather_judgment.py`(판정 함수 전수), `tests/test_recommendation_pipeline.py`
  (사실/발화/ENJOY 반전/IGNORE-vs-실패 케이스), Context Fixture 4종에 `precipitation`/
  `sky` 보강.
- **근거 문장이 원인(비/눈/폭염/한파)까지 정확히 말하게 수정**(2026-08-05 검수에서
  발견). `explanation.py`가 `weather_condition`만 보고 라벨을 골랐는데, 이러면
  ENJOY 반전으로 비인데 GOOD이 된 경우 "맑은 날씨"라고 말하고, 폭염/한파로 BAD가
  된 경우도 전부 "비 예보"라고 말하는 사실-근거 불일치가 있었다(온도가 판정에
  없던 시절엔 BAD=강수뿐이라 문제없었지만, 이번에 온도를 판정에 추가하면서
  새로 생겼다). 판정 함수가 `(WeatherCondition, WeatherReason)` 튜플을 반환하도록
  바꾸고(`WeatherReason` = rain/snow/heat/cold — 강수는 sleet/shower를 rain으로
  뭉치고 snow만 구분), `scoring.py::RankedCandidate`/`evidence.py::RecommendationEvidence`에
  `weather_reason`을 실어 `explanation.py`까지 관통시켰다. reason이 있으면 그걸로
  라벨을 고르고(비/눈/폭염/한파 예보), 없으면(맑음/흐림, 발화 GOOD) 기존
  `weather_condition` 기반 라벨로 폴백한다.
- **기온 판정을 주의보/경보 2단계로 재설계**(2026-08-05). 원래는 폭염주의보/
  한파주의보 기준(33°C/-12°C) 하나만 넘으면 BAD, 아니면 곧바로 하늘 상태로
  판정했다 — 그 사이 완충 NEUTRAL 구간을 안 뒀는데, 처음엔 28°C/0°C 같은 근거
  없는 값을 새로 만들지 않으려는 선택이었다. 재검수하면서 기상청 실제 특보
  단계(폭염주의보 33°C/경보 35°C, 한파주의보 -12°C/경보 -15°C)를 확인했고, 이
  경계를 그대로 가져와 3단계로 나눴다: 주의보 미만은 기존처럼 하늘 상태로 판정,
  주의보 이상~경보 미만은 NEUTRAL, 경보 이상만 BAD. 두 경계 모두 임의값이
  아니라 공식 등급이라 "근거 없는 완충"이라는 원래 문제를 재현하지 않는다.
  다만 이 변경은 부분적이다 — 30~32°C처럼 주의보 미만인 "그냥 더운 날"은
  여전히 하늘 상태로만 판정되어 맑으면 GOOD이다. 그 구간까지 다루려면 다시
  근거 없는 임의값이 필요해지므로 의도적으로 남겨뒀다(날씨 Feature 가중치가
  40%로 가장 크고 GOOD/BAD 낙차가 outdoor 기준 0.7점이라, 이 트레이드오프가
  순위에 미치는 영향은 결코 작지 않다는 걸 인지하고 있다).

#### 해결됨 (2026-08-06)

- **2차 Scoring(`rerank_with_concentration()`) 배선 불일치** — A가 정리했다(커밋
  `dc0de63`). `rerank_with_concentration()`이 사전 계산된 `weather_condition` 대신
  `context`를 받고, `RealRecommendationProvider`가 내부에서 `resolve_weather_condition()`을
  호출해 `weather_condition`/`weather_reason`을 함께 넘긴다. 구버전
  `to_weather_condition()`은 삭제됐다.
- **`WeatherForecast.condition` 필드 제거** — C가 정리했다. 제거 전에 소비처를 전수
  확인한 결과, 값을 읽어 판정에 쓰는 곳은 A의 `to_weather_condition()`이 마지막이었고
  위 커밋으로 사라졌다. 나머지는 전부 쓰기 전용(mapper가 채우고 아무도 안 읽음)이었다.
  `StrictModel(extra="forbid")`이라 A의 `services/runtime/stubs.py`가 넘기던
  `condition="neutral"` 한 줄을 함께 지웠고, Context Fixture 7종의 `condition` 키도
  제거했다(안 지우면 파싱 자체가 거부된다).
  - 함께 정리: `WeatherProvider.get_current_condition()` — 앱 코드에서 아무도 호출하지
    않고 테스트에서만 쓰이던 죽은 경로였다(protocol/Real/Fake 3곳 제거).
  - 함께 정리: `has_usable_sky_or_precipitation()` 분리. slot 폐기 규칙이 원래
    `map_sky_pty_to_condition()`이 던지는 예외로만 표현돼 있어서, 판정을 걷어낼 때
    필터까지 같이 사라질 자리였다. 규칙을 별도 함수로 빼고 테스트로 못 박았다.

#### 남은 것 (`Proposed`)

- **`conditions.environment` 처리 방침** (문제 5) — 살릴지 제거할지 미정
- **`tool_intelligence` 계약의 `precipitation_type`** — 기상청 코드가 원문으로 노출돼
  있다. 이번 범위에 넣지 않았다. 이 디렉터리는 `package_work_breakdown.md`의 A/B/C/D
  어느 목록에도 없어 소유자 확인이 선행돼야 한다.

### D-052 — Gemini 동일 벤더 내 모델 fallback (`LLM_FALLBACK_MODEL_NAMES`)

- 상태: `Accepted`, 구현 완료
- 배경: 멀티턴 대화("비오는날 실내 추천해줘" → "더 추천해줘" → "반경 넓혀서
  추천해줘") 3번째 턴에서 502(`Gemini 연동에 문제가 발생했어요`)가 발생했는데,
  서버 로그가 한 줄도 없었다. 조사 결과 원인은 두 가지였다.
  1. `RealGeminiProvider._generate()`부터 `handle_app_error`(`main.py`)까지
     `AppError`가 전파되는 경로 전체에 `logger.error`/`warning` 호출이 전혀
     없었다 — Gemini 전용 문제가 아니라 어떤 Provider든 502가 나면 조용히
     사라졌다.
  2. Gemini 5xx/타임아웃 재시도는 이미 있었지만(지수 백오프, `max_retries`회)
     항상 같은 모델만 재시도했다. 턴마다 Gemini를 2회씩 호출하므로(Intent 분류 +
     조건 추출) 턴이 누적될수록 일시적 5xx를 만날 누적 확률이 올라가고, 재시도
     예산이 소진될 가능성도 커진다 — "3번째 턴에서 유독 실패"는 프롬프트가
     커져서가 아니라(확인함 — `current_conditions`는 매턴 새로 덮어써서 누적
     안 됨) 호출 횟수 누적 문제로 보인다.
- 결정: `RealGeminiProvider`가 `LLM_MODEL_NAME`(1순위) 재시도 소진 후
  `LLM_FALLBACK_MODEL_NAMES`(쉼표 구분, 선택 사항)에 지정된 모델을 순서대로
  시도한다. 각 모델의 재시도 예산(`EXTERNAL_API_RETRY_COUNT`)은 폴백 목록
  길이와 무관하게 기존과 동일하게 유지한다 — 두 설정을 서로 독립적으로
  유지하기 위함이며, 대신 모델 수 × 재시도 수만큼 최악 지연이 늘어나는 건
  감수한다. 4xx 등 비재시도 오류는 모델을 바꿔도 결과가 같으므로 폴백하지
  않는다(`_try_model()`에서 즉시 raise, `_RetryableExhaustedError`로 감싸지
  않음). 폴백 전환 시 `logger.warning`, 전 모델 소진 시 `logger.error`로 어떤
  모델이 실패했고 어떤 모델로 넘어갔는지, 최종적으로 어떤 모델이 응답했는지
  남긴다. 추가로 `main.py`의 `handle_app_error`(모든 `AppError`가 거쳐가는
  단일 지점)에도 `logger.error` 한 줄을 추가해, Gemini 외 다른 Provider의 502도
  같이 로그에 남도록 했다.
- D-042와의 관계: D-042(Real Provider 실패 시 Fake로 자동 전환하지 않는다)는
  Real→Fake 조용한 전환만 범위로 하며, "같은 성격의 다른 Real 경로로 넘어가는
  것"과 재시도/서킷 브레이커는 명시적으로 범위 밖이라고 밝히고 있다. 같은
  벤더(Gemini)의 다른 모델로 넘어가는 이번 결정은 D-042 위반이 아니다. 다만
  D-042의 취지("조용한 폴백 금지")를 지키기 위해 폴백 발생을 반드시 로그로
  남긴다 — 로그 없는 폴백은 D-042가 경계하는 것과 본질적으로 같은 문제다.
- 기본값: `LLM_FALLBACK_MODEL_NAMES`가 비어 있으면(기본값) 기존과 동일하게
  단일 모델만 사용한다. 기존 `.env`는 변경 없이 그대로 동작한다.
- 구현: `app/config.py`(`llm_fallback_model_names`, `resolved_llm_models`),
  `app/providers/gemini.py`(`RealGeminiProvider._generate()`을 모델 목록 순회
  + `_try_model()`로 분리, `_RetryableExhaustedError` 내부 신호로 재시도-소진과
  비재시도-오류를 구분), `app/providers/factory.py`(배선 + 부팅 시 중복 모델명
  거부), `app/main.py`(`handle_app_error` 로깅). 테스트는
  `tests/test_gemini_provider.py`(폴백 성공/전체 소진/4xx 무폴백/로깅 확인)와
  `tests/test_provider_settings.py`(`resolved_llm_models` 파싱, 중복 모델명
  거부)에 추가했다.
- 범위 밖(후속 검토 필요): 서로 다른 LLM 공급사(Anthropic/OpenAI 등) 간
  fallback, timeout 정책 자체의 재검토, 모델별 비용/품질 차이를 고려한 라우팅.
  이 결정은 "같은 Gemini 계정 내 모델 fallback"으로 범위를 좁힌다.
- 확인 방법: `tests/test_gemini_provider.py`(신규 5건: 1순위 성공/폴백 성공/전
  모델 소진/4xx 무폴백/로깅), `tests/test_provider_settings.py`(신규 5건).
  전체 회귀(1020+ passed) 확인.

### D-053 — 위치 변경 판정에서 지명 단독은 제외하고, `environment` 미언급은 조건을 해제하지 않는다

- 상태: `Accepted`, 구현 완료
- 배경: TP-67(PR #113)에서 "이전 추천 뒤 위치만 바꾸는 발화가 RECOMMEND로 분류되어
  soft reset으로 앞 턴 조건이 사라지는" 문제를 프롬프트·Fake·되묻기 경로에서 고쳤다.
  그 결과를 재검증하면서 두 가지가 남아 있는 걸 확인했다.
  1. `environment`가 여전히 소실된다. 되묻기 답변 경로는 `reset_scope=None`이라 조건이
     유지되지만, LLM이 미언급을 `ANY`로 표현해 보내면 `_full_replace_operations()`가
     `Update`를 만들어 앞 턴의 `indoor`(비를 피하려던 조건)를 덮어쓴다. TP-67에서
     `weather_intent=NO_MENTION`·`concentration_intent=IGNORE`는 막았지만
     `environment`는 목록에 없었다 — 원 증상(`environment: indoor → any`)의 절반이
     남아 있던 셈이다.
  2. 지명 단독(`"경복궁"`)까지 위치 변경 MODIFY로 분류됐다. 추천을 받은 뒤 지명 하나로
     그 장소를 묻는 흐름(경계 사례 `"경복궁" (단독) → INFO`)이 위치 변경에 가려진다.
- 결정 1 (지명 단독은 INFO): 위치 변경 판정은 **지명에 근처/주변 또는 조사·어미가 붙은
  발화**("광화문 근처에서", "광화문 근처", "광화문으로")로 한정한다. 지명 단독은 이전
  추천 이력이 있어도 INFO로 둔다 — 위치를 바꾸려는 사용자는 보통 조사나 근처 표현을
  함께 쓰고, 지명만 던지는 건 그 장소를 지목한 질문으로 보는 쪽이 실제 발화에 가깝다.
  `"경복궁 오늘 열어?"`처럼 질문 형태는 원래부터 INFO라 영향이 없다.
- 결정 2 (`environment` 미언급): 추출 프롬프트에 "언급이 없으면 null, `any`는 무관함을
  명시했을 때만"이라는 규칙을 명시하고(근본), 되묻기 답변 경로의
  `_CLARIFICATION_DEFAULT_FIELDS`에 `environment: ANY`를 추가한다(안전망). `ANY`를
  미언급으로 보는 게 안전한 이유는 되묻기 답변에 실내외 무관 선언이 함께 오는 경우가
  드물기 때문이고, 실내/실외를 명시한 값(`indoor`/`outdoor`)은 그대로 적용된다.
- 한계: `WeatherIntent`에는 `NO_MENTION`과 `IGNORE`가 나뉘어 있지만 `Environment`에는
  `ANY` 하나뿐이라 "언급 안 함"과 "실내외 상관없음"을 타입으로 구분할 수 없다. 그래서
  구분을 프롬프트 규칙에 의존하고, 되묻기 경로에서는 미언급 쪽으로 해석한다. 스키마에
  `NO_MENTION` 상당 값을 추가하는 건 A-C/B 계약이 함께 움직여야 해 별건으로 남긴다.
- 범위 밖: 일반 RECOMMEND의 soft reset은 그대로 둔다(conditions-schema.md §6의 의도된
  설계). 프롬프트를 고쳐도 LLM 분류는 확률적이라 간헐적으로 RECOMMEND로 오분류되면 그
  턴의 조건은 여전히 소실되는데, 상태 레벨 방어(RECOMMEND의 soft reset 예외 확대)는
  `_full_replace_operations()`의 "Add == replace" 등가성 가정을 깨뜨려
  `exclude_tags`/`special_requirements` 처리까지 함께 손봐야 하므로 채택하지 않았다.
  실서버 반복 측정에서 오분류가 잔존하면 그때 별건으로 다룬다.
- 구현: `app/providers/gemini_prompts.py`(맥락 의존 규칙에서 지명 단독 제외 + 경계
  사례 원복 + `environment` 추출 규칙 추가, `PROMPT_VERSION` 1.0.2),
  `app/providers/stub.py`(`_is_location_only_change()`가 지명 단독을 False로),
  `app/services/interpret/state_transform.py`(`_CLARIFICATION_DEFAULT_FIELDS`).
- 확인 방법: `tests/test_llm_provider.py`(지명 단독이 이력 유무 무관하게 INFO),
  `tests/test_state_transform.py`(되묻기 답변의 `ANY`는 Operation 미생성, 명시된
  `outdoor`는 적용), `tests/test_agent_runtime.py`(되묻기 E2E에서 `weather`·
  `environment` 유지). 전체 회귀 1137 passed / 22 skipped, ruff 통과.
- 실 Gemini 측정(2026-08-06, `gemini-2.5-flash`, 프롬프트 1.0.2,
  `has_previous_recommendation=True`/`shown_place_count=5`): TP-67 리포트의 발화 11종을
  3회씩 재측정해 전부 의도한 값으로 고정됐다. 오분류 4종("광화문 근처에서", "광화문 근처",
  "광화문 근처 어때?", "종로3가역 근처에서")이 모두 `MODIFY` 3/3, 지명 단독("광화문")은
  `INFO` 3/3, 원래 정상이던 6종도 `MODIFY` 3/3을 유지했다. 리포트에서 5회 중 1회만
  `MODIFY`였던 "북촌 근처에서"는 5회 반복에서 `MODIFY` 5/5로 흔들림이 사라졌다. 반대
  방향 회귀도 확인했다 — 이력 없음 + "광화문 근처에서"는 `RECOMMEND` 5/5, "경복궁 오늘
  열어?"는 `INFO` 5/5, "다른 곳 보여줘"는 `MODIFY` 5/5.
- Fake와 실 Gemini의 판정 정렬(2026-08-06 해소): "경복궁 근처 카페 추천해줘"는 이전
  추천이 있을 때 실 Gemini가 `MODIFY` 5/5로 분류한다(위치·카테고리를 바꾸는 조건 변경으로
  보는 쪽이 맞다고 확인함). `FakeLLMProvider`는 `_is_location_only_change()`가 "카페"라는
  잔여 조건 때문에 False가 되어 fallback인 `RECOMMEND`로 떨어졌는데, 이 차이를 없앴다 —
  Fake는 회귀 테스트가 실제 설계를 반영해야 하는 물건이라(stub.py docstring, PR #113 방침)
  갈리는 지점을 남겨둘 이유가 없다.
  - `_is_location_scoped_change()`를 새로 두고 `_is_location_only_change()`는 그대로
    뒀다. 전자는 "지명 바로 뒤에 근처/주변이 붙는가"만 보므로 잔여 조건이 있어도 통과하고,
    지명 단독은 뒤에 근처/주변이 없어 자연히 빠져 결정 1(지명 단독은 `INFO`)이 유지된다.
    정보/일반 질문 어휘(`_INFO_QUESTION_MARKERS`/`_GENERAL_MARKERS`)가 섞이면 빠지게 해
    "경복궁 근처에 화장실 있어?"가 `INFO`, "경복궁 근처 동네는 어때?"가 `GENERAL`로 남는다.
    두 함수를 합치지 않은 건 잔여 조건 화이트리스트(`_LOCATION_ONLY_REMAINDERS`)가
    "광화문으로"·"광화문에서"처럼 근처/주변 없이 조사만 붙는 발화를 계속 맡아야 해서다.
  - `extract_modify_conditions()`에 날씨 처리를 추가했다 — "비"면
    `weather=RAIN`/`weather_intent=AVOID`/`environment=INDOOR`를 `changed_fields`와 함께
    채운다. `extract_recommend_conditions()`의 기존 비 처리와 같은 결이다. `search_center`
    갱신 조건에도 새 판정을 함께 물렸다.
  - 이 차이에 기대던 `test_agent_runtime.py`의
    `test_agent_context_request_weather_not_mixed_with_provider_weather`는 2턴째가 이제
    `MODIFY` 경로를 타므로 그 전제를 명시(`intent == "MODIFY"` 단언)하도록 고치고,
    원래 검증하려던 RECOMMEND 경로는 이력 없는 단일 턴으로 같은 발화를 태우는
    `test_agent_recommend_path_weather_not_mixed_with_provider_weather`로 분리해 남겼다.
  - 확인 방법: `tests/test_llm_provider.py`(지명+근처+다른 조건이 이력 있으면 `MODIFY`,
    이력 없으면 `RECOMMEND`, 정보/일반 질문은 안 가려짐, MODIFY 경로 비 처리),
    `tests/test_agent_runtime.py`(위 두 E2E). 전체 회귀 1145 passed / 22 skipped,
    ruff 통과.

### D-054 — INFO 상세 질의는 Supabase 상세 캐시가 아니라 TourAPI를 직접 조회한다

- 상태: `Accepted`, C 구현 완료 (A 배선 대기)
- 배경: INT-02(INFO)의 `question_type` 8종 중 실제로 동작하는 건 `concentration`
  하나뿐이었다. 나머지를 채우려고 상세 데이터 출처를 확인하다가, 운영 설정
  (`PLACE_DETAILS_SOURCE=supabase`)에서는 답할 데이터가 아예 없다는 걸 발견했다 —
  `SupabasePlaceDetailsProvider._to_place_details()`가 `overview`/`homepage`/
  `telephone`을 `None`으로, `raw_common`/`raw_intro`를 빈 dict로 채운다. places
  테이블의 동기화 대상이 `operating_hours_raw`/`rest_date_raw`뿐이기 때문이다.
- 결정: INFO 상세 질의는 `PLACE_DETAILS_SOURCE`와 무관하게 `PlaceProvider`(TourAPI)를
  직접 호출한다. 전용 Tool(`tools/place_detail.py::GetPlaceDetailTool`)을 두고
  Factory가 `get_place_provider()`를 주입한다.
- 근거: Supabase 캐시를 도입한 이유는 추천 후보 N건의 상세조회를 없애는 것이었다
  (18.0초 → 0.33초). INFO는 대상이 장소 1건이라 그 근거가 적용되지 않는다. 반대로
  캐시를 쓰면 `fee`/`parking`/`facility`/`general_info` 4종이 **조용히** 빈 응답으로
  떨어진다 — 오류가 아니라 "정보 없음"으로 보이므로 발견도 늦다. 이 저장소가 D-042를
  만든 사건과 같은 성격이다.
- 예외 하나: `location_info`는 `ResolveLocationTool`이 주소를 이미 들고 나오므로
  상세 조회를 아예 하지 않는다.
- `operating_hours`는 지금도 이 경로를 함께 탄다. 값 자체는 provider가 유형별 키를
  정규화해둔 `PlaceDetails.operating_hours`/`rest_date`에서 읽으므로 Supabase 캐시로도
  답할 수 있지만, 그러려면 한 Tool이 질문 유형에 따라 두 출처를 오가야 한다. 호출
  1회를 아끼려고 경로를 둘로 만드는 것보다 단순한 쪽을 택했다 — 필요해지면
  `operating_hours`만 캐시로 빼는 건 나중에도 가능하다.
- 범위 밖: `event`는 같은 날 D-055로 별도 처리했다(최초에는 `unsupported`로 두었다).
  동기화 파이프라인에 `overview`/요금/주차 컬럼을 추가하는 근본 해결은 DB 마이그레이션
  + 847건 재동기화가 필요하고 TourAPI 일일 한도에 묶여 있어 별건으로 남긴다.
- 조용한 fake 방지: `FakePlaceProvider.get_details()`의 `raw_intro`가 빈 dict라
  필드 추출 로직이 한 줄도 안 돈 채 테스트가 통과하는 상태였다. 실 detailIntro2와
  같은 키 이름(`usefee`/`parkingculture`/`parkingfood` …)으로 채우고,
  `tests/agent_context/test_info_field_rules.py::TestFakeProviderCarriesIntro`가
  Fake로도 추출 결과가 비지 않는지 고정한다.
- 구현: `app/agent_context/info_schemas.py`(`question_type` 8종 확장,
  `specific_question` 추가, `result`를 `ConcentrationInfoResult | PlaceInfoResult`
  union으로), `app/agent_context/info_field_rules.py`(신설),
  `app/tools/place_detail.py`(신설), `app/agent_context/service.py`
  (`fetch_info_context()` 분기 + 기존 집중률 흐름을 `_fetch_concentration_info()`로
  추출, 로직 변경 없음), `app/agent_context/factory.py`, `app/providers/stub.py`.
- 확인 방법: `tests/agent_context/test_info_field_rules.py`(23건),
  `tests/agent_context/test_info_place_detail.py`(15건). 전체 회귀 1231 passed /
  22 skipped, ruff 통과.
- A 배선 필요: `to_info_context_request()`가 `question_type`을 넘기지 않고,
  `agent_runtime.py`의 게이트가 `CONCENTRATION`으로 한정돼 있으며,
  `response_composer`에 상세 응답 렌더 경로가 없다. 셋 다 A 소유라 별도 카드로 넘긴다.

### D-055 — 트리비 페르소나와 추천 결과 요약 LLM 추가

- 상태: Implemented
- 배경: `RECOMMEND`/`MODIFY` 성공 응답의 `AgentResponse.message`가 고정 문구
  `"이런 곳들을 찾아봤어요:"`만 반환해 국내 여행 챗봇의 정체성과 대화감이 약했다.
  또한 "넌 누구야?", "이름이 뭐야?", "뭘 할 수 있어?" 같은 서비스 정체성 질문을
  안정적으로 처리할 별도 topic이 없었다.
- 결정:
  - 챗봇 이름은 **트리비**로 정한다.
  - 서비스 정체성 질문은 `build_interpretation()`에서 LLM 1차 분류 전에
    `GENERAL(service_identity)`로 선처리하고, 트리비가
    TripBranch의 국내 여행 챗봇이며 위치·날씨·운영시간·거리·혼잡도 선호를 함께
    고려해 장소 추천을 돕는다고 답한다.
  - `RECOMMEND`/`MODIFY` 성공 경로에는 `generate_recommendation_summary()` LLM 호출을
    추가해 추천 카드들을 감싸는 1~2문장 요약을 만든다.
- 안전장치:
  - 추천 요약 LLM 입력은 `name`, `category`, `distance_km`, `remaining_minutes`,
    `recommendation_reason`, `explanations`로 제한한다.
  - `warnings`, `score`, `feature_scores`, `weights_used`는 넘기지 않는다. 사용자에게
    "날씨 점수 제외", "가중치 재분배", "API 실패" 같은 내부 계산 사정을 말하지 않게
    하기 위한 경계다.
  - 요약 LLM 호출이 실패하면 추천 카드 응답은 유지하고 기존 고정 wrapper로 fallback한다.
  - "넌 누구야?", "이름이 뭐야?"는 Gemini가 `role_request`/`OUT_OF_SCOPE`로 오분류할
    수 있으므로 프롬프트만 믿지 않고 A 오케스트레이터에서 deterministic하게 처리한다.
- 구현: `app/schemas.py`(`GeneralTopic.SERVICE_IDENTITY`),
  `app/providers/gemini_prompts.py`(트리비 페르소나, service_identity 분류/답변 규칙,
  추천 요약 프롬프트, `PROMPT_VERSION` 1.0.5), `app/providers/gemini.py`/
  `app/providers/stub.py`(`generate_recommendation_summary()`),
  `app/services/interpret/orchestrator.py`(service_identity 선처리),
  `response_composer.py`(추천 성공 메시지에서 요약 LLM 호출).
- 확인 방법: `tests/test_llm_provider.py`(정체성 질문 분류/답변), `tests/test_response_
  composer.py`(추천 요약 호출 및 fallback), `tests/test_gemini_provider.py`(요약 입력에서
  내부 scoring 필드 제외).

### D-055 — INFO `event`는 지역 행사 목록 + 좌표 근접으로 답한다

- 상태: `Accepted`, C 구현 완료 (A 배선 대기)
- 배경: D-054에서 `event`만 `unsupported`로 남겼다가, 실제로 답할 데이터가 있는지
  실측했다(2026-08-07). 처음 조회에서 "종로구에 진행 중인 행사 0건"이 나와 미지원이
  타당해 보였는데, 필터를 바꾸자 결론이 뒤집혔다.
- **발견 1 — `sigunguCode` 필터가 함정이다.** `searchFestival2` 응답 항목의 상당수가
  `areacode`/`sigungucode`를 빈 문자열로 내려주고, 그 항목들은 서버 필터에서 통째로
  탈락한다. 같은 종로구를 두 방식으로 조회한 결과:

  | 필터 | 결과 | 오늘 진행 중 |
  | --- | --- | --- |
  | `sigunguCode=23` | 14건 (전부 2025년) | **0건** |
  | `lDongRegnCd=11` + `lDongSignguCd=110` | 25건 | **6건** |

  장소 검색이 이미 같은 이유로 법정동 코드를 쓰고 있었다
  (`place_search_policy.PLACE_SEARCH_LDONG_*`, 2026-08-03). 같은 함정을 두 번째로
  밟은 셈이라 provider 모듈 docstring에 근거를 남겼다.
- **발견 2 — 장소명 매칭은 안 붙지만 좌표는 100% 있다.** `eventplace`는
  `"광화문광장&세종로공원"`, `"청와대 사랑채 1층"`, `"서울 전역"`처럼 우리 `places.title`과
  형태가 다르다. 2026-08-07 진행 중 6건 중 이름이 붙는 건 0건이었다. 반면 목록 응답의
  `mapx`/`mapy`는 전 항목에 채워져 있다.
- 결정: `event`를 **"그 장소에서 열리는 행사"가 아니라 "그 장소 근처에서 진행 중인 행사"**로
  답한다. 종로구(법정동 110) 행사를 받아 기준일에 진행 중인 것만 남기고, 대상 장소
  좌표에서 가까운 순으로 정렬해 최대 5건을 싣는다. 제목에 장소명이 들어간 행사
  (`"경복궁 별빛야행"`)만 `is_direct_match=True`로 올려 먼저 보여준다.
- INFO 명세는 바꾸지 않는다: `place_name`이 여전히 앵커이고, 답변만 근접 의미로 나간다.
  이건 집중률의 D-036 인근 대체 조회와 같은 패턴이다 — 직접 데이터가 없으면 인근
  기준으로 답하되 반드시 고지한다. `EventItem.is_direct_match`/`distance_km`이
  `ConcentrationInfoResult.is_proxy`에 대응한다. **A는 이 구분을 문구에 반드시 반영해야
  한다** — 요청한 장소의 행사인 것처럼 말하면 사실과 다르다.
- 반경 컷오프를 두지 않은 이유: 조회가 이미 종로구로 한정돼 지역 필터가 반경 역할을
  한다. 여기서 임의 반경을 하나 더 두면 근거 없는 숫자가 늘어난다. 대신 건수 상한
  (`INFO_EVENT_RESULT_LIMIT = 5`)만 둔다.
- `eventplace`를 안 쓴 이유: 목록 응답에 없고 행사마다 `detailIntro2`를 열어야 한다(N+1).
  제목 매칭으로 직접/근접을 가르는 선에서 멈췄다. 정확도가 문제가 되면 상위 몇 건만
  상세를 여는 방식으로 넓힐 수 있다.
- 계약: `EventInfoResult`/`EventItem`을 신설하고 `InfoContextResponse.result` union에
  추가했다. 행사가 다건이라 `PlaceInfoResult.fields`(`dict[str, str]`)로는 표현할 수 없다.
- 조용한 fake 방지: `FakeFestivalProvider`의 좌표·기간·명칭을 실측 응답에서 가져왔고,
  진행 중/종료/예정과 직접 매칭/근접이 모두 섞이도록 구성했다. Fake가 전부 직접
  매칭이면 근접 경로가 한 번도 실행되지 않는다
  (`tests/agent_context/test_info_event.py::TestFakeProviderShape`).
- 구현: `app/providers/festival.py`(신설), `app/providers/protocols.py`(`FestivalProvider`),
  `app/providers/contracts.py`(`TOUR_API_FESTIVAL`/`FAKE_FESTIVAL`),
  `app/tools/festival.py`(신설), `app/agent_context/info_schemas.py`,
  `app/agent_context/service.py`(`_fetch_event_info()`), 양쪽 factory.
- 확인 방법: `tests/test_festival_provider.py`(12건), `tests/agent_context/test_info_event.py`
  (14건). 전체 회귀 1276 passed / 22 skipped, ruff 통과. 실 TourAPI 실측으로 경복궁
  기준 5건(0.21~0.86km), 북촌한옥마을 기준 5건(0.69~1.23km)이 거리순으로 나오는 것을
  확인했다.
- 한계: 오늘 기준 진행 중 6건 전부가 근접 매칭이다(직접 매칭 0건). 사용자에게는 "경복궁
  근처에서 진행 중인 행사"로 나가므로 질문이 "경복궁에서 뭐 해?"였다면 기대와 다를 수
  있다. 종로구 등록 행사 자체가 25건뿐이라 표본이 작다는 점도 함께 둔다.

### D-056 — TourAPI 주차·요금·이미지 원문은 `places`에 직접 둔다

- 상태: `Accepted`, 마이그레이션 작성 완료 (DB 적용·코드 배선 대기)
- 배경: 추천 카드에 주차·요금·썸네일을 노출하려는데, 저장 위치를 `places` 컬럼 추가와
  별도 테이블 분리 중 어디로 할지 정해야 했다.
- 결정: `places`에 컬럼 6개를 추가한다 — `parking_info_raw`, `parking_fee_raw`,
  `use_fee_raw`, `discount_info_raw`, `first_image_url`, `thumbnail_url`.
- 근거: 출처(`detailIntro2`)·관계(1:1)·갱신 주기(`detail_fetched_at` TTL)가
  기존 `operating_hours_raw`와 동일하다. 분리하면 수명주기 컬럼(`detail_fetch_status`,
  `detail_fetched_at`)을 복제하거나 두 테이블의 신선도가 어긋난다. `place_enrichments`도
  아니다 — 그쪽 `source_type`은 `manual_research`/`external_data`/`derived`로 제한된
  사람 조사·파생값이고, TourAPI 원문은 성격이 다르다.
- 외부 호출은 늘지 않는다: `place_sync`가 이미 장소마다 `detailIntro2`를 부르고
  있고(운영시간·휴무일 용도) 같은 응답에서 더 읽기만 한다. 이미지 2개는
  `areaBasedList2` 목록 응답에 이미 들어 있어 상세조회조차 필요 없다.
- **함정 — 축제(15)의 이용요금 필드명은 `usetimefestival`이다.** 이름은 시간처럼
  보이지만 내용은 요금이다. `real_place.py`의 `_OPERATING_HOURS_KEYS`가 이 키를 일부러
  제외하고 축제는 `playtime`을 쓰는 이유이므로, 요금 매핑을 추가할 때 그 구분을 깨면
  영업시간 자리에 "5,000원"이 들어간다.
- 커버리지 한계(2026-08-08 실측, 종로구 844건):
  - 주차 806건(95%) — 축제(15) 38건에는 주차 필드가 아예 없다.
  - 이용요금 204건(24%) — 14·15·28에만 있다. 12 관광지·32 숙박·38 쇼핑은 요금이
    `detailCommon2`의 `overview` 산문에 섞여 있어 별도 파싱이나 수동 보강이 필요하다.
  - 우선 있는 값으로 카드를 채우고, 누락분은 이후 `place_enrichments`로 보강한다.
- 이미지 2개는 `detail_fetched_at`이 아니라 `list_fetched_at` 주기를 따른다. 상세조회가
  실패한 장소에서도 이미지는 최신일 수 있다.
- 구현: `supabase/migrations/202608080001_add_place_parking_fee_image_columns.sql`.
  provider 매핑(`real_place.py`)과 `place_sync.py` 저장 반영은 후속 작업.

### D-057 — 집중률 검색어는 토큰 전부를 희소성 순으로 쓰고, 대조는 임계값 0.9를 둔다

- 상태: `Accepted`, 구현 완료
- 배경: `concentration_search_key`(D-051 계열 결정)는 장소당 검색어를 **하나만** 둔다.
  공백이 든 값을 넘기면 0건이 돌아오기 때문에 이름을 잘라 하나를 골랐는데, 그 결과
  변별력 없는 토큰이 검색어가 된 사례가 남았다 — `'청와대 앞길'` → `'앞길'`,
  `'한국교회 100주년 기념관'` → `'100주년'`, `'창덕궁과 후원'` → `'창덕궁과'`.
- 결정:
  1. **검색어는 공백 토큰 전부를 저장한다.** 하나만 고르지 않는다.
  2. **호출 순서는 ① 기존 `concentration_search_key`가 있으면 그것을 1순위로 고정,
     ② 나머지 토큰은 코퍼스 등장 빈도 오름차순, 동률이면 긴 토큰 우선**으로 한다.
     결과가 나오면 멈춰 호출 수를 아낀다.
  3. **대조는 양쪽 공백을 모두 제거한 뒤** 수행한다. 지금은 `.strip()`만 해서
     `'서울 운현궁'`과 `'운현궁'`이 다른 문자열로 취급된다.
  4. **채택은 정확 일치 > 유사도 0.9 이상 최고값 > `no_data`** 순이다.
- **기존 검색어를 1순위로 고정하는 이유 — 희소성만으로는 순서가 정해지지 않는다.**
  종로구 이름 113개는 토큰 대부분이 1회만 등장해 동률이 쏟아진다. 빈도만으로 정렬하면
  현재 검색어 24건 중 **10건의 1순위가 바뀌고**, 그중 다수가 더 나빠진다(2026-08-08 실측):
  `'서울 문묘와 성균관'` `성균관`→`문묘와`, `'홍지문 및 탕춘대성'` `탕춘대성`→`홍지문`,
  `'아름다운 차박물관'` `차박물관`→`아름다운`, `'낙원동 아구찜 거리'` `아구찜`→`낙원동`.
  현재 24건은 전부 정상 조회되는 것이 확인됐으므로, 검증된 값을 휴리스틱으로 재계산해
  회귀를 만들 이유가 없다. 토큰 추가는 **순수한 능력 추가**로만 둔다.
- **적용 범위는 INFO 질의 경로다.** 그 경로는 발화에서 장소를 뽑아 매핑 테이블과
  대조한 뒤 검색어로 **1회** 호출한다. 목적은 `'닭한마리 골목 혼잡해?'`처럼 정식 명칭
  (`서울 동대문 닭한마리 골목`)과 어긋나는 발화를 찾아내는 것이다.
- **추천 경로의 호출 수 문제는 이 결정에 포함하지 않는다(보류).**
  `enrichment_service._enrich_candidate()`는 후보마다 1회씩 호출한다. `tAtsNm` 없이
  종로구 전량을 4회에 받을 수 있음을 확인했으나(3,390행 = 113장소 × 30일,
  `baseYmd` 20260808~20260906), 이는 검색어 설계와 무관한 별개의 최적화다. INFO
  경로는 요청당 1회라 전량 수집이 오히려 손해이므로 함께 묶지 않는다.
- **손으로 쓴 불용어 목록을 두지 않는다.** 처음에 `서울`·`골목`·`거리`와 함께
  `닭한마리`·`낙지볶음` 같은 음식명을 불용어 후보로 묶었는데, 실측하니 정반대였다
  (2026-08-08, 종로구 113개 이름):
  - 2회 이상 등장하는 토큰은 7개뿐 — `서울`(9), `동대문`·`터`·`골목`·`쌈지길`·
    `[유네스코`·`세계유산]`(각 2).
  - `닭한마리`·`낙지볶음`·`아구찜`·`앞길`·`전망대`는 모두 **1회**로, 코퍼스에서 가장
    변별력이 높다.
  즉 기준은 품사나 의미가 아니라 **코퍼스 내 희소성**이다. 빈도 정렬 하나로 `서울`은
  자동으로 뒤로 밀리고, "닭한마리 골목 혼잡해?"는 `닭한마리`로 바로 찾아진다.
  데이터가 바뀌면 빈도도 따라 바뀌므로 목록을 손보지 않아도 된다.
- **임계값 0.9는 유사도 매칭 금지 방침의 조건부 예외다.**
  `build_concentration_mappings.py`는 "편집거리 같은 유사도 매칭은 쓰지 않는다 —
  이름이 크게 다른 장소를 잘못 붙이면 엉뚱한 곳의 혼잡도를 답한다"는 이유로 보수적
  매칭만 해왔다. 그 취지를 유지하려면 바닥 없는 `max()`를 쓰면 안 된다 — 찾는 장소가
  응답에 없어도 가장 덜 틀린 것이 정답인 척 나가고, 지금 `None`을 반환하며 포기하는
  자리([`enrichment_service.py`의 `select_concentration_forecast()`])가 조용한 오답으로
  바뀐다. 0.9는 사실상 표기 차이만 흡수하는 값이다. 낮추는 것은 실측 결과를 보고
  판단한다.
- 실측으로 확인한 전제(2026-08-08):
  - `tAtsNm`은 부분 일치이며 **`areaCd`/`signguCd`로 좁혀진 뒤** 적용된다.
    `'전망대'`가 종로구에서 고유 이름 1건(`채석장 전망대`), 강남구에서 0건이다.
    전국을 훑지 않으므로 종로구 코퍼스 기준 빈도가 올바른 척도다.
  - `'닭한마리'` 단독 검색은 `서울 동대문 닭한마리 골목` 하나만 반환한다.
  - `'서울'`은 고유 이름 4건으로 갈린다.
  - 집중률 API의 `signguCd`는 `11110`으로, TourAPI 목록의 `lDongSignguCd`(`110`)와
    체계가 다르다. 코드를 섞으면 조용히 0건이 돌아온다.
- 남는 한계: 집중률 API에만 있고 `places`에 짝이 없는 이름 12건은 이 변경으로
  풀리지 않는다(`돈의문박물관마을`, `부엉이박물관`, `화정박물관` 등). 수동 오버라이드가
  따로 필요하다.
- 구현 예정 범위(C): `app/providers/concentration.py`,
  `app/agent_context/enrichment_service.py`, `scripts/build_concentration_mappings.py`,
  `place_concentration_mappings` 스키마(검색어 복수 저장).
- 구현: 마이그레이션 `202608080002_add_concentration_search_keys.sql`이 배열 컬럼
  추가·backfill·단수 컬럼 삭제를 한 번에 처리하고, 코드도 같은 PR에서 전부
  이관했다. 단수 컬럼을 남겨 병행하지 않은 이유는 목록의 1순위가 기존 검색어와
  같은 값이라 진실의 원천이 둘이 되기 때문이다(저장소에서 반복된 "레거시 필드의
  이중 경로" 유형). 스키마 문서는
  [place-database-schema.md §6.1](./design/place-database-schema.md)에 반영했다.

### D-058 — 운영시간이 요일을 열거했으면 빠진 요일은 휴무로 유도한다

- 상태: `Accepted`, 구현 완료 (D 리뷰 대기 — D-008 경계를 옮기는 결정이라 소유자 확인 필요)
- 배경: 운영시간 파서가 요일별 시간을 분리하지 못해 두 가지가 조용히 통과하고 있었다.
  `_WEEKLY_CLOSURE_PATTERN`의 구분자에 `~`가 없어 `매주 월요일~화요일`이 `[월]`만
  남겼고(활성 33건), `_parse_operating_rules()`가 `weekdays=None` 고정이라 요일마다
  시간이 다른 원문이 요일 구분 없는 규칙들로 평탄화됐다(활성 88건). 둘 다
  `parse_status=parsed`에 warning도 없었다.
- 요일 분리를 구현하고 나니 남는 질문이 하나 생겼다 — **원문이 요일을 열거했는데 어떤
  요일이 빠져 있으면, 그 요일은 휴무인가 미확인인가.** D-008은 "운영시간 미확인은
  폐점이 아니다"라 미확인이면 하드 필터를 통과하고 가중치만 재분배된다.
- 결정: **빠진 요일을 정기 휴무로 유도해 `ClosureRule`로 내보낸다.** 단, 요일 없는
  규칙(`weekdays=None`)이 하나라도 있으면 그 규칙이 7요일 전부를 덮으므로 유도하지
  않는다.
- 근거(2026-08-08 실측, 활성 844건): 요일을 열거하고도 빠진 요일이 있는 장소가 39건인데,
  그중 **38건은 그 빠진 요일이 휴무 원문에 이미 명시**돼 있었다. 원문 자체가 규칙을
  38번 교차검증해준 셈이다. 남은 1건(북촌문화센터, `130903`)은 반례가 아니라 휴무
  필드가 비어 있는 원본 결함이고, 실제로도 월요일에 문을 닫는다.
- **원문 휴무와 유도 휴무는 `source_text`로만 구분한다** — 유도분은
  `DERIVED_CLOSURE_SOURCE_TEXT`("운영시간에 열거되지 않은 요일")를 갖는다. `place_sync`가
  `source_text`를 직렬화하므로 DB에서도 골라낼 수 있다. D 판정 자체는 원문 휴무와 같다.
- **파싱 실수의 대가가 커진다.** 요일 범위를 하나 잘못 읽으면 결과가 "점수가 틀림"이
  아니라 "후보가 하드 필터로 사라짐"이 된다. 복구 경로가 없다. 현재 코퍼스에서 유도가
  붙는 장소는 1건뿐이라 노출이 작지만, **종로구 밖으로 데이터를 넓히면 유도가 붙는
  장소 수부터 다시 재야 한다.**
- 회귀 범위(구/신 파서를 7일 × 6개 시각으로 대조): 활성 844건 중 **97건**의 운영 판정이
  달라졌다 — 열림→닫힘 335건, 구간변경 404건(그중 운영점수가 실제로 달라진 것 61건,
  최대 ±0.75점 → 가중치 0.4 기준 총점 0.3점). `parse_status` 분포는 바뀌지 않는다.
  이번 변경은 "몇 건을 읽었나"가 아니라 "읽은 내용이 맞나"를 고친 것이다.
- 구현: `app/domain/operating_hours.py` — `_split_weekday_segments()`(요일 선언 단위
  분할, 줄 경계를 넘어 유지), `_expand_weekdays()`(범위 전개, 주 경계 포함),
  `_derive_unlisted_weekday_closures()`. 소비 측(`candidate_mapper.py`)의
  `_rule_applies()`·`_is_regular_closure()`가 이미 요일을 읽고 있어 D 코드 변경은 없다.
  `OPERATING_PARSER_VERSION` `1.1.0` → `1.2.0`(저장분 재파싱 트리거).
- 함께 잡은 오독 3종: 요일 선언과 시간 구간이 다른 줄에 오는 원문(`[평일]<br>-
  10:00~17:00`), 시설 구획이 바뀔 때 앞 구획 요일이 새어나가는 문제(`[자율학습실]
  07:00~22:00`이 앞의 `주말` 전용이 됨), 요일이 범위가 아닌 안내인 경우
  (`※ 매주 화요일 휴관`, `주중 브레이크타임`, `토요일 미사`, `매월 마지막 수요일`).
- 남는 것: `준비시간`·`브레이크타임` 구간이 운영 구간으로 파싱된다. 지금은 앞 구간이
  먼저 매칭돼 실질 피해가 없어 범위 밖으로 둔다.

### D-059 — SCHEDULE 되묻기 답변은 프롬프트 컨텍스트로 이어간다(상태 레벨 override 아님)

- 상태: `Accepted`, 구현 완료
- 배경: 1턴 "주말에 종로에서 일정 짜줘" → Intent=SCHEDULE, 장소가 여러 곳으로 해석돼
  Tool(C) 레벨 `location_ambiguous` 되묻기로 끝남. 2턴 "광화문으로 알려줘" → Intent=MODIFY로
  오분류되어 일정 편성이 아니라 장소 추천/변경 응답이 나갔다.
- 원인 조사 결과 3가지: (1) `build_interpretation()`이 `classify_intent()`를 호출할 때
  `has_previous_recommendation`/`shown_place_count`만 넘기고 "직전 턴이 되묻기로
  끝났는지/그 되묻기가 어떤 Intent였는지"는 전혀 전달하지 않았다. RECOMMEND는
  `_INTENT_PRIORITY`의 fallback 기본값이라 이런 상황에서도 대개 자연스럽게 RECOMMEND로
  떨어지지만, SCHEDULE은 "일정/코스/순서" 키워드가 있어야만 선택되는 명시적 분류라
  fallback이 없다 — "광화문으로"는 오히려 `_CONTEXT_DEPENDENT_RULES`의 MODIFY 예시
  패턴("지명+조사")과 정확히 일치해 그쪽으로 끌린다. (2) 되묻기 플래그 소비
  화이트리스트(`agent_runtime.py`)가 `(RECOMMEND, MODIFY)`뿐이라, 설령 SCHEDULE로 옳게
  분류되더라도 `pending_clarification` 플래그가 지워지지 않았다. (3)
  `state_transform.transform()`은 이미 SCHEDULE을 RECOMMEND와 동일하게 취급해 되묻기
  답변 시 soft reset을 건너뛰는 로직을 갖추고 있었다 — 분류만 SCHEDULE로 바로잡으면
  나머지(조건 병합)는 이미 정상 동작하는 상태였다.
- 결정: D-053("단독 지명은 정보 조회")과 같은 방향 — **상태 레벨 결정적 override가 아니라
  `classify_intent`에 필요한 컨텍스트를 넘기고 프롬프트 규칙만 추가**해 LLM 판단을
  바로잡는다. `InterpretRequest`에 `pending_clarification`/`last_intent`
  (B의 `SessionContextResponse`에서 그대로 채움)를 추가하고, `classify_intent()`
  시그니처(Protocol/Real/Fake 3곳)에 동일 키워드 인자를 추가해 `orchestrator.py`가
  그대로 전달한다. 실 Gemini 프롬프트(`_CONTEXT_DEPENDENT_RULES`/`_BOUNDARY_CASES`)에
  "직전 턴이 SCHEDULE 되묻기로 끝났고 이번 발화가 그 답변으로 보이면 SCHEDULE 유지"
  규칙을 추가하고, "현재 대화 컨텍스트" 블록에 되묻기 여부를 한 줄 노출한다(SCHEDULE
  외 다른 `last_intent`는 이번 범위 밖이라 노출하지 않음 — 프롬프트 비대화 방지).
  `PROMPT_VERSION` 1.0.6 → 1.0.7.
- Fake(`FakeLLMProvider`)도 동일한 정보를 받아 미러링한다 — `_SCHEDULE_MARKERS` 매칭
  분기 바로 뒤, `has_previous_recommendation` MODIFY 분기보다 먼저 "직전 SCHEDULE
  되묻기 + 명시적 재시작 표현 아님" 조건을 검사해 SCHEDULE로 분류한다. 재시작 표현
  목록은 `state_transform._RESET_SCOPE_PHRASES`와 같은 문구를 stub.py 로컬 상수로
  미러링한다 — Fake는 프로덕션 상태 모듈에 의존하지 않는 기존 레이어 분리를 유지한다.
- 부가 수정: `agent_runtime.py`의 되묻기 플래그 소비 화이트리스트에 `Intent.SCHEDULE`
  추가 — 옳게 SCHEDULE로 이어져도 플래그가 안 지워지던 문제를 함께 고쳤다.
- 대안(state-level override)을 채택하지 않은 이유: classify_intent 호출 자체를 건너뛰고
  "직전이 SCHEDULE 되묻기면 무조건 SCHEDULE로 강제"하는 방식도 검토했으나, LLM이
  OUT_OF_SCOPE/GENERAL 등으로 정확히 분류해야 하는 경우(되묻기 답변에 욕설이나 완전히
  무관한 질문이 온 경우)까지 SCHEDULE로 덮어써 버릴 위험이 있다. 프롬프트 규칙은 LLM의
  판단을 계속 신뢰하면서 이 특정 경계(되묻기 이어가기 vs MODIFY)만 바로잡는다 — D-053이
  이미 이 방향을 팀 방침으로 확정했다.
- 범위 밖: SCHEDULE 외 다른 Intent(INFO, COMPARE 등)가 되묻기로 끝나는 경우의 이어가기는
  이번 재현 범위가 아니다. 필요성이 확인되면 같은 패턴(컨텍스트 전달 + 프롬프트 규칙)을
  확장한다. `MODIFY`가 `current_conditions is None`일 때의 기존 자체 되묻기 처리
  (`orchestrator.py` 별도 분기)는 이번 버그와 무관해 손대지 않았다.
- 구현: `app/schemas.py`(`InterpretRequest`), `app/services/runtime/agent_runtime.py`
  (컨텍스트 전달, 소비 화이트리스트), `app/services/interpret/orchestrator.py`
  (`classify_intent()` 호출부), `app/providers/protocols.py`/`gemini.py`/`stub.py`
  (시그니처), `app/providers/gemini_prompts.py`(프롬프트 규칙 + 버전).
- 확인 방법: `tests/test_llm_provider.py`(SCHEDULE 되묻기 이어가기가 MODIFY 패턴보다
  우선함, 명시적 재시작 표현은 강제되지 않음, 컨텍스트 없을 때 기존 동작 회귀 없음,
  프롬프트 텍스트에 규칙·컨텍스트 줄 반영 확인), `tests/test_agent_runtime.py`
  (SCHEDULE 되묻기 E2E — intent 유지 + 플래그 소비 확인). 전체 회귀 1333 passed / 22
  skipped, ruff 통과.

### D-060 — INFO 상세 질의는 정규화 필드로 읽고, 출처는 캐시로 단일화한다

- 상태: `Accepted`, C 구현 완료 (마이그레이션 적용 완료, 값 적재 대기)
- 배경: 추천 카드에 이어 INFO 상세 질의도 places 캐시로 답하려 했는데 세 가지가
  막혔다. (1) `extract_info_fields()`가 요금·주차·편의시설을 `PlaceDetails.raw_intro`
  에서 TourAPI 원본 키로 찾는데, 저장소는 유형별 키를 한 컬럼으로 눌러 담아 원본
  키를 복원할 수 없다. (2) 전화번호의 출처가 불분명했다. (3) 편의시설은 캐시에
  대응 컬럼이 아예 없었다.
- 결정 1 — **요금·주차·편의시설을 정규화 필드로 옮긴다.** `PlaceDetails`에 `fee`/
  `parking`/`parking_fee`/`baby_carriage`/`pet`/`credit_card`/`restroom`을 추가하고
  provider가 contenttypeid별 키를 훑어 채운다. `extract_info_fields()`는 이 필드를
  읽고, **`raw_intro`를 읽던 옛 경로는 전부 지웠다.**
- 근거: `operating_hours`가 진작부터 이 방식이었다("provider가 이미 유형별 키를 훑어
  정규화해둔 값이 있다"). 대안으로 하이브리드가 `raw_intro`를 합성 dict로 되돌려
  채우는 방식도 검토했으나, 키 몇 개짜리 합성 dict는 "없는 키"와 "그 장소에 없는
  정보"를 구분할 수 없어 같은 조용한 실패를 다시 만든다. 두 경로를 함께 두는
  선택지는 버렸다 — 같은 질문이 provider에 따라 다르게 답한다.
- 결정 2 — **전화번호는 `detailIntro2`의 안내처가 출처다.** `places.info_center_raw`를
  추가하고 동기화가 채운다.
- 근거(2026-08-10 실측, 표본 35건): `detailCommon2`의 `tel`이 채워진 것은 축제(15)
  5/5뿐이고 12·14·28·32·38·39는 전부 0/5였다. 같은 표본의 `detailIntro2`
  `infocenter*` 계열은 33건 중 32건(97%)이 채워져 있다. 축제는 `infocenter` 계열이
  없어 `tel`을 쓰므로 두 출처를 순서대로 본다(안내처 → tel).
- 결정 3 — **편의시설도 컬럼 4개로 캐시한다.** `baby_carriage_raw`/`pet_raw`/
  `credit_card_raw`/`restroom_raw`. jsonb 하나로 합치지 않는다 — 소비 측이 키 이름을
  알아야 하고 "키가 없다"와 "정보가 없다"가 구분되지 않아 결정 1이 걷어낸 문제를
  되살린다. 이름은 A에게 나가는 계약 키와 1:1로 맞춘다.
- 근거(2026-08-10 실측, facility 필드가 존재하는 유형 5종에서 55건): 값이 하나라도
  있는 장소가 22/55(40%)다. 카드결제 19/55(쇼핑 12/12·음식점 6/12·관광지 1/12),
  화장실 12/55(쇼핑 12/12), 유모차 4/55(값은 모두 `없음`), 반려동물 0/55.
  **쇼핑에 몰려 있다는 점이 결정적이다** — 인사동·광장시장 같은 곳의 "화장실 있어?"를
  캐시만으로 답하려면 이 컬럼이 필요하다.
  (조사 초기에 "표본 33건 중 1~4건"으로 과소평가했는데, 그 표본에는 facility 필드가
  아예 없는 축제(15)·숙박(32)이 섞여 있어 비율이 희석된 것이었다.)
- 결정 4 — **INFO 상세 출처를 고르는 설정을 두지 않는다.** 하이브리드 경로만 남긴다.
  캐시가 `question_type` 전부를 덮게 되면서 TourAPI 직접 조회와 답할 수 있는 질문이
  같아졌고, 고를 이유가 사라졌다. 검토 단계에서 `INFO_PLACE_DETAIL_SOURCE`를 도입했다가
  편의시설 공백이 메워지면서 철회했다. 설정을 남겨두면 두 경로의 동작이 갈리는지
  계속 확인해야 한다.
- 외부 호출: INFO 상세 질의가 3회(searchKeyword2 + detailCommon2 + detailIntro2)에서
  **1회**(detailCommon2)로 준다. `overview`(표본 35건에서 100%, 평균 326자)와
  `homepage`(63%)는 캐시에 없어 그 1회가 남는다.
- D-054를 대체한다. 그 결정은 "캐시에는 INFO가 답할 데이터가 없다"가 전제였고, 당시
  동기화 대상은 `operating_hours_raw`/`rest_date_raw`뿐이었다. D-056(주차·요금)과
  이번 안내처·편의시설로 전제가 사라졌다.
- 미완결: `info_center_raw`와 편의시설 4개 컬럼은 마이그레이션만 적용됐고 값은 비어
  있다. 동기화를 다시 돌려야 채워진다. 그때까지 INFO 전화번호·편의시설은 빈 응답이다.
- 별건으로 남긴 것: `location_info`는 `_fetch_place_detail_info()`에서 상세조회 전에
  early return 하므로(주소만으로 답이 성립한다는 판단) `extract_info_fields()`의
  `location_info` 분기가 서비스에서 도달하지 않는다. 캐시에 전화번호가 생기면서
  "외부 호출 한 번을 아낀다"는 그 근거가 사라졌으므로 early return을 재검토해야
  전화번호가 실제로 쓰인다.
- 조용한 실패 방지: 정규화 필드를 provider가 안 채워도 규칙 테스트는 통과한다. 그래서
  `tests/test_place_details_normalized_fields.py`가 **provider를 직접 태우고**
  `extract_info_fields()` 출력이 비지 않는지 단언한다. `_to_place_details`에서
  `parking=None`·`restroom=None`으로 배선을 끊으면 실제로 실패하는 것을 확인했다.
  `app/providers/tour_intro_keys.py`를 분리해 실 provider와 fake가 같은 키 목록을
  쓰도록 구조로 고정했다.
- 구현: `supabase/migrations/202608100001_add_place_info_center_column.sql`,
  `202608100002_add_place_facility_columns.sql`,
  `app/providers/hybrid_place_details.py`, `app/providers/tour_intro_keys.py`,
  `app/domain/models.py`, `app/providers/real_place.py`/`stub.py`/
  `supabase_place_details.py`/`factory.py`/`protocols.py`,
  `app/agent_context/info_field_rules.py`/`factory.py`,
  `app/repositories/supabase_places.py`/`protocols.py`, `app/services/place_sync.py`,
  `app/tools/place_detail.py`.

### D-061 — 상세 카드용 운영시간 표시 구조를 C가 정규화해 제공한다

- 상태: `Proposed` — C 확인·구현 필요
- 배경: 현재 INFO·추천 상세 카드의 `PlaceCard.operating_hours`는 TourAPI 운영시간 원문을
  문자열로 전달한다. 월별 표기(`[1월~2월]09:00~17:00...`)는 프론트가 읽기 좋게 나눌 수
  있지만, `10:00~18:00 수,토 10:00~21:00`처럼 기본 구간과 요일 예외가 한 줄로 붙은
  원문은 구조를 알 수 없어 그대로 노출된다. 이 값은 Scoring의 당일 개폐 판정에는 이미
  쓰이지만, 사용자가 읽는 상세 카드에는 별도 표시 계약이 없다.
- 제안: C가 기존 `OperatingSchedule` 파싱 결과를 바탕으로 INFO `PlaceCard`와 추천 상세
  조회가 함께 쓸 표시 전용 구조화 운영시간을 제공한다. 예:
  `[{"label":"기본","hours":"10:00–18:00"}, {"label":"수요일 · 토요일","hours":"10:00–21:00"}]`.
  원문 `operating_hours`는 감사·파서 보완용으로 계속 보존하고, A/프론트는 새 구조가 있을
  때만 카드 행으로 렌더링하며 없으면 원문 표시로 폴백한다.
- C 확인 사항: (1) `OperatingSchedule`에서 요일별 예외를 손실 없이 꺼낼 수 있는지,
  (2) 월별·요일별·휴무·24시간 표기를 하나의 표시 모델에 어떤 필드로 담을지,
  (3) `PlaceCard` 계약에 추가할지 또는 단건 상세조회 전용 모델로 분리할지 결정한다.
- 범위 밖: 이번 작업은 운영시간 계산·Scoring 필터·파서 규칙을 바꾸지 않는다. 프론트의
  임시 문자열 분해는 새 C 계약이 확정될 때까지 표시 폴백으로만 유지한다.

### D-062 — 게스트 로그인은 Supabase 익명 사용자로 발급한다

- 상태: `Proposed` — 설계 확정, 구현 전
- 배경: 정식 로그인 기능이 아직 없다. 현재 사용자 개념 자체가 없고 익명
  `session_id`(TTL 30분) 하나만 있어서, 로그인 도입 전까지의 사용자 데이터를 담을
  주체가 없다. 정식 로그인은 Supabase Auth로 가기로 정해져 있다.
- 결정: 게스트를 "로그인 안 한 상태"로 두지 않고 Supabase Auth
  `signInAnonymously()`로 발급한 **정식 사용자 한 명**(`auth.users`에 행 생성,
  `is_anonymous = true`)으로 취급한다.
- 이유: 나중에 `linkIdentity()`/`updateUser()`로 계정을 연결하면 `sub`(uid)가 유지된
  채 `is_anonymous`만 false가 되므로, 게스트 데이터 승계가 이관이 아니라 플래그
  전환이 된다. 자체 `guest_id`를 발급했다가 병합하는 방식에서 필요한 병합 로직·부분
  실패 복구·중복 소유자 처리를 만들지 않아도 된다.
- 계층: 신원(uid, 기기 영속)과 세션(`sess_...`, TTL 30분)을 분리한다. B 계약 5.2절의
  세션 발급·만료·재발급 규칙은 바꾸지 않는다.
- 전달: `Authorization: Bearer <supabase access token>` 헤더로만 받는다.
  `AgentRequest` body에 `user_id`를 두지 않는다 — 클라이언트가 임의의 uid를 적어 보낼
  수 있기 때문이다.
- 조용한 통과 방지: 초기에는 인증을 optional로 두되, **토큰 없음**은 통과시키고 `WARN`
  로그와 응답 메타 `authenticated: false`로 드러내며, **토큰이 있는데 검증 실패**한
  경우는 익명으로 강등하지 않고 401로 끊는다 (D-042와 같은 방향).
- 저장: `agent_states`/`recommendation_histories`에 `user_id uuid null`을 추가한다.
  RLS 정책은 신설하지 않는다 — 프론트는 DB에 직접 붙지 않고 FastAPI만 통하므로 서버
  secret key 단독 경로를 유지한다.
- 운영 전제: Supabase 대시보드에서 익명 로그인을 활성화한다(2026-08-19 완료). 누구나
  무제한으로 사용자를 만들 수 있는 엔드포인트라 방치하면 MAU가 부풀어난다. 남용 방지는
  rate limit(기본 IP당 시간당 30회)을 먼저 쓰고, CAPTCHA는 익명 사용자 수가 실제로
  비정상적으로 늘 때 켠다 — 켜면 모든 auth 엔드포인트에 적용돼 이후 소셜 로그인까지
  영향을 받고 프론트 위젯·토큰 전달 배선이 따라온다. 익명 사용자 발급은 페이지 로드가
  아니라 "게스트로 시작하기" 버튼을 눌렀을 때만 한다.
- 미결: (1) 오래된 익명 사용자 정리 주기와 참조 행 처리, (2) 이미 계정이 있는 사용자가
  게스트 상태에서 로그인할 때의 데이터 병합 — uid가 달라지는 유일한 케이스로, 로그인 도입 시점에 별도
  결정으로 다룬다.
- 개인정보: 게스트라고 익명 데이터가 아니다 — uid가 유지된 채 계정으로 승격되므로
  게스트 기간 기록이 실명 사용자에게 소급 귀속된다. 대화 원문은 자유 텍스트라 민감정보
  혼입을 통제할 수 없어 이번 범위에서 서버 저장을 하지 않는다. 대화 이어쓰기가 필요해지면
  프론트 `localStorage` → 조건만 복원 → 서버 대화 로그 순으로 검토한다(위험도와 구현
  비용 순서가 같다). 음성은 현재대로 저장하지 않는다.
- LLM 전송: 발화를 Gemini에 넘기는 것 자체는 처리위탁 구조라 문제가 아니지만, 현재
  경로가 Vertex AI가 아니라 Gemini Developer API(AI Studio)라 (1) 무료 티어면 입력이
  모델 학습에 쓰일 수 있고 (2) 리전 지정이 안 돼 사실상 국외이전이다. `LLM_API_KEY`의
  티어 확인과 처리방침 명시가 선행 조건이다. **프롬프트와 LLM 호출 메타데이터에는
  게스트 uid·`session_id`·좌표를 넣지 않는다** — 현재 `gemini_prompts.py`가 이미 그런
  상태이고 이를 규칙으로 고정한다. 추적이 필요하면 내부에만 남는 `trace_records`를 쓴다.
- 검증: 이 프로젝트 Auth는 비대칭 키(ES256)로 서명하고 JWKS로 공개키를 공개한다
  (`key_ops: ["verify"]`). 백엔드는 비밀값을 보관하지 않고 공개키를 캐시해 로컬에서
  검증한다 — `GET /auth/v1/user` 호출 방식은 요청마다 왕복이 붙고 Auth 장애가 전 API
  장애로 번진다. 위험은 공개키 유출이 아니라 검증 코드에 있다: `algorithms`를 우리가
  고정하고(헤더의 `alg`를 따르면 알고리즘 혼동 공격으로 공개키가 HMAC 비밀키로
  악용된다), JWKS 주소는 설정값으로 고정하며, `iss`/`exp`를 확인하고, 모르는 `kid`면
  JWKS를 다시 받는다.
- 상세: `docs/design/guest-auth-design.md`

### D-063 — 게스트 신원을 세션에 저장하기 전에 정할 것 (B 확인 필요)

- 상태: `Proposed` — **Package B 확인 대기.** 네 항목 모두 B 소유 영역이다.
- 배경: D-062 Phase 1~2로 프론트가 신원을 발급해 보내고 백엔드가 검증까지 하게 됐다
  (PR #183). 다음 단계는 검증한 `user_id`를 세션에 붙여 저장하는 것인데, 대상이
  `agent_states`·`recommendation_histories`와 `AgentState` 계약이라 B 판단이 선행해야
  한다. 상세와 마이그레이션 초안은 `docs/design/guest-auth-design.md` 6-1절에 있다.
- 결정 1 — **저장소 전환 시점.** `STATE_STORE_BACKEND` 기본값이 `memory`라 이대로
  `user_id`를 저장하면 재시작마다 소유자 정보가 사라진다. 권장: 전환을 Phase 3에
  포함하지 않고, `supabase`로 켜는 순간 동작하는 상태까지만 만든다. 전환은 모든 세션
  읽기·쓰기가 네트워크를 타게 되어 지연·장애 특성이 달라지므로 저장소 소유자가 시점을
  정한다. 이 설정은 게스트 로그인이 만든 것이 아니라 `[B-05]`(2026-08-03)로 이미
  있던 것이다.
- 결정 2 — **소유권 검증 위치.** 지금은 `session_id`만 알면 남의 세션도 조회된다.
  권장: Phase 4(인증 필수화)로 미룬다. 신원이 반드시 있다는 전제가 서는 시점이라
  소유자 대조를 넣기 자연스럽고, Phase 3에 넣으면 신원 없는 요청 처리가 애매해진다.
- 결정 3 — **비어 있는 세션에 신원이 붙는 경우.** 권장: `user_id`가 비어 있으면 채우고,
  값이 있으면 절대 덮어쓰지 않는다. 빈 칸을 채우는 것은 소유권 이전이 아니지만 값이
  있는 것을 덮어쓰는 것은 소유권 탈취다.
- 결정 4 — **`auth.users(id)` 외래키.** 사용자 테이블은 이미 있다(Supabase 관리
  `auth.users`, `signInAnonymously()`마다 행 생성). 권장: FK를 걸지 않는다.
  (1) `db-store-design-v2.md` §2-3이 테이블 간 FK를 의도적으로 두지 않았고,
  (2) `public`이 통제 밖인 `auth` 스키마에 의존하게 되며,
  (3) 오래된 익명 사용자 정리와 충돌한다(`restrict`면 삭제가 막히고 `cascade`면 세션이
  함께 지워진다).
- 상태 갱신(2026-08-20): 네 결정 모두 확정되어 TP-101 3단계 착수·완료. 마이그레이션
  `supabase/migrations/202608200002_add_user_id_to_agent_state_tables.sql` 작성
  완료(아직 미적용), `AgentState`/`RecommendationHistory.user_id` 필드와 연결
  로직(`session.attach_user_id()`/`history.attach_user_id()`) 구현·테스트 완료.
  `record_recommendation`/`record_closed_exclusions`/`apply()`의 rejected_places
  경로까지 세 곳 모두 연결되어, 세션(`agent_states`)과 이력(`recommendation_histories`)
  양쪽 모두 신원이 채워진다. 남은 건 마이그레이션을 실제 Supabase에 적용하는 것뿐이다.
- 상세: `docs/design/guest-auth-design.md` 6-1절

### D-064 — 프롬프트 `meta.yaml`은 당분간 사람이 읽는 선언으로 두고, 런타임은 Markdown만 읽는다

- 상태: `Superseded` — 아래 "미룬 것 1"(`version:` 소비)은 **D-065로 즉시 착수해 완료**했다.
  나머지(`owner:`, `evals:`, 미조합 공통 규칙 3건)는 여전히 `Deferred`.
- 배경: 인텐트별 프롬프트 라이브러리(`backend/app/prompts/`)를 도입하면서 프롬프트 본문을
  `gemini_prompts.py`의 f-string에서 인텐트 폴더의 Markdown으로 옮겼다(커밋 `0695d86`).
  이관 직후 점검에서 `meta.yaml`의 일부 필드가 어떤 코드에도 소비되지 않는다는 것이
  확인됐다. 이관 자체는 프롬프트 텍스트를 바꾸지 않는 순수 이동이었고, 렌더 결과
  스냅샷 27건이 0바이트 차이로 이를 증명한다.
- 결정 — **`meta.yaml`을 런타임 설정값으로 승격하지 않는다.** 런타임(`loader.py`)은
  Markdown 자산만 읽고, `meta.yaml`은 (1) 사람이 읽는 소유·버전 표시와 (2) CI 검사의
  입력으로만 쓴다. 강의 교재 25-6의 YAGNI 원칙 — *"필요해질 때 도입하는 것이 원칙"* — 을
  따른다. 지금 승격해도 사용자에게 달라지는 것이 없다.
- 현재 강제되는 것 (`backend/tests/prompts/test_prompt_assets.py`):
  - `template`·`bundle` 선언이 **실제 조합과 일치**해야 한다. 선언만 하고 코드가 안 읽으면
    CI 실패 — 이관 전 실제로 있었던 "담당자가 `.md`를 고쳐도 서비스는 그대로인" 조용한
    실패를 막는다.
  - 아무도 읽지 않는 자산(고아 파일)이 생기면 CI 실패. 예외는 이유를 적어
    `KNOWN_UNCOMPOSED`에 올려야 한다.
- ~~미룬 것 1 — `version:`이 아무 데서도 소비되지 않는다.~~ → **D-065로 해소됨.**
- 미룬 것 2 — **`owner:`도 소비처가 없다.** `app/prompts/OWNERS.md`와 이중으로 적혀 있어
  어긋날 수 있다. 필요해지면 `.github/CODEOWNERS`와의 일치를 CI로 검사한다.
- 미룬 것 3 — **`evals:`가 가리키는 인텐트별 평가 케이스가 아직 없다.** `evals/` 아래에
  README만 있고 실제 케이스는 0건이다. 인텐트별 단위 평가를 채우더라도 **머지 게이트는
  기존 `backend/test_results/agent_quality/`의 다중 턴 전수 실행을 유지한다** — 골드셋
  다중 턴 케이스가 인텐트 경계를 넘나들어(dev 35건 중 13건) 인텐트별로 쪼갤 수 없고,
  강의 27-4가 요구하는 것도 *"세트 전체의 향상"*이기 때문이다. 인텐트별 평가는 담당자의
  빠른 반복용이지 게이트가 아니다.
- 함께 미룬 것 — `_shared/rules/{factuality,safety,service_scope}.md` 3건은 작성돼 있으나
  아직 어느 프롬프트에도 조합되지 않았다. 넣으면 프롬프트 출력이 바뀌므로 골드셋 평가와
  함께 별도 변경으로 진행한다. 이유는 `KNOWN_UNCOMPOSED`에 기록돼 있다.
- 범위 밖: 프롬프트 편집 UI, 런타임 핫스왑, 프롬프트 DB 저장, Langfuse 등 외부 프롬프트
  관리 SaaS. 채점자가 저장소를 직접 읽는 프로젝트라 자산을 저장소 밖으로 빼지 않는다.
  관측 도구가 필요해지면 그때 붙이되 직접 만들지 않는다(강의 94-5).
- 상세: `backend/app/prompts/README.md`, `backend/app/prompts/OWNERS.md`

### D-065 — 실행 기록에는 그 턴이 실제로 쓴 슬롯의 버전을 남긴다

- 상태: `Accepted` — 구현 완료. D-064의 "미룬 것 1"을 대체한다.
- 배경: 기존에는 `record_trace(prompt_version=...)`에 손으로 적은 고정 문자열
  `agent-interpret-prompts-1.0.16` **하나만** 실렸다. 인텐트별로 담당자가 나뉜 뒤에는
  INFO 담당자가 `info/extract.md`를 고쳐도 이 값이 그대로여서, *"이 응답은 어느
  프롬프트에서 나왔나"*에 답할 수 없었다. 진짜 버전은 `meta.yaml`에 있는데 기록에는
  무관한 고정값이 붙는 상태였다.
- 결정 — **`registry.py`가 `meta.yaml`을 실제로 파싱**하고, 턴마다 그 턴이 사용한 슬롯의
  버전을 조합해 기록한다.

  | | 값 |
  |---|---|
  | 이전 | `agent-interpret-prompts-1.0.16` |
  | 현재 | `router.classify@2.0.0+info.extract@3.0.0` |

  과거 기준선으로 실행 중이면(`TRIPBRANCH_PROMPT_VARIANT`) 뒤에
  `+variant:<ID>`가 붙어 "옛 프롬프트로 낸 기록"임이 남는다.
- 슬롯 선택은 `INTENT_SLOTS` 라우팅 테이블로 한다(강의 89-3 "새 의도는 테이블에 한 줄").
  분류(`router.classify`)는 항상 돌고 그 뒤 인텐트별 추출/편성 슬롯이 하나 더 돈다.
  실제 렌더된 슬롯을 런타임에서 수집하지 않는 이유는 요청 컨텍스트 전파 배선이
  4~5개 파일에 걸치는 데 비해 인텐트→슬롯 대응이 결정적이기 때문이다.
- 답변 생성 슬롯(`*.answer`, `*.summary`)은 넣지 않았다 — 기록 시점
  (`step="llm_interpret"`)에는 아직 돌지 않았고, 회귀 판정에 쓰는 지표(intent·조건 추출
  정확도)가 전부 해석 단계 산출물이라 없이도 추적이 성립한다. 필요해지면
  `step="llm_answer"` trace를 추가한다.
- B 영향 없음 — 계약상 B는 이 값을 해석하지 않고 문자열로만 저장한다
  (`llmops-trace-contract-v1.md` §7 Q2). 형식이 바뀌어도 B 쪽 스키마 변경이 없다.
- 프롬프트 출력 불변 — 딱지만 바꾼 변경이라 챗봇 응답은 그대로다. 렌더 스냅샷 27건이
  0바이트 차이로 이를 보증한다.
- 안전장치 3건 (`backend/tests/prompts/test_prompt_assets.py`):
  - `INTENT_SLOTS`가 참조하는 슬롯이 `meta.yaml`에 전부 있어야 한다 — 슬롯 이름을 바꾸고
    표를 안 고치면 기록에서 슬롯 하나가 **조용히 빠지므로** 여기서 먼저 터뜨린다.
  - 모든 `Intent`가 `INTENT_SLOTS`에 등록돼야 한다 — 새 인텐트를 추가하고 등록하지 않으면
    분류 슬롯 버전만 남는다.
  - 조합 문자열이 슬롯을 빠짐없이 담는지 인텐트별로 확인한다.
- 남은 운영 부담: 프롬프트를 고칠 때 `meta.yaml`의 `version:`도 함께 올려야 한다. 지금은
  사람이 챙긴다 — 스냅샷 테스트가 "텍스트가 바뀌었다"는 사실 자체는 잡아주므로(갱신
  시점에 버전도 올리면 된다), 자동 강제는 두지 않았다.
- 상세: `backend/app/prompts/registry.py`

### D-066 — 답변·요약 계열 5곳에도 thinking_budget=0을 적용한다

- 상태: `Accepted` — 구현 완료. `_thinking_config_for()`(gemini.py)가 남겨뒀던 미해결
  메모를 대체한다.
- 배경: gemini-2.5-flash → gemini-3.5-flash 전환 이후 실사용에서 GENERAL 인사말
  ("안녕") 응답에도 6~7초 TTFT가 걸리고, COMPARE류 후속 질문에서 분류+추출 두 호출이
  합쳐 18초 넘게 걸려 클라이언트 45초 무활동 타임아웃에 근접하는 문제가 확인됐다
  (실제로 한 세션에서 48초 `stream_inactive` 오류 재현). 원인은 답변·요약 계열
  5곳(`generate_general_answer`/`stream_general_answer`/
  `generate_recommendation_summary`/`stream_recommendation_summary`/
  `stream_info_answer`/`generate_compare_summary`)이 `thinking_budget`을 아예 안 넘겨
  모델 기본 동작(gemini-3.5-flash는 MEDIUM, 항상 켜짐)을 그대로 썼기 때문 — 이전
  thinking_budget=0 적용(SCHEDULE·classify_intent·extract_recommend_conditions) 때는
  "문장 생성·요약류는 품질 저하 리스크"라는 이유로 의도적으로 제외했던 곳들이다
  (`_thinking_config_for()` docstring 참고).
- 결정 — `scripts/compare_answer_thinking_budget.py`로 5개 케이스 × 3회 실측
  (thinking_budget=None vs 0)한 결과, thinking_budget=0이 평균 **3.9배** 빠르면서
  (예: GENERAL 자기소개 5.9초→1.3초, COMPARE 요약 6.4초→1.6초) 답변 문구는 페르소나·
  자기소개("트리비")·문장 수 규칙을 그대로 지켰다(수동 확인 — 우려했던 품질 저하는 이
  케이스들에서 근거로 뒷받침되지 않았다). 결과:
  `test_results/answer_thinking_budget_latency.csv`. 5개 호출부 모두 SCHEDULE과 같은
  방식으로 `thinking_budget=0`을 내부에 고정했다(공개 API로 노출하지 않음 — 프로덕션에서
  이 값을 바꿔 부를 필요가 없다).
- 실사용 검증: `/api/chat/stream`에 같은 대화를 재현해 확인.
  - "안녕"(GENERAL): 9.35초 → 5.06초, TTFT 6.5초 → 0.85초
  - "첫 번째랑 두 번째 중에 어디가 더 가까워?"(COMPARE, 분류+추출): 18.8초 → 2.8초
- 안전장치: `tests/test_gemini_provider.py`에 5곳 각각 실제로 `thinking_config.
  thinking_level == MINIMAL`이 실리는지 확인하는 회귀 테스트 6건 추가(구조화 출력
  4곳 + 스트리밍 3곳, 스트리밍은 `generate_content_stream` mock으로 검증).
- Out of Scope: 분류·추출 계열 중 아직 손 안 댄 4곳(`extract_modify_conditions`/
  `extract_info_query`/`extract_compare_request`/`extract_general_request`)은 이번
  범위 밖 — 이번 작업은 "답변 생성 계열부터"로 한정했다. 45초 타임아웃의 다른 절반
  원인(분류·추출 단계에 SCHEDULE 같은 하트비트가 없는 문제)도 별도 작업이다.
- 상세: `backend/app/providers/gemini.py`(`_thinking_config_for()`),
  `backend/scripts/compare_answer_thinking_budget.py`

### D-067 — 후보를 줄 세우는 기준점은 검색 기준점이 아니라 사용자 위치다

- 상태: `Accepted` — 구현 완료. TP-109와 TP-112 카드가 남긴 "`distance_km` 기준점을
  바꾸지 않는다"를 대체한다.
- 배경: `"지금 혜화역인데 안국역 근처 갈만한 곳"`처럼 사용자 위치와 검색 기준점이
  갈리는 요청에서, 거리·경로·근거 문장이 전부 검색 기준점(안국역)에서 계산됐다.
  실사용 실측에서 `"자동차 이동 1분"`으로 표시된 후보가 사용자(서대문역) 기준으로는
  23분이었다 — 어긋남 22분(TP-112 코멘트, 네이버 Directions 실측).
- 결정 — **모으는 중심과 줄 세우는 기준점을 분리한다.**
  - 후보 수집은 그대로 검색 기준점 중심이다. `"안국역 근처"`라고 했으면 안국역
    주변을 뒤지는 것이 맞다.
  - 거리(`distance_km`)·실측 경로 origin·근거 문장의 기준점 이름은 사용자 위치
    (`context.user_location`)에서 잰다. 실제로 이동하는 사람이 사용자이기 때문이다.
  - 사용자 위치를 모르는 요청(발화도 기기 GPS도 없음)은 예전처럼 검색 기준점으로
    돌아간다. 지어낸 좌표로 줄을 세우지 않는다.
- 근거 — 검색 기준점에서 **같은 거리에 있는 두 후보를 타겟 기준으로는 영영 구분할 수
  없다.** 방향이 반대여도 동점이라 `place_id` 순으로 밀린다. 사용자 기준으로 재야
  사용자 쪽 후보가 앞선다(`tests/test_ranking_origin.py`의
  `test_user_side_candidate_wins_a_target_side_tie`).
- 거리 점수 분모: **사용자가 이동시간을 말한 요청은 손대지 않는다.** 그때 분모는
  `max_travel_time × 속도`이고 실측 분기에서 같은 속도로 다시 나뉘어 "사용자가 말한
  30분"이 그대로 예산이 된다 — 시간 약속은 어디서 재든 같은 값이라 애초에 원점이
  없다. 여기 거리를 더하면 "30분"이 사실상 30분+α가 된다.

  **말하지 않은 요청에만 사용자 → 검색 기준점 거리를 더한다.** 그때 분모는
  `DEFAULT_PLACE_SEARCH_RADIUS_KM`(2.0km)인데, 이 값은 "타겟 주변 얼마를
  뒤지는가"라는 수집 정책에서 빌려온 거리라 원점이 타겟에 묶여 있다. 분자만 사용자
  기준으로 바꾸면 사용자가 타겟에서 멀 때 모든 후보가 분모를 넘겨 거리 Feature
  (가중치 0.20)가 통째로 죽고, 순위가 날씨·운영시간만으로 정해진다. 후보는 전부 타겟
  중심 수집 반경 안에 있으므로 삼각부등식에 따라 사용자 기준 거리는
  `사용자→타겟 + 수집 반경`을 넘을 수 없다 — 이 값을 더하면 어떤 후보도 0으로 잘리지
  않고, 사용자가 기준점에 서 있으면 0.0이라 기존 분모로 되돌아간다.
- 채택하지 않은 것:
  - 수집 중심까지 사용자 위치로 옮기기 — `"안국역 근처 추천해줘"`라는 요청 자체를
    배신한다.
  - 후보들의 사용자 기준 거리로 min-max 정규화 — 변별력은 최대지만 분모가 후보
    집합에 따라 매번 달라져 "사용자가 말한 시간이 곧 예산"이라는 설계를 버리게 된다.
  - 분모를 타겟 기준으로 둔 채 분자만 옮기기 — 위 0점 문제가 그대로 남는다.
- 남은 것: 이동시간 미언급 분기의 분모에는 `MAX_PLACE_SEARCH_RADIUS_KM`(20km) clamp를
  걸지 않았다. 그 상수는 장소 검색 Provider가 허용하는 **수집** 상한이라 채점 분모에
  걸면 0점 문제가 되살아난다. 종로구 MVP 범위에서 20km 밖 사용자는 드물지만, 채점
  분모 전용 상한이 필요한지는 정하지 않았다.
- 상세: `backend/app/domain/ranking_origin.py`,
  `backend/app/services/recommendation_pipeline.py`(`_distance_denominator_offset_km`),
  `backend/tests/test_ranking_origin.py`

### D-068 — 피드백을 남긴 턴에 한해서만 질문·답변 원문을 저장한다

- 상태: `Accepted` — 구현 완료.
- 배경: `response_feedback`(roadmap.md 14번, D-062/D-063와 별개 트랙)은 `session_id`/
  `run_id`/`rating`만 저장해, 테스트 중 "이 반응이 정확히 뭐에 대한 것인지" 원문으로
  확인할 방법이 없었다. `guest-auth-design.md` 9절은 대화 원문을 저장 위험도가 가장
  높은 항목으로 분류하고(자유 텍스트, 개인정보·민감정보 통제 불가), 서버 대화 로그
  저장 자체를 9-4절에서 의도적으로 미루고 있다 — 이 전제는 그대로 유지한다.
- 결정 — **대화 전체가 아니라, 사용자가 좋아요/싫어요를 명시적으로 남긴 턴만** 그
  턴의 질문(`user_input`)·답변(`assistant_message`) 원문을 `response_feedback`에
  함께 저장한다. 두 컬럼 모두 nullable — 프론트가 텍스트를 못 찾거나 안 보내도
  `rating` 기록 자체는 그대로 유효하다.
- 근거: 전체 대화 로그(9-4절의 "3번")보다 노출 범위가 훨씬 좁다 — 사람이 실제로
  반응한 턴만 남는다. 그 목적(테스트 중 피드백 검토 편의)에도 대화 전체보다
  정확히 맞는다.
- 채택하지 않은 것:
  - 모든 턴의 원문을 저장 — guest-auth-design.md 9절이 경고한 가장 높은 위험
    시나리오와 같다. 지금 목적(피드백 검토)에 비해 과도하다.
  - `conditions`처럼 구조화해서 저장 — 자유 발화 자체를 구조화 없이 그대로 보여줘야
    "뭐라고 물어봤는지" 확인이라는 목적을 만족한다.
- 남은 것: 보관기간·자동삭제 정책은 아직 없다 — 지금은 개발/테스트 단계 전제다.
  실서비스 공개 전에는 9-3절(보관기간·동의 지점·삭제 요구 경로)을 이 컬럼에도
  적용할지 다시 결정해야 한다.
- 상세: `supabase/migrations/202608210004_add_feedback_turn_text.sql`,
  `backend/app/state/schema.py`(`FeedbackRecord`), `backend/app/state/feedback.py`,
  `frontend/src/components/chat/FeedbackButtons.tsx`,
  `frontend/src/utils/turnText.ts`

### D-069 — 피드백에 intent(그대로 복사)와 comment(싫어요 사유)를 추가한다

- 상태: `Accepted` — 구현 완료.
- 배경: D-068 구현 직후, 다른 제안(피드백 테이블에 intent/is_clarification/
  clarification_code/comment까지 함께 저장하고 모두 NOT NULL로 두자는 안)이
  들어왔다. 검토 결과 그대로 채택할 수 없는 부분과 그대로 채택 가능한 부분이
  섞여 있었다 — 아래 "채택하지 않은 것"에 이유를 정리한다.
- 결정:
  1. `intent`(선택, nullable) 추가 — 그 턴의 `assistant_text` 메시지가 이미
     들고 있는 값을 그대로 복사해 저장한다. B는 값을 검증하지 않는다
     (step/prompt_version과 같은 성격).
  2. `comment`(선택, nullable) 추가 — "싫어요" 사유를 사용자가 직접 남기는
     자유 텍스트. 클릭 즉시 전송하지 않고, 인라인 입력창(제출/건너뛰기)을
     먼저 띄운 뒤 하나의 레코드로 함께 보낸다 — append-only 구조에서 사유
     없이 먼저 보내고 나중에 사유 있는 레코드를 또 쌓으면 같은 run_id의
     dislike가 중복 집계되기 때문.
- 근거: intent는 이미 프론트가 들고 있는 값을 옮기기만 하면 되어 구현 부담이
  거의 없다. comment는 D-068과 같은 "테스트 중 피드백 검토 편의" 목적에
  직접 부합한다(사유가 있으면 왜 별로였는지 바로 보인다) — 다만 원 요청
  범위를 넘는 새 UI라 AskUserQuestion으로 사용자에게 직접 확인받았다.
- 채택하지 않은 것:
  - 모든 컬럼 NOT NULL — 프론트가 턴 텍스트를 못 찾는 예외 상황(레거시
    카드 재구성 경로 등)에서 텍스트만 비는 게 아니라 rating 기록 자체가
    통째로 실패하게 된다. nullable로 두고 텍스트는 "있으면 같이"가 더
    안전한 실패 방식이다(D-068과 동일한 판단).
  - `is_clarification`/`clarification_code` — 지금 구조에서는 되묻기
    (clarification) 메시지에 피드백 버튼 자체가 없다(추천/일정 결과
    카드에만 있음). 채울 방법이 없는 컬럼을 미리 만들지 않는다 — 되묻기
    메시지에도 피드백을 받고 싶어지면 그때 버튼 배선부터 다시 설계한다.
  - 프론트 `state.user_input` 등 reducer 최상위 상태를 그대로 사용 —
    세션에 하나뿐인 필드라 새 턴이 오면 덮어써진다. 화면을 스크롤해 예전
    카드에 피드백을 남기면 최신 턴의 값이 잘못 붙는다. 대신 카드 위치
    기준으로 거슬러 올라가 찾는 기존 `findTurnText`를 그대로 확장해 intent도
    같이 찾도록 했다.
- 병합 후기(같은 날 develop merge): 이 작업 직후 develop에 팀원이 독립적으로
  구현한 comment 기능(PR)이 먼저 merge됐다 — 같은 목적을 다른 방식으로
  구현한 우연한 충돌. 병합 시 develop 쪽을 기준으로 정리했다: comment 컬럼은
  develop의 마이그레이션(`202608210003_add_comment_to_response_feedback.sql`,
  DB단 500자 CHECK 제약 포함, pydantic max_length=500과 이중 방어)을 그대로
  채택하고 우리 쪽 comment 컬럼 추가는 제거, FeedbackButtons UI도 develop의
  아이콘 기반 버전(더 완성도 높음)을 채택해 우리 버전은 버렸다. intent만
  우리 쪽 추가로 남았다. 또한 develop이 `recommendation_result`/
  `schedule_result` 메시지에서 피드백 버튼을 분리해 별도 `"feedback"`
  ChatMessage 타입(카드 뒤에 이어지는 독립 메시지)으로 구조를 바꿔서,
  `findTurnText` 호출 지점도 결과 카드가 아니라 이 `"feedback"` 메시지의
  index로 옮겼다 — `findTurnText`는 텍스트가 없는 메시지를 건너뛰므로 로직
  변경은 필요 없었다. 마이그레이션 번호 충돌(둘 다 202608210002/003을 씀)로
  우리 쪽 파일은 004/005로 재번호했다.
- 정정(병합 후 발견): 위 "채택하지 않은 것"의 `is_clarification`/
  `clarification_code` 제외 근거("되묻기 메시지에 피드백 버튼 자체가
  없다")가 병합 이후로는 더 이상 사실이 아니다 — develop이 피드백을
  `run_id`만 있으면 붙는 범용 `"feedback"` 메시지로 바꾸면서, 백엔드가
  되묻기 응답에도 항상 `run_id`를 발급하기 때문에(`service.py` `apply()`,
  확정 여부와 무관하게 매 턴 발급) 되묻기 턴에도 피드백 버튼이 이미 뜨고
  rating은 저장되고 있었다. 다만 `findTurnText`가 답변 자리에서
  `"assistant_text"`만 찾고 `"clarification"` 타입은 인식하지 못해
  `assistant_message`가 계속 비어 있던 것을 확인해, `"clarification"`도
  답변으로 인식하도록 확장했다(`intent`는 clarification 메시지에 그 값 자체가
  없어 여전히 비어 있다 — `is_clarification`/`clarification_code` DB 컬럼을
  새로 만들지 않기로 한 결정 자체는 유지, 그 컬럼들을 채울 데이터가 필요해지면
  그때 다시 검토).
- 상세: `supabase/migrations/202608210005_add_feedback_intent.sql`,
  `backend/app/state/schema.py`(`FeedbackRecord`), `backend/app/state/feedback.py`,
  `backend/app/state/service.py`, `frontend/src/utils/turnText.ts`,
  `frontend/src/components/chat/FeedbackButtons.tsx`,
  `frontend/src/components/chat/ChatMessageList.tsx`

### D-070 — reason_code(구조화된 싫어요 사유) PR 검토·반영, 마이그레이션 뷰 버그 수정

- 상태: `Accepted` — 구현은 팀원(PR #214, `feature/llm-interpret`)이 완료해 develop에
  merge, B는 상태·Supabase 저장 계약 검토와 마이그레이션 적용을 요청받아 수행.
- 배경: D-069 병합 직후, 같은 팀원이 "싫어요" 사유를 자유 텍스트(comment)뿐 아니라
  집계 가능한 표준 코드(`reason_code`)로도 남길 수 있게 하는 기능을 독립적으로
  구현해 PR #214로 develop에 merge했다. PR 설명에서 B(상태·Supabase 저장 계약
  소유자)에게 두 가지를 요청 — ① 상태·저장 계약이 깨지지 않는지 검토, ②
  `202608210006_add_feedback_reason_code.sql` 마이그레이션을 실서비스 DB에 적용.
- 결정:
  1. `reason_code` 그대로 채택 — `FeedbackReasonCode` 7값 Literal(intent_mismatch/
     clarification_unhelpful/context_not_preserved/location_misunderstood/
     conditions_not_applied/recommendation_not_suitable/other)이 DB CHECK 제약과
     정확히 일치하고, `RecordFeedbackRequest` validator가 "좋아요"에는 reason_code/
     comment 둘 다 못 붙이게 막아 계약 위반 없음을 확인.
  2. `intent`/`user_input`/`assistant_message` 캡처 아키텍처는 이쪽(render-time
     `findTurnText`)을 그대로 유지 — PR #214가 자체적으로 시도했던 reducer 시점
     임베딩 방식(`ChatMessage` 생성 시 값을 미리 박아두는 방식)은 최종 merge에서
     채택되지 않았다. D-069에서 정리한 "스크롤해 예전 카드에 피드백을 남기면
     최신 턴 값이 잘못 붙는" 문제를 render-time 방식이 이미 해결한 상태라 되돌아갈
     이유가 없었다.
  3. 마이그레이션 적용 중 발견한 버그 수정 — `202608210006`의 `response_feedback_kst`
     뷰 재정의가 기존 컬럼 순서(`...user_input, assistant_message, intent...`)를
     깨고 `intent`를 앞으로 옮기려다 PostgreSQL의 `create or replace view` 제약
     (42P16: 기존 컬럼 이름·순서 변경 불가)에 걸려 실서비스 적용이 실패했다. 기존
     순서를 그대로 두고 `reason_code`를 맨 뒤에 추가하도록 수정. `begin`/`commit`으로
     감싸져 있어 실패 시 전체 롤백 — 부분 적용된 상태는 없었다.
- 근거: 표준 사유 코드는 "좋아요/싫어요 수만으로는 어떤 인텐트·응답에서 문제가
  생겼는지 분석할 수 없다"는 D-069 이후로도 유효했던 한계를 정확히 메운다. B
  자체 구현 없이 검토·인프라(마이그레이션) 역할만 맡는 것도 팀 내 실제 구현자와
  중복 작업하지 않는다는 원칙에 맞는다.
- 채택하지 않은 것: PR #214의 reducer-embedding 방식(intent/user_input/
  assistant_message를 `"feedback"` 메시지 생성 시점에 미리 채워두는 안) — 코드
  구조는 더 단순하지만 D-069가 이미 해결해둔 문제를 다시 열 이유가 없어 review
  단계에서 채택하지 않았다.
- 남은 것: 없음 — 계약 검토·마이그레이션 적용 모두 완료. `llmops-trace-contract-v1.md`
  §8-3에 계약 반영.
- 상세: `supabase/migrations/202608210006_add_feedback_reason_code.sql`,
  `backend/app/state/schema.py`(`FeedbackReasonCode`),
  `backend/app/state/service.py`(`RecordFeedbackRequest` validator),
  `frontend/src/components/chat/FeedbackButtons.tsx`

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
| 2026-08-05 | 혼잡도 실서버 E2E 검증 문서(`concentration-e2e-verification.md`) 작성. D-050으로 혼잡도 2차 Scoring 결과의 순서만 B에 저장되고 점수/등급 값은 저장 안 됨을 기록(코드 미변경) |
| 2026-08-05 | D-051 날씨 사실/판정 분리 — C의 사실 전달과 `NO_MENTION` 수용 구현, 판정 이관은 D 확인 대기 |
| 2026-08-05 | D-052 Gemini 동일 벤더 내 모델 fallback(`LLM_FALLBACK_MODEL_NAMES`) 구현 + AppError 전파 경로 로깅 추가(무로그 502 문제 해결) |
| 2026-08-05 | D-051 판정 이관 구현 완료 — `weather_judgment.py` 신설(사실/발화 기반 판정 + 의도 재해석), `recommendation_pipeline.py`가 PR #102의 `conditions` 파라미터를 받아 사실 우선·발화 폴백으로 배선, `resolve_weather_condition()` public 전환(2차 Scoring 재사용용), `weather_ignored` 판별을 IGNORE 전용으로 정정. 2차 Scoring 배선 통일과 `condition` 필드 제거는 남은 것으로 기록 |
| 2026-08-05 | D-051 근거 문장 정확도 수정 — 판정 함수가 `WeatherReason`(rain/snow/heat/cold)을 함께 반환하도록 바꾸고 `scoring.py`/`evidence.py`/`explanation.py`까지 관통시켜, "폭염인데 비 예보"·"ENJOY로 GOOD인데 맑은 날씨"라고 말하던 사실-근거 불일치를 해소 |
| 2026-08-05 | D-051 기온 판정을 기상청 주의보/경보 2단계(33·35°C, -12·-15°C)로 재설계 — 주의보~경보 사이를 NEUTRAL로 두어 근거 있는 완충 구간 확보. 30~32°C 등 주의보 미만 구간은 의도적으로 미해결로 남김 |
| 2026-08-06 | D-051 `condition` 전면 제거 — `WeatherForecastSlot.condition`(D 소유)부터 `SelectedWeatherForecast.condition`, `map_sky_pty_to_condition()`, `tool_intelligence` 계약, `fake_weather_condition` 설정까지 걷어냄. `tool-intelligence-contract-v1.md`의 `TI-09`를 `Superseded`로, §9 `api_weather` 매핑을 D-038 무효로 반영 |
| 2026-08-07 | D-055 신설 — INFO `event` 지원(C). `sigunguCode` 필터가 응답 다수를 탈락시키는 것을 실측으로 확인해 법정동 코드로 전환하고, 장소명 매칭 대신 좌표 근접으로 "근처 진행 중 행사"를 답하도록 결정. `EventInfoResult` 신설 |
| 2026-08-07 | D-054 신설 — INFO `question_type` 8종으로 확장(C). 상세 질의는 Supabase 캐시에 데이터가 없어 TourAPI를 직접 조회하도록 결정하고 `GetPlaceDetailTool`·`info_field_rules` 신설. `event`는 `unsupported`, A 배선 3건은 별도 카드 |
| 2026-08-06 | D-053 신설 — TP-67(PR #113) 후속으로 위치 변경 판정에서 지명 단독을 제외해 `INFO`(정보 조회) 흐름을 지키고, `environment` 미언급(`ANY`)이 되묻기 답변에서 앞 턴의 `indoor`를 덮어쓰던 갭을 프롬프트 규칙 + 보존 목록으로 막음. `PROMPT_VERSION` 1.0.2 |
| 2026-08-07 | D-054 트리비 페르소나와 `GENERAL(service_identity)`, RECOMMEND/MODIFY 추천 결과 요약 LLM 추가. 요약 입력에서 내부 scoring 필드는 제외 |
| 2026-08-08 | D-056 신설 — TourAPI 주차·요금·이미지 원문을 `places` 컬럼 6개로 추가(C). 별도 테이블 분리 대신 컬럼 추가를 택한 근거와 축제 `usetimefestival` 함정, 커버리지 한계(주차 95%/요금 24%)를 기록 |
| 2026-08-08 | D-057 신설 — 집중률 검색어를 단일 값에서 공백 토큰 전부로 바꾸고, 코퍼스 등장 빈도 오름차순으로 조회하도록 결정하고 구현(C). 손으로 쓴 불용어 목록 대신 희소성 기준을 쓰는 근거를 실측(종로구 113개 이름)으로 기록하고, 대조 유사도 임계값 0.9를 유사도 매칭 금지 방침의 조건부 예외로 명시 |
| 2026-08-08 | D-058 신설 — 운영시간 요일 파싱 수정(C). `매주 월요일~화요일`의 물결표 요일 범위 전개와 요일별 운영시간 분리를 구현하고, 요일을 열거한 원문에서 빠진 요일을 정기 휴무로 유도하도록 결정. 유도 근거는 활성 844건 중 39건 실측(38건이 휴무 원문과 일치). 활성 97건의 운영 판정이 달라짐. `OPERATING_PARSER_VERSION` 1.2.0 |
| 2026-08-08 | D-059 신설 — SCHEDULE 되묻기 답변이 MODIFY로 오분류되던 문제 수정(A). `classify_intent()`에 `pending_clarification`/`last_intent` 컨텍스트를 전달하고 프롬프트 규칙만 추가(상태 레벨 override 채택 안 함, D-053과 같은 방향). 되묻기 플래그 소비 화이트리스트에 SCHEDULE 누락도 함께 수정. `PROMPT_VERSION` 1.0.7 |
| 2026-08-10 | D-060 신설 — INFO 상세 질의의 요금·주차·편의시설을 `raw_intro` 원본 키 조회에서 `PlaceDetails` 정규화 필드로 이관하고 옛 경로를 삭제(C). 전화번호 출처를 `detailCommon2` `tel`(축제만 5/5)이 아니라 `detailIntro2` 안내처(33건 중 32건)로 확정하고 `places`에 `info_center_raw` + 편의시설 컬럼 4개를 신설(편의시설은 대상 유형 55건 중 22건, 쇼핑은 카드결제·화장실 12/12). 캐시가 `question_type` 전부를 덮게 되어 INFO 상세 출처는 하이브리드로 단일화하고 선택 설정을 두지 않는다 — 외부 호출 3회 → 1회. D-054 대체 |
| 2026-08-18 | D-061 신설 — 상세 카드에서 요일별 운영시간 원문이 한 줄로 노출되는 문제를 기록. C가 `OperatingSchedule` 기반 표시 전용 구조를 제공하는 후속 작업을 제안하고, A/프론트는 계약 확정 전까지 원문 폴백을 유지 |
| 2026-08-19 | D-062 신설 — 정식 로그인 도입 전까지의 게스트 로그인 설계. 게스트를 Supabase 익명 사용자로 발급해 승계를 uid 유지로 해결하고, 신원(uid)과 세션(`sess_...`)을 분리. `Authorization` 헤더 전용 계약, optional 인증에서 토큰 없음(통과+경고)과 검증 실패(401)를 구분, `agent_states`/`recommendation_histories`에 `user_id` 추가. 승계가 익명성도 함께 무너뜨린다는 점과 대화 로그 서버 저장을 미루는 근거, LLM 전송의 티어·국외이전 쟁점과 프롬프트 식별자 금지 규칙을 개인정보 절로 기록. JWT 검증은 공개키 로컬 검증으로 확정하고 알고리즘 혼동 방어 항목을 함께 남김. `docs/design/guest-auth-design.md` 신설 |
| 2026-08-19 | D-063 신설 — D-062 Phase 3(신원을 세션에 저장) 착수 전 B 확인이 필요한 네 항목을 정리. `STATE_STORE_BACKEND` 전환 시점(Phase 3 제외 권장), 소유권 검증 위치(Phase 4 권장), 빈 `user_id` 채우기 규칙(덮어쓰기 금지), `auth.users` FK(걸지 않기 권장). 마이그레이션 초안은 소유자 확인 전까지 `supabase/migrations/`에 두지 않고 설계 문서 6-1절에만 둔다 |
| 2026-08-19 | D-064 신설 — 인텐트별 프롬프트 라이브러리 이관 완료 후, `meta.yaml`을 런타임 설정값으로 승격하지 않고 사람이 읽는 선언 + CI 검사 입력으로만 두기로 결정(YAGNI, 강의 25-6). `template`·`bundle`은 실제 조합과의 일치를 CI가 강제하고, 소비처가 없는 `version`·`owner`·`evals` 3건과 미조합 공통 규칙 3건(`factuality`/`safety`/`service_scope`)은 필요해질 때 착수하도록 미룸. 인텐트별 평가를 채우더라도 머지 게이트는 `agent_quality`의 다중 턴 전수 실행을 유지한다(강의 27-4) |
| 2026-08-19 | D-065 신설 — D-064의 "미룬 것 1"을 즉시 착수해 해소. `registry.py`가 `meta.yaml`을 파싱해 슬롯 버전을 읽고, `record_trace(prompt_version=...)`에 그 턴이 실제로 쓴 슬롯 버전을 남긴다(`agent-interpret-prompts-1.0.16` → `router.classify@1+info.extract@1`). 슬롯 선택은 `INTENT_SLOTS` 라우팅 테이블(강의 89-3), 과거 기준선 실행 시 `+variant:<ID>` 접미. 프롬프트 출력은 불변(스냅샷 27건 0바이트 차이), B 계약 변경 없음. 슬롯 이름 불일치·미등록 인텐트를 잡는 안전장치 3건 추가. D-064의 `owner`·`evals`·미조합 공통 규칙은 계속 `Deferred` |
| 2026-08-20 | D-066 신설 — gemini-3.5-flash 전환 뒤 미해결로 남아 있던 답변·요약 계열(GENERAL/RECOMMEND/COMPARE/INFO 답변 5곳)에 thinking_budget=0 적용. 실사용에서 "안녕" 응답 6~7초 TTFT, COMPARE류 후속 질문 18초+ 소요(45초 타임아웃 근접, 실제로 48초 stream_inactive 오류 재현)를 확인 후 `scripts/compare_answer_thinking_budget.py`로 5개 케이스 × 3회 실측 — 평균 3.9배 개선, 답변 품질(페르소나·자기소개·문장 수 규칙) 유지 확인. 5곳 모두 SCHEDULE과 같은 방식으로 내부 고정(공개 API 미노출). 실사용 재현으로 "안녕" 9.35초→5.06초(TTFT 6.5초→0.85초), COMPARE 분류+추출 18.8초→2.8초 확인. 회귀 테스트 6건 추가. 나머지 미최적화 추출 4곳과 분류·추출 단계 하트비트 부재는 범위 밖 |
| 2026-08-21 | D-067 신설 — 랭킹 기준점을 검색 기준점에서 사용자 위치로 이관(D·A). 후보 수집 중심은 검색 기준점 그대로 두고 거리·경로 origin·근거 문장 기준점 이름만 옮겼다. 검색 기준점에서 등거리인 두 후보를 타겟 기준으로는 구분할 수 없다는 것이 근거. 거리 점수 분모는 이동시간을 말한 요청에서는 그대로 두고(시간 약속은 원점이 없다), 말하지 않은 요청에만 사용자→기준점 거리를 더해 0점 전멸을 막는다. TP-109·TP-112의 `distance_km` 기준점 유지 방침을 대체한다 |
| 2026-08-21 | D-068 신설 — 피드백을 남긴 턴에 한해서만 질문·답변 원문(`user_input`/`assistant_message`)을 `response_feedback`에 저장하기로 결정. 대화 전체 로그 저장(guest-auth-design.md 9절이 위험도 "높음"으로 분류)과는 다르며, 사용자가 AskUserQuestion으로 "피드백 남긴 턴만"을 직접 선택. 두 컬럼 모두 nullable |
| 2026-08-21 | D-069 신설 — D-068 후속. `intent`(assistant_text 메시지 값 그대로 복사)와 `comment`(싫어요 사유 자유 텍스트) 필드 추가. comment는 append-only 중복 방지를 위해 클릭 즉시 전송하지 않고 인라인 입력창(제출/건너뛰기)에서 한 번에 전송. NOT NULL 전면 적용과 `is_clarification`/`clarification_code`(되묻기 메시지엔 피드백 버튼이 아예 없어 채울 수 없음)는 채택하지 않음 |
| 2026-08-21 | D-070 신설 — 팀원 PR #214(`reason_code` 구조화된 싫어요 사유)를 B 관점에서 검토·반영. FeedbackReasonCode 7값이 DB CHECK와 일치함을 확인, intent/user_input/assistant_message 캡처는 render-time `findTurnText` 방식을 그대로 유지(PR #214가 시도한 reducer-embedding 방식은 미채택). 마이그레이션 `202608210006` 적용 중 `response_feedback_kst` 뷰 컬럼 순서 버그(PostgreSQL 42P16) 발견·수정 |
