# TripBranch

TripBranch는 여행 중 날씨 악화, 방문 장소 이용 불가, 남은 시간 부족 같은 상황에서 대체 장소를 추천하는 서비스를 만들기 위한 **최소 팀 프로젝트 골격**입니다.

현재 기본 브랜치는 의도적으로 백엔드 응답을 Stub으로 고정해 두었습니다. 프론트엔드, 백엔드, Provider, 추천 도메인 담당자가 실제 구현을 설계하기 전에 작고 실행 가능한 앱에서 출발할 수 있게 하는 것이 목적입니다.

## 현재 사용자 흐름

```text
사용자 자유 입력
-> 고정된 입력 해석 결과
-> 조건 확인 화면
-> 고정된 추천 결과
-> 결과 화면
-> 다른 장소 보기
-> 처음부터 다시 시작
```

## 기술 스택

- 백엔드: Python 3.11+, FastAPI, Pydantic, pytest, Ruff
- 프론트엔드: Node.js 20+, React, TypeScript, Vite, React Router, Tailwind CSS, Vitest
- 루트 실행 스크립트: npm + 간단한 Node 스크립트

## 프로젝트 구조

```text
tripbranch/
├─ package.json
├─ package-lock.json
├─ README.md
├─ .gitignore
├─ .github/workflows/ci.yml
├─ backend/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ routes/
│  │  ├─ services/
│  │  ├─ providers/
│  │  ├─ schemas.py
│  │  ├─ config.py
│  │  └─ errors.py
│  ├─ tests/
│  ├─ pyproject.toml
│  └─ .env.example
└─ frontend/
   ├─ src/
   │  ├─ api/
   │  ├─ components/
   │  ├─ pages/
   │  ├─ state/
   │  ├─ test/
   │  ├─ App.tsx
   │  ├─ main.tsx
   │  ├─ index.css
   │  └─ types.ts
   ├─ package.json
   ├─ package-lock.json
   ├─ vite.config.ts
   ├─ eslint.config.js
   └─ .env.example
```

## 설치 방법

루트 의존성을 설치합니다.

```bash
npm ci
```

백엔드 가상환경을 만들고 활성화합니다.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
cd ..
```

Windows PowerShell에서는 다음 명령으로 가상환경을 활성화합니다.

```powershell
backend\.venv\Scripts\Activate.ps1
```

프론트엔드 의존성을 설치합니다.

```bash
cd frontend
npm ci
cp .env.example .env
cd ..
```

루트의 백엔드 관련 명령은 현재 활성화된 `python`을 사용합니다. 루트 스크립트를 실행하기 전에 `backend/.venv`를 활성화해 주세요.

## 실행 명령

```bash
npm run dev
npm run lint
npm run test
npm run build
```

`npm run dev`는 다음 서버를 실행합니다.

- 프론트엔드: http://localhost:5173
- 백엔드: http://localhost:8000
- Swagger/OpenAPI 문서: http://localhost:8000/docs

Vite 개발 서버는 `/api/*` 요청을 FastAPI 백엔드로 프록시합니다.

## 백엔드 Stub 계약

`POST /api/interpret`는 비어 있지 않은 모든 입력에 대해 고정된 조건 해석 결과를 반환합니다.

```json
{
  "location_query": "경복궁",
  "preferred_categories": ["museum", "cafe"],
  "weather_condition": "bad",
  "search_radius_km": 1.0
}
```

`POST /api/recommendations`는 고정된 추천 장소 목록을 반환합니다. 요청의 `shown_place_ids`에 포함된 장소 ID는 결과에서 제외됩니다.

현재 구현된 엔드포인트는 다음과 같습니다.

- `GET /api/health`
- `POST /api/interpret`
- `POST /api/recommendations`

현재 공통 오류 응답 형식은 다음과 같습니다.

```json
{
  "error": {
    "code": "invalid_request",
    "message": "요청 내용을 확인해주세요.",
    "retryable": false,
    "details": null
  }
}
```

## 프론트엔드 상태

프론트엔드는 Stub 흐름에 필요한 최소 상태만 관리합니다.

- `user_input`
- `interpreted_conditions`
- `recommendations`
- `unverified_recommendations`
- `shown_place_ids`

`sessionStorage`를 사용해 같은 탭에서 새로고침해도 현재 상태를 복구합니다.

## 이후 팀 작업

상세 추천 프로토타입은 이 골격으로 축소하기 전에 Git에 보존되어 있습니다. 참고 구현이 필요하면 보존 커밋 또는 보존 브랜치에서 복구할 수 있습니다.

- 보존 브랜치: `archive-full-prototype`
- 보존 커밋: `cb75c48 Archive full TripBranch prototype`

권장 구현 순서는 다음과 같습니다.

1. Stub 추천 결과를 Place Provider 계약으로 교체
2. 지오코딩 Provider와 위치 해석 추가
3. 거리 필터 구현
4. 운영시간 파싱과 `open` / `closed` / `unknown` 판정 구현
5. 날씨 Provider와 날씨-환경 유형 매칭 추가
6. 가중치 기반 점수 계산 구현
7. 결정적 정렬과 `shown_place_ids` 제외 처리 구현
8. 후보 부족 처리 구현
9. 실제 Provider 구현 연결

향후 추천 로직 구현 시 보존할 점수 규칙은 다음과 같습니다.

```yaml
weights:
  category: 0.40
  remaining_open_time: 0.30
  weather: 0.20
  distance: 0.10
weights_without_weather:
  category: 0.50
  remaining_open_time: 0.375
  distance: 0.125
category_score:
  rank_1: 1.00
  rank_2: 0.85
  rank_3: 0.70
remaining_open_time:
  180_minutes_or_more: 1.00
  120_to_179: 0.85
  60_to_119: 0.65
  30_to_59: 0.35
  less_than_30: 0.10
distance:
  within_25_percent_of_radius: 1.00
  within_50_percent_of_radius: 0.80
  within_75_percent_of_radius: 0.60
  within_100_percent_of_radius: 0.40
```

날씨와 장소 환경 유형 점수표는 다음과 같습니다.

| 날씨 | indoor | mixed | outdoor | unknown |
| --- | ---: | ---: | ---: | ---: |
| good | 0.8 | 0.9 | 1.0 | 0.7 |
| neutral | 1.0 | 0.9 | 0.8 | 0.7 |
| bad | 1.0 | 0.7 | 0.3 | 0.5 |

## 현재 골격에서 제외된 범위

- 실제 LLM 입력 해석
- 실제 지오코딩, 날씨, 장소 API 연동
- 거리 계산, 운영시간 계산, 날씨 반영, 점수 계산, 정렬 로직
- OpenAPI TypeScript 타입 생성
- production 정적 파일 서빙
- 데이터베이스, 로그인, Docker, 자동 조건 완화
