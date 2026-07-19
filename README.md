# TripBranch

여행 중 날씨 악화, 방문 장소 이용 불가, 남은 시간 부족 등의 상황에서 사용자의 현재 위치와
선호 조건을 바탕으로 주변 대체 장소를 추천하는 웹 서비스입니다.

초기 MVP는 대한민국 국내 여행만 지원합니다.

핵심 흐름:

```text
사용자 자유 입력 → 입력 구조화 → 사용자 확인 및 수정 → 주변 장소 검색 → 추천 점수 계산 → 추천 결과 표시
```

> 이 저장소는 **실행 가능한 개발용 골격**입니다. 실제 LLM/날씨/장소/지오코딩 API는 아직
> 연결되어 있지 않고, 모든 흐름은 Fake Provider로 end-to-end 동작합니다.

## 빠른 시작

```bash
# 1) 루트 의존성
npm ci

# 2) 백엔드 가상환경
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
cp .env.example .env
cd ..

# 3) 프론트엔드 의존성
cd frontend
npm ci
cp .env.example .env
cd ..

# 4) 실행
npm run dev
```

- 프론트엔드: http://localhost:5173
- 백엔드 API: http://localhost:8000/api/health
- Swagger 문서: http://localhost:8000/docs

이후 자주 쓰는 명령:

```bash
npm run lint      # frontend ESLint + backend Ruff check
npm run test      # frontend Vitest --run + backend pytest
npm run build     # frontend 타입체크 + production build
```

## 필수 설치 도구

- Node.js 20+ / npm 10+
- Python 3.11+

## 기술 스택

**백엔드**: Python, FastAPI, Pydantic, pytest, Ruff

**프론트엔드**: TypeScript, React, Vite, React Router, Tailwind CSS, React Context + `useReducer`,
Vitest, React Testing Library, ESLint, Prettier

## 프로젝트 구조

```text
tripbranch/
├─ backend/
│  ├─ app/
│  │  ├─ api/            # HTTP 요청/응답 (routes, deps)
│  │  ├─ schemas/        # Pydantic 요청·응답 모델
│  │  ├─ services/       # 입력 해석·추천 흐름 조합
│  │  ├─ domain/         # 거리·운영시간·점수·정렬 (외부 라이브러리 의존 없음)
│  │  ├─ providers/      # LLM/날씨/장소/지오코딩 (protocols, fake, real)
│  │  ├─ core/           # 설정, 공통 예외, 로깅, 시간(Clock), 정적 파일 서빙
│  │  └─ main.py
│  ├─ tests/
│  ├─ .env.example
│  └─ pyproject.toml
├─ frontend/
│  ├─ src/
│  │  ├─ api/            # 공통 API 클라이언트
│  │  ├─ components/     # PlaceCard, ErrorBanner 등
│  │  ├─ context/        # Context + useReducer 상태관리, sessionStorage 연동
│  │  ├─ generated/      # (선택) OpenAPI 타입 생성 결과물 - 아직 코드에서 안 씀
│  │  ├─ pages/          # InputPage, ConfirmPage, ResultsPage
│  │  ├─ routes/         # 라우트 가드
│  │  ├─ types/          # 기본 타입 정의 (백엔드 스키마와 snake_case로 동일)
│  │  └─ App.tsx
│  ├─ .env.example
│  └─ package.json
├─ package.json           # 루트 오케스트레이션 스크립트
├─ .github/workflows/ci.yml
└─ README.md
```

의존 방향: `api → services → domain`, `services → Provider Protocol`, `Provider 구현 → 외부 API`.
`domain` 계층은 FastAPI/Pydantic 등 외부 라이브러리를 몰라야 합니다.

## 백엔드 설치 방법 (상세)

```bash
cd backend
python3 -m venv .venv
```

가상환경 활성화:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

