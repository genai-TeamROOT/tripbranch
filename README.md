# TripBranch

사용자의 자연어 요청과 현재 상황을 해석해 서울 지역의 장소 후보를 수집하고,
조건별 가중치를 적용해 적합한 장소를 추천하는 서비스입니다.

> 현재 단계: **Phase 1-A — Core AI Agent Flow**
> 현재 저장소는 React/FastAPI 골격, Fake/Real Provider, LLM 해석, 세션 상태 병합,
> C Context Service와 가중치 Scoring 기반을 갖추고 있습니다. 통합 Chat API와
> A–D 실제 추천 연결, 자연어 응답 생성은 아직 구현 전입니다.

## 해결하려는 문제

여행 중에는 날씨, 남은 시간, 이동 거리, 운영 여부, 혼잡도처럼 상황이 계속
바뀝니다. TripBranch는 “경복궁 근처인데 비가 와”, “여기는 너무 붐벼” 같은
자연어 요청을 구조화하고 이전 대화 맥락과 현재 외부 데이터를 결합해 다음 장소를
추천하는 것을 목표로 합니다.

목표 사용자 흐름은 다음과 같습니다.

```text
사용자 자연어 입력
→ Chat API
→ Interpret 및 이전 대화 조건 병합
→ Tool / Provider를 통한 외부 데이터 보완
→ RecommendationRequest 생성
→ 가중치 기반 추천
→ RecommendationResult 및 자연어 응답 생성
→ 프론트엔드 표시
```

현재 구현은 `/api/interpret`와 `/api/recommendations`가 분리되어 있습니다.
Interpret는 Fake/Real LLM Provider와 Backend 세션 상태를 사용하고, 추천 API는
Fake/Real 외부 Provider가 공유하는 Tool·Candidate·Scoring 파이프라인을 실행합니다.
목표 흐름과 현재 구현의 차이는
[아키텍처 문서](docs/architecture.md)에 정리되어 있습니다.

## 현재 주요 기능

- React 기반 채팅형 추천 화면과 같은 탭 내 상태 복원
- FastAPI Health, Interpret, Recommendations API
- Fake/Real LLM 기반 Intent·조건 추출과 Backend 세션 상태 병합
- Fake/Real Provider 전환 구조
- Naver Geocoding 기반 위치 좌표 변환
- 종로구 범위·alias fallback·모호성 검증을 적용하는 `ResolveLocationTool`
- 기상청 단기예보 기반 날씨 상태 정규화
- 방문 예정 시각과 가장 가까운 초단기예보를 선택하는 `GetWeatherForecastTool`
- TourAPI 위치 기반 장소 검색, 키워드 검색, 장소 상세조회
- 장소명 정확 일치 검색 후 상세조회하는 `find_details_by_name()`
- 주변 후보와 다건 상세정보를 결합하는 `NearbyPlaceDetailsTool`
- TourAPI 운영시간·휴무 원문 보존 및 제한적 구조화
- TourAPI 대·중·소분류 기준 데이터 240건 JSON 정규화
- 관광지 집중률 예측 조회
- 한국천문연구원 공휴일 조회
- 5개 Provider 공통 `ProviderResult`·`ProviderMetadata` 계약
- 위치·날씨·장소·집중률·공휴일 Tool의 공통 상태·오류·metadata 필드
- Tool 결과를 동일 형식으로 보관하는 `AgentToolContext`
- A 조건을 받아 C 내부에서 Provider를 조립하는 `ContextService`
- 장소 유형·태그를 TourAPI 분류 요청으로 변환하는 Category Rule
- 장소 Tool 결과를 Scoring 입력으로 변환하는 Candidate Mapper
- 위치·장소·날씨 Tool → Candidate → Scoring → 상위 5개 추천 파이프라인
- Scoring 상위 후보에 한정한 집중률 후조회
- 추천 API 응답의 전체 Backend 파이프라인 처리시간 `elapsed_ms`
- 실제 외부 요청을 명시적으로만 실행하는 Smoke/Inspection Test

아직 구현되지 않은 핵심 범위:

