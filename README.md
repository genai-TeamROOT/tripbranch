# TripBranch

사용자의 자연어 요청과 현재 상황을 해석해 서울 지역의 장소 후보를 수집하고,
조건별 가중치를 적용해 적합한 장소를 추천하는 서비스입니다.

> 현재 단계: **Phase 1-A — Core AI Agent Flow**
> 현재 저장소는 실행 가능한 React/FastAPI 골격과 Provider 연동 기반을 갖추고 있지만,
> 통합 Chat API·LLM 해석·상태 병합·가중치 Scoring은 아직 구현 전입니다.

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

현재 구현은 `/api/interpret`와 `/api/recommendations`가 분리되어 있고, Interpret와
추천 응답은 Stub 중심입니다. 목표 흐름과 현재 구현의 차이는
[아키텍처 문서](docs/architecture.md)에 정리되어 있습니다.

## 현재 주요 기능

- React 기반 채팅형 추천 화면과 같은 탭 내 상태 복원
- FastAPI Health, Interpret, Recommendations API
- Stub Interpret 및 Stub 추천 결과
- Fake/Real Provider 전환 구조
- Naver Geocoding 기반 위치 좌표 변환
- 기상청 단기예보 기반 날씨 상태 정규화
- TourAPI 위치 기반 장소 검색, 키워드 검색, 장소 상세조회
- 장소명 정확 일치 검색 후 상세조회하는 `find_details_by_name()`
- 관광지 집중률 예측 조회
- 한국천문연구원 공휴일 조회
- 실제 외부 요청을 명시적으로만 실행하는 Smoke/Inspection Test

아직 구현되지 않은 핵심 범위:

- 통합 `POST /api/chat`
- 실제 LLM 기반 Intent/조건 추출 및 자연어 응답 생성
- 이전 대화 조건 병합과 백엔드 세션 상태
- Tool 계층과 Orchestrator
- `RecommendationRequest Builder`
- 운영시간 계산, 하드 필터, 가중치 Scoring 및 결정적 정렬
- Naver Blog Search 근거 수집
- Supabase 영속화
- `chatSessionId`, `recommendationRunId` 처리

## 기술 스택

- Backend: Python 3.11+, FastAPI, Pydantic 2, httpx, pytest, Ruff
- Frontend: Node.js 20+, React 19, TypeScript, Vite, React Router, Tailwind CSS
- 개발 실행: npm, Node.js 스크립트, Uvicorn
- 영속 저장소: TBD (Supabase 사용 방향만 합의됨)
- LLM Provider: TBD

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
│   │   ├── routes/              # health, interpret, recommendations
│   │   ├── services/            # Stub Interpret와 추천 파이프라인
│   │   └── providers/           # Fake/Real Provider와 Mapper
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
`*_PROVIDER` 값으로 재정의할 수 있습니다. 실제 Provider 사용 시 필요한 키는
다음과 같습니다.

| 환경변수 | 용도 |
| --- | --- |
| `WEATHER_API_KEY` | 기상청 날씨 API |
| `TOUR_API_SERVICE_KEY` | TourAPI, 집중률, 공휴일 API |
| `NAVER_MAP_CLIENT_ID` | Naver Geocoding Client ID |
| `NAVER_MAP_CLIENT_SECRET` | Naver Geocoding Client Secret |
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
2. Orchestrator, Context Merge, Tool 경계 도입
3. 실제 Interpret 및 Response Generator LLM Provider 결정
4. 내부 `RecommendationRequest` 스키마 확정
5. 운영시간·날씨·거리·혼잡도 Feature 정규화
6. 하드 필터와 가중치 Scoring 구현
7. `chatSessionId`/`recommendationRunId` 및 Supabase 저장 모델 확정
8. 프론트 저장소를 `sessionStorage`에서 `localStorage`로 바꿀지 결정

상기 항목의 세부 계약과 일정은 현재 논의 중이며 확정되지 않은 값은 각 문서에서
`TBD`로 표시합니다.