의존성 설치:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
cp .env.example .env             # 기본값(Fake Provider)만으로 바로 동작합니다
```

가상환경 자체(`backend/.venv/`)는 Git에 포함되지 않습니다. `backend/scripts/venv-run.mjs`가
백엔드 npm 스크립트(`dev`/`lint`/`test`)에서 이 `.venv`를 사용합니다 - **`.venv`가 없으면
PATH의 다른 Python으로 조용히 넘어가지 않고 설치 방법을 안내하며 바로 실패**합니다.

## 프론트엔드 설치 방법 (상세)

```bash
cd frontend
npm ci
cp .env.example .env             # 값을 비워두면 same-origin "/api"를 사용합니다
```

## 의존성 정책

- 팀원은 `npm install`이 아니라 **`npm ci`**를 사용하세요 (`package-lock.json`에 고정된 버전 그대로
  설치됩니다). `package-lock.json`은 Git에 커밋되어 있으며, 이유 없이 삭제/재생성하지 마세요.
- ESLint는 9.x 계열을 사용합니다. TypeScript는 6 이하 canary가 아닌 안정 버전(현재 5.9.3, 실제
  lockfile 기준)을 사용합니다.
- Python은 이번 단계에서 별도 lock 도구(uv/pip-tools 등)를 도입하지 않습니다.

## 환경변수 설정 방법

- `backend/.env.example` → `backend/.env` 로 복사 후 사용. 기본값은 모든 Provider가 `fake` 이므로
  API 키 없이 바로 실행/테스트할 수 있습니다.
- `frontend/.env.example` → `frontend/.env` 로 복사. `VITE_API_BASE_URL`을 비워두면 개발 환경에서는
  Vite 프록시가, 배포 환경에서는 same-origin `/api`가 사용됩니다.
- 실제 `.env` 파일(과 `.env.*` 변형)은 Git에 커밋되지 않습니다. `.env.example`만 추적됩니다.

## 테스트 실행 방법

```bash
npm run test                     # 루트에서 프론트 + 백엔드 테스트 모두 실행
npm run test --prefix backend    # pytest만
npm run test --prefix frontend   # vitest만
```

## 린트 명령

```bash
npm run lint                     # ESLint(frontend) + Ruff check(backend)
```

`npm run format`(Prettier + Ruff format)도 있지만 이번 단계에서는 팀 배포의 필수 기준이
아닙니다 - 편하게 쓰되 CI 게이트로 걸려 있지 않습니다.

## 빌드 방법

```bash
npm run build                    # 타입체크 + 프론트엔드 빌드 (frontend/dist/)
```

## Fake Provider 사용법

`backend/.env`의 `LLM_PROVIDER` / `WEATHER_PROVIDER` / `PLACE_PROVIDER` / `GEOCODING_PROVIDER`가
모두 기본값 `fake`이면, 실제 API 키 없이 다음이 전부 동작합니다.

- **FakeGeocodingProvider**: `경복궁`, `서울역`, `광화문` 세 위치를 좌표로 변환합니다.
- **FakeWeatherProvider**: `FAKE_WEATHER_CONDITION` 환경변수(`good`/`neutral`/`bad`)로 고정된 날씨를
  반환합니다.
- **FakePlaceProvider**: 10개의 고정 장소 데이터를 제공합니다 (`app/providers/fake/places_data.py`).
  실내/야외/혼합/미확인 환경, 운영 중/영업 종료/30분 이내 마감/운영시간 미확인, 서로 다른 카테고리와
  거리를 모두 포함합니다.
- **FakeLlmProvider**: 키워드 기반 규칙으로 자유 입력을 구조화합니다.

**Fake 환경의 "지금 시각"**: 추천 API는 `datetime.now()`를 직접 부르지 않고
`app/core/clock.py`의 `Clock`을 주입받습니다 (`app/api/deps.py`의 `get_clock`).
`PLACE_PROVIDER=fake`(기본값)이면 `backend/.env`의 `FAKE_CURRENT_DATETIME`
(기본 `2026-07-15T14:00:00`, 평일 낮)으로 고정된 시각을 사용해서, 실행 시각과 무관하게
표준 입력("경복궁 근처에서 비를 피할 수 있는 박물관이나 카페를 찾고 싶어")이 항상 정상
추천을 반환합니다. `PLACE_PROVIDER=real`이면 실제 시스템 시각을 씁니다.

## 실제 Provider 구현 위치

`app/providers/real/{geocoding,weather,places,llm}.py`에 각 Provider 클래스와 생성자(설정 주입)가
이미 정의되어 있고, 메서드 본문은 `NotImplementedError`로 남겨져 있습니다. 실제 API 연동 시 해당
파일만 수정하면 됩니다 (서비스/도메인/API 계층은 `app/providers/protocols/*.py`의 Protocol에만
의존하므로 변경할 필요가 없습니다). Provider 선택은 `backend/.env`의 `*_PROVIDER=real` 로 전환합니다.

## 팀원 작업 영역

| 담당 | 작업 범위 |
| --- | --- |
| 백엔드 A | `backend/app/providers/real/geocoding.py`, `real/places.py` |
| 백엔드 B | `backend/app/providers/real/weather.py`, `real/llm.py` |
| 백엔드 C | `backend/app/domain/scoring.py`, `domain/weights.py`, `services/recommendation_service.py` |
| 프론트 A | `frontend/src/pages/ConfirmPage.tsx` (카테고리 편집 UX) |
| 프론트 B | `frontend/src/pages/ResultsPage.tsx`, `components/PlaceCard.tsx` |
| 프론트 C | 프론트엔드 테스트 (`frontend/src/**/*.test.{ts,tsx}`) |

**공통 파일** - 여러 담당 영역이 함께 의존하므로 임의로 바꾸지 말고 변경이 필요하면 먼저
팀 리드와 합의하세요:

```text
backend/app/api/deps.py
backend/app/core/config.py
backend/app/schemas/*
frontend/src/types/domain.ts
```

## 현재 TODO

- 실제 LLM/날씨/장소/지오코딩 API 연동 (`providers/real/*`)
- 후보가 `MINIMUM_RECOMMENDATION_COUNT` 미만일 때의 조건 완화 재시도 로직
  (`recommendation_service.py`의 `TODO` 주석 참고; 현재 프론트에서는 사용자가 버튼으로 반경을
  넓혀 재요청하는 수동 흐름만 구현되어 있습니다)
- 실제 단일 배포 시 React Router SPA fallback 확장 검토
  (`backend/app/core/static.py`에 기본 구현과 테스트가 이미 있지만, production 배포 자체는
  이번 단계 범위 밖이라 추가 검증 없이 확정하지 않았습니다)
- 로그인, 데이터베이스, 사용자 기록 저장은 범위 밖입니다 (MVP 제한사항)

---

## 참고: 선택 사항 / 다음 단계

아래는 지금 단계에서 팀 개발을 막지 않는 선택적 항목들입니다.

### OpenAPI 타입 생성 (선택)

FastAPI의 Pydantic 모델이 API 규격의 기준입니다. `openapi-typescript`로 OpenAPI 명세에서
TypeScript 타입을 생성할 수 있습니다.

```bash
npm run generate:api-types
```

1. `backend`: `app.main:app`의 OpenAPI 스펙을 `backend/openapi.json`으로 내보냅니다.
2. `frontend`: `openapi-typescript`로 `frontend/src/generated/api-types.ts`를 생성합니다.

`frontend/src/generated/*.ts`는 **자동 생성 파일이며 직접 수정하지 않습니다.** 현재는
`frontend/src/types/domain.ts`의 수동 타입이 기본이고, 프론트 코드 어디서도 generated 타입을
가져다 쓰지 않습니다 (둘 다 `.gitignore` 대상이라 clone 직후 `npm run dev`/`npm run build`가
이 파일 없이도 정상 동작합니다). API 스키마가 안정화되면 generated 타입을 본격 연계할 예정이며,
CI에서 diff를 강제하는 것도 그때 함께 검토합니다.

### Production 정적 배포 (구현은 있으나 배포 검증은 다음 단계)

`backend/app/core/static.py`의 `mount_frontend_if_built()`는 `frontend/dist/`가 존재하면 FastAPI
단독 실행만으로 프론트+백엔드를 함께 서빙하도록 마운트하고, `/confirm`·`/results` 같은 React
Router 경로도 `index.html`로 fallback합니다 (백엔드 테스트 `tests/test_static_spa.py` 참고).
API/추천 로직과 완전히 분리되어 있어 나중에 프론트를 별도 배포할 때 이 파일만 제거하면 됩니다.
다만 실제 production 배포 전략(어디에 어떻게 배포할지)은 이번 단계에서 결정하지 않았으므로,
이 코드가 실제 배포 환경에서 검증됐다고 간주하지 마세요.