- 통합 `POST /api/chat`
- 자연어 추천 응답 생성
- 통합 Chat API에 연결된 전체 Orchestrator
- `RecommendationRequest Builder`
- A Runtime의 D 실제 추천 구현 연결
- 운영시간의 공휴일·복합 예외 판정
- Naver Blog Search 근거 수집
- Supabase 영속화
- `chat_session_id`, `recommendation_run_id` 처리

## 기술 스택

- Backend: Python 3.11+, FastAPI, Pydantic 2, httpx, pytest, Ruff
- Frontend: Node.js 20+, React 19, TypeScript, Vite, React Router, Tailwind CSS
- 개발 실행: npm, Node.js 스크립트, Uvicorn
- 영속 저장소: 프로세스 내 State Store, Supabase Place Repository 부분 구현
- LLM Provider: Fake, Google Gemini

## 저장소 구조

```text
TripBranch/
├── README.md
├── package.json                 # 통합 dev/lint/test/build 명령
├── scripts/                     # 프론트·백엔드 동시 실행 및 Ruff 래퍼
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 조립 및 오류 처리
│   │   ├── config.py            # 환경변수 설정
│   │   ├── schemas.py           # 현재 공개 API Pydantic 모델
│   │   ├── domain/models.py     # Provider 공통 도메인 모델
│   │   ├── routes/              # health, interpret, recommendations, chat, state
│   │   ├── agent_context/       # A–C 계약, Category Rule, Context Service
│   │   ├── services/            # Interpret/Runtime/추천 파이프라인
│   │   ├── state/               # Backend 세션 조건·이력 병합
│   │   └── providers/           # Fake/Real Provider와 Mapper
│   ├── resources/
│   │   └── tour_api/
│   │       └── tour_api_category_codes.json
│   │                              # TourAPI 대·중·소분류 기준 데이터
│   ├── tests/
│   ├── docs/                    # Provider 계약·샘플·테스트 가이드
│   ├── pyproject.toml
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── api/                 # 백엔드 API 클라이언트
│   │   ├── components/          # 장소 카드와 채팅 컴포넌트
│   │   ├── pages/               # HomePage, ChatPage
│   │   ├── state/               # React Context와 sessionStorage
│   │   └── types.ts
│   ├── package.json
│   └── .env.example
└── docs/
    ├── architecture.md
    ├── api-contracts.md
    ├── development-guide.md
    ├── decision-log.md
    └── design/                  # Intent별 설계 초안
```

## 환경변수 설정

예시 파일을 복사합니다.

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

Backend Provider는 `PROVIDER_MODE=fake|real`로 일괄 전환하며, 개별
`*_PROVIDER` 값으로 재정의할 수 있습니다. 장소명 기반 좌표 보완을 위한
Naver Local Search는 `LOCAL_SEARCH_PROVIDER=real`로 별도 활성화합니다. 실제 Provider 사용 시 필요한 키는
다음과 같습니다.

| 환경변수 | 용도 |
| --- | --- |
| `WEATHER_API_KEY` | 기상청 날씨 API |
| `TOUR_API_SERVICE_KEY` | TourAPI, 집중률, 공휴일 API |
| `NAVER_MAP_CLIENT_ID` | Naver Geocoding Client ID |
| `NAVER_MAP_CLIENT_SECRET` | Naver Geocoding Client Secret |
| `NAVER_LOCAL_SEARCH_CLIENT_ID` | Naver API Hub Local Search API Key ID |
| `NAVER_LOCAL_SEARCH_CLIENT_SECRET` | Naver API Hub Local Search API Key |
| `LLM_API_KEY` | 예약 필드이며 현재 사용하지 않음 |
| `DATABASE_URL` | 예약 필드이며 현재 사용하지 않음 |

Frontend의 `VITE_API_BASE_URL`은 비워두면 `/api`를 사용하며,
`VITE_SHOW_INTERPRETATION_DEBUG`는 Interpret 디버그 카드 표시를 제어합니다.
`VITE_` 변수에는 비밀값을 넣으면 안 됩니다.

상세한 설정은 [개발 가이드](docs/development-guide.md)를 참고하세요.

## 로컬 설치 및 실행

```bash
npm ci

cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cd ..

cd frontend
npm ci
cd ..

npm run dev
```

- Frontend: http://localhost:5173
- Backend: http://localhost:8000
- Swagger UI: http://localhost:8000/docs

루트 명령은 활성화된 Python 환경을 사용하므로 `npm run dev`, `npm run test`,
`npm run lint` 전에 `backend/.venv`를 활성화해야 합니다.

## Naming 규칙

Backend가 소유하는 Python 필드와 JSON 필드에는 모두 `snake_case`를 사용합니다.

```text
retrieved_at
chat_session_id
recommendation_run_id
provider_metadata
```

Python과 JSON 사이에 camelCase alias를 두지 않습니다. Frontend 컴포넌트의 내부
상태는 TypeScript 관례를 따를 수 있지만 Backend API 요청·응답 타입은 Backend JSON
계약의 `snake_case`를 그대로 사용합니다. TourAPI처럼 외부 Provider가 정한 원본
필드명은 Provider/Mapper 경계 안에서만 유지합니다.

## 테스트와 검사

```bash
npm run lint
npm run test
npm run build
```

Provider 단위·실제 연동 테스트는 별도 가이드를 따릅니다.

```bash
cd backend
python -m pytest -q
RUN_REAL_PROVIDER_TESTS=true python -m pytest -m smoke -v -s
RUN_REAL_PROVIDER_INSPECTION=true python -m pytest -m inspection -v -s
```

실제 API 테스트는 키와 네트워크를 사용하므로 명시적 플래그가 있을 때만 실행됩니다.
요청·응답 Inspection 출력은 인증 쿼리와 헤더를 `<redacted>`로 마스킹합니다.

## TourAPI 장소 분류 데이터

TourAPI의 대·중·소분류 기준 데이터는
[`backend/resources/tour_api/tour_api_category_codes.json`](backend/resources/tour_api/tour_api_category_codes.json)에
보관합니다. CSV 원본의 계층형 빈 셀을 부모 분류 값으로 채워, 각 JSON 항목만으로
대분류부터 소분류 및 `content_type_id`까지 확인할 수 있도록 정규화했습니다.

서버 시작 시 파일을 한 번 읽어 대·중·소분류의 이름·코드 인덱스를 생성하고,
프로세스 안에서 같은 Registry를 재사용합니다. 소분류 조회 결과는
`PlaceCategoryFilter`로 변환해 `PlaceProvider` 요청에 전달할 수 있습니다. 실행
중인 서버에는 JSON 변경이 자동 반영되지 않으며, MVP에서는 서버 재시작 시 다시
로드합니다. 사용자 자연어 별칭을 표준 분류명으로 변환하는 Interpret 연동은 아직
구현되지 않았습니다.

## 문서

- [아키텍처](docs/architecture.md)
- [API 및 내부 계약](docs/api-contracts.md)
- [개발 가이드](docs/development-guide.md)
- [의사결정 로그](docs/decision-log.md)
- [Provider Contract v1](backend/docs/provider-contract-v1.md)
- [Provider 테스트 가이드](backend/docs/provider-test-guide.md)
- [Intent 정의](docs/design/intent-definition.md)

## 다음 작업

1. `ChatRequest`/`ChatResponse` 공개 계약 확정 및 `POST /api/chat` 구현
2. A Runtime의 D 실제 추천 구현 연결
3. 자연어 Response Generator 구현
4. 공휴일·복합 운영정보 판정과 후보 부족 시 추가 조회 정책 확정
5. 혼잡도 Feature 반영 여부와 fallback 정책 확정
6. Backend 세션·추천 Snapshot의 Supabase 저장 모델 확정
7. 프론트 저장소를 `sessionStorage`에서 `localStorage`로 바꿀지 결정

상기 항목의 세부 계약과 일정은 현재 논의 중이며 확정되지 않은 값은 각 문서에서
`TBD`로 표시합니다.
